#!/bin/bash

# https://github.com/janeczku/calibre-web/wiki/Automatically-import-new-books-(Linux)

# This script is used to automatically import downloaded eBook's into a Calibre database.
# Reference: https://manual.calibre-ebook.com/generated/en/calibredb.html#add
echo "STARTING CALIBRE SCANNER"

# Folder to monitor
WATCH_FOLDER=$(grep -o '"import_folder": "[^"]*' /etc/calibre-web-automator/dirs.json | grep -o '[^"]*$')
echo "Watching folder: $WATCH_FOLDER"

# Calibre library path
CALIBRE_LIBRARY=$(grep -o '"calibre_library_dir": "[^"]*' /etc/calibre-web-automator/dirs.json | grep -o '[^"]*$')
echo "Calibre library: $CALIBRE_LIBRARY"

# Function to add new eBook to Calibre database
add_to_calibre() {
    # Path to calibredb executable
    CALIBREDB="/usr/bin/calibredb"
    
    # Run calibredb command to add the new eBook to the database
    $CALIBREDB add -r $WATCH_FOLDER --library-path="$CALIBRE_LIBRARY"
    echo "Added $1 to Calibre database"
}

# Monitor the folder for new files
inotifywait -m -e create -e moved_to "$WATCH_FOLDER" |
while read -r directory events filename; do
        echo "New file detected: $filename"
        add_to_calibre "$filename"
        echo "Removing $filename from import folder..."
        rm -r "/books/to_calibre/*"
        sleep 10s
        chown -R abc:1000 "/calibre-main/Calibre Library"
done