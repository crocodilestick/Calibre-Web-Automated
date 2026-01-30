#!/bin/bash
set -e

echo "[entrypoint] Starting Rootless CWA container..."

# ----------------------------------------------------------------------------
# 1. Version Resolution (cwa-init)
# ----------------------------------------------------------------------------
echo "[entrypoint] Resolving CWA versions..."
export CWA_INSTALLED_VERSION="$(cat /app/CWA_RELEASE 2>/dev/null || echo 'V0.0.0')"
echo "[entrypoint] Installed version: $CWA_INSTALLED_VERSION"

# Attempt to fetch stable version (best effort)
CWA_STABLE_VERSION=""
if command -v jq >/dev/null 2>&1; then
  CWA_STABLE_VERSION="$(timeout 5 curl -sS --max-time 3 --connect-timeout 2 https://api.github.com/repos/crocodilestick/calibre-web-automated/releases/latest 2>/dev/null | timeout 2 jq -r '.tag_name' 2>/dev/null || true)"
else
  CWA_STABLE_VERSION="$(timeout 5 curl -sS --max-time 3 --connect-timeout 2 https://api.github.com/repos/crocodilestick/calibre-web-automated/releases/latest 2>/dev/null | timeout 2 sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1 || true)"
fi

if [[ -z "$CWA_STABLE_VERSION" ]]; then
  CWA_STABLE_VERSION="V0.0.0" 
fi
export CWA_STABLE_VERSION
echo "$CWA_STABLE_VERSION" > /app/CWA_STABLE_RELEASE 2>/dev/null || true
echo "[entrypoint] Stable version: $CWA_STABLE_VERSION"

# ----------------------------------------------------------------------------
# 2. Process Recovery (cwa-process-recovery)
# ----------------------------------------------------------------------------
echo "[entrypoint] Cleaning up stale temp files..."
rm -rf /config/.cwa_conversion_tmp/*.tmp 2>/dev/null || true
rm -rf /tmp/staging* 2>/dev/null || true
# Reset ingest status if needed
if [ -f "/config/cwa_ingest_status" ]; then
    # Simple check: if it says processing, maybe reset to idle if no process running?
    # Supervisord starts fresh, so no old processes are running.
    echo "idle" > "/config/cwa_ingest_status"
fi

# ----------------------------------------------------------------------------
# 3. Calibre Binaries Check
# ----------------------------------------------------------------------------
if command -v calibredb >/dev/null 2>&1; then
    echo "[entrypoint] Calibre binaries found: $(calibredb --version | head -n1)"
else
    echo "[entrypoint] WARNING: Calibredb not found in PATH!"
    # In the rootless build, we install it to /app/calibre. We need to ensure it's in PATH or symlinked.
    # The Dockerfile adds /app/calibre to PATH? No wait, looking at Dockerfile...
    # I copied /app/calibre. But I didn't explicitly add it to PATH in Dockerfile ENV?
    # "COPY --from=dependencies /app/calibre /app/calibre"
    # "COPY --from=dependencies /usr/local/bin /usr/local/bin" 
    # The original Dockerfile didn't seem to add it to PATH ENV either, maybe it relied on symlinks?
    # "ln -sf /usr/bin/python3.13 /usr/bin/python3"
    # Wait, the original Dockerfile installs calibre to /app/calibre.
    # Does s6 add it to path?
    # I should check if I need to add /app/calibre to PATH.
    export PATH="/app/calibre:$PATH"
fi

# ----------------------------------------------------------------------------
# 4. Checksum Backfill (Background Task)
# ----------------------------------------------------------------------------
# We can't block entrypoint indefinitely. 
# We'll spawn a background process that waits for DB and runs backfill.
(
    echo "[backfill] Waiting for DB..."
    sleep 10
    # Loop checking for DB table
    ATTEMPTS=0
    while [ $ATTEMPTS -lt 30 ]; do
        if sqlite3 /calibre-library/metadata.db "SELECT name FROM sqlite_master WHERE type='table' AND name='book_format_checksums';" 2>/dev/null | grep -q "book_format_checksums"; then
            echo "[backfill] DB ready. Running checksum generation..."
            python3 /app/calibre-web-automated/scripts/generate_book_checksums.py --library-path /calibre-library --batch-size 50
            exit 0
        fi
        sleep 2
        ATTEMPTS=$((ATTEMPTS+1))
    done
    echo "[backfill] Timeout waiting for DB."
) &

# ----------------------------------------------------------------------------
# 5. Start Supervisord
# ----------------------------------------------------------------------------
echo "[entrypoint] Starting Supervisord..."
exec /usr/bin/supervisord
