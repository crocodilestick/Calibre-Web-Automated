#!/bin/sh

docker build --tag calibre-web-automated:dev --build-arg="BUILD_DATE=$(date '+%Y/%m/%d')" --build-arg="VERSION=2.1.0-dev" .
mkdir -p build
cp -n docker-compose.yml.dev build/docker-compose.yml
cd build/
docker compose up -d



