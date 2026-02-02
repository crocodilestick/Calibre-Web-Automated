#!/bin/bash

# Make required directories and files for metadata enforcement
make_dirs () {
    install -d -o abc -g abc /app/calibre-web-automated/metadata_change_logs
    install -d -o abc -g abc /app/calibre-web-automated/metadata_temp
    install -d -o abc -g abc /cwa-book-ingest
    install -d -o abc -g abc /calibre-library
}

# Change ownership & permissions as required
change_script_permissions () {
    chown -R abc:abc /etc/s6-overlay
    chmod +x /etc/s6-overlay/s6-rc.d/cwa-auto-library/run
    chmod +x /etc/s6-overlay/s6-rc.d/cwa-auto-zipper/run
    chmod +x /etc/s6-overlay/s6-rc.d/cwa-ingest-service/run
    chmod +x /etc/s6-overlay/s6-rc.d/cwa-init/run
    chmod +x /etc/s6-overlay/s6-rc.d/cwa-process-recovery/run
    chmod +x /etc/s6-overlay/s6-rc.d/metadata-change-detector/run
    chmod +x /etc/s6-overlay/s6-rc.d/calibre-binaries-setup/run
    chmod +x /etc/s6-overlay/s6-rc.d/svc-calibre-web-automated/run
    chmod +x /app/calibre-web-automated/scripts/check-cwa-services.sh
    chmod +x /app/calibre-web-automated/scripts/compile_translations.sh
    chmod 775 /app/calibre-web-automated/cps/editbooks.py
    chmod 775 /app/calibre-web-automated/cps/admin.py
}

# Add aliases to .bashrc
add_aliases () {
    cat << 'EOF' >> ~/.bashrc

# Calibre-Web Automated Aliases
alias cwa-check='bash /app/calibre-web-automated/scripts/check-cwa-services.sh'
alias cwa-change-dirs='nano /app/calibre-web-automated/dirs.json'
cover-enforcer () {
    python3 /app/calibre-web-automated/scripts/cover_enforcer.py "$@"
}
convert-library () {
    python3 /app/calibre-web-automated/scripts/convert_library.py "$@"
}
EOF
    
    source ~/.bashrc
}

echo "Running docker image setup script..."
make_dirs
change_script_permissions
add_aliases
# Generate .mo files from .po files in translations directory
bash /app/calibre-web-automated/scripts/compile_translations.sh