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

return SyncLogic
