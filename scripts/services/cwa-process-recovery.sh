#!/bin/bash
# cwa-process-recovery.sh — One-shot stale process/file cleanup

echo "[process-recovery] Starting..."

# Clean stale temp files
for temp_dir in /config/.cwa_conversion_tmp /tmp; do
    [[ -d "$temp_dir" ]] || continue
    find "$temp_dir" -name "staging*" -type d -mmin +60 -exec rm -rf {} + 2>/dev/null || true
    find "$temp_dir" -name "*.tmp" -mmin +60 -delete 2>/dev/null || true
    find "$temp_dir" -name "*_converting_*" -mmin +60 -delete 2>/dev/null || true
done

# Reset stuck processing status
STATUS_FILE="/config/cwa_ingest_status"
if [[ -f "$STATUS_FILE" ]]; then
    CONTENT=$(cat "$STATUS_FILE" 2>/dev/null || echo "unknown")
    if [[ "$CONTENT" == processing:* ]]; then
        TIMESTAMP=$(echo "$CONTENT" | cut -d':' -f3- 2>/dev/null || echo "")
        if [[ -n "$TIMESTAMP" ]]; then
            STATUS_EPOCH=$(date -d "$TIMESTAMP" +%s 2>/dev/null || echo "0")
            AGE_MIN=$(( ( $(date +%s) - STATUS_EPOCH ) / 60 ))
            [[ $AGE_MIN -gt 30 ]] && echo "idle" > "$STATUS_FILE"
        else
            echo "idle" > "$STATUS_FILE"
        fi
    fi
else
    echo "idle" > "$STATUS_FILE"
fi

echo "[process-recovery] Complete."
