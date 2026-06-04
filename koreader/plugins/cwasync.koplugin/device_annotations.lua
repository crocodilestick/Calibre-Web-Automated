--[[
Device-write provider seam (Phase 2, generic transport).

Selects how annotations the server says belong on this device get written
locally. Today there is one provider — KoboReader.sqlite (Kobo only), which
puts highlights onto stock Nickel. A KOReader-native (`.sdr` sidecar) provider
that works on every KOReader device is a future addition behind this same
interface; nothing else in the plugin needs to change when it lands.

Provider interface:
    available()                       -> bool   (is this provider usable here?)
    readAll(volume_id)                -> list    (device's annotations, portable)
    applyToDevice(portables, vol_id)  -> count   (write server annotations locally)
    backup()                          -> path|false
]]--

local DeviceAnnotations = {}

local PROVIDERS = {
    require("kobo_sqlite_provider"),
    -- future: require("koreader_sdr_provider"),
}

-- First provider that reports itself usable on this device, or nil.
function DeviceAnnotations.getProvider()
    for _, p in ipairs(PROVIDERS) do
        local ok, usable = pcall(p.available)
        if ok and usable then
            return p
        end
    end
    return nil
end

function DeviceAnnotations.available()
    return DeviceAnnotations.getProvider() ~= nil
end

return DeviceAnnotations
