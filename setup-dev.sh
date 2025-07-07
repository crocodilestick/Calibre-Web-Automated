#!/bin/bash

echo "Setting up Calibre-Web-Automated development environment..."

# Create build directory and subdirectories
mkdir -p build/config
mkdir -p build/cwa-book-ingest
mkdir -p build/calibre-library

# Copy empty library if it doesn't exist
if [ ! -f "build/calibre-library/metadata.db" ]; then
    echo "Setting up empty calibre library..."
    cp -r empty_library/* build/calibre-library/
fi

# Set proper permissions
echo "Setting permissions..."
chmod -R 755 build/

echo "Development environment setup complete!"
echo ""
echo "Next steps:"
echo "1. Make build.sh executable: chmod +x build.sh"
echo "2. Build the dev image: ./build.sh"
echo "3. Start development environment: docker-compose -f docker-compose.yml.dev up -d"
echo "4. Access the application at: http://localhost:8084"
echo ""
echo "To view logs: docker-compose -f docker-compose.yml.dev logs -f"
echo "To stop: docker-compose -f docker-compose.yml.dev down" 