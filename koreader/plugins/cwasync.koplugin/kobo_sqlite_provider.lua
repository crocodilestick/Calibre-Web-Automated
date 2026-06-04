--[[
KoboReader.sqlite device-write provider (Phase 2, generic-transport / Kobo
target first).

Bridges the portable annotation shape (from the CWNG server) to the Kobo
`Bookmark` table so highlights created in the web reader / on another device
appear on stock Nickel. KOReader-on-Kobo can read/write KoboReader.sqlite
directly; this is the only path to put a server-side highlight on a stock Kobo.

Safety (the High-severity risk — see
notes/2026-05-25-annotation-two-way-phase1-phase2-DESIGN.md §4.3):
  * backup KoboReader.sqlite before the first write of a session,
  * writes are INSERT OR IGNORE only (idempotent on BookmarkID),
  * v1 does NOT delete or update Nickel's own rows — deletes are honored
    server-side (hidden) and surfaced in the reader, not pushed destructively
    to the device until the round-trip is hardware-proven,
  * opt-in (default off) + gated on real-device verification.

The sqlite FFI is lazy-required inside the I/O functions so the pure
field-mapping helpers (the risky get-it-right logic) are unit-testable without
KOReader. The I/O is verified on-device per the manual checklist.
]]--

local KoboSqliteProvider = {}

local DEFAULT_KOBO_DB = "/mnt/onboard/.kobo/KoboReader.sqlite"

-- Kobo's Color codes (Bookmark.Color). Web/KOReader use the 4 named colors a
-- Kobo round-trips; anything else degrades to yellow.
local COLOR_NAME_TO_INT = { yellow = 0, red = 1, green = 2, blue = 3 }
local COLOR_INT_TO_NAME = { [0] = "yellow", [1] = "red", [2] = "green", [3] = "blue" }

-- ── Pure field-mapping helpers (unit-tested) ──────────────────────────────

function KoboSqliteProvider.colorNameToKoboInt(name)
    return COLOR_NAME_TO_INT[name] or 0
end

function KoboSqliteProvider.koboIntToColorName(code)
    return COLOR_INT_TO_NAME[code] or "yellow"
end

-- "kobo.4.1" -> "span#kobo\.4\.1" (Kobo escapes the dots in the CSS selector).
function KoboSqliteProvider.escapeKoboSpanSelector(kobospan_id)
    if not kobospan_id or kobospan_id == "" then return nil end
    local escaped = kobospan_id:gsub("%.", "\\.")
    return "span#" .. escaped
end

-- "span#kobo\.4\.1" (or unescaped) -> "kobo.4.1".
function KoboSqliteProvider.extractKoboSpanId(container_path)
    if not container_path then return nil end
    local frag = container_path:match("#(.+)$")
    if not frag then return nil end
    return (frag:gsub("\\", ""))
end

-- portable annotation + the book's Kobo VolumeID -> a Bookmark row table.
function KoboSqliteProvider.buildBookmarkRow(portable, volume_id)
    local now = os.date("!%Y-%m-%dT%H:%M:%SZ")
    return {
        BookmarkID = portable.annotation_id,
        VolumeID = volume_id,
        ContentID = portable.content_id,
        StartContainerPath = KoboSqliteProvider.escapeKoboSpanSelector(portable.start_kobospan),
        StartContainerChildIndex = -99,   -- kepub selector sentinel
        StartOffset = portable.start_offset or 0,
        EndContainerPath = KoboSqliteProvider.escapeKoboSpanSelector(portable.end_kobospan or portable.start_kobospan),
        EndContainerChildIndex = -99,     -- NOT NULL in the real Kobo schema
        EndOffset = portable.end_offset or 0,
        Text = portable.highlighted_text,
        Annotation = portable.note_text,
        Color = KoboSqliteProvider.colorNameToKoboInt(portable.color),
        ContextString = portable.context_string,
        Type = "highlight",
        DateCreated = now,
        DateModified = now,
        Hidden = "false",
    }
end

-- A Bookmark row (from a device SELECT) -> portable annotation.
function KoboSqliteProvider.bookmarkRowToPortable(row)
    return {
        annotation_id = row.BookmarkID,
        highlighted_text = row.Text,
        note_text = row.Annotation,
        color = KoboSqliteProvider.koboIntToColorName(row.Color),
        content_id = row.ContentID,
        start_kobospan = KoboSqliteProvider.extractKoboSpanId(row.StartContainerPath),
        start_offset = row.StartOffset or 0,
        end_kobospan = KoboSqliteProvider.extractKoboSpanId(row.EndContainerPath),
        end_offset = row.EndOffset or 0,
        context_string = row.ContextString,
        chapter_progress = row.ChapterProgress,
        source = "kobo",
        device_origin_id = row.BookmarkID,
    }
