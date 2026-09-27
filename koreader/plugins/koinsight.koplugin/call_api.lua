local socketutil = require("socketutil")
local ltn12 = require("ltn12")
local logger = require("logger")
local socket = require("socket")
local http = require("socket.http")
local UIManager = require("ui/uimanager")
local JSON = require("json")
local InfoMessage = require("ui/widget/infomessage")
local _ = require("koinsight_l10n")

function response_not_valid(content)
  logger.err("[KoInsight] callApi: response was not valid JSON", content)
  UIManager:show(InfoMessage:new({
    text = _("Server response is not valid."),
  }))
end

return function(method, url, headers, body, filepath, quiet)
  quiet = quiet or false

  local sink = {}
  local request = {
    method = method,
  }

  request.url = url
  request.headers = headers or {}

  request.sink = ltn12.sink.table(sink)
  socketutil:set_timeout(socketutil.LARGE_BLOCK_TIMEOUT, socketutil.LARGE_TOTAL_TIMEOUT)

  if body ~= nil then
    request.source = ltn12.source.string(body)
  end

  logger.dbg("[KoInsight] callApi:", request.method, request.url)

  local code, resp_headers, status = socket.skip(1, http.request(request))
  socketutil:reset_timeout()

  -- Raise error if network is unavailable
  if resp_headers == nil then
    logger.err("[KoInsight] callApi: network error", status or code)
    return false, "network_error"
  end

  -- If the request returned successfully
  if code == 200 then
    local content = table.concat(sink)

    if content == nil or content == "" or string.sub(content, 1, 1) ~= "{" then
      response_not_valid(content)
      return false, "empty_response"
    end

    local ok, result = pcall(JSON.decode, content)

    if ok and result then
      return true, result
    else
      response_not_valid(content)
      return false, "invalid_response"
    end
  else
    if not quiet then
      logger.err("[KoInsight] callApi: HTTP error", status or code, resp_headers, result)
      UIManager:show(InfoMessage:new({
        text = _("Server error") .. (result and ": " .. result["error"] or ""),
      }))
    end

    logger.err("[KoInsight] callApi: HTTP error", status or code, resp_headers)
    return false, "http_error", code
  end
end
