#!/usr/bin/env bash

#shellcheck disable=SC2086

/app/calibre-web-automated/scripts/cwa-init.sh

python3 /app/calibre-web-automated/scripts/auto_library.py &

/app/calibre-web-automated/scripts/cwa-auto-zipper.sh &

/app/calibre-web-automated/scripts/cwa-ingest-service.sh &

/app/calibre-web-automated/scripts/metadata-change-detector.sh &

exec \
  python3  \
    /app/calibre-web/cps.py \
    -o /dev/stdout \
    "$@"