#!/bin/bash
# Compile all .po files to .mo files in the translations directory

TRANSLATIONS_DIR="$(dirname "$0")/cps/translations"

find "$TRANSLATIONS_DIR" -type f -name "messages.po" | while read -r po_file; do
    mo_file="${po_file%.po}.mo"
    echo "Compiling $po_file -> $mo_file"
    msgfmt "$po_file" -o "$mo_file"
done

echo "All .po files compiled to .mo files."
