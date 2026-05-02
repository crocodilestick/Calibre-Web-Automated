#!/bin/bash
# cwa-init.sh — One-shot initialization (adapted from upstream s6-rc.d/cwa-init/run)

APP_DIR="/app/calibre-web-automated"
CALIBRE_DIR="/app/calibre"
CONFIG_DIR="/config"
LIBRARY_DIR="/calibre-library"
CWA_USER="calibre"

echo "[cwa-init] Starting CWA initialization..."

# Verify essential directories
for dir in "$APP_DIR" "$CONFIG_DIR" "$LIBRARY_DIR" "$CALIBRE_DIR"; do
    if [[ ! -d "$dir" ]]; then
        echo "[cwa-init] ERROR: Essential directory $dir does not exist!"
        exit 1
    fi
done

# ImageMagick policy
if [[ -f /defaults/policy.xml ]]; then
    rm -rf /etc/ImageMagick-6/policy.xml
    ln -s /defaults/policy.xml /etc/ImageMagick-6/policy.xml 2>/dev/null || true
fi

# Google drive client_secrets.json
[[ ! -f /config/client_secrets.json ]] && echo "{}" > /config/client_secrets.json

# Ensure kepubify is executable
[[ -f /usr/bin/kepubify && ! -x /usr/bin/kepubify ]] && chmod +x /usr/bin/kepubify

# Create cache directory
mkdir -p "$APP_DIR/cps/cache"

# Clean up leftover lock files
for f in ingest_processor.lock convert_library.lock cover_enforcer.lock kindle_epub_fixer.lock restore_calibre_db.lock; do
    rm -f "/tmp/$f"
done

# Create app.db if missing
export CALIBRE_DBPATH=/config
if [[ ! -f /config/app.db ]]; then
    echo "[cwa-init] Creating app.db..."
    cp "$APP_DIR/empty_library/app.db" /config/app.db
fi

# Set binary paths in app.db
sqlite3 /config/app.db <<EOS 2>/dev/null || true
update settings set config_kepubifypath='/usr/bin/kepubify', config_converterpath='/usr/bin/ebook-convert', config_binariesdir='/usr/bin';
EOS

# Create required directories
mkdir -p /config/processed_books/{converted,imported,failed,fixed_originals,duplicate_resolutions}
mkdir -p /config/log_archive
mkdir -p /config/.cwa_conversion_tmp
mkdir -p /config/.config/calibre/plugins

# Ensure ingest directory exists
INGEST_DIR=$(python3 -c "
import json
try:
    with open('$APP_DIR/dirs.json') as f: print(json.load(f).get('ingest_folder',''))
except: print('')
" 2>/dev/null || echo "")
[[ -n "$INGEST_DIR" ]] && mkdir -p "$INGEST_DIR" 2>/dev/null || true

# Create user_profiles.json if missing
[[ ! -f /config/user_profiles.json ]] && echo -e "{\n}" > /config/user_profiles.json

# Enforce dark theme
python3 - <<'PY' 2>/dev/null || true
import sqlite3
try:
    conn = sqlite3.connect("/config/app.db")
    cur = conn.cursor()
    try: cur.execute("UPDATE settings SET config_theme = 1")
    except: pass
    try:
        cur.execute("PRAGMA table_info(user)")
        cols = {row[1] for row in cur.fetchall()}
        if "theme" in cols: cur.execute("UPDATE user SET theme = 1 WHERE theme IS NULL OR theme != 1")
    except: pass
    conn.commit()
except: pass
PY

# Set permissions (skip network shares)
NSM="${NETWORK_SHARE_MODE:-false}"
NSM="${NSM,,}"
for d in "$CONFIG_DIR" "$APP_DIR" "$LIBRARY_DIR"; do
    if [[ "$NSM" =~ ^(true|1|yes|on)$ ]]; then
        case "$d" in /config|/config/*|/calibre-library|/calibre-library/*|/cwa-book-ingest|/cwa-book-ingest/*) continue ;; esac
    fi
    chown -R "$CWA_USER:$CWA_USER" "$d" 2>/dev/null || true
done
chown -R "$CWA_USER:$CWA_USER" "$APP_DIR/cps/cache" 2>/dev/null || true

# Qt6 kernel compatibility check
MIN_KERNEL="6.0"
HOST_KERNEL_RAW="$(uname -r)"
HOST_KERNEL="${HOST_KERNEL_RAW%%-*}"
QT_SENTINEL="$CALIBRE_DIR/.qt6_processed"
if [[ ! -f "$QT_SENTINEL" ]]; then
    if [[ "$(printf '%s\n' "$MIN_KERNEL" "$HOST_KERNEL" | sort -V | tail -n1)" = "$HOST_KERNEL" ]]; then
        echo "[cwa-init][qt6] Kernel $HOST_KERNEL_RAW >= $MIN_KERNEL, Qt6 libs intact."
    else
        echo "[cwa-init][qt6] Kernel $HOST_KERNEL_RAW < $MIN_KERNEL, stripping ABI tags..."
        if command -v strip >/dev/null 2>&1; then
            for f in "$CALIBRE_DIR"/lib/libQt6*.so*; do
                [[ -f "$f" ]] || continue
                if timeout 10 readelf -S "$f" 2>/dev/null | grep -q ".note.ABI-tag"; then
                    timeout 10 strip --remove-section=.note.ABI-tag "$f" 2>/dev/null || true
                fi
            done
        fi
    fi
    touch "$QT_SENTINEL" 2>/dev/null || true
fi

echo "[cwa-init] Complete."
