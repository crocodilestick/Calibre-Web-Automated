-- Cloned from https://github.com/koreader/koreader/tree/master/plugins/cwasync.koplugin

local _ = require("gettext")
return {
    name = "cwasync",
    fullname = _("NextGen Progress Sync"),
    description = _([[Synchronizes your reading progress to Calibre-Web NextGen and across your KOReader devices.]]),
    version = "4.0.166",  -- Updates Manager reads this; keep in lockstep with main.lua and the CWNG release tag
}
