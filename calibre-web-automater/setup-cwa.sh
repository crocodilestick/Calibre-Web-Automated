#! /bin/bash

# Script to automatically enable the automatic importing of epubs from the 'to_calibre' import folder upon container restart
# For help with S6 commands ect.: https://wiki.artixlinux.org/Main/S6

apt install -y inotify-tools
apt install -y python3
apt install -y python3-pip

# Loctation of this current script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# Run setup.py to get dirs from user and store them in dirs.json
python3 $SCRIPT_DIR/setup.py

# Copy book processing python script & dirs.json to it's own directory in /etc
mkdir /etc/calibre-web-automater
cp "$SCRIPT_DIR/new-book-processor.py" /etc/calibre-web-automater/new-book-processor.py
cp "$SCRIPT_DIR/dirs.json" /etc/calibre-web-automater/dirs.json

mkdir /etc/s6-overlay/s6-rc.d/calibre-scan
echo "longrun" >| /etc/s6-overlay/s6-rc.d/calibre-scan/type
echo "bash run.sh" >| /etc/s6-overlay/s6-rc.d/calibre-scan/up
cp "$SCRIPT_DIR/calibre-scan.sh" /etc/s6-overlay/s6-rc.d/calibre-scan/run
touch /etc/s6-overlay/s6-rc.d/user/contents.d/calibre-scan

mkdir /etc/s6-overlay/s6-rc.d/books-to-process-scan
echo "longrun" >| /etc/s6-overlay/s6-rc.d/books-to-process-scan/type
echo "bash run.sh" >| /etc/s6-overlay/s6-rc.d/books-to-process-scan/up
cp "$SCRIPT_DIR/books-to-process-scan.sh" /etc/s6-overlay/s6-rc.d/books-to-process-scan/run
touch /etc/s6-overlay/s6-rc.d/user/contents.d/books-to-process-scan

echo " "
echo "SUCSESS: calibre-scan & books-to-process-scan setup complete, please restart the container so the changes will take effect"
echo "Then run 's6-rc -a list' to check if calibre-scan & books-to-process-scan are in the list of running services" 