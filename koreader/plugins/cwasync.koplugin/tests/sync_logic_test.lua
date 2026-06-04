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

local function assertTrue(cond, message)
    if not cond then error(message, 2) end
end

local function findById(list, id)
    for _, a in ipairs(list) do
        if a.annotation_id == id then return a end
    end
    return nil
end

-- Phase 2: annotation merge (last-synced-wins; position immutable).
local function testMergeAnnotation()
    local older = { annotation_id = "x", color = "yellow", note_text = "old",
                    hidden = false, start_kobospan = "kobo.1.1", last_synced = "2026-05-01T00:00:00Z" }
    local newer = { annotation_id = "x", color = "red", note_text = "new",
                    hidden = false, start_kobospan = "kobo.1.1", last_synced = "2026-05-02T00:00:00Z" }
    local m = SyncLogic.mergeAnnotation(older, newer)
    assertEqual(m.color, "red", "newer color wins")
    assertEqual(m.note_text, "new", "newer note wins")
    -- order-independent: newer is still the winner when args are swapped
    local m2 = SyncLogic.mergeAnnotation(newer, older)
    assertEqual(m2.color, "red", "newer wins regardless of arg order")
    -- a newer delete wins (delete honored)
    local del = { annotation_id = "x", hidden = true, last_synced = "2026-05-03T00:00:00Z" }
    assertEqual(SyncLogic.mergeAnnotation(newer, del).hidden, true, "newer delete wins")
    -- position preserved even if the newer payload omits it
    assertEqual(SyncLogic.mergeAnnotation(older, del).start_kobospan, "kobo.1.1", "position immutable / preserved")
end

-- Phase 2: diff (which annotations flow to the device vs the server).
local function testDiffAnnotations()
    local localList = {
        { annotation_id = "both-local-newer", color = "red",    last_synced = "2026-05-02T00:00:00Z" },
        { annotation_id = "both-equal",       color = "yellow", last_synced = "2026-05-01T00:00:00Z" },
        { annotation_id = "local-only",       color = "green",  last_synced = "2026-05-01T00:00:00Z" },
        { annotation_id = "both-remote-newer",color = "yellow", last_synced = "2026-05-01T00:00:00Z" },
    }
    local remoteList = {
        { annotation_id = "both-local-newer", color = "yellow", last_synced = "2026-05-01T00:00:00Z" },
        { annotation_id = "both-equal",       color = "yellow", last_synced = "2026-05-01T00:00:00Z" },
        { annotation_id = "remote-only",      color = "blue",   last_synced = "2026-05-01T00:00:00Z" },
        { annotation_id = "both-remote-newer",color = "blue",   last_synced = "2026-05-09T00:00:00Z" },
    }

    local d = SyncLogic.diffAnnotations(localList, remoteList)

    -- apply_to_device: remote-only + both-remote-newer
    assertTrue(findById(d.apply_to_device, "remote-only") ~= nil, "remote-only applies to device")
    assertTrue(findById(d.apply_to_device, "both-remote-newer") ~= nil, "remote-newer applies to device")
    assertTrue(findById(d.apply_to_device, "both-equal") == nil, "converged row not re-applied (no echo)")
    assertTrue(findById(d.apply_to_device, "local-only") == nil, "local-only never applies to device")

    -- send_to_server: local-only + both-local-newer
    assertTrue(findById(d.send_to_server, "local-only") ~= nil, "local-only pushes to server")
    assertTrue(findById(d.send_to_server, "both-local-newer") ~= nil, "local-newer pushes to server")
    assertTrue(findById(d.send_to_server, "both-equal") == nil, "converged row not re-pushed (no echo)")
end

testIsRemoteProgressFromThisDevice()
testDidBookProgressChange()
testMergeAnnotation()
testDiffAnnotations()

print("sync_logic tests passed")
