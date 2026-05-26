local BookList = require("ui/widget/booklist")
local ConfirmBox = require("ui/widget/confirmbox")
local Device = require("device")
local Dispatcher = require("dispatcher")
local Event = require("ui/event")
local InfoMessage = require("ui/widget/infomessage")
local Json = require("json")
local Math = require("optmath")
local MultiInputDialog = require("ui/widget/multiinputdialog")
local NetworkMgr = require("ui/network/manager")
local UIManager = require("ui/uimanager")
local WidgetContainer = require("ui/widget/container/widgetcontainer")
local logger = require("logger")
local md5 = require("ffi/sha2").md5
local random = require("random")
local SyncLogic = require("sync_logic")
local time = require("ui/time")
local util = require("util")
local T = require("ffi/util").template
local _ = require("gettext")
local bit = require("bit")

if G_reader_settings:hasNot("device_id") then
    G_reader_settings:saveSetting("device_id", random.uuid())
end

local CWASync = WidgetContainer:extend{
    name = "cwasync",
    title = _("Login to NextGen Server"),
    version = "4.0.60",  -- Plugin version mirrors CWNG release tag

    push_timestamp = nil,
    pull_timestamp = nil,
    page_update_counter = nil,
    last_page = nil,
    last_page_turn_timestamp = nil,
    periodic_push_task = nil,
    periodic_push_scheduled = nil,

    settings = nil,
}

local SYNC_STRATEGY = {
    PROMPT  = 1,
    SILENT  = 2,
    DISABLE = 3,
}


-- Debounce push/pull attempts
local API_CALL_DEBOUNCE_DELAY = time.s(25)

-- NOTE: This is used in a migration script by ui/data/onetime_migration,
--       which is why it's public.
CWASync.default_settings = {
    server = nil,
    username = nil,
    password = nil,
    -- Do *not* default to auto-sync, as wifi may not be on at all times, and the nagging enabling this may cause requires careful consideration.
    auto_sync = false,
    pages_before_update = nil,
    sync_forward = SYNC_STRATEGY.PROMPT,
    sync_backward = SYNC_STRATEGY.DISABLE,
}

function CWASync:init()
    self.push_timestamp = 0
    self.pull_timestamp = 0
    self.page_update_counter = 0
    self.last_page = -1
    self.last_page_turn_timestamp = 0
    self.periodic_push_scheduled = false

    -- Like AutoSuspend, we need an instance-specific task for scheduling/resource management reasons.
    self.periodic_push_task = function()
        self.periodic_push_scheduled = false
        self.page_update_counter = 0
        -- We do *NOT* want to make sure networking is up here, as the nagging would be extremely annoying; we're leaving that to the network activity check...
        self:updateProgress(false, false)
    end

    self.settings = G_reader_settings:readSetting("cwasync", self.default_settings)
    self.device_id = G_reader_settings:readSetting("device_id")

    -- Disable auto-sync if beforeWifiAction was reset to "prompt" behind our back...
    if self.settings.auto_sync and Device:hasSeamlessWifiToggle() and G_reader_settings:readSetting("wifi_enable_action") ~= "turn_on" then
        self.settings.auto_sync = false
        logger.warn("CWASync: Automatic sync has been disabled because wifi_enable_action is *not* turn_on")
    end

    self.ui.menu:registerToMainMenu(self)
end

function CWASync:getSyncPeriod()
    if not self.settings.auto_sync then
        return _("Not available")
    end

    local period = self.settings.pages_before_update
    if period and period > 0 then
        return period
    else
        return _("Never")
    end
end

local function getNameStrategy(type)
    if type == 1 then
        return _("Prompt")
    elseif type == 2 then
        return _("Auto")
    else
        return _("Disable")
    end
end

local function showSyncedMessage()
    UIManager:show(InfoMessage:new{
        text = _("Progress has been synchronized."),
        timeout = 3,
    })
end

local function promptLogin()
    UIManager:show(InfoMessage:new{
        text = _("Please login before using the progress synchronization feature."),
        timeout = 3,
    })
end

local function showSyncError()
    UIManager:show(InfoMessage:new{
        text = _("Something went wrong when syncing progress, please check your network connection and try again later."),
        timeout = 3,
    })
end

local function getBodyMessage(body, fallback)
    if type(body) == "table" then
        return body.message or fallback
    end
    if type(body) == "string" and body ~= "" then
        return body
    end
    return fallback
end

local function showNoBookMessage()
    UIManager:show(InfoMessage:new{
        text = _("No book is currently open to push progress for."),
        timeout = 3,
    })
end

local function ensureServerConfigured(server)
    if server and server ~= "" then
        return true
    end
    UIManager:show(InfoMessage:new{
        text = _("Please set the NextGen Server address first."),
        timeout = 3,
    })
    return false
end

local function validate(entry)
    if not entry then return false end
    if type(entry) == "string" then
        if entry == "" or not entry:match("%S") then return false end
    end
    return true
end

local function validateUser(user, pass)
    local error_message = nil
    local user_ok = validate(user)
    local pass_ok = validate(pass)
    if not user_ok and not pass_ok then
        error_message = _("invalid username and password")
    elseif not user_ok then
        error_message = _("invalid username")
    elseif not pass_ok then
        error_message = _("invalid password")
    end

    if not error_message then
        return user_ok and pass_ok
    else
        return user_ok and pass_ok, error_message
    end
end

