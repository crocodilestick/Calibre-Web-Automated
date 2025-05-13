#!/bin/bash

# Make required directories and files for metadata enforcement
make_dirs () {
    mkdir /config/metadata_change_logs
    mkdir /config/metadata_temp
    mkdir /cwa-book-ingest
    mkdir /calibre-library
}

# Change ownership & permissions as required
change_script_permissions () {
    echo ""
    #chmod 775 /app/calibre-web/cps/editbooks.py
    #chmod 775 /app/calibre-web/cps/admin.py
}

# Add aliases to /etc/bash.bashrc
add_aliases () {
    cat << 'EOF' >> /etc/bash.bashrc

# Calibre-Web Automated Aliases
alias cwa-check='bash /app/calibre-web-automated/scripts/check-cwa-services.sh'
alias cwa-change-dirs='nano /config/dirs.json'

cover-enforcer () {
    python3 /app/calibre-web-automated/scripts/cover_enforcer.py "$@"'
}

convert-library () {
    python3 /app/calibre-web-automated/scripts/convert_library.py "$@"'
}
EOF
}

echo "Running docker image setup script..."
make_dirs
change_script_permissions
add_aliases