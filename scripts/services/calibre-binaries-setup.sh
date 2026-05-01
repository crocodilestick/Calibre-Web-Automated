#!/bin/bash
# calibre-binaries-setup.sh — One-shot Calibre binary registration

echo "[calibre-setup] Starting Calibre binaries setup..."

if timeout 10 calibredb --version >/dev/null 2>&1; then
    VER=$(timeout 10 calibredb --version 2>/dev/null || echo "")
    if [[ "$VER" =~ calibredb.*calibre\ [0-9]+\.[0-9]+ ]]; then
        echo "[calibre-setup] Calibre already installed: $VER"
        exit 0
    fi
fi

if [[ ! -f /app/calibre/calibre_postinstall ]]; then
    echo "[calibre-setup] ERROR: calibre_postinstall not found"
    exit 1
fi
[[ ! -x /app/calibre/calibre_postinstall ]] && chmod +x /app/calibre/calibre_postinstall

echo "[calibre-setup] Running calibre_postinstall..."
if timeout 300 /app/calibre/calibre_postinstall; then
    echo "[calibre-setup] Complete."
else
    echo "[calibre-setup] ERROR: calibre_postinstall failed or timed out"
    exit 1
fi
