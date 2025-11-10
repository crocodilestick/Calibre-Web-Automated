# Progress Syncing Module

Syncs reading progress across e-readers using file checksums for book identification.

## Quick Start

```python
from cps.progress_syncing import calculate_and_store_checksum, get_latest_checksum

# Generate and store checksum
checksum = calculate_and_store_checksum(
    book_id=123,
    book_format='EPUB',
    file_path='/calibre-library/Author/Book/book.epub'
)
# Returns: '9e107d9d372bb6826bd81d3542a419d6'

# Retrieve for sync lookup
checksum = get_latest_checksum(book_id=123, book_format='EPUB')
```

## Structure

```
cps/progress_syncing/
├── models.py              # Database schema
├── checksums/
│   ├── koreader.py       # Partial MD5 algorithm
│   └── manager.py        # Storage and retrieval
└── protocols/
    └── kosync.py         # KOSync protocol (KOReader)
```

## Checksum Algorithm

KOReader partialMD5: Samples 1024 bytes at 11 positions (0, 4K, 16K, 64K, 256K, 1M, 4M, 16M, 64M, 256M, 1G) instead of hashing entire file. Returns 32-character MD5 hex.

**Auto-generated on:**
- Book import
- Metadata enforcement
- EPUB fixes
- Format conversion
- OPDS download with embedded metadata
- Container startup (backfills existing books)

**History tracking:** All checksums stored indefinitely. New checksums added alongside old ones when files change, enabling sync with any file version on user devices.

## Database Schema

```sql
CREATE TABLE book_format_checksums (
    id INTEGER PRIMARY KEY,
    book INTEGER REFERENCES books(id),
    format TEXT,           -- 'EPUB', 'PDF', etc.
    checksum TEXT(32),     -- MD5 hex
    version TEXT,          -- 'koreader'
    created TIMESTAMP
);
CREATE INDEX idx_checksum_lookup ON book_format_checksums(checksum, format);
```

Stored in `metadata.db`. Query orders by `created DESC` to prefer latest checksums.

## API

### Checksum Management

```python
from cps.progress_syncing import (
    calculate_koreader_partial_md5,
    calculate_and_store_checksum,
    get_latest_checksum,
    get_checksum_history
)

# Calculate without storing
checksum = calculate_koreader_partial_md5('/path/to/book.epub')
# => '9e107d9d372bb6826bd81d3542a419d6' or None

# Calculate and store
checksum = calculate_and_store_checksum(
    book_id=123,
    book_format='EPUB',
    file_path='/path/to/book.epub'
)

# Get latest
checksum = get_latest_checksum(book_id=123, book_format='EPUB')

# Get history (newest first)
history = get_checksum_history(book_id=123, book_format='EPUB')
# => [('abc...', 'koreader', '2025-11-09T10:30:00'), ...]
```

### Book Lookup

```python
from cps.progress_syncing.protocols.kosync import get_book_by_checksum

result = get_book_by_checksum('9e107d9d372bb6826bd81d3542a419d6')
if result:
    book_id, format, title, path, version = result
```

## KOSync Protocol

HTTP Basic Auth endpoints for KOReader devices:

- `GET /kosync` - Plugin download
- `GET /kosync/users/auth` - Authentication
- `GET /kosync/syncs/progress/<checksum>` - Get progress
- `PUT /kosync/syncs/progress` - Update progress

Progress stored in `kosync_progress` table (app.db). Updates `ReadBook` and `KoboReadingState` tables for web UI and Kobo device sync.

## Testing

```bash
# Unit tests - Algorithm, storage, database
pytest tests/unit/test_progress_syncing_*.py -v

# Integration tests - Full sync workflow
pytest tests/integration/test_progress_syncing_*.py -v
pytest tests/integration/test_kosync_*.py -v
```

## Extending

### New Sync Protocol

```python
# protocols/new_protocol.py
from flask import Blueprint, request
from .kosync import get_book_by_checksum

new_protocol = Blueprint('new_protocol', __name__)

@new_protocol.route('/new_protocol/sync', methods=['PUT'])
def sync():
    checksum = request.json['document']
    book_id, format, title, path, version = get_book_by_checksum(checksum)
    # Implement sync logic
```

Register in `cps/main.py`:
```python
from .progress_syncing.protocols.new_protocol import new_protocol
app.register_blueprint(new_protocol)
```

### New Checksum Algorithm

```python
# checksums/new_algorithm.py
def calculate_new_algorithm(filepath: str) -> str:
    # Implementation
    return checksum

# Store alongside existing
from .manager import store_checksum
store_checksum(book_id=123, book_format='EPUB',
               checksum=new_checksum, version='algorithm_v2')
```

Database supports multiple algorithm versions per book automatically.

## References

- [KOReader partialMD5](https://github.com/koreader/koreader/blob/master/frontend/util.lua#L1107)
- [KOSync protocol](https://github.com/koreader/koreader-sync-server)
- CWA plugin: `koreader/plugins/cwasync.koplugin/`
