#!/bin/bash
# metadata-change-detector.sh — Long-running metadata change watcher

echo "========== STARTING METADATA CHANGE DETECTOR =========="

APP_DIR="/app/calibre-web-automated"
WATCH_FOLDER="$APP_DIR/metadata_change_logs"
echo "[metadata-change-detector] Watching folder: $WATCH_FOLDER"
mkdir -p "$WATCH_FOLDER"

run_fallback() {
    echo "[metadata-change-detector] Falling back to polling watcher"
    python3 "$APP_DIR/scripts/watch_fallback.py" \
        --path "$WATCH_FOLDER" --interval 5 --exts "json,log" |
    while read -r events filepath; do
        echo "[metadata-change-detector] New file detected: $(basename "$filepath")"
        python3 "$APP_DIR/scripts/cover_enforcer.py" "--log" "$(basename "$filepath")"
    done
}

# Determine watch mode
NSM="${NETWORK_SHARE_MODE:-}"
NSM="${NSM,,}"
if [[ "$NSM" =~ ^(true|1|yes|on)$ ]]; then
    run_fallback; exit 0
fi
if [[ "${CWA_WATCH_MODE:-inotify}" == "poll" ]]; then
    run_fallback; exit 0
fi
OSR=$(cat /proc/sys/kernel/osrelease 2>/dev/null || true)
if echo "$OSR" | grep -qi 'microsoft\|linuxkit'; then
    run_fallback; exit 0
fi

# Main inotifywait loop with fallback and automatic restart
while true; do
    (
        set -o pipefail
        inotifywait -m -e close_write -e moved_to --exclude '^.*\.(swp)$' "$WATCH_FOLDER" |
        while read -r directory events filename; do
            echo "[metadata-change-detector] New file detected: $filename"
            python3 "$APP_DIR/scripts/cover_enforcer.py" "--log" "$filename"
        done
    ) || run_fallback
    echo "[metadata-change-detector] Watcher exited, restarting in 5 seconds..." >&2
    sleep 5
done
