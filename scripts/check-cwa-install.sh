#!/bin/bash

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

# Print promt title
echo "====== Calibre-Web Automated -- Status of Monitoring Services ======"
echo ""

# if s6-rc -a list | grep -q 'new-book-detector'; then
#     echo -e "- new-book-detector ${GREEN}is running${NC}"
#     nb=true
# else
#     echo -e "- new-book-detector ${RED}is not running${NC}"
#     nb=false
# fi

if s6-rc -a list | grep -q 'cwa-ingest-service'; then
    echo -e "- cwa-ingest-service ${GREEN}is running${NC}"
    is=true
else
    echo -e "- cwa-ingest-service ${RED}is not running${NC}"
    is=false
fi

if s6-rc -a list | grep -q 'metadata-change-detector'; then
    echo -e "- metadata-change-detector ${GREEN}is running${NC}"
    mc=true
else
    echo -e "- metadata-change-detector ${RED}is not running${NC}"
    mc=false
fi


echo ""

if $is && $mc; then
    echo -e "Calibre-Web-Automated was ${GREEN}successfully installed ${NC}and ${GREEN}is running properly!${NC}"
else
    echo -e "Calibre-Web-Automated was ${RED}not installed successfully${NC}, please check the logs for more information."
fi