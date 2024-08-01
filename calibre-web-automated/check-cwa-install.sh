#!/bin/bash

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m' # No Color

# Print promt title
echo "====== Calibre-Web Automator -- Status of Monitoring Services ======"
echo ""

if s6-rc -a list | grep -q 'new-book-detector'; then
    echo -e "- new-book-detector ${GREEN}is running${NC}"
    nb=true
else
    echo -e "- new-book-detector ${RED}is not running${NC}"
    nb=false
fi

if s6-rc -a list | grep -q 'books-to-process-detector'; then
    echo -e "- books-to-process-detector ${GREEN}is running${NC}"
    bp=true
else
    echo -e "- books-to-process-detector ${RED}is not running${NC}"
    bp=false
fi

if s6-rc -a list | grep -q 'metadata-change-detector'; then
    echo -e "- metadata-change-detector ${GREEN}is running${NC}"
    mc=true
else
    echo -e "- metadata-change-detector ${RED}is not running${NC}"
    mc=false
fi

echo ""

if $cs && $bs && $mc; then
    echo -e "Calibre-Web-Automater was ${GREEN}successfully installed ${NC}and ${GREEN}is running properly!${NC}"
else
    echo -e "Calibre-Web-Automater was ${RED}not installed successfully${NC}, please check the logs for more information."
fi