#!/bin/bash
# cwa-auto-zipper.sh — Long-running daily backup compression

echo "[cwa-auto-zipper] Starting..."

# Set timezone
tz="${TZ:-}"
if [[ -n "$tz" ]]; then
    region=$(echo "$tz" | awk -F '/' '{ print $1 }')
    city=$(echo "$tz" | awk -F '/' '{ print $2 }')
    zoneinfo="/usr/share/zoneinfo/$region/$city"
    if [[ -f "$zoneinfo" ]]; then
        ln -sfn "$zoneinfo" /etc/localtime
        echo "$tz" > /etc/timezone
        echo "[cwa-auto-zipper] Timezone set to $tz"
    else
        echo "[cwa-auto-zipper] Zoneinfo for $tz not found, using UTC"
    fi
else
    echo "[cwa-auto-zipper] No TZ env, defaulting to UTC"
fi

WAKEUP="23:59"
while true; do
    SECS=$(( $(date -d "$WAKEUP" +%s) - $(date +%s) ))
    [[ $SECS -lt 0 ]] && SECS=$(( $(date -d "tomorrow $WAKEUP" +%s) - $(date +%s) ))
    echo "[cwa-auto-zipper] Next run in $SECS seconds."
    sleep "$SECS" &
    wait $!
    python3 /app/calibre-web-automated/scripts/auto_zip.py
    case $? in
        1) echo "[cwa-auto-zipper] Error during initialisation." ;;
        2) echo "[cwa-auto-zipper] Error while zipping." ;;
        3) echo "[cwa-auto-zipper] Error removing zipped files." ;;
    esac
    sleep 60
done
