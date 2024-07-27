#!/bin/bash

GREEN='\033[0;32m'
NC='\033[0m' # No Color

# Script to automatically enable the automatic importing of epubs from the import folder upon container restart
# For help with S6 commands ect.: https://wiki.artixlinux.org/Main/S6

# Install required packages
apt install -y xdg-utils
apt install -y inotify-tools
apt install -y python3
apt install -y python3-pip
apt install -y nano
apt install -y sqlite3

# Install python dependencies
pip install tabulate

# Loctation of this current script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# Make required directories and files for metadata enforcment
mkdir /etc/calibre-web-automator
mkdir /etc/calibre-web-automator/metadata_change_logs
mkdir /etc/calibre-web-automator/metadata_temp
mkdir /etc/calibre-web-automator/cwa-import

# Move python scripts & dirs.json to /etc/calibre-web-automator/
cp $SCRIPT_DIR/new-book-processor.py /etc/calibre-web-automator/new-book-processor.py
# cp $SCRIPT_DIR/dirs.json /etc/calibre-web-automator/dirs.json
cp $SCRIPT_DIR/check-cwa-install.sh /etc/calibre-web-automator/check-cwa-install.sh
cp $SCRIPT_DIR/cover-enforcer.py /etc/calibre-web-automator/cover-enforcer.py
cp $SCRIPT_DIR/cwa_db.py /etc/calibre-web-automator/cwa_db.py
cp $SCRIPT_DIR/convert-library.py /etc/calibre-web-automator/convert-library.py

# Change permissions of /etc/calibre-web-automator/
chown -R abc:1000 /etc/calibre-web-automator

# Make sure other sctipts are executable and permissions are correct
chown -R abc:users /config
chown -R abc:users /etc/calibre-web-automator

chmod +x $SCRIPT_DIR/check-cwa-install.sh
chmod +x $SCRIPT_DIR/to-process-detector.sh
chmod +x $SCRIPT_DIR/new-book-detector.sh
chmod +x $SCRIPT_DIR/metadata-change-detector.sh
chmod 775 $SCRIPT_DIR/editbooks_cwa.py

# Run setup.py to get dirs from user and store them in dirs.json
python3 $SCRIPT_DIR/setup.py

# Replace editbooks.py with the CWA edited version
cp $SCRIPT_DIR/editbooks_cwa.py /app/calibre-web/cps/editbooks.py

# Add aliases to .bashrc
echo "" | cat >> ~/.bashrc
echo "# Calibre-Web Automator Aliases" | cat >> ~/.bashrc
echo "alias cwa-check='bash /etc/calibre-web-automator/check-cwa-install.sh'" | cat >> ~/.bashrc
echo "alias cwa-change-dirs='nano /etc/calibre-web-automator/dirs.json'" | cat >> ~/.bashrc

echo "cover-enforcer () {" | cat >> ~/.bashrc
echo '    python3 /etc/calibre-web-automator/cover-enforcer.py "$@"' | cat >> ~/.bashrc
echo "}" | cat >> ~/.bashrc

echo "convert-library () {" | cat >> ~/.bashrc
echo '    python3 /etc/calibre-web-automator/convert-library.py "$@"' | cat >> ~/.bashrc
echo "}" | cat >> ~/.bashrc

source ~/.bashrc

# Setup inotify to watch for changes in the import_folder stored in dirs.json
mkdir /etc/s6-overlay/s6-rc.d/new-book-detector
echo "longrun" >| /etc/s6-overlay/s6-rc.d/new-book-detector/type
echo "bash run.sh" >| /etc/s6-overlay/s6-rc.d/new-book-detector/up
cp "$SCRIPT_DIR/new-book-detector.sh" /etc/s6-overlay/s6-rc.d/new-book-detector/run
touch /etc/s6-overlay/s6-rc.d/user/contents.d/new-book-detector

# Setup inotify to watch for changes in the ingest folder stored in dirs.json
mkdir /etc/s6-overlay/s6-rc.d/books-to-process-detector
echo "longrun" >| /etc/s6-overlay/s6-rc.d/books-to-process-detector/type
echo "bash run.sh" >| /etc/s6-overlay/s6-rc.d/books-to-process-detector/up
cp "$SCRIPT_DIR/books-to-process-detector.sh" /etc/s6-overlay/s6-rc.d/books-to-process-detector/run
touch /etc/s6-overlay/s6-rc.d/user/contents.d/books-to-process-detector

# Setup inotify to watch for changes to the metadata.db in the given calibre library
mkdir /etc/s6-overlay/s6-rc.d/metadata-change-detector
echo "longrun" >| /etc/s6-overlay/s6-rc.d/metadata-change-detector/type
echo "bash run.sh" >| /etc/s6-overlay/s6-rc.d/metadata-change-detector/up
cp "$SCRIPT_DIR/metadata-change-detector.sh" /etc/s6-overlay/s6-rc.d/metadata-change-detector/run
touch /etc/s6-overlay/s6-rc.d/user/contents.d/metadata-change-detector

# Setup completion notification
echo ""
echo -e "======== ${GREEN}SUCCESS${NC}: Calibre-Web-Automator Setup Complete! ========"
echo ""
echo " - Please restart the container so the changes will take effect."
echo " - Do so by typing 'exit', presing enter, then running the docker command:"
echo -e "    -- '${GREEN}docker restart <name-of-your-calibre-web-container${NC}'"
echo ""
echo -e "To check if CWA is running properly following the restart, use the\ncommand '${GREEN}cwa-check${NC}' in the container's terminal."