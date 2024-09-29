#!/bin/sh

docker build --tag crocodilestick/calibre-web-automated:master 
# optional: --build-arg="BUILD_DATE=27-09-2024 12:06" --build-arg="VERSION=2.1.0-test-5" .

mkdir -p build

