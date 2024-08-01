#!/bin/bash

# Stores the loctation of this script
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# Make required directories and files for metadata enforcment
make_dirs () {
    mkdir /app/calibre-web-automated/metadata_change_logs
    mkdir /app/calibre-web-automated/metadata_temp
    mkdir /app/calibre-web-automated/cwa-import
}

# Change ownership & permissions as required
change_script_permissions () {
    # chown -R abc:users $SCRIPT_DIR/
    chmod +x $SCRIPT_DIR/check-cwa-install.sh
    chmod +x $SCRIPT_DIR/root/etc/s6-overlay/s6-rc.d/to-process-detector/run
    chmod +x $SCRIPT_DIR/root/etc/s6-overlay/s6-rc.d/new-book-detector/run
    chmod +x $SCRIPT_DIR/root/etc/s6-overlay/s6-rc.d/metadata-change-detector/run
    chmod 775 $SCRIPT_DIR/root/app/calibre-web/cps/editbooks.py
    chmod 775 $SCRIPT_DIR/root/app/calibre-web/cps/admin.py
}

# Move python scripts & dirs.json to /etc/calibre-web-automator/
# TODO Try with COPY in Dockerfile
# move_scripts () {
#     cp $SCRIPT_DIR/new-book-processor.py /etc/calibre-web-automator/new-book-processor.py
#     cp $SCRIPT_DIR/dirs.json /etc/calibre-web-automator/dirs.json
#     cp $SCRIPT_DIR/check-cwa-install.sh /etc/calibre-web-automator/check-cwa-install.sh
#     cp $SCRIPT_DIR/cover-enforcer.py /etc/calibre-web-automator/cover-enforcer.py
#     cp $SCRIPT_DIR/cwa_db.py /etc/calibre-web-automator/cwa_db.py
#     cp $SCRIPT_DIR/convert-library.py /etc/calibre-web-automator/convert-library.py
# }

# Run setup.py to get dirs from user and store them in dirs.json
# run_cli_setup () {
#     python3 $SCRIPT_DIR/setup.py
# }

# Replace stock CW scripts with CWA modded ones
# replace_stock_cw_scripts () {
#     cp $SCRIPT_DIR/editbooks_cwa.py /app/calibre-web/cps/editbooks.py
#     cp $SCRIPT_DIR/admin_cwa.py /app/calibre-web/cps/admin.py
#     cp $SCRIPT_DIR/admin_cwa.html /app/calibre-web/cps/templates/admin.html
# }

# Add aliases to .bashrc
add_aliases () {
    echo "" | cat >> ~/.bashrc
    echo "# Calibre-Web Automator Aliases" | cat >> ~/.bashrc
    echo "alias cwa-check='bash /app/calibre-web-automated/check-cwa-install.sh'" | cat >> ~/.bashrc
    echo "alias cwa-change-dirs='nano /app/calibre-web-automated/dirs.json'" | cat >> ~/.bashrc
    
    echo "cover-enforcer () {" | cat >> ~/.bashrc
    echo '    python3 /app/calibre-web-automated/cover-enforcer.py "$@"' | cat >> ~/.bashrc
    echo "}" | cat >> ~/.bashrc
    
    echo "convert-library () {" | cat >> ~/.bashrc
    echo '    python3 /app/calibre-web-automated/convert-library.py "$@"' | cat >> ~/.bashrc
    echo "}" | cat >> ~/.bashrc
    
    source ~/.bashrc
}

# setup_monitoring_processes () {
#     # Setup inotify to watch for changes in the import_folder stored in dirs.json
#     mkdir /etc/s6-overlay/s6-rc.d/new-book-detector
#     echo "longrun" >| /etc/s6-overlay/s6-rc.d/new-book-detector/type
#     echo "bash run.sh" >| /etc/s6-overlay/s6-rc.d/new-book-detector/up
#     cp "$SCRIPT_DIR/new-book-detector.sh" /etc/s6-overlay/s6-rc.d/new-book-detector/run
#     touch /etc/s6-overlay/s6-rc.d/user/contents.d/new-book-detector
    
