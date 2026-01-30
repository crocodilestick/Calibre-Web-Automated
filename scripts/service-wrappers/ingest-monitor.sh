#!/bin/bash
set -e

# Load environment
export CALIBRE_DBPATH=/config

# Trap signals and forward to child
trap 'kill -TERM $PID' TERM INT

echo "[ingest-monitor] Starting ingest monitor..."

# Define variables matching original script
WATCH_FOLDER="/cwa-book-ingest"
STATUS_FILE="/config/cwa_ingest_status"
QUEUE_FILE="/config/cwa_ingest_retry_queue"
MAX_QUEUE_SIZE=50
TEMP_SUFFIXES="tmp part crdownload"
SUPPORTED_EXT_REGEX='.*\.(epub|mobi|azw3?|pdf|txt|cb[rz7c]|fb2z?|docx?|html?z?|lit|lrf|odt|prc|pdb|pml|rb|snb|tcr|txtz|kepub|acsm)$'
STABLE_CHECKS=3
STABLE_INTERVAL=1
STABLE_CONSEC_MATCH=3

# Ensure config files exist
touch "$STATUS_FILE" "$QUEUE_FILE"
chmod 666 "$STATUS_FILE" "$QUEUE_FILE" 2>/dev/null || true

# Function to get timeout from DB
get_timeout_from_db() {
    # Default to 3 minutes if DB query fails
    local timeout=180
    if [ -f "/config/cwa.db" ]; then
        local db_timeout=$(sqlite3 "/config/cwa.db" "SELECT value FROM system_settings WHERE key='INGEST_TIMEOUT';" 2>/dev/null)
        if [ -n "$db_timeout" ] && [ "$db_timeout" -eq "$db_timeout" ] 2>/dev/null; then
            timeout=$db_timeout
        fi
    fi
    echo "$timeout"
}

# Retry queue processing function
process_retry_queue() {
    if [ -s "$QUEUE_FILE" ]; then
        echo "[ingest-monitor] Processing retry queue..."
        local temp_queue=$(mktemp)
        
        while IFS= read -r queued_file; do
            if [ -f "$queued_file" ]; then
                echo "[ingest-monitor] Retrying: $queued_file"
                local configured_timeout=$(get_timeout_from_db)
                local safety_timeout=$((configured_timeout * 3))
                
                timeout $safety_timeout python3 /app/calibre-web-automated/scripts/ingest_processor.py "$queued_file"
                local retry_exit=$?
                
                if [ $retry_exit -eq 2 ]; then
                    # Still busy
                    echo "$queued_file" >> "$temp_queue"
                elif [ $retry_exit -eq 124 ]; then
                    # Timeout
                    echo "[ingest-monitor] TIMEOUT on retry: $queued_file"
                    if [ -d "/config/processed_books/failed" ]; then
                         local timestamp=$(date '+%Y%m%d_%H%M%S')
                         local failed_filename="${timestamp}_retry_timeout_$(basename "$queued_file")"
                         cp "$queued_file" "/config/processed_books/failed/$failed_filename" 2>/dev/null || true
                    fi
                    rm -f "$queued_file" 2>/dev/null || true
                elif [ $retry_exit -eq 0 ]; then
                    echo "[ingest-monitor] Successfully processed retry: $queued_file"
                else
                    echo "[ingest-monitor] Error on retry: $queued_file (exit: $retry_exit)"
                fi
            fi
        done < "$QUEUE_FILE"
        
        mv "$temp_queue" "$QUEUE_FILE"
    fi
}

handle_event() {
    local filepath="$1"
    local filename=$(basename "$filepath")
    
    # Check suffixes
    for suf in $TEMP_SUFFIXES; do
        [[ "$filepath" == *.$suf ]] && return 0
    done
    
    # Check extension
    if ! [[ "$filename" =~ $SUPPORTED_EXT_REGEX ]]; then
        return 0
    fi
    
    local configured_timeout=$(get_timeout_from_db)
    local safety_timeout=$((configured_timeout * 3))
    
    echo "[ingest-monitor] New file detected: $filename"
    echo "processing:$filename:$(date '+%Y-%m-%d %H:%M:%S')" > "$STATUS_FILE"
    
    timeout $safety_timeout python3 /app/calibre-web-automated/scripts/ingest_processor.py "$filepath"
    local exit_code=$?
    
    if [ $exit_code -eq 124 ]; then
         echo "[ingest-monitor] SAFETY TIMEOUT: $filename"
         echo "safety_timeout:$filename:$(date '+%Y-%m-%d %H:%M:%S')" > "$STATUS_FILE"
         if [ -d "/config/processed_books/failed" ]; then
             local timestamp=$(date '+%Y%m%d_%H%M%S')
             local failed_filename="${timestamp}_safety_timeout_${filename}"
             cp "$filepath" "/config/processed_books/failed/$failed_filename" 2>/dev/null || true
         fi
         rm -f "$filepath" 2>/dev/null || true
    elif [ $exit_code -eq 2 ]; then
         echo "[ingest-monitor] Processor busy, queueing: $filename"
         echo "queued:$filename:$(date '+%Y-%m-%d %H:%M:%S')" > "$STATUS_FILE"
         echo "$filepath" >> "$QUEUE_FILE"
    elif [ $exit_code -ne 0 ]; then
         echo "[ingest-monitor] Error processing $filename (exit: $exit_code)"
         echo "error:$filename:$exit_code:$(date '+%Y-%m-%d %H:%M:%S')" > "$STATUS_FILE"
    else
         echo "[ingest-monitor] Successfully processed: $filename"
         echo "completed:$filename:$(date '+%Y-%m-%d %H:%M:%S')" > "$STATUS_FILE"
         process_retry_queue
    fi
    
    echo "idle" > "$STATUS_FILE"
}

run_fallback() {
    echo "[ingest-monitor] Using polling watcher"
    python3 /app/calibre-web-automated/scripts/watch_fallback.py --path "$WATCH_FOLDER" --interval 5 |
    while read -r events filepath; do
        handle_event "$filepath"
    done
}

# Logic to choose watcher
if [ "${NETWORK_SHARE_MODE,,}" = "true" ] || [ "${NETWORK_SHARE_MODE}" = "1" ] || [ "${CWA_WATCH_MODE:-inotify}" = "poll" ]; then
    run_fallback
    exit 0
fi

# Try inotify
if ! inotifywait -m -r --format="%e %w%f" -e close_write -e moved_to "$WATCH_FOLDER" 2>/dev/null | \
   while read -r events filepath; do handle_event "$filepath"; done; then
       echo "[ingest-monitor] inotifywait failed/exited, falling back to polling"
       run_fallback
fi
