#!/bin/sh

docker build --tag cwa-dev .
mkdir -p build
cp -n docker-compose.yml.dev build/docker-compose.yml
cd build/
docker compose up -d



