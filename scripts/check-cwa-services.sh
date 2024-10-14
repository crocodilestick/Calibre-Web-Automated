#!/bin/bash

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

# Print promt title
echo "====== Calibre-Web Automated -- Status of Monitoring Services ======"
echo ""


if s6-rc -a list | grep -q 'metadata-change-detector'; then
    echo -e "- metadata-change-detector ${GREEN}is running${NC}"
    mc=true
else
    echo -e "- metadata-change-detector ${RED}is not running${NC}"
    mc=false
fi

echo ""

if $mc; then
    echo -e "Calibre-Web-Automated was ${GREEN}successfully installed ${NC}and ${GREEN}is running properly!${NC}"
    exit 0
else
    echo -e "Calibre-Web-Automated was ${RED}not installed successfully${NC}, please check the logs for more information."
    if [ "$is" = true ] && [ "$mc" = false ] ; then
        exit 1
    elif [ "$is" = false ] && [ "$mc" = true ] ; then
        exit 2
    else
        exit 3
    fi
fi