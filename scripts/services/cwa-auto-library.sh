#!/bin/bash
# cwa-auto-library.sh — One-shot library auto-detection

DISABLE="${DISABLE_LIBRARY_AUTOMOUNT:-}"
DISABLE="${DISABLE,,}"
if [[ "$DISABLE" =~ ^(true|yes|1)$ ]]; then
    echo "[auto-library] DISABLE_LIBRARY_AUTOMOUNT set, skipping."
    exit 0
fi

python3 /app/calibre-web-automated/scripts/auto_library.py
RC=$?
if [[ $RC -eq 0 ]]; then
    echo "[auto-library] Completed successfully."
else
    echo "[auto-library] Exited with code $RC."
fi
