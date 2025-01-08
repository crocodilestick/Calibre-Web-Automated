#!/bin/bash -e

NOW="$(date +"%Y-%m-%d %H:%M:%S")"

version="V9.99.99"

if [[ -e build/testnum ]]; then
    testnum=$(cat build/testnum)
    testnum=$(( testnum + 1))
else
    echo Enter test version number\:
    read testnum
fi
echo $testnum > build/testnum

docker build --tag calibre-web-automated:dev --build-arg="BUILD_DATE=$NOW" --build-arg="VERSION=$version-TEST-$testnum" .

rm -rf build/ingest build/library build/config
mkdir -p build/ingest build/library build/config
cd build

PUID=$(id -u) PGID=$(id -g) docker compose -f docker-compose-dev.yml up -d calibre-web-automated-dev
( docker logs -f cwa-dev 2>/dev/null & ) | grep -q "\[ls.io-init\] done."
echo "Dev build is up at http://localhost:8088"
