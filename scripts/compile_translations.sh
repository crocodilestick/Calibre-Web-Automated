#!/bin/bash
# Compile all .po files to .mo files in the translations directory

SCRIPT_DIR="$( cd -- "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
ROOT_DIR="$( cd "$SCRIPT_DIR/.." && pwd )"
TRANSLATIONS_DIR="$ROOT_DIR/cps/translations"

# Ensure directory exists
if [ ! -d "$TRANSLATIONS_DIR" ]; then
  echo "[!] Translations directory not found: $TRANSLATIONS_DIR" >&2
  exit 1
fi

find "$TRANSLATIONS_DIR" -type f -name "messages.po" | while read -r po_file; do
    mo_file="${po_file%.po}.mo"
    echo "Compiling $po_file -> $mo_file"
    if ! msgfmt "$po_file" -o "$mo_file"; then
      echo "[!] msgfmt failed for $po_file" >&2
      exit 1
    fi
done

echo "All .po files compiled to .mo files."
