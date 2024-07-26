#!/bin/sh

# This is for installations before the default library change from "/calibre-main/Calibre Library
# to /calibre-main. This ensures no hiccups for these older installations
if [ -d "/calibre-main/Calibre Library" ];then
	echo "Calibre Library detected. Changing cwa library path to it..."
	tmp=$(mktemp)
	dirpath="/etc/calibre-web-automator/dirs.json"

	# Modify calibre_library_dir to "/calibre-main/Calibre Library"
	jq '.calibre_library_dir = "/calibre-main/Calibre Library"' $dirpath > "$tmp" && mv "$tmp" $dirpath
fi

