#!/bin/bash

# # Stores the loctation of this script
# SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# Make required directories and files for metadata enforcment
make_dirs () {
    mkdir /app/calibre-web-automated/metadata_change_logs
    mkdir /app/calibre-web-automated/metadata_temp
    mkdir /app/calibre-web-automated/cwa-import
}

# Change ownership & permissions as required
change_script_permissions () {
    # chown -R abc:users $SCRIPT_DIR/
    chmod +x /app/calibre-web-automated/scripts/check-cwa-install.sh
    chmod +x /app/calibre-web-automated/root/etc/s6-overlay/s6-rc.d/to-process-detector/run
    chmod +x /app/calibre-web-automated/root/etc/s6-overlay/s6-rc.d/new-book-detector/run
    chmod +x /app/calibre-web-automated/root/etc/s6-overlay/s6-rc.d/metadata-change-detector/run
    chmod 775 /app/calibre-web-automated/root/app/calibre-web/cps/editbooks.py
    chmod 775 /app/calibre-web-automated/root/app/calibre-web/cps/admin.py
}

# Add aliases to .bashrc
add_aliases () {
    echo "" | cat >> ~/.bashrc
    echo "# Calibre-Web Automator Aliases" | cat >> ~/.bashrc
    echo "alias cwa-check='bash /app/calibre-web-automated/scripts/check-cwa-install.sh'" | cat >> ~/.bashrc
    echo "alias cwa-change-dirs='nano /app/calibre-web-automated/dirs.json'" | cat >> ~/.bashrc
    
    echo "cover-enforcer () {" | cat >> ~/.bashrc
    echo '    python3 /app/calibre-web-automated/scripts/cover-enforcer.py "$@"' | cat >> ~/.bashrc
    echo "}" | cat >> ~/.bashrc
    
    echo "convert-library () {" | cat >> ~/.bashrc
    echo '    python3 /app/calibre-web-automated/scripts/convert-library.py "$@"' | cat >> ~/.bashrc
    echo "}" | cat >> ~/.bashrc
    
    source ~/.bashrc
}

echo "Running docker image setup script..."
make_dirs
change_script_permissions
add_aliases