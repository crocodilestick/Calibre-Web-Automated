#!/bin/bash
# Scaffold local development directory structure for CWA Alexandria

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Initializing local development environment ==="

# Create directories
mkdir -p local-dev/config
mkdir -p local-dev/ingest
mkdir -p local-dev/calibre-library

echo "Created local-dev directory structure."

# Copy app.db (Calibre-Web config database)
if [ -f "empty_library/app.db" ]; then
    if [ ! -f "local-dev/config/app.db" ]; then
        cp empty_library/app.db local-dev/config/app.db
        echo "Copied empty app.db to local-dev/config/app.db"
    else
        echo "local-dev/config/app.db already exists. Skipping copy."
    fi
else
    echo "Error: empty_library/app.db not found! Cannot initialize development environment." >&2
    exit 1
fi

# Copy metadata.db (Calibre library database)
if [ -f "empty_library/metadata.db" ]; then
    if [ ! -f "local-dev/calibre-library/metadata.db" ]; then
        cp empty_library/metadata.db local-dev/calibre-library/metadata.db
        echo "Copied empty metadata.db to local-dev/calibre-library/metadata.db"
    else
        echo "local-dev/calibre-library/metadata.db already exists. Skipping copy."
    fi
else
    echo "Error: empty_library/metadata.db not found! Cannot initialize development environment." >&2
    exit 1
fi

echo "Initialization complete."
