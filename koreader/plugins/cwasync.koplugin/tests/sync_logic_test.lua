package.path = table.concat({
    "./?.lua",
    "../?.lua",
    package.path,
}, ";")

local SyncLogic = require("sync_logic")

local function assertEqual(actual, expected, message)
    if actual ~= expected then
        error(string.format("%s\nexpected: %s\nactual: %s", message, tostring(expected), tostring(actual)), 2)
    end
end

local function testIsRemoteProgressFromThisDevice()
    assertEqual(SyncLogic.isRemoteProgressFromThisDevice({ device = "Foo", device_id = "abc" }, "Foo", "abc"), true,
        "same device payload should match")
    assertEqual(SyncLogic.isRemoteProgressFromThisDevice({ device = "Foo", device_id = "xyz" }, "Foo", "abc"), false,
        "different device_id should not match")
    assertEqual(SyncLogic.isRemoteProgressFromThisDevice({ device = "Bar", device_id = "abc" }, "Foo", "abc"), false,
        "different device model should not match")
    assertEqual(SyncLogic.isRemoteProgressFromThisDevice(nil, "Foo", "abc"), false,
        "non-table payload should not match")
end

local function testDidBookProgressChange()
    local previous = {
        percent_finished = 0.5,
        last_page = 12,
        last_xpointer = nil,
        status = "reading",
    }
    assertEqual(SyncLogic.didBookProgressChange(previous, {
        percent_finished = 0.5,
        last_page = 12,
        last_xpointer = nil,
        status = "reading",
    }), false, "identical state should not count as changed")
    assertEqual(SyncLogic.didBookProgressChange(previous, {
        percent_finished = 1,
        last_page = 12,
        last_xpointer = nil,
        status = "complete",
    }), true, "percent/status changes should count as changed")
    assertEqual(SyncLogic.didBookProgressChange(previous, {
        percent_finished = 0.5,
        last_page = nil,
        last_xpointer = "/body/1/4",
        status = "reading",
    }), true, "switching from page to xpointer should count as changed")
end

testIsRemoteProgressFromThisDevice()
testDidBookProgressChange()

print("sync_logic tests passed")
