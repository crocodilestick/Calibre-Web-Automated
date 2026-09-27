local _ = require("koinsight_l10n")
local callApi = require("call_api")
local InfoMessage = require("ui/widget/infomessage")
local JSON = require("json")
local KoInsightDbReader = require("db_reader")
local KoInsightAnnotationReader = require("annotation_reader")
local logger = require("logger")
local UIManager = require("ui/uimanager")
local const = require("./const")
local Device = require("device")

local API_UPLOAD_LOCATION = "/api/plugin/import"
local API_DEVICE_LOCATION = "/api/plugin/device"

local KoInsightUpload = {}

function get_headers(body)
  local headers = {
    ["Content-Type"] = "application/json",
    ["Content-Length"] = tostring(#body),
  }
  return headers
end

function render_response_message(response, prefix, default_text)
  local text = prefix .. " " .. default_text
  if response ~= nil and response["message"] ~= nil then
    logger.dbg("[KoInsight] API message received: ", JSON.encode(response))
    text = prefix .. " " .. response["message"]
  end

  UIManager:show(InfoMessage:new({
    text = text,
  }))
end

function send_device_data(server_url, silent)
  local url = server_url .. API_DEVICE_LOCATION
  local body = {
    id = G_reader_settings:readSetting("device_id"),
    model = Device.model,
    version = const.VERSION,
  }
  body = JSON.encode(body)

  local ok, response = callApi("POST", url, get_headers(body), body)

  if ok ~= true and not silent then
    render_response_message(response, _("Error:"), _("Unable to register device."))
  end
end

function send_statistics_data(server_url, silent)
  local url = server_url .. API_UPLOAD_LOCATION

  -- Get annotations from currently opened book
  local annotations = KoInsightAnnotationReader.getAnnotationsByBook()

  local annotation_count = 0
  for _, book_annotations in pairs(annotations) do
    annotation_count = annotation_count + #book_annotations
  end

  if annotation_count > 0 then
    logger.info("[KoInsight] Syncing", annotation_count, "annotations")
  end

  local body = {
    stats = KoInsightDbReader.progressData(),
    books = KoInsightDbReader.bookData(),
    annotations = annotations,
    version = const.VERSION,
  }

  body = JSON.encode(body)

  local ok, response = callApi("POST", url, get_headers(body), body)

  if not silent then
    if ok then
      render_response_message(response, _("Success:"), _("Data uploaded."))
    else
      render_response_message(response, _("Error:"), _("Data upload failed."))
    end
  end
end

-- Send annotations for a specific book
function send_book_annotations(server_url, book_md5, annotations, total_pages, book_metadata)
  local url = server_url .. API_UPLOAD_LOCATION
  local device_id = G_reader_settings:readSetting("device_id")

  -- Clean up annotations for JSON serialization
  local cleaned_annotations = KoInsightAnnotationReader.cleanAnnotations(annotations, total_pages)

  -- Use provided book metadata instead of querying database
  -- This allows bulk sync to work even if book isn't in statistics DB yet
  local book_to_send = book_metadata

  -- Fallback: try to get from statistics database if metadata not provided
  if not book_to_send then
    local all_books = KoInsightDbReader.bookData()
    for _, book in ipairs(all_books) do
      if book.md5 == book_md5 then
        book_to_send = book
        break
      end
    end
  end

  -- WARN: We MUST have book metadata to send annotations
  -- The server has a foreign key constraint: annotations.book_md5 -> book.md5
  -- If we don't send book data, annotation insert will fail
  if not book_to_send then
    logger.err(
      "[KoInsight] Cannot sync annotations for book " .. book_md5 .. ": no book metadata available"
    )
    return false, { error = "No book metadata available" }
  end

  -- Create minimal payload
  local annotations_by_book = {}
  annotations_by_book[book_md5] = cleaned_annotations

  local body = {
    stats = {}, -- empty stats on annotations sync path, handled server side
    books = { book_to_send }, -- Always send book metadata for FK constraint
    annotations = annotations_by_book,
    device_id = device_id,
    version = const.VERSION,
  }

  body = JSON.encode(body)
  return callApi("POST", url, get_headers(body), body)
end

-- Bulk sync all books with annotations
function bulk_sync_all_books(server_url, progress_callback)
  logger.info("[KoInsight] Starting bulk sync of all books")

  -- Get all books with annotations from reading history
  local books_with_annotations = KoInsightAnnotationReader.getAllBooksWithAnnotations()

  if #books_with_annotations == 0 then
    logger.info("[KoInsight] No books with annotations found")
    if progress_callback then
      progress_callback({
        phase = "complete",
        total = 0,
        success = 0,
        failed = 0,
        message = "No books with annotations found",
      })
    end
    return
  end

  logger.info("[KoInsight] Found", #books_with_annotations, "books to sync")

  local total_books = #books_with_annotations
  local success_count = 0
  local failed_count = 0

  -- Sync each book one by one
  for i, book_info in ipairs(books_with_annotations) do
    logger.info(
      string.format(
        "[KoInsight] Syncing book %d/%d (MD5: %s, %d annotations)",
        i,
        total_books,
        book_info.md5,
        book_info.annotation_count
      )
    )

    -- Report progress
    if progress_callback then
      progress_callback({
        phase = "syncing",
        current = i,
        total = total_books,
        book_md5 = book_info.md5,
        annotation_count = book_info.annotation_count,
      })
    end

    -- Send annotations for this book
    local ok, response = send_book_annotations(
      server_url,
      book_info.md5,
      book_info.annotations,
      book_info.total_pages,
      book_info.book_metadata -- Pass metadata from sidecar
    )

    if ok then
      success_count = success_count + 1
      logger.info("[KoInsight] Successfully synced book:", book_info.md5)
    else
      failed_count = failed_count + 1
      logger.err("[KoInsight] Failed to sync book:", book_info.md5)
    end

    -- Small delay between requests to avoid overwhelming the server
    -- and to allow UI to update
    if i < total_books then
      UIManager:nextTick(function() end)
    end
  end

  logger.info(
    string.format(
      "[KoInsight] Bulk sync complete: %d/%d books synced successfully, %d failed",
      success_count,
      total_books,
      failed_count
    )
  )

  -- Report completion
  if progress_callback then
    progress_callback({
      phase = "complete",
      total = total_books,
      success = success_count,
      failed = failed_count,
    })
  end
end

-- Sync current book only (stats + current book annotations)
function KoInsightUpload.syncCurrentBook(server_url, silent)
  if silent == nil then
    silent = false
  end
  if server_url == nil or server_url == "" then
    UIManager:show(InfoMessage:new({
      text = _("Please configure the server URL first."),
    }))
    return
  end

  send_device_data(server_url, silent)
  send_statistics_data(server_url, silent)
end

-- Sync all books (stats + all book annotations)
function KoInsightUpload.syncAllBooks(server_url, progress_callback)
  if server_url == nil or server_url == "" then
    UIManager:show(InfoMessage:new({
      text = _("Please configure the server URL first."),
    }))
    return
  end

  send_device_data(server_url, true) -- silent

  -- First, sync all statistics data from the database
  -- This includes all reading progress (page_stat_data) and book metadata
  send_statistics_data(server_url, true) -- silent

  -- Then, sync all annotations for all books
  bulk_sync_all_books(server_url, progress_callback)
end

return KoInsightUpload