#     # Setup inotify to watch for changes in the ingest folder stored in dirs.json
#     mkdir /etc/s6-overlay/s6-rc.d/books-to-process-detector
#     echo "longrun" >| /etc/s6-overlay/s6-rc.d/books-to-process-detector/type
#     echo "bash run.sh" >| /etc/s6-overlay/s6-rc.d/books-to-process-detector/up
#     cp "$SCRIPT_DIR/books-to-process-detector.sh" /etc/s6-overlay/s6-rc.d/books-to-process-detector/run
#     touch /etc/s6-overlay/s6-rc.d/user/contents.d/books-to-process-detector
    
#     # Setup inotify to watch for changes to the metadata.db in the given calibre library
#     mkdir /etc/s6-overlay/s6-rc.d/metadata-change-detector
#     echo "longrun" >| /etc/s6-overlay/s6-rc.d/metadata-change-detector/type
#     echo "bash run.sh" >| /etc/s6-overlay/s6-rc.d/metadata-change-detector/up
#     cp "$SCRIPT_DIR/metadata-change-detector.sh" /etc/s6-overlay/s6-rc.d/metadata-change-detector/run
#     touch /etc/s6-overlay/s6-rc.d/user/contents.d/metadata-change-detector
# }

# Setup script install method completion screen
# setup_script_completion_screen () {
#     echo ""
#     echo -e "======== ${GREEN}SUCCESS${NC}: Calibre-Web-Automator Setup Complete! ========"
#     echo ""
#     echo " - Please restart the container so the changes will take effect."
#     echo " - Do so by typing 'exit', presing enter, then running the docker command:"
#     echo -e "    -- '${GREEN}docker restart <name-of-your-calibre-web-container${NC}'"
#     echo ""
#     echo -e "To check if CWA is running properly following the restart, use the\ncommand '${GREEN}cwa-check${NC}' in the container's terminal."
# }

# # Remove unnecessary files from /app/calibre-web-automted
# remove_unnecessary_files_from_app_dir () {
#     shopt -s extglob
#     rm -v -r /app/calibre-web-automated/!(calibre-web-automated|*.db|requirements.txt|LICENSE|README.md)
#     shopt -u extglob
# }

# # Change shown name throughout Web UI to Calibre-Web-Automated
# change_name_in_web_ui () {
#     sed -i -r '/<!DOCTYPE html>/i\{% set instance = "Calibre-Web Automated" %\}' /app/calibre-web/cps/templates/layout.html
# }
# # Add a switch theme button to the Web UI
# add_theme_switch_button () {
#     sed -i -r '/from \.web import web/i\ \ \ \ from .cwa_switch_theme import switch_theme' /app/calibre-web/cps/main.py
#     sed -i -r '/app\.register_blueprint\(search\)/i\ \ \ \ app\.register_blueprint\(switch_theme\)' /app/calibre-web/cps/main.py
#     cp $SCRIPT_DIR/cwa_switch_theme.py /app/calibre-web/cps/cwa-switch-theme.py
# }

# SCRIPT RUNS FROM HERE

# Check if any arguments were given with the script and change it's behaviour depending on what's given
# if [[ -z "$1" ]]
# then
#     echo "Starting CWA Manual installation..."
#     install_required_packages
#     make_dirs
#     change_script_permissions
#     move_scripts
#     run_cli_setup
#     replace_stock_cw_scripts
#     add_aliases
#     setup_monitoring_processes
#     change_name_in_web_ui
#     add_theme_switch_button
#     setup_script_completion_screen
# elif [[ "$1" == "-dockerbuild" ]]
# then
echo "Running docker image setup script..."
make_dirs
change_script_permissions
    # move_scripts
    # replace_stock_cw_scripts
add_aliases
    # setup_monitoring_processes
    # change_name_in_web_ui
    # add_theme_switch_button
    # remove_unnecessary_files_from_app_dir
# else
#     echo "$1 is not a valid argument for this script"
# fi