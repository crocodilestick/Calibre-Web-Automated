#!/bin/bash
set -e

WATCH_FOLDER="/app/calibre-web-automated/metadata_change_logs"

run_fallback() {
    echo "[metadata-monitor] Using polling watcher"
    # Simple loop since we don't have a specific fallback script for metadata?
    # Original used watch_fallback.py logic? No, s6 script said "run_fallback" but didn't define it in the snippet I saw? 
    # Wait, the snippet for metadata-change-detector/run calls `run_fallback` but I didn't see the definition in the previous `grep`.
    # Actually, looking at ingest service, it uses watch_fallback.py.
    # Metadata monitor calls `cover_enforcer.py`.
    
    while true; do
        # Poll every 30 seconds
        # Actually this might be inefficient if done naively.
        # Let's assume we can use watch_fallback.py here too if it supports generic callbacks?
        # watch_fallback.py seems to output events.
        
        # Or we can just sleep loop check?
        # Let's try to reuse watch_fallback.py if possible, or just implement a simple poller.
        # But watch_fallback.py is designed for this.
        
        python3 /app/calibre-web-automated/scripts/watch_fallback.py --path "$WATCH_FOLDER" --interval 30 |
        while read -r events filename; do
             echo "[metadata-monitor] New file detected: $filename"
             python3 /app/calibre-web-automated/scripts/cover_enforcer.py "--log" "$filename"
        done
        sleep 5
    done
}

handle_event() {
    local directory="$1"
    local events="$2"
    local filename="$3"
    
    echo "[metadata-monitor] New file detected: $filename"
    python3 /app/calibre-web-automated/scripts/cover_enforcer.py "--log" "$filename"
}


if [ "${NETWORK_SHARE_MODE,,}" = "true" ] || [ "${NETWORK_SHARE_MODE}" = "1" ] || [ "${CWA_WATCH_MODE:-inotify}" = "poll" ]; then
    run_fallback
    exit 0
fi

# Inotify
echo "[metadata-monitor] Starting inotify watcher on $WATCH_FOLDER"
inotifywait -m -e close_write -e moved_to --exclude '^.*\.(swp)$' "$WATCH_FOLDER" | \
while read -r directory events filename; do
    echo "[metadata-monitor] Change detected: $filename"
    python3 /app/calibre-web-automated/scripts/cover_enforcer.py "--log" "$filename"
done || run_fallback
