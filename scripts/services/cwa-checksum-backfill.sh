#!/bin/bash
# cwa-checksum-backfill.sh — One-shot KOReader checksum backfill

echo "[checksum-backfill] Waiting for database schema..."

for i in $(seq 1 30); do
    if sqlite3 /calibre-library/metadata.db \
        "SELECT name FROM sqlite_master WHERE type='table' AND name='book_format_checksums';" \
        2>/dev/null | grep -q "book_format_checksums"; then
        echo "[checksum-backfill] Schema ready (attempt $i)"
        break
    fi
    sleep 1
done

echo "[checksum-backfill] Running checksum generation..."
python3 /app/calibre-web-automated/scripts/generate_book_checksums.py \
    --library-path /calibre-library --batch-size 50 || true
echo "[checksum-backfill] Complete."
