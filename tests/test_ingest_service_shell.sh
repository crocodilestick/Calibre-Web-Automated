#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
tmpdir=$(mktemp -d)
trap 'rm -rf "$tmpdir"' EXIT

mkdir -p "$tmpdir/watch" "$tmpdir/processing" "$tmpdir/recent"
processor_log="$tmpdir/processor.log"
post_batch_log="$tmpdir/post-batch.log"
touch "$processor_log"
touch "$post_batch_log"

stub="$tmpdir/processor-stub.sh"
cat > "$stub" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$1" >> "$PROCESSOR_LOG"
exit "${PROCESSOR_EXIT_CODE:-0}"
STUB
chmod +x "$stub"

post_batch_stub="$tmpdir/post-batch-stub.sh"
cat > "$post_batch_stub" <<'STUB'
#!/usr/bin/env bash
set -euo pipefail
printf 'post-batch\n' >> "$POST_BATCH_LOG"
STUB
chmod +x "$post_batch_stub"

export WATCH_FOLDER="$tmpdir/watch"
export CWA_INGEST_SERVICE_TEST_MODE=1
export CWA_INGEST_PROCESSING_DIR="$tmpdir/processing"
export CWA_INGEST_RECENT_DIR="$tmpdir/recent"
export CWA_INGEST_RETRY_QUEUE="$tmpdir/retry_queue"
export CWA_INGEST_STATUS_FILE="$tmpdir/status"
export CWA_INGEST_RECENT_EVENT_TTL=1
export CWA_INGEST_BATCH_DIRTY_FILE="$tmpdir/batch_dirty"
export CWA_INGEST_BATCH_LAST_SUCCESS_FILE="$tmpdir/batch_last_success"
export CWA_INGEST_BATCH_QUIET_SECONDS=1
export CWA_INGEST_POST_BATCH_CMD="$post_batch_stub"
export CWA_INGEST_PROCESSOR_CMD="$stub"
export PROCESSOR_LOG="$processor_log"
export POST_BATCH_LOG="$post_batch_log"
export PROCESSOR_EXIT_CODE=0

# shellcheck disable=SC1091
source "$REPO_ROOT/root/etc/s6-overlay/s6-rc.d/cwa-ingest-service/run" >/dev/null

assert_contains() {
        local haystack="$1"
        local needle="$2"
        if [[ "$haystack" != *"$needle"* ]]; then
                printf 'Expected output to contain: %s\nActual output:\n%s\n' "$needle" "$haystack" >&2
                exit 1
        fi
}

assert_processor_invocations() {
        local expected="$1"
        local actual
        actual=$(wc -l < "$processor_log" | tr -d ' ')
        if [ "$actual" != "$expected" ]; then
                printf 'Expected %s processor invocations, saw %s\n' "$expected" "$actual" >&2
                printf 'Processor log:\n' >&2
                cat "$processor_log" >&2
                exit 1
        fi
}

assert_marker_count() {
        local dir="$1"
        local expected="$2"
        local actual
        actual=$(find "$dir" -type f | wc -l | tr -d ' ')
        if [ "$actual" != "$expected" ]; then
                printf 'Expected %s marker(s) in %s, saw %s\n' "$expected" "$dir" "$actual" >&2
                find "$dir" -type f -print >&2
                exit 1
        fi
}

missing_path="$tmpdir/watch/missing.epub"
output=$(handle_event "$missing_path" 2>&1)
assert_contains "$output" "Skipping stale event for missing file"
assert_processor_invocations 0
assert_marker_count "$CWA_INGEST_RECENT_DIR" 1

output=$(handle_event "$missing_path" 2>&1)
assert_contains "$output" "Skipping duplicate recent event"
assert_processor_invocations 0
assert_marker_count "$CWA_INGEST_RECENT_DIR" 1

sleep 2
printf 'replacement\n' > "$missing_path"
output=$(handle_event "$missing_path" 2>&1)
assert_contains "$output" "Starting Ingest Processor"
assert_processor_invocations 1
assert_marker_count "$CWA_INGEST_PROCESSING_DIR" 0

odd_path="$tmpdir/watch/odd name [1] ; test.epub"
printf 'odd\n' > "$odd_path"
output=$(handle_event "$odd_path" 2>&1)
assert_contains "$output" "Starting Ingest Processor"
assert_processor_invocations 2
assert_marker_count "$CWA_INGEST_PROCESSING_DIR" 0

if ! grep -Fxq "$odd_path" "$processor_log"; then
        printf 'Expected odd path to be passed safely to processor stub\n' >&2
        cat "$processor_log" >&2
        exit 1
fi

output=$(handle_event "$odd_path" 2>&1)
assert_contains "$output" "Skipping duplicate recent event"
assert_processor_invocations 2

printf 'odd changed content\n' > "$odd_path"
output=$(handle_event "$odd_path" 2>&1)
assert_contains "$output" "Starting Ingest Processor"
assert_processor_invocations 3
assert_marker_count "$CWA_INGEST_PROCESSING_DIR" 0

export PROCESSOR_EXIT_CODE=2
busy_path="$tmpdir/watch/busy.epub"
printf 'busy\n' > "$busy_path"
handle_event "$busy_path" >/dev/null 2>&1 || true
assert_processor_invocations 4
assert_marker_count "$CWA_INGEST_PROCESSING_DIR" 0
if ! grep -Fxq "$busy_path" "$CWA_INGEST_RETRY_QUEUE"; then
        printf 'Expected busy path to remain in retry queue\n' >&2
        cat "$CWA_INGEST_RETRY_QUEUE" >&2
        exit 1
fi

rm -f "$busy_path"
process_retry_queue >/dev/null 2>&1
if [ -s "$CWA_INGEST_RETRY_QUEUE" ]; then
        printf 'Expected vanished retry path to be dropped from queue\n' >&2
        cat "$CWA_INGEST_RETRY_QUEUE" >&2
        exit 1
fi

rm -f "$missing_path" "$odd_path" "$busy_path"
printf 'dirty\n' > "$CWA_INGEST_BATCH_DIRTY_FILE"
touch "$CWA_INGEST_BATCH_LAST_SUCCESS_FILE"
sleep 2
output=$(maybe_run_post_batch_follow_up 2>&1)
assert_contains "$output" "Post-batch follow-up triggered"
assert_contains "$output" "Post-batch follow-up completed"
if [ -e "$CWA_INGEST_BATCH_DIRTY_FILE" ]; then
        printf 'Expected dirty marker to be cleared after successful post-batch follow-up\n' >&2
        exit 1
fi
if [ "$(wc -l < "$post_batch_log" | tr -d ' ')" != "1" ]; then
        printf 'Expected exactly one post-batch invocation\n' >&2
        cat "$post_batch_log" >&2
        exit 1
fi
maybe_run_post_batch_follow_up >/dev/null 2>&1
if [ "$(wc -l < "$post_batch_log" | tr -d ' ')" != "1" ]; then
        printf 'Expected clean state not to retrigger post-batch follow-up\n' >&2
        cat "$post_batch_log" >&2
        exit 1
fi
