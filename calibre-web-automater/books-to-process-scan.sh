#!/bin/bash

# https://github.com/janeczku/calibre-web/wiki/Automatically-import-new-books-(Linux)

# This script is used to automatically import downloaded eBook's into a Calibre database.
# Reference: https://manual.calibre-ebook.com/generated/en/calibredb.html#add
echo "STARTING NEW-BOOK-PROCESSING SCANNER"
apt install inotify-tools

# Folder to monitor, replace "/books/to_process" with the folder you want to monitor e.g. your download folder for books
WATCH_FOLDER=grep -o '"ingest_folder": "[^"]*' /etc/calibre-web-automater/dirs.json | grep -o '[^"]*$'
echo "Watching folder: $WATCH_FOLDER"

# Monitor the folder for new files
inotifywait -m -e create -e moved_to "$WATCH_FOLDER" |
while read -r directory events filename; do
        echo "PROCESSING: New files detected."
        python3 /config/new-book-processor.py
        echo "PROCESSING: New files sucsessfully moved/converted, the to_process folder has been emptied and is ready to go again."
done