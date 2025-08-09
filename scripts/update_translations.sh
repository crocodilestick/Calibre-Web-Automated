#!/bin/bash
set -euo pipefail

# Resolve repo root (script_dir/..)
SCRIPT_DIR="$( cd -- "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ROOT_DIR="$( cd "$SCRIPT_DIR/.." && pwd )"
cd "$ROOT_DIR"

CONFIG="$ROOT_DIR/babel.cfg"
POT="$ROOT_DIR/messages.pot"

echo "[i] Using config: $CONFIG"
echo "[i] Generating POT: $POT"

# 1. Extract messages
pybabel extract -F "$CONFIG" -o "$POT" . || { echo "pybabel extract failed"; exit 1; }

# 2. Merge updates
shopt -s nullglob
for po in "$ROOT_DIR"/cps/translations/*/LC_MESSAGES/messages.po; do
    echo "[i] Updating $po"
    msgmerge --update "$po" "$POT" || { echo "msgmerge failed for $po"; exit 1; }
done

# 3. Compile
for po in "$ROOT_DIR"/cps/translations/*/LC_MESSAGES/messages.po; do
    mo="${po%.po}.mo"
    echo "[i] Compiling $po -> $mo"
    msgfmt "$po" -o "$mo" || { echo "msgfmt failed for $po"; exit 1; }
done

echo "[✓] Translation update complete."