end

-- ── Device I/O (lazy sqlite; verified on-device) ──────────────────────────

local function db_path()
    return DEFAULT_KOBO_DB
end

-- This provider is usable only on a Kobo (where KoboReader.sqlite exists).
function KoboSqliteProvider.available()
    local f = io.open(db_path(), "rb")
    if f then f:close(); return true end
    return false
end

-- Copy KoboReader.sqlite -> .cwn-bak-<ts> before the first write. Keeps the
-- user recoverable if a write ever corrupts the DB.
function KoboSqliteProvider.backup()
    local path = db_path()
    local src = io.open(path, "rb")
    if not src then return false end
    local data = src:read("*a"); src:close()
    local bak = path .. ".cwn-bak-" .. os.date("!%Y%m%dT%H%M%SZ")
    local out = io.open(bak, "wb")
    if not out then return false end
    out:write(data); out:close()
    return bak
end

local function open_db()
    -- KOReader bundles lua-ljsqlite3; lazy-require so the pure helpers above
    -- load without it (tests / non-KOReader hosts).
    local SQ3 = require("lua-ljsqlite3/init")
    return SQ3:open(db_path())
end

-- Read every highlight Bookmark for a VolumeID -> portable list.
function KoboSqliteProvider.readAll(volume_id)
    local ok, conn = pcall(open_db)
    if not ok then return {} end
    local out = {}
    local ok2, err = pcall(function()
        local stmt = conn:prepare(
            "SELECT BookmarkID, VolumeID, ContentID, StartContainerPath, StartOffset, " ..
            "EndContainerPath, EndOffset, Text, Annotation, Color, ContextString, " ..
            "ChapterProgress FROM Bookmark WHERE VolumeID = ? AND Type = 'highlight'")
        local rs = stmt:reset():bind(volume_id):step()
        while rs ~= nil do
            out[#out + 1] = KoboSqliteProvider.bookmarkRowToPortable({
                BookmarkID = rs[1], VolumeID = rs[2], ContentID = rs[3],
                StartContainerPath = rs[4], StartOffset = rs[5],
                EndContainerPath = rs[6], EndOffset = rs[7], Text = rs[8],
                Annotation = rs[9], Color = rs[10], ContextString = rs[11],
                ChapterProgress = rs[12],
            })
            rs = stmt:step()
        end
        stmt:close()
    end)
    conn:close()
    if not ok2 then return {} end
    return out
end

-- Write annotations the server says belong on this device. INSERT OR IGNORE
-- only (idempotent on BookmarkID); never UPDATE/DELETE Nickel's own rows in v1.
-- Returns the count inserted. Backs up before the first insert of a session:
-- `_backed_up` is a module-level flag so pressing "Sync highlights now"
-- repeatedly in one KOReader run snapshots KoboReader.sqlite once, not once per
-- call (an unguarded backup fills /mnt/onboard with full-size copies). A failed
-- backup leaves the flag clear so the next call retries before any write.
local _backed_up = false

function KoboSqliteProvider.applyToDevice(portables, volume_id)
    if not portables or #portables == 0 then return 0 end
    if not _backed_up then
        if KoboSqliteProvider.backup() then
            _backed_up = true
        end
    end
    local ok, conn = pcall(open_db)
    if not ok then return 0 end
    local inserted = 0
    pcall(function()
        for _, p in ipairs(portables) do
            if not p.hidden then   -- v1: do not materialize deletes on-device
                local row = KoboSqliteProvider.buildBookmarkRow(p, volume_id)
                local stmt = conn:prepare(
                    "INSERT OR IGNORE INTO Bookmark " ..
                    "(BookmarkID, VolumeID, ContentID, StartContainerPath, " ..
                    "StartContainerChildIndex, StartOffset, EndContainerPath, " ..
                    "EndContainerChildIndex, EndOffset, Text, Annotation, Color, " ..
                    "ContextString, Type, DateCreated, DateModified, Hidden) " ..
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)")
                stmt:reset():bind(
                    row.BookmarkID, row.VolumeID, row.ContentID, row.StartContainerPath,
                    row.StartContainerChildIndex, row.StartOffset, row.EndContainerPath,
                    row.EndContainerChildIndex, row.EndOffset, row.Text, row.Annotation,
                    row.Color, row.ContextString, row.Type, row.DateCreated,
                    row.DateModified, row.Hidden):step()
                stmt:close()
                inserted = inserted + 1
            end
        end
    end)
    conn:close()
    return inserted
end

return KoboSqliteProvider
