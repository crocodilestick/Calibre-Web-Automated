#!/bin/bash

# https://github.com/janeczku/calibre-web/wiki/Automatically-import-new-books-(Linux)

# This script is used to automatically import downloaded eBook's into a Calibre database.
# Reference: https://manual.calibre-ebook.com/generated/en/calibredb.html#add
echo "========== STARTING NEW BOOK DETECTOR =========="

# Folder to monitor
WATCH_FOLDER=$(grep -o '"import_folder": "[^"]*' /etc/calibre-web-automator/dirs.json | grep -o '[^"]*$')
echo "[new-book-detector]: Watching folder: $WATCH_FOLDER"

# Calibre library path
CALIBRE_LIBRARY=$(grep -o '"calibre_library_dir": "[^"]*' /etc/calibre-web-automator/dirs.json | grep -o '[^"]*$')

# Function to add new eBook to Calibre database
add_to_calibre() {
    # Path to calibredb executable
    CALIBREDB="/usr/bin/calibredb"
    
    # Run calibredb command to add the new eBook to the database
    $CALIBREDB add -r "$1" --library-path="$CALIBRE_LIBRARY"
    echo "[new-book-detector] Added $1 to Calibre database"
}

# Monitor the folder for new files
inotifywait -m -r --format="%e %w%f" -e close_write -e moved_to "$WATCH_FOLDER" |
while read -r events filepath; do
        echo "[new-book-detector]: New file detected: $filepath"
        add_to_calibre "$filepath"
        echo "[new-book-detector]: Removing $filepath from import folder..."
        chown -R abc:users "$WATCH_FOLDER"
        #find "$WATCH_FOLDER/" -mindepth 1 -type f,d -delete
        rm "$filepath"
        sleep 10s
        chown -R abc:1000 "$CALIBRE_LIBRARY"
        echo "[new-book-detector]: $filepath successfully moved/converted, the Ingest Folder has been emptied and is ready"
done

