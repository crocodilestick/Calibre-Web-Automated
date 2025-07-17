local UIManager = require("ui/uimanager")
local logger = require("logger")
local socketutil = require("socketutil")

-- Push/Pull
local PROGRESS_TIMEOUTS = { 2,  5 }
-- Authentication
local AUTH_TIMEOUTS     = { 5, 10 }

local CWASyncClient = {
    service_spec = nil,
    service_url = nil,
}

function CWASyncClient:new(o)
    if o == nil then o = {} end
    setmetatable(o, self)
    self.__index = self
    if o.init then o:init() end
    return o
end

function CWASyncClient:init()
    local Spore = require("Spore")
    self.client = Spore.new_from_spec(self.service_spec, {
        base_url = self.service_url,
    })
    package.loaded["Spore.Middleware.GinClient"] = {}
    require("Spore.Middleware.GinClient").call = function(_, req)
        req.headers["accept"] = "application/vnd.koreader.v1+json"
    end
    package.loaded["Spore.Middleware.CWASyncAuth"] = {}
    require("Spore.Middleware.CWASyncAuth").call = function(args, req)
        -- Use HTTP Basic Authentication
        local credentials = args.username .. ":" .. args.password
        -- Base64 encode the credentials (compatible implementation)
        local base64_chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
        local function base64_encode(data)
            local encoded = ""
            local i = 1
            while i <= #data do
                local a = string.byte(data, i) or 0
                local b = string.byte(data, i + 1) or 0
                local c = string.byte(data, i + 2) or 0

                -- Use bit operations compatible with Lua 5.1+
                local bitmap = a * 65536 + b * 256 + c

                -- Extract 6-bit chunks
                local c1 = math.floor(bitmap / 262144) % 64  -- bits 18-23
                local c2 = math.floor(bitmap / 4096) % 64    -- bits 12-17
                local c3 = math.floor(bitmap / 64) % 64      -- bits 6-11
                local c4 = bitmap % 64                       -- bits 0-5

                encoded = encoded .. string.sub(base64_chars, c1 + 1, c1 + 1)
                encoded = encoded .. string.sub(base64_chars, c2 + 1, c2 + 1)

                if i + 1 <= #data then
                    encoded = encoded .. string.sub(base64_chars, c3 + 1, c3 + 1)
                else
                    encoded = encoded .. "="
                end

                if i + 2 <= #data then
                    encoded = encoded .. string.sub(base64_chars, c4 + 1, c4 + 1)
                else
                    encoded = encoded .. "="
                end

                i = i + 3
            end
            return encoded
        end

        local base64_credentials = base64_encode(credentials)
        req.headers["Authorization"] = "Basic " .. base64_credentials
    end
    package.loaded["Spore.Middleware.AsyncHTTP"] = {}
    require("Spore.Middleware.AsyncHTTP").call = function(args, req)
        -- disable async http if Turbo looper is missing
        if not UIManager.looper then return end
        req:finalize()
        local result
        require("httpclient"):new():request({
            url = req.url,
            method = req.method,
            body = req.env.spore.payload,
            on_headers = function(headers)
                for header, value in pairs(req.headers) do
                    if type(header) == "string" then
                        headers:add(header, value)
                    end
                end
            end,
        }, function(res)
            result = res
            -- Turbo HTTP client uses code instead of status
            -- change to status so that Spore can understand
            result.status = res.code
            coroutine.resume(args.thread)
        end)
        return coroutine.create(function() coroutine.yield(result) end)
    end
end

function CWASyncClient:authorize(username, password)
    self.client:reset_middlewares()
    self.client:enable("Format.JSON")
    self.client:enable("GinClient")
    self.client:enable("CWASyncAuth", {
        username = username,
        password = password,
    })
    socketutil:set_timeout(AUTH_TIMEOUTS[1], AUTH_TIMEOUTS[2])
    local ok, res = pcall(function()
        return self.client:authorize()
    end)
    socketutil:reset_timeout()
    if ok then
        return res.status == 200, res.body
    else
        logger.dbg("CWASyncClient:authorize failure:", res)
        return false, res.body
    end
end

function CWASyncClient:update_progress(
        username,
        password,
        document,
        progress,
        percentage,
        device,
        device_id,
        callback)
    self.client:reset_middlewares()
    self.client:enable("Format.JSON")
    self.client:enable("GinClient")
    self.client:enable("CWASyncAuth", {
        username = username,
        password = password,
    })
    -- Set *very* tight timeouts to avoid blocking for too long...
    socketutil:set_timeout(PROGRESS_TIMEOUTS[1], PROGRESS_TIMEOUTS[2])
    local co = coroutine.create(function()
        local ok, res = pcall(function()
            return self.client:update_progress({
                document = document,
                progress = tostring(progress),
                percentage = percentage,
                device = device,
                device_id = device_id,
            })
        end)
        if ok then
            callback(res.status == 200, res.body)
        else
            logger.dbg("CWASyncClient:update_progress failure:", res)
            callback(false, res.body)
        end
    end)
    self.client:enable("AsyncHTTP", {thread = co})
    coroutine.resume(co)
    if UIManager.looper then UIManager:setInputTimeout() end
    socketutil:reset_timeout()
end

function CWASyncClient:get_progress(
        username,
        password,
        document,
        callback)
    self.client:reset_middlewares()
    self.client:enable("Format.JSON")
    self.client:enable("GinClient")
    self.client:enable("CWASyncAuth", {
        username = username,
        password = password,
    })
    socketutil:set_timeout(PROGRESS_TIMEOUTS[1], PROGRESS_TIMEOUTS[2])
    local co = coroutine.create(function()
        local ok, res = pcall(function()
            return self.client:get_progress({
                document = document,
            })
        end)
        if ok then
            callback(res.status == 200, res.body)
        else
            logger.dbg("CWASyncClient:get_progress failure:", res)
            callback(false, res.body)
        end
    end)
    self.client:enable("AsyncHTTP", {thread = co})
    coroutine.resume(co)
    if UIManager.looper then UIManager:setInputTimeout() end
    socketutil:reset_timeout()
end

return CWASyncClient
