# Progress Syncing Module

Syncs reading progress across e-reader devices (KOReader, etc.) using file checksums to identify books.

## Quick Start

```python
from cps.progress_syncing import calculate_and_store_checksum, get_latest_checksum

# Store checksum when book is added/modified
checksum = calculate_and_store_checksum(
    book_id=123,
    book_format='EPUB',
    file_path='/calibre-library/Author/Book/book.epub'
)

# Retrieve checksum for sync lookups
checksum = get_latest_checksum(book_id=123, book_format='EPUB')
```

## Structure

```
cps/progress_syncing/
├── models.py                # Database schema (book_format_checksums table)
├── checksums/
│   ├── koreader.py         # KOReader partialMD5 algorithm
│   └── manager.py          # Checksum storage and retrieval
└── protocols/
    └── kosync.py           # KOSync API for KOReader
```

## How It Works

### Checksum Algorithm

Uses KOReader's partialMD5: samples 1024 bytes at exponentially-spaced positions instead of hashing entire file.

**Positions:** 0, 4K, 16K, 64K, 256K, 1M, 4M, 16M, 64M, 256M, 1G

**Output:** 32-character hex MD5 hash

### Checksum History

All checksums are stored indefinitely. When a book file changes (metadata update, format conversion, EPUB fix), a new checksum is generated alongside the old one. This allows sync to work with any version of a file on user devices.

**Checksums generated:**
- Book import (`ingest_processor.py`)
- Metadata enforcement (`cover_enforcer.py`)
- EPUB fixing (`kindle_epub_fixer.py`)
- Format conversion
- OPDS download with embedded metadata (`helper.py`)
- Backfill for existing books (`generate_book_checksums.py` runs on boot)

### Database Schema

**book_format_checksums** (metadata.db)
```sql
CREATE TABLE book_format_checksums (
    id INTEGER PRIMARY KEY,
    book INTEGER REFERENCES books(id),
    format TEXT,           -- 'EPUB', 'PDF', etc.
    checksum TEXT(32),     -- MD5 hex
    version TEXT,          -- 'koreader'
    created TIMESTAMP      -- When generated
);
```

## API Functions

### Checksum Management

```python
from cps.progress_syncing import (
    calculate_koreader_partial_md5,
    calculate_and_store_checksum,
    get_latest_checksum,
    get_checksum_history,
    CHECKSUM_VERSION
)

# Calculate only (no storage)
checksum = calculate_koreader_partial_md5('/path/to/book.epub')
# Returns: '9e107d9d372bb6826bd81d3542a419d6' or None

# Calculate and store
checksum = calculate_and_store_checksum(
    book_id=123,
    book_format='EPUB',
    file_path='/path/to/book.epub'
)

# Get most recent checksum
checksum = get_latest_checksum(book_id=123, book_format='EPUB')

# Get all historical checksums (newest first)
history = get_checksum_history(book_id=123, book_format='EPUB')
# Returns: [('abc...', 'koreader', '2025-11-09T10:30:00'), ...]
```

### Book Lookup

```python
from cps.progress_syncing.protocols.kosync import get_book_by_checksum

result = get_book_by_checksum('9e107d9d372bb6826bd81d3542a419d6')
if result:
    book_id, format, title, path, version = result
    print(f"{title} (ID: {book_id}, {format})")
```

## KOSync Protocol

KOReader devices sync to `/kosync` endpoints using HTTP Basic Auth.

**Endpoints:**
- `GET /kosync` - Plugin download page
- `GET /kosync/users/auth` - Authentication check
- `GET /kosync/syncs/progress/<checksum>` - Get reading progress
- `PUT /kosync/syncs/progress` - Update reading progress

**Progress stored in:** `kosync_progress` table (app.db)

## Testing

```bash
# Unit tests
pytest tests/unit/test_progress_syncing_checksums.py -v  # Algorithm
pytest tests/unit/test_progress_syncing_manager.py -v    # Storage
pytest tests/unit/test_progress_syncing_models.py -v     # Database

# Integration
pytest tests/integration/test_kosync_checksums.py -v     # End-to-end
```

## Extending

### Add New Sync Protocol

1. Create `protocols/new_protocol.py`:
```python
from flask import Blueprint
from .kosync import get_book_by_checksum

new_protocol = Blueprint('new_protocol', __name__)

@new_protocol.route('/new_protocol/sync', methods=['PUT'])
def sync():
    checksum = request.json['document']
    result = get_book_by_checksum(checksum)
    # ... implement sync logic
```

2. Register in `cps/main.py`:
```python
from .progress_syncing.protocols.new_protocol import new_protocol
app.register_blueprint(new_protocol)
```

### Add New Checksum Algorithm

1. Implement in `checksums/new_algorithm.py`:
```python
def calculate_new_algorithm(filepath: str) -> Optional[str]:
    # ... implementation
    return checksum

NEW_VERSION = 'algorithm_v1'
```

2. Store alongside existing checksums:
```python
from .manager import store_checksum

store_checksum(
    book_id=123,
    book_format='EPUB',
    checksum=new_checksum,
    version='algorithm_v1'
)
```

The database automatically handles multiple algorithm versions per book.

## References

- [KOReader partialMD5 source](https://github.com/koreader/koreader/blob/master/frontend/util.lua#L1107)
- [KOSync protocol](https://github.com/koreader/koreader-sync-server)
- CWA KOReader plugin: `koreader/plugins/cwasync.koplugin/`
