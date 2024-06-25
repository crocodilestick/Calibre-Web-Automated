#!/bin/bash

GREEN='\033[0;32m'
NC='\033[0m' # No Color

# Script to automatically enable the automatic importing of epubs from the 'to_calibre' import folder upon container restart
# For help with S6 commands ect.: https://wiki.artixlinux.org/Main/S6

# Install required packages
apt install -y inotify-tools
apt install -y python3
apt install -y python3-pip
apt install -y nano

# Loctation of this current script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# Make sure other sctipts are executable and permissions are correct
chown -R abc:users /config
chmod +x $SCRIPT_DIR/check-cwa-install.sh
chmod +x $SCRIPT_DIR/books-to-process-scan.sh
chmod +x $SCRIPT_DIR/calibre-scan.sh

# Run setup.py to get dirs from user and store them in dirs.json
python3 $SCRIPT_DIR/setup.py

# Copy book processing python script & dirs.json to it's own directory in /etc
mkdir /etc/calibre-web-automator
cp "$SCRIPT_DIR/new-book-processor.py" /etc/calibre-web-automator/new-book-processor.py
cp "$SCRIPT_DIR/dirs.json" /etc/calibre-web-automator/dirs.json
cp "$SCRIPT_DIR/check-cwa-install.sh" /etc/calibre-web-automator/check-cwa-install.sh 

# Add aliases to .bashrc
echo "" | cat >> ~/.bashrc
echo "# Calibre-Web Automator Aliases" | cat >> ~/.bashrc
echo "alias cwa-check='sh /config/check-cwa-install.sh'" | cat >> ~/.bashrc
echo "alias cwa-change-dirs='nano /etc/calibre-web-automater/dirs.json'" | cat >> ~/.bashrc
source ~/.bashrc

# Setup inotify to watch for changes in the 'to_calibre' folder
mkdir /etc/s6-overlay/s6-rc.d/calibre-scan
echo "longrun" >| /etc/s6-overlay/s6-rc.d/calibre-scan/type
echo "bash run.sh" >| /etc/s6-overlay/s6-rc.d/calibre-scan/up
cp "$SCRIPT_DIR/calibre-scan.sh" /etc/s6-overlay/s6-rc.d/calibre-scan/run
touch /etc/s6-overlay/s6-rc.d/user/contents.d/calibre-scan

# Setup inotify to watch for changes in the 'to_process' folder
mkdir /etc/s6-overlay/s6-rc.d/books-to-process-scan
echo "longrun" >| /etc/s6-overlay/s6-rc.d/books-to-process-scan/type
echo "bash run.sh" >| /etc/s6-overlay/s6-rc.d/books-to-process-scan/up
cp "$SCRIPT_DIR/books-to-process-scan.sh" /etc/s6-overlay/s6-rc.d/books-to-process-scan/run
touch /etc/s6-overlay/s6-rc.d/user/contents.d/books-to-process-scan

# Setup completion notification
echo "${GREEN}SUCSESS${NC}: calibre-scan & books-to-process-scan setup complete!"
echo " - Please restart the container so the changes will take effect by typing 'exit' then presing enter, then running the docker command:"
echo "   docker restart <name-of-your-calibre-web-container>"
echo "\nTo check if the container is running properly followin the restart, use the command 'cwa-check' in the container's terminal."