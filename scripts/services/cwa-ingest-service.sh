#!/bin/bash
# cwa-ingest-service.sh — Long-running ingest file watcher

echo "========== STARTING INGEST SERVICE =========="

APP_DIR="/app/calibre-web-automated"
WATCH_FOLDER=$(grep -o '"ingest_folder": "[^"]*' "$APP_DIR/dirs.json" | grep -o '[^"]*$')
echo "[cwa-ingest-service] Watching folder: $WATCH_FOLDER"

QUEUE_FILE="/config/cwa_ingest_retry_queue"
STATUS_FILE="/config/cwa_ingest_status"
touch "$QUEUE_FILE"
echo "idle" > "$STATUS_FILE"
mkdir -p "/config/processed_books/failed" 2>/dev/null || true

SUPPORTED_EXT_REGEX='(epub|mobi|azw3|azw|pdf|txt|rtf|cbz|cbr|cb7|cbc|fb2|fbz|docx|html|htmlz|lit|lrf|odt|prc|pdb|pml|rb|snb|tcr|txtz|kepub|m4b|m4a|mp4|acsm|kfx|kfx-zip)$'
TEMP_SUFFIXES="crdownload download part uploading"

get_timeout() {
    local min
    min=$(sqlite3 /config/cwa.db "SELECT ingest_timeout_minutes FROM cwa_settings LIMIT 1;" 2>/dev/null || echo "15")
    echo $(( min * 60 ))
}

get_stale_temp_minutes() { sqlite3 /config/cwa.db "SELECT ingest_stale_temp_minutes FROM cwa_settings LIMIT 1;" 2>/dev/null || echo "120"; }
get_stale_temp_interval() { sqlite3 /config/cwa.db "SELECT ingest_stale_temp_interval FROM cwa_settings LIMIT 1;" 2>/dev/null || echo "600"; }

cleanup_stale_temps() {
    local minutes
    minutes=$(get_stale_temp_minutes)
    [[ -z "$minutes" || "$minutes" -le 0 || ! -d "$WATCH_FOLDER" ]] && return 0
    for suf in $TEMP_SUFFIXES; do
        find "$WATCH_FOLDER" -type f -name "*.$suf" -mmin +"$minutes" -delete 2>/dev/null || true
    done
}

process_retry_queue() {
    [[ -s "$QUEUE_FILE" ]] || return 0
    echo "[cwa-ingest-service] Processing retry queue..."
    local tmpq=$(mktemp)
    while IFS= read -r qf; do
        [[ -f "$qf" ]] || continue
        local safety=$(( $(get_timeout) * 3 ))
        timeout "$safety" python3 "$APP_DIR/scripts/ingest_processor.py" "$qf"
        local rc=$?
        if [[ $rc -eq 2 ]]; then
            echo "$qf" >> "$tmpq"
        elif [[ $rc -eq 124 ]]; then
            local ts=$(date '+%Y%m%d_%H%M%S')
            cp "$qf" "/config/processed_books/failed/${ts}_retry_timeout_$(basename "$qf")" 2>/dev/null || true
            rm -f "$qf" 2>/dev/null || true
        fi
    done < "$QUEUE_FILE"
    mv "$tmpq" "$QUEUE_FILE"
}

handle_event() {
    local filepath="$1" filename
    filename=$(basename "$filepath")
    for suf in $TEMP_SUFFIXES; do [[ "$filepath" == *.$suf ]] && return 0; done
    [[ "$filepath" == *.cwa.json || "$filepath" == *.cwa.failed.json ]] && return 0
    [[ ! "$filepath" =~ $SUPPORTED_EXT_REGEX ]] && return 0

    cleanup_stale_temps
    local configured_timeout=$(get_timeout)
    local safety_timeout=$(( configured_timeout * 3 ))

    echo "[cwa-ingest-service] New file detected - $filepath"
    echo "processing:$filename:$(date '+%Y-%m-%d %H:%M:%S')" > "$STATUS_FILE"

    timeout "$safety_timeout" python3 "$APP_DIR/scripts/ingest_processor.py" "$filepath"
    local rc=$?

    if [[ $rc -eq 124 ]]; then
        echo "[cwa-ingest-service] SAFETY TIMEOUT: $filepath"
        echo "safety_timeout:$filename:$(date '+%Y-%m-%d %H:%M:%S')" > "$STATUS_FILE"
        local ts=$(date '+%Y%m%d_%H%M%S')
        cp "$filepath" "/config/processed_books/failed/${ts}_safety_timeout_${filename}" 2>/dev/null || true
        rm -f "$filepath" 2>/dev/null || true
    elif [[ $rc -eq 2 ]]; then
        echo "[cwa-ingest-service] Busy, queueing: $filepath"
        echo "queued:$filename:$(date '+%Y-%m-%d %H:%M:%S')" > "$STATUS_FILE"
        echo "$filepath" >> "$QUEUE_FILE"
    elif [[ $rc -ne 0 ]]; then
        echo "[cwa-ingest-service] Error ($rc): $filepath"
        echo "error:$filename:$rc:$(date '+%Y-%m-%d %H:%M:%S')" > "$STATUS_FILE"
    else
        echo "[cwa-ingest-service] Done: $filepath"
        echo "completed:$filename:$(date '+%Y-%m-%d %H:%M:%S')" > "$STATUS_FILE"
        process_retry_queue
    fi
    echo "idle" > "$STATUS_FILE"
}

run_fallback() {
    echo "[cwa-ingest-service] Falling back to polling watcher"
    python3 "$APP_DIR/scripts/watch_fallback.py" --path "$WATCH_FOLDER" --interval 5 |
    while read -r events filepath; do handle_event "$filepath"; done
}

# Determine watch mode
NSM="${NETWORK_SHARE_MODE:-}"
NSM="${NSM,,}"
if [[ "$NSM" =~ ^(true|1|yes|on)$ ]]; then
    echo "[cwa-ingest-service] NETWORK_SHARE_MODE=true -> polling"
    run_fallback; exit 0
fi
if [[ "${CWA_WATCH_MODE:-inotify}" == "poll" ]]; then
    run_fallback; exit 0
fi
# Docker Desktop check
OSR=$(cat /proc/sys/kernel/osrelease 2>/dev/null || true)
if echo "$OSR" | grep -qi 'microsoft\|linuxkit'; then
    echo "[cwa-ingest-service] Docker Desktop detected -> polling"
    run_fallback; exit 0
fi

# Background stale temp cleanup
(
    while true; do
        cleanup_stale_temps
        sleep "$(get_stale_temp_interval)" 2>/dev/null || sleep 60
    done
) &

# Main inotifywait loop with fallback and automatic restart
while true; do
    (
        set -o pipefail
        inotifywait -m -r --format="%e %w%f" -e close_write -e moved_to "$WATCH_FOLDER" |
        while read -r events filepath; do handle_event "$filepath"; done
    ) || run_fallback
    echo "[cwa-ingest-service] Watcher exited, restarting in 5 seconds..." >&2
    sleep 5
done
