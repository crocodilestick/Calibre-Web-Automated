#!/bin/bash
set -euo pipefail

# Resolve repo root (script_dir/..)
SCRIPT_DIR="$( cd -- "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ROOT_DIR="$( cd "$SCRIPT_DIR/.." && pwd )"
cd "$ROOT_DIR"

CONFIG="$ROOT_DIR/babel.cfg"
POT="$ROOT_DIR/messages.pot"
DUPLICATE_FIXER="$SCRIPT_DIR/fix_po_duplicates.py"

# Set up Python environment
PYTHON_CMD="python3"
PYBABEL_CMD="python3 -m babel.messages.frontend"

# Check if virtual environment exists and use it
if [ -f "$ROOT_DIR/.venv/bin/python" ]; then
    PYTHON_CMD="$ROOT_DIR/.venv/bin/python"
    PYBABEL_CMD="$PYTHON_CMD -m babel.messages.frontend"
fi

# Get the latest version from GitHub releases
echo "[i] Fetching latest version from GitHub..."
VERSION=$(curl -s https://api.github.com/repos/crocodilestick/Calibre-Web-Automated/releases/latest | grep '"tag_name":' | sed -E 's/.*"([^"]+)".*/\1/' || echo "unknown")
if [ "$VERSION" = "unknown" ] || [ -z "$VERSION" ]; then
    echo "[!] Warning: Could not fetch version from GitHub, using fallback"
    VERSION="dev"
fi

echo "[i] Using config: $CONFIG"
echo "[i] Generating POT: $POT"
echo "[i] Using Python: $PYTHON_CMD"
echo "[i] Project version: $VERSION"

# 1. Extract messages
$PYBABEL_CMD extract -F "$CONFIG" -o "$POT" \
    --project="Calibre-Web Automated" \
    --version="$VERSION" \
    --msgid-bugs-address="https://github.com/crocodilestick/Calibre-Web-Automated" \
    --copyright-holder="Calibre-Web Automated Contributors" \
    . || { echo "pybabel extract failed"; exit 1; }

# 2. Merge updates
shopt -s nullglob
for po in "$ROOT_DIR"/cps/translations/*/LC_MESSAGES/messages.po; do
    echo "[i] Updating $po"
    
    # Try msgmerge, but capture any failures
    if ! msgmerge --update "$po" "$POT" 2>/dev/null; then
        echo "[!] msgmerge failed for $po, checking for duplicates..."
        
        # Check if the error is related to duplicates
        msgmerge_output=$(msgmerge --update "$po" "$POT" 2>&1 || true)
        if echo "$msgmerge_output" | grep -q "duplicate message definition"; then
            echo "[i] Duplicate messages detected in $po, attempting to fix..."
            
            if [ -f "$DUPLICATE_FIXER" ]; then
                $PYTHON_CMD "$DUPLICATE_FIXER" "$po" || {
                    echo "[!] Warning: Failed to fix duplicates in $po automatically"
                    echo "[!] Manual intervention may be required"
                    continue
                }
                
                # Try msgmerge again after fixing duplicates
                echo "[i] Retrying msgmerge for $po after duplicate fix..."
                if ! msgmerge --update "$po" "$POT"; then
                    echo "[!] msgmerge still failed for $po even after duplicate fix"
                    continue
                fi
            else
                echo "[!] Warning: Duplicate fixer script not found at $DUPLICATE_FIXER"
                echo "[!] Please fix duplicates manually or ensure the script is available"
                continue
            fi
        else
            echo "[!] msgmerge failed for $po with non-duplicate errors:"
            echo "$msgmerge_output"
            continue
        fi
    fi
done

# 3. Final validation and compile
for po in "$ROOT_DIR"/cps/translations/*/LC_MESSAGES/messages.po; do
    mo="${po%.po}.mo"
    echo "[i] Compiling $po -> $mo"
    
    # Final validation before compilation
    if ! msgfmt --check "$po" >/dev/null 2>&1; then
        echo "[!] ERROR: $po still has errors after duplicate fixing:"
        msgfmt --check "$po" 2>&1 || true
        echo "[!] Skipping compilation of $po"
        continue
    fi
    
    msgfmt "$po" -o "$mo" || { echo "msgfmt compilation failed for $po"; exit 1; }
done

echo "[✓] Translation update complete."