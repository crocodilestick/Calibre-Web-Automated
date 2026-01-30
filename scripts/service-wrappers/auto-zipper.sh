#!/bin/bash

echo "[auto-zipper] Starting CWA-Auto-Zipper service..."

# Timezone handling
tz=${TZ:-UTC}
# In rootless we might not be able to set /etc/localtime if read-only or not owned by user.
# But we are 'abc'. If this fails, we just export TZ.
export TZ=$tz

echo "[auto-zipper] Using timezone: $TZ"

WAKEUP="23:59"

while :
do
    # Calculate seconds until next 23:59
    # Use python for better portability than date math in shell
    SECS=$(python3 -c "import datetime, time; now = datetime.datetime.now(); target = now.replace(hour=23, minute=59, second=0, microsecond=0); target += datetime.timedelta(days=1) if target <= now else datetime.timedelta(0); print(int((target - now).total_seconds()))")
    
    echo "[auto-zipper] Next run in $SECS seconds."
    sleep $SECS &
    wait $!
    
    echo "[auto-zipper] Running auto_zip.py"
    python3 /app/calibre-web-automated/scripts/auto_zip.py
    
    if [[ $? == 1 ]]; then
        echo "[auto-zipper] Error occurred during script initialisation."
    elif [[ $? == 2 ]]; then
        echo "[auto-zipper] Error occurred while zipping today's files."
    elif [[ $? == 3 ]]; then
        echo "[auto-zipper] Error occurred while trying to remove the files that have been zipped."
    fi
    sleep 60
done
