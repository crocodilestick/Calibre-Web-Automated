local SyncLogic = {}

function SyncLogic.isRemoteProgressFromThisDevice(body, device_model, device_id)
    return type(body) == "table"
        and body.device == device_model
        and body.device_id == device_id
end

function SyncLogic.didBookProgressChange(previous, new_values)
    return previous.percent_finished ~= new_values.percent_finished
        or previous.last_page ~= new_values.last_page
        or previous.last_xpointer ~= new_values.last_xpointer
        or previous.status ~= new_values.status
end

-- Phase 2: annotation sync. Annotations are portable tables (see the server's
-- cps/services/annotation_portable.py) keyed by `annotation_id`. Conflict rule:
-- last-`last_synced`-wins per field; position is immutable; a delete (hidden)
-- wins when it is the latest action. ISO-8601 `last_synced` strings sort
-- lexicographically in timestamp order, so plain string comparison works.

function SyncLogic.mergeAnnotation(a, b)
    local newer, older
    if (b.last_synced or "") >= (a.last_synced or "") then
        newer, older = b, a
    else
        newer, older = a, b
    end
    local out = {}
    for k, v in pairs(older) do out[k] = v end
    for k, v in pairs(newer) do
        if v ~= nil then out[k] = v end
    end
    -- Position is immutable: a delete/partial payload may omit the anchor;
    -- keep whatever the records established at creation time.
    if out.start_kobospan == nil then out.start_kobospan = older.start_kobospan end
    if out.end_kobospan == nil then out.end_kobospan = older.end_kobospan end
    if out.content_id == nil then out.content_id = older.content_id end
    return out
end

-- Given the device's local annotations and the server's pulled annotations,
-- return { apply_to_device = {...}, send_to_server = {...} }:
--   * remote-only            -> apply_to_device
--   * local-only             -> send_to_server
--   * in both, remote newer  -> apply_to_device (merged)
--   * in both, local newer   -> send_to_server (merged)
--   * in both, equal         -> converged, emitted to neither (no feedback loop)
function SyncLogic.diffAnnotations(localList, remoteList)
    local function byId(list)
        local m = {}
        for _, a in ipairs(list or {}) do
            if a.annotation_id then m[a.annotation_id] = a end
        end
        return m
    end
    local L = byId(localList)
    local R = byId(remoteList)
    local apply_to_device, send_to_server = {}, {}
    for id, r in pairs(R) do
        local l = L[id]
        if not l then
            table.insert(apply_to_device, r)
        else
            local rt = r.last_synced or ""
            local lt = l.last_synced or ""
            if rt > lt then
                table.insert(apply_to_device, SyncLogic.mergeAnnotation(l, r))
            elseif lt > rt then
                table.insert(send_to_server, SyncLogic.mergeAnnotation(r, l))
            end
        end
    end
    for id, l in pairs(L) do
        if not R[id] then
            table.insert(send_to_server, l)
        end
    end
    return { apply_to_device = apply_to_device, send_to_server = send_to_server }
end

return SyncLogic
