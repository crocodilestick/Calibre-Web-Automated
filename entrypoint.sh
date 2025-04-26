#!/usr/bin/env bash

#shellcheck disable=SC2086

exec /app/calibre-web-automated/scripts/cwa-init.sh

exec python3 /app/calibre-web-automated/scripts/auto_library.py &

exec /app/calibre-web-automated/scripts/cwa-auto-zipper.sh &

exec /app/calibre-web-automated/scripts/cwa-ingest-service.sh &

exec /app/calibre-web-automated/scripts/metadata-change-detector.sh &

exec \
  python3  \
    /app/calibre-web/cps.py \
    -o /dev/stdout \
    "$@"