function CWASync:onDispatcherRegisterActions()
    Dispatcher:registerAction("cwasync_push_progress", { category="none", event="CWASyncPushProgress", title=_("Push progress from this device"), reader=true,})
    Dispatcher:registerAction("cwasync_pull_progress", { category="none", event="CWASyncPullProgress", title=_("Pull progress from other devices"), reader=true, separator=true,})
end

function CWASync:onReaderReady()
    if self.settings.auto_sync then
        UIManager:nextTick(function()
            self:getProgress(true, false)
        end)
    end
    -- NOTE: Keep in mind that, on Android, turning on WiFi requires a focus switch, which will trip a Suspend/Resume pair.
    --       NetworkMgr will attempt to hide the damage to avoid a useless pull -> push -> pull dance instead of the single pull requested.
    --       Plus, if wifi_enable_action is set to prompt, that also avoids stacking three prompts on top of each other...
    self:registerEvents()
    self:onDispatcherRegisterActions()

    self.last_page = self.ui:getCurrentPage()
end

function CWASync:addToMainMenu(menu_items)
    menu_items.cwa_progress_sync = {
        text = _("NextGen Progress Sync"),
        sorting_hint = "tools",
        sub_item_table = {
            {
                text = _("Set NextGen Server"),
                keep_menu_open = true,
                tap_input_func = function()
                    return {
                        -- @translators Server address defined by user for progress sync.
                        title = _("NextGen Server Address"),
                        input = self.settings.server or "https://",
                        callback = function(input)
                            self:setServer(input)
                        end,
                    }
                end,
            },
            {
                text_func = function()
                    return self.settings.password and (_("Logout"))
                        or _("Login")
                end,
                keep_menu_open = true,
                callback_func = function()
                    if self.settings.password then
                        return function(menu)
                            self:logout(menu)
                        end
                    else
                        return function(menu)
                            self:login(menu)
                        end
                    end
                end,
                separator = true,
            },
            {
                text = _("Automatically keep documents in sync"),
                checked_func = function() return self.settings.auto_sync end,
                help_text = _([[This may lead to nagging about toggling WiFi on document close and suspend/resume, depending on the device's connectivity.]]),
                callback = function()
                    -- Actively recommend switching the before wifi action to "turn_on" instead of prompt, as prompt will just not be practical (or even plain usable) here.
                    if Device:hasSeamlessWifiToggle() and G_reader_settings:readSetting("wifi_enable_action") ~= "turn_on" and not self.settings.auto_sync then
                        UIManager:show(InfoMessage:new{ text = _("You will have to switch the 'Action when Wi-Fi is off' Network setting to 'turn on' to be able to enable this feature!") })
                        return
                    end

                    self.settings.auto_sync = not self.settings.auto_sync
                    self:registerEvents()
                    if not(self:hasActiveDocument()) then
                        return
                    end
                    if self.settings.auto_sync then
                        -- Since we will update the progress when closing the document,
                        -- pull the current progress now so as not to silently overwrite it.
                        self:getProgress(true, true)
                    else
                        -- Since we won't update the progress when closing the document,
                        -- push the current progress now so as not to lose it.
                        self:updateProgress(true, true)
                    end
                end,
            },
            {
                text_func = function()
                    return T(_("Periodically sync every # pages (%1)"), self:getSyncPeriod())
                end,
                enabled_func = function() return self.settings.auto_sync end,
                -- This is the condition that allows enabling auto_disable_wifi in NetworkManager ;).
                help_text = NetworkMgr:getNetworkInterfaceName() and _([[Unlike the automatic sync above, this will *not* attempt to setup a network connection, but instead relies on it being already up, and may trigger enough network activity to passively keep WiFi enabled!]]),
                keep_menu_open = true,
                callback = function(touchmenu_instance)
                    local SpinWidget = require("ui/widget/spinwidget")
                    local items = SpinWidget:new{
                        text = _([[This value determines how many page turns it takes to update book progress.
If set to 0, updating progress based on page turns will be disabled.]]),
                        value = self.settings.pages_before_update or 0,
                        value_min = 0,
                        value_max = 999,
                        value_step = 1,
                        value_hold_step = 10,
                        ok_text = _("Set"),
                        title_text = _("Number of pages before update"),
                        default_value = 0,
                        callback = function(spin)
                            self:setPagesBeforeUpdate(spin.value)
                            if touchmenu_instance then touchmenu_instance:updateItems() end
                        end
                    }
                    UIManager:show(items)
                end,
                separator = true,
            },
            {
                text = _("Sync behavior"),
                sub_item_table = {
                    {
                        text_func = function()
                            -- NOTE: With an up-to-date Sync server, "forward" means *newer*, not necessarily ahead in the document.
                            return T(_("Sync to a newer state (%1)"), getNameStrategy(self.settings.sync_forward))
                        end,
                        sub_item_table = {
                            {
                                text = _("Silently"),
                                checked_func = function()
                                    return self.settings.sync_forward == SYNC_STRATEGY.SILENT
                                end,
                                callback = function()
                                    self:setSyncForward(SYNC_STRATEGY.SILENT)
                                end,
                            },
                            {
                                text = _("Prompt"),
                                checked_func = function()
                                    return self.settings.sync_forward == SYNC_STRATEGY.PROMPT
                                end,
                                callback = function()
                                    self:setSyncForward(SYNC_STRATEGY.PROMPT)
                                end,
                            },
                            {
                                text = _("Never"),
                                checked_func = function()
                                    return self.settings.sync_forward == SYNC_STRATEGY.DISABLE
                                end,
                                callback = function()
                                    self:setSyncForward(SYNC_STRATEGY.DISABLE)
                                end,
                            },
                        }
                    },
                    {
                        text_func = function()
                            return T(_("Sync to an older state (%1)"), getNameStrategy(self.settings.sync_backward))
                        end,
                        sub_item_table = {
                            {
                                text = _("Silently"),
                                checked_func = function()
                                    return self.settings.sync_backward == SYNC_STRATEGY.SILENT
                                end,
                                callback = function()
                                    self:setSyncBackward(SYNC_STRATEGY.SILENT)
                                end,
                            },
                            {
                                text = _("Prompt"),
                                checked_func = function()
                                    return self.settings.sync_backward == SYNC_STRATEGY.PROMPT
                                end,
                                callback = function()
                                    self:setSyncBackward(SYNC_STRATEGY.PROMPT)
                                end,
                            },
                            {
                                text = _("Never"),
                                checked_func = function()
                                    return self.settings.sync_backward == SYNC_STRATEGY.DISABLE
                                end,
                                callback = function()
                                    self:setSyncBackward(SYNC_STRATEGY.DISABLE)
                                end,
                            },
                        }
                    },
                },
                separator = true,
            },
            {
                text = _("Push progress from this device now") .. self:statusTextIfActionUnavailable(),
                enabled_func = function()
                    return self.settings.password ~= nil and self:hasActiveDocument()
                end,
                callback = function()
                    self:updateProgress(true, true)
                end,
            },
            {
                text = _("Pull progress from other devices now") .. self:statusTextIfActionUnavailable(),
                enabled_func = function()
                    return self.settings.password ~= nil and self:hasActiveDocument()
                end,
                callback = function()
                    self:getProgress(true, true)
                end,
                separator = true,
            },
            {
                text = T(_("Plugin version: %1"), self.version),
                keep_menu_open = true,
                callback = function()
                    UIManager:show(InfoMessage:new{
                        text = T(_("NextGen Progress Sync Plugin\nVersion: %1\n\nThis plugin syncs your reading progress to Calibre-Web NextGen."), self.version),
                    })
                end,
            },
        }
    }
end

function CWASync:hasActiveDocument()
    return (self.ui and self.ui.document) ~= nil
end

function CWASync:statusTextIfActionUnavailable()
    local missingPasswordNotice = not(self.settings.password ~= nil) and _(" (Password Not Set)")
    local inactiveDocumentNotice = not(self:hasActiveDocument()) and _(" (No Active Document)")
    return missingPasswordNotice or inactiveDocumentNotice or ""
end

function CWASync:setPagesBeforeUpdate(pages_before_update)
    self.settings.pages_before_update = pages_before_update > 0 and pages_before_update or nil
end

function CWASync:setServer(server)
    logger.dbg("CWASync: Setting server to:", server)
    self.settings.server = server ~= "" and server or nil
end

function CWASync:setSyncForward(strategy)
    self.settings.sync_forward = strategy
end

function CWASync:setSyncBackward(strategy)
    self.settings.sync_backward = strategy
end

function CWASync:login(menu)
    if NetworkMgr:willRerunWhenOnline(function() self:login(menu) end) then
        return
    end

    local dialog
    dialog = MultiInputDialog:new{
        title = self.title,
        fields = {
            {
                text = self.settings.username,
                hint = "username",
            },
            {
                hint = "password",
                text_type = "password",
            },
        },
        buttons = {
            {
                {
                    text = _("Cancel"),
                    id = "close",
                    callback = function()
                        UIManager:close(dialog)
                    end,
                },
                {
                    text = _("Login"),
                    callback = function()
                        local username, password = unpack(dialog:getFields())
                        username = util.trim(username)
                        local ok, err = validateUser(username, password)
                        if not ok then
                            UIManager:show(InfoMessage:new{
                                text = T(_("Cannot login: %1"), err),
                                timeout = 2,
                            })
                        else
                            UIManager:close(dialog)
                            UIManager:scheduleIn(0.5, function()
                                self:doLogin(username, password, menu)
                            end)
                            UIManager:show(InfoMessage:new{
                                text = _("Logging in. Please wait…"),
                                timeout = 1,
                            })
                        end
                    end,
                },
            },
        },
    }
    UIManager:show(dialog)
    dialog:onShowKeyboard()
end

function CWASync:doLogin(username, password, menu)
    if not ensureServerConfigured(self.settings.server) then
        return
    end
    local CWASyncClient = require("CWASyncClient")
    local client = CWASyncClient:new{
        service_url = self.settings.server .. "/kosync",
        service_spec = self.path .. "/api.json"
    }
    Device:setIgnoreInput(true)
    local ok, status, body = pcall(client.authorize, client, username, password)
    if not ok then
        if status then
            UIManager:show(InfoMessage:new{
                text = _("An error occurred while logging in:") ..
                    "\n" .. status,
            })
        else
            UIManager:show(InfoMessage:new{
                text = _("An unknown error occurred while logging in."),
            })
        end
        Device:setIgnoreInput(false)
        return
    elseif status then
        self.settings.username = username
        self.settings.password = password
        if menu then
            menu:updateItems()
        end
        UIManager:show(InfoMessage:new{
            text = _("Logged in to NextGen server."),
        })
    else
        UIManager:show(InfoMessage:new{
            text = getBodyMessage(body, _("Unknown server error")),
        })
    end
    Device:setIgnoreInput(false)
end

function CWASync:logout(menu)
    self.settings.password = nil
    self.settings.auto_sync = true
    if menu then
        menu:updateItems()
    end
end

function CWASync:getLastPercent()
    if self.ui.document.info.has_pages then
        return Math.roundPercent(self.ui.paging:getLastPercent())
    else
        return Math.roundPercent(self.ui.rolling:getLastPercent())
    end
end

function CWASync:getLastProgress()
    if self.ui.document.info.has_pages then
        return self.ui.paging:getLastProgress()
    else
        return self.ui.rolling:getLastProgress()
    end
end

function CWASync:hasCurrentDocument()
    return self.ui and self.ui.document ~= nil
end

function CWASync:getCurrentDocumentFile()
    if self.view and self.view.document and self.view.document.file then
        return self.view.document.file
    elseif self.ui and self.ui.document and self.ui.document.file then
        return self.ui.document.file
    end

    return nil
end

function CWASync:getDocumentDigest(file_path)
    local digest = nil
    if not file_path and self.ui and self.ui.doc_settings and self.ui.doc_settings.readSetting then
        digest = self.ui.doc_settings:readSetting("partial_md5_checksum")
    elseif file_path then
        local ok, DocSettings = pcall(require, "docsettings")
        if ok and DocSettings then
            local ok_open, doc_settings = pcall(DocSettings.open, DocSettings, file_path)
            if ok_open and doc_settings and doc_settings.readSetting then
                digest = doc_settings:readSetting("partial_md5_checksum")
            end
        end
    end

    if digest and digest ~= "" then
        return digest
    end

    if not file_path then
        file_path = self:getCurrentDocumentFile()
    end

    if util.partialMD5 and file_path then
        local ok, result = pcall(util.partialMD5, file_path)
        if ok and result and result ~= "" then
            return result
        end
    end

    if file_path then
        local ok, result = pcall(function(path)
            local f = io.open(path, "rb")
            if not f then
                return nil
            end

            local step = 1024
            local sample_size = 1024
            local chunks = {}
            for i = -1, 10 do
                local position = bit.lshift(step, 2 * i)
                local ok_seek = f:seek("set", position)
                if not ok_seek then
                    break
                end

                local sample = f:read(sample_size)
                if not sample or #sample == 0 then
                    break
                end
                chunks[#chunks + 1] = sample
            end
            f:close()

            if #chunks == 0 then
                return nil
            end

            return md5(table.concat(chunks))
        end, file_path)

        if ok and result and result ~= "" then
            return result
        end
    end

    return nil
end

function CWASync:getLibraryBookPaths()
    local paths = {}
    local seen = {}
    local document_registry_ok, DocumentRegistry = pcall(require, "document/documentregistry")

    local function addPath(path)
        if type(path) ~= "string" or path == "" or seen[path] then
            return
        end
        if document_registry_ok and DocumentRegistry and DocumentRegistry.hasProvider then
            local ok, has_provider = pcall(DocumentRegistry.hasProvider, DocumentRegistry, path)
            if not ok or not has_provider then
                return
            end
        end
        seen[path] = true
        paths[#paths + 1] = path
    end

    local function addItemPaths(items)
        if type(items) ~= "table" then
            return
        end
        for _, item in ipairs(items) do
            if type(item) == "table" and (item.is_file == nil or item.is_file) then
                addPath(item.path or item.file)
            end
        end
    end

    if self.ui and type(self.ui.selected_files) == "table" then
        for path, selected in pairs(self.ui.selected_files) do
            if selected then
                addPath(path)
            end
        end
    end

    if #paths > 0 then
        return paths
    end

    addItemPaths(self.ui and self.ui.booklist_menu and self.ui.booklist_menu.item_table)

    local chooser = self.ui and self.ui.file_chooser
    if chooser then
        local items = chooser.item_table
        if chooser.getList and chooser.path then
            local ok, result = pcall(function()
                if chooser.getCollate then
                    return chooser:getList(chooser.path, chooser:getCollate())
                end
                return chooser:getList(chooser.path)
            end)
            if ok and type(result) == "table" then
                items = result
            end
        end
        addItemPaths(items)
    end

    return paths
end

function CWASync:getLibraryRootPath()
    local chooser = self.ui and self.ui.file_chooser
    if chooser and chooser.path and util.directoryExists(chooser.path) then
        return chooser.path
    end

    local home_dir = G_reader_settings:readSetting("home_dir")
    if home_dir and util.directoryExists(home_dir) then
        return home_dir
    end

    local lastdir = G_reader_settings:readSetting("lastdir")
    if lastdir and util.directoryExists(lastdir) then
        return lastdir
    end

    if Device.home_dir and util.directoryExists(Device.home_dir) then
        return Device.home_dir
    end

    return nil
end

function CWASync:getLibraryBooksForSync()
    local paths = self:getLibraryBookPaths()
    if #paths > 0 then
        logger.dbg("CWASync: [Bulk Pull] using current view paths", #paths)
        return paths, false, nil
    end

    local root_path = self:getLibraryRootPath()
    if not root_path then
        logger.dbg("CWASync: [Bulk Pull] no library root available for fallback scan")
        return {}, false, nil
    end

    logger.dbg("CWASync: [Bulk Pull] scanning fallback root", root_path)

    local document_registry_ok, DocumentRegistry = pcall(require, "document/documentregistry")
    local seen = {}
    paths = {}

    util.findFiles(root_path, function(path)
        if seen[path] then
            return
        end
        if document_registry_ok and DocumentRegistry and DocumentRegistry.hasProvider then
            local ok, has_provider = pcall(DocumentRegistry.hasProvider, DocumentRegistry, path)
            if ok and has_provider then
                seen[path] = true
                paths[#paths + 1] = path
            end
        end
    end, true)

    logger.dbg("CWASync: [Bulk Pull] fallback scan found", #paths, "supported books under", root_path)

    return paths, true, root_path
end

function CWASync:refreshLibraryViews(changed_files)
    if type(changed_files) ~= "table" or #changed_files == 0 then
        return
    end

    logger.dbg("CWASync: [Refresh] invalidating metadata for", #changed_files, "books")
    for _, file_path in ipairs(changed_files) do
        BookList.resetBookInfoCache(file_path)

        if self.ui and self.ui.file_chooser and self.ui.file_chooser.resetBookInfoCache then
            self.ui.file_chooser.resetBookInfoCache(file_path)
        end
        if self.ui and self.ui.booklist_menu and self.ui.booklist_menu.resetBookInfoCache then
            self.ui.booklist_menu.resetBookInfoCache(file_path)
        end

        UIManager:broadcastEvent(Event:new("InvalidateMetadataCache", file_path))
    end
    UIManager:broadcastEvent(Event:new("BookMetadataChanged"))

    local refreshed = {}
    local function refreshMenu(menu, name)
        if type(menu) ~= "table" or type(menu.updateItems) ~= "function" or refreshed[menu] then
            return
        end
        refreshed[menu] = true
        logger.dbg("CWASync: [Refresh] refreshing", name)
        menu.no_refresh_covers = nil
        menu:updateItems(1, true)
    end

    refreshMenu(self.ui and self.ui.file_chooser, "file chooser")
    refreshMenu(self.ui and self.ui.booklist_menu, "book list menu")
    refreshMenu(self.ui and self.ui.menu, "menu")

    if self.ui and type(self.ui.getMenuInstance) == "function" then
        refreshMenu(self.ui:getMenuInstance(), "active menu instance")
    end
end

function CWASync:applyProgressToBook(file_path, progress, percentage)
    local DocSettings = require("docsettings")
    local doc_settings = DocSettings:open(file_path)
    local summary = doc_settings:readSetting("summary") or {}
    local previous_percent = doc_settings:readSetting("percent_finished")
    local previous_page = doc_settings:readSetting("last_page")
    local previous_xpointer = doc_settings:readSetting("last_xpointer")
    local previous_status = summary.status
    local new_page = tonumber(progress)
    local new_xpointer = new_page == nil and progress or nil

    logger.dbg("CWASync: [Apply] start for", file_path)
    logger.dbg("CWASync: [Apply] previous settings", {
        percent_finished = previous_percent,
        last_page = previous_page,
        last_xpointer = previous_xpointer,
        status = previous_status,
    })

    doc_settings:saveSetting("percent_finished", percentage)
    if new_page ~= nil then
        doc_settings:saveSetting("last_page", new_page)
        if doc_settings.delSetting then
            doc_settings:delSetting("last_xpointer")
        end
    else
        doc_settings:saveSetting("last_xpointer", progress)
        if doc_settings.delSetting then
            doc_settings:delSetting("last_page")
        end
    end

    if percentage >= 1 then
        summary.status = "complete"
    elseif summary.status == "complete" then
        summary.status = "reading"
    end
    doc_settings:saveSetting("summary", summary)

    logger.dbg("CWASync: [Apply] new settings", {
        percent_finished = percentage,
        last_page = new_page,
        last_xpointer = new_xpointer,
        status = summary.status,
    })

    doc_settings:flush()

    local changed = SyncLogic.didBookProgressChange({
        percent_finished = previous_percent,
        last_page = previous_page,
        last_xpointer = previous_xpointer,
        status = previous_status,
    }, {
        percent_finished = percentage,
        last_page = new_page,
        last_xpointer = new_xpointer,
        status = summary.status,
    })
    logger.dbg("CWASync: [Apply] result for", file_path, changed and "changed" or "unchanged")
    logger.dbg("CWASync: [Apply] finished for", file_path)
    return changed
end

function CWASync:pullLibraryProgress(ensure_networking)
    if not self.settings.username or not self.settings.password then
        promptLogin()
        return
    end

    if not ensureServerConfigured(self.settings.server) then
        return
    end

    local now = UIManager:getElapsedTimeSinceBoot()
    if ensure_networking and NetworkMgr:willRerunWhenOnline(function() self:pullLibraryProgress(ensure_networking) end) then
        return
    end

    logger.dbg("CWASync: [Bulk Pull] start")

    local paths, used_root_scan, root_path = self:getLibraryBooksForSync()
    if #paths == 0 then
        logger.dbg("CWASync: [Bulk Pull] end with no books found")
        UIManager:show(InfoMessage:new{
            text = used_root_scan and T(_("No supported books were found under %1."), root_path)
                or _("No books were found in the current library view."),
            timeout = 3,
        })
        return
    end

    local CWASyncClient = require("CWASyncClient")
    local client = CWASyncClient:new{
        service_url = self.settings.server .. "/kosync",
        service_spec = self.path .. "/api.json"
    }

    local index = 1
    local remote_found = 0
    local changed = 0
    local missing = 0
    local failed = 0
    local changed_files = {}

    local function finish()
        self.pull_timestamp = now
        self:refreshLibraryViews(changed_files)
        logger.dbg("CWASync: [Bulk Pull] end", {
            remote_found = remote_found,
            changed = changed,
            missing = missing,
            failed = failed,
            used_root_scan = used_root_scan,
            root_path = root_path,
        })
        UIManager:show(InfoMessage:new{
            text = T(_("Library sync finished. Remote progress: %1, changed: %2, no remote progress: %3, failed: %4."), remote_found, changed, missing, failed),
            timeout = 5,
        })
    end

    local function pullNextBook()
        local file_path = paths[index]
        index = index + 1

        if not file_path then
            finish()
            return
        end

        logger.dbg("CWASync: [Bulk Pull] syncing path", file_path)

        local doc_digest = self:getDocumentDigest(file_path)
        if not doc_digest then
            logger.warn("CWASync: Unable to compute document digest for", file_path)
            failed = failed + 1
            pullNextBook()
            return
        end

        local ok, err = pcall(client.get_progress,
            client,
            self.settings.username,
            self.settings.password,
            doc_digest,
            function(request_ok, body)
                logger.dbg("CWASync: [Bulk Pull] server response for", file_path, "ok=", request_ok, "body=", body)
                if not request_ok or type(body) ~= "table" then
                    failed = failed + 1
                    pullNextBook()
                    return
                end

                if not body.percentage or body.progress == nil then
                    missing = missing + 1
                    pullNextBook()
                    return
                end

                if SyncLogic.isRemoteProgressFromThisDevice(body, Device.model, self.device_id) then
                    logger.dbg("CWASync: [Bulk Pull] skipping same-device progress for", file_path)
                    pullNextBook()
                    return
                end

                local percentage = Math.roundPercent(tonumber(body.percentage) or 0)
                remote_found = remote_found + 1
                local apply_ok, changed_or_err = pcall(self.applyProgressToBook, self, file_path, body.progress, percentage)
                if apply_ok then
                    if changed_or_err then
                        changed = changed + 1
                        changed_files[#changed_files + 1] = file_path
                    end
                    logger.dbg("CWASync: [Bulk Pull] applied remote progress for", file_path)
                else
                    logger.dbg("CWASync: failed applying pulled progress for", file_path, changed_or_err)
                    failed = failed + 1
                end
                pullNextBook()
            end)
        if not ok then
            logger.dbg("CWASync: failed pulling library progress for", file_path, err)
            failed = failed + 1
            pullNextBook()
        end
    end

    pullNextBook()
end

function CWASync:syncToProgress(progress)
    logger.dbg("CWASync: [Sync] progress to", progress)
    if self.ui.document.info.has_pages then
        self.ui:handleEvent(Event:new("GotoPage", tonumber(progress)))
    else
        self.ui:handleEvent(Event:new("GotoXPointer", progress))
    end
end

function CWASync:updateProgress(ensure_networking, interactive, on_suspend)
    if not self.settings.username or not self.settings.password then
        if interactive then
            promptLogin()
        end
        return
    end

    if not self:hasCurrentDocument() then
        if interactive then
            showNoBookMessage()
        end
        return
    end

    if not ensureServerConfigured(self.settings.server) then
        return
    end

    local now = UIManager:getElapsedTimeSinceBoot()
    if not interactive and now - self.push_timestamp <= API_CALL_DEBOUNCE_DELAY then
        logger.dbg("CWASync: We've already pushed progress less than 25s ago!")
        return
    end

    if ensure_networking and NetworkMgr:willRerunWhenOnline(function() self:updateProgress(ensure_networking, interactive, on_suspend) end) then
        return
    end

    local CWASyncClient = require("CWASyncClient")
    local client = CWASyncClient:new{
        service_url = self.settings.server .. "/kosync",
        service_spec = self.path .. "/api.json"
    }
    local current_file = self:getCurrentDocumentFile()
    logger.dbg("CWASync: [Push] start for", current_file)
    local doc_digest = self:getDocumentDigest()
    if not doc_digest then
        logger.warn("CWASync: Unable to compute document digest for", current_file)
        if interactive then
            UIManager:show(InfoMessage:new{
                text = _("Unable to compute document checksum for this book."),
                timeout = 3,
            })
        end
        return
    end
    local progress = self:getLastProgress()
    local percentage = self:getLastPercent()
    logger.dbg("CWASync: [Push] payload", {
        file = current_file,
        document = doc_digest,
        progress = progress,
        percentage = percentage,
        device = Device.model,
        device_id = self.device_id,
    })
    local ok, err = pcall(client.update_progress,
        client,
        self.settings.username,
        self.settings.password,
        doc_digest,
        progress,
        percentage,
        Device.model,
        self.device_id,
        function(ok, body)
            logger.dbg("CWASync: [Push] progress to", percentage * 100, "% =>", progress, "for", self.view.document.file)
            logger.dbg("CWASync: ok:", ok, "body:", body)
            if interactive then
                if ok then
                    UIManager:show(InfoMessage:new{
                        text = _("Progress has been pushed."),
                        timeout = 3,
                    })
                else
                    showSyncError()
                end
            end
        end)
    if not ok then
        if interactive then showSyncError() end
        if err then logger.dbg("err:", err) end
        logger.dbg("CWASync: [Push] request setup failed for", current_file, err)
    else
        -- This is solely for onSuspend's sake, to clear the ghosting left by the "Connected" InfoMessage
        if on_suspend then
            -- Our top-level widget should be the "Connected to network" InfoMessage from NetworkMgr's reconnectOrShowNetworkMenu
            local widget = UIManager:getTopmostVisibleWidget()
            if widget and widget.modal and widget.tag == "NetworkMgr" and not widget.dismiss_callback then
                -- We want a full-screen flash on dismiss
                widget.dismiss_callback = function()
                    -- Enqueued, because we run before the InfoMessage's close
                    UIManager:setDirty(nil, "full")
                end
            end
        end
    end

    if on_suspend then
        -- NOTE: We want to murder Wi-Fi once we're done in this specific case (i.e., Suspend),
        --       because some of our hasWifiManager targets will horribly implode when attempting to suspend with the Wi-Fi chip powered on,
        --       and they'll have attempted to kill Wi-Fi well before *we* run (e.g., in `Device:onPowerEvent`, *before* actually sending the Suspend Event)...
        if Device:hasWifiManager() then
            NetworkMgr:disableWifi()
        end
    end

    self.push_timestamp = now
end

function CWASync:getProgress(ensure_networking, interactive)
    if not self.settings.username or not self.settings.password then
        if interactive then
            promptLogin()
        end
        return
    end

    if not self:hasCurrentDocument() then
        if interactive then
            local root_path = self:getLibraryRootPath()
            UIManager:show(ConfirmBox:new{
                text = root_path
                    and T(_("No book is currently open. Pull progress for all books under %1?"), root_path)
                    or _("No book is currently open. Pull progress for all books in the current library view?"),
                ok_callback = function()
                    self:pullLibraryProgress(ensure_networking)
                end,
            })
        end
        return
    end

    if not ensureServerConfigured(self.settings.server) then
        return
    end

    local now = UIManager:getElapsedTimeSinceBoot()
    if not interactive and now - self.pull_timestamp <= API_CALL_DEBOUNCE_DELAY then
        logger.dbg("CWASync: We've already pulled progress less than 25s ago!")
        return
    end

    if ensure_networking and NetworkMgr:willRerunWhenOnline(function() self:getProgress(ensure_networking, interactive) end) then
        return
    end

    local CWASyncClient = require("CWASyncClient")
    local client = CWASyncClient:new{
        service_url = self.settings.server .. "/kosync",
        service_spec = self.path .. "/api.json"
    }
    local current_file = self:getCurrentDocumentFile()
    logger.dbg("CWASync: [Pull] start for", current_file)
    local doc_digest = self:getDocumentDigest()
    if not doc_digest then
        logger.warn("CWASync: Unable to compute document digest for", current_file)
        if interactive then
            UIManager:show(InfoMessage:new{
                text = _("Unable to compute document checksum for this book."),
                timeout = 3,
            })
        end
        return
    end
    local ok, err = pcall(client.get_progress,
        client,
        self.settings.username,
        self.settings.password,
        doc_digest,
        function(ok, body)
            logger.dbg("CWASync: [Pull] progress for", self.view.document.file)
            logger.dbg("CWASync: ok:", ok, "body:", body)

            if not ok or not body then
                logger.dbg("CWASync: [Pull] end for", current_file, "with failure")
                if interactive then
                    showSyncError()
                end
                return
            end

            -- Some older KOReader Spore versions can return the raw JSON string
            -- rather than a Lua table as the body.
            if type(body) == "string" and body:find("^(%s*){") ~= nil then
                logger.dbg("CWASync: attempting to decode body payload as json string")
                local decoded_ok, decoded_body = pcall(function()
                    return Json.decode(body)
                end)
                body = decoded_body
                if interactive and not decoded_ok then
                    showSyncError()
                    return
                end
            end

            if type(body) ~= "table" then
                logger.dbg("CWASync: [Pull] end for", current_file, "with invalid body")
                if interactive then
                    showSyncError()
                end
                return
            end

            if not body.percentage then
                logger.dbg("CWASync: [Pull] end for", current_file, "with no remote progress")
                if interactive then
                    UIManager:show(InfoMessage:new{
                        text = _("No progress found for this document."),
                        timeout = 3,
                    })
                end
                return
            end

            if body.progress == nil then
                logger.dbg("CWASync: [Pull] end for", current_file, "with missing progress field")
                if interactive then
                    showSyncError()
                end
                return
            end

            if SyncLogic.isRemoteProgressFromThisDevice(body, Device.model, self.device_id) then
                logger.dbg("CWASync: [Pull] end for", current_file, "latest progress already belongs to this device")
                if interactive then
                    UIManager:show(InfoMessage:new{
                        text = _("Latest progress is coming from this device."),
                        timeout = 3,
                    })
                end
                return
            end

            body.percentage = Math.roundPercent(tonumber(body.percentage) or 0)
            local progress = self:getLastProgress()
            local percentage = self:getLastPercent()
            logger.dbg("CWASync: Current progress:", percentage * 100, "% =>", progress)

            if percentage == body.percentage
            or body.progress == progress then
                logger.dbg("CWASync: [Pull] end for", current_file, "progress already synchronized")
                if interactive then
                    UIManager:show(InfoMessage:new{
                        text = _("The progress has already been synchronized."),
                        timeout = 3,
                    })
                end
                return
            end

            -- The progress needs to be updated.
            if interactive then
                -- If user actively pulls progress from other devices,
                -- we always update the progress without further confirmation.
                self:syncToProgress(body.progress)
                showSyncedMessage()
                logger.dbg("CWASync: [Pull] end for", current_file, "interactive sync applied", {
                    remote_progress = body.progress,
                    remote_percentage = body.percentage,
                })
                return
            end

            local self_older
            if body.timestamp ~= nil then
                self_older = (body.timestamp > self.last_page_turn_timestamp)
            else
                -- If we are working with an old sync server, we can only use the percentage field.
                self_older = (body.percentage > percentage)
            end
            if self_older then
                if self.settings.sync_forward == SYNC_STRATEGY.SILENT then
                    self:syncToProgress(body.progress)
                    showSyncedMessage()
                    logger.dbg("CWASync: [Pull] end for", current_file, "auto-applied newer remote progress")
                elseif self.settings.sync_forward == SYNC_STRATEGY.PROMPT then
                    logger.dbg("CWASync: [Pull] awaiting prompt to apply newer remote progress for", current_file)
                    UIManager:show(ConfirmBox:new{
                        text = T(_("Sync to latest location %1% from device '%2'?"),
                                 Math.round(body.percentage * 100),
                                 body.device),
                        ok_callback = function()
                            self:syncToProgress(body.progress)
                        end,
                    })
                end
            else -- if not self_older then
                if self.settings.sync_backward == SYNC_STRATEGY.SILENT then
                    self:syncToProgress(body.progress)
                    showSyncedMessage()
                    logger.dbg("CWASync: [Pull] end for", current_file, "auto-applied older remote progress")
                elseif self.settings.sync_backward == SYNC_STRATEGY.PROMPT then
                    logger.dbg("CWASync: [Pull] awaiting prompt to apply older remote progress for", current_file)
                    UIManager:show(ConfirmBox:new{
                        text = T(_("Sync to previous location %1% from device '%2'?"),
                                 Math.round(body.percentage * 100),
                                 body.device),
                        ok_callback = function()
                            self:syncToProgress(body.progress)
                        end,
                    })
                end
            end
        end)
    if not ok then
        if interactive then showSyncError() end
        if err then logger.dbg("err:", err) end
        logger.dbg("CWASync: [Pull] request setup failed for", current_file, err)
    end

    self.pull_timestamp = now
end

function CWASync:_onCloseDocument()
    logger.dbg("CWASync: onCloseDocument")
    -- NOTE: Because everything is terrible, on Android, opening the system settings to enable WiFi means we lose focus,
    --       and we handle those system focus events via... Suspend & Resume events, so we need to neuter those handlers early.
    self.onResume = nil
    self.onSuspend = nil
    -- NOTE: Because we'll lose the document instance on return, we need to *block* until the connection is actually up here,
    --       we cannot rely on willRerunWhenOnline, because if we're not currently online,
    --       it *will* return early, and that means the actual callback *will* run *after* teardown of the document instance
    --       (and quite likely ours, too).
    NetworkMgr:goOnlineToRun(function()
        -- Drop the inner willRerunWhenOnline ;).
        self:updateProgress(false, false)
    end)
end

function CWASync:schedulePeriodicPush()
    UIManager:unschedule(self.periodic_push_task)
    -- Use a sizable delay to make debouncing this on skim feasible...
    UIManager:scheduleIn(10, self.periodic_push_task)
    self.periodic_push_scheduled = true
end

function CWASync:_onPageUpdate(page)
    if page == nil then
        return
    end

    if self.last_page ~= page then
        self.last_page = page
        self.last_page_turn_timestamp = os.time()
        self.page_update_counter = self.page_update_counter + 1
        -- If we've already scheduled a push, regardless of the counter's state, delay it until we're *actually* idle
        if self.periodic_push_scheduled or self.settings.pages_before_update and self.page_update_counter >= self.settings.pages_before_update then
            self:schedulePeriodicPush()
        end
    end
end

function CWASync:_onResume()
    logger.dbg("CWASync: onResume")
    -- If we have auto_restore_wifi enabled, skip this to prevent both the "Connecting..." UI to pop-up,
    -- *and* a duplicate NetworkConnected event from firing...
    if Device:hasWifiRestore() and NetworkMgr.wifi_was_on and G_reader_settings:isTrue("auto_restore_wifi") then
        return
    end

    -- And if we don't, this *will* (attempt to) trigger a connection and as such a NetworkConnected event,
    -- but only a single pull will happen, since getProgress debounces itself.
    UIManager:scheduleIn(1, function()
        self:getProgress(true, false)
    end)
end

function CWASync:_onSuspend()
    logger.dbg("CWASync: onSuspend")
    -- We request an extra flashing refresh on success, to deal with potential ghosting left by the NetworkMgr UI
    self:updateProgress(true, false, true)
end

function CWASync:_onNetworkConnected()
    logger.dbg("CWASync: onNetworkConnected")
    UIManager:scheduleIn(0.5, function()
        -- Network is supposed to be on already, don't wrap this in willRerunWhenOnline
        self:getProgress(false, false)
    end)
end

function CWASync:_onNetworkDisconnecting()
    logger.dbg("CWASync: onNetworkDisconnecting")
    -- Network is supposed to be on already, don't wrap this in willRerunWhenOnline
    self:updateProgress(false, false)
end

function CWASync:onCWASyncPushProgress()
    self:updateProgress(true, true)
end

function CWASync:onCWASyncPullProgress()
    self:getProgress(true, true)
end

function CWASync:registerEvents()
    if self.settings.auto_sync then
        self.onCloseDocument = self._onCloseDocument
        self.onPageUpdate = self._onPageUpdate
        self.onResume = self._onResume
        self.onSuspend = self._onSuspend
        self.onNetworkConnected = self._onNetworkConnected
        self.onNetworkDisconnecting = self._onNetworkDisconnecting
    else
        self.onCloseDocument = nil
        self.onPageUpdate = nil
        self.onResume = nil
        self.onSuspend = nil
        self.onNetworkConnected = nil
        self.onNetworkDisconnecting = nil
    end
end

function CWASync:onCloseWidget()
    UIManager:unschedule(self.periodic_push_task)
    self.periodic_push_task = nil
end

return CWASync
