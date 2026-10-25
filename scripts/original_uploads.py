# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Original-byte provenance for opt-in exact duplicate prevention.

Original hashes survive CWA metadata rewrites. UUID validation prevents stale
book IDs from suppressing imports. External format replacement cannot be
identified from UUIDs, so skipped inputs are always retained in quarantine.
"""
import errno
import hashlib
import os
import re
import shutil
import sqlite3
import stat
import uuid
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

_UPLOAD_PREFIX = re.compile(r'^new_[0-9]+_([0-9]{8})_([0-9]{6})_([0-9]{6})_(?=.+\.[^.]+$)')


class GuardError(RuntimeError):
    """Preserve incoming data when exact duplicate handling cannot complete."""


def clean_upload_filename(filename):
    """Strip only a valid generated web-upload prefix from a basename."""
    if not filename or Path(filename).name != filename or "\\" in filename:
        raise GuardError("invalid upload basename")
    match = _UPLOAD_PREFIX.match(filename)
    if match is None:
        return filename
    try:
        datetime.strptime("".join(match.groups()), "%Y%m%d%H%M%S%f")
    except ValueError:
        return filename
    return filename[match.end():]


def _safe_path(path):
    path = Path(os.path.abspath(path))
    if any(item.is_symlink() for item in (path, *path.parents)):
        raise GuardError('symlink path refused')
    return path


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _regular(path):
    info = _safe_path(path).stat()
    if not stat.S_ISREG(info.st_mode):
        raise GuardError('regular file required')
    return info


def _sha256(path):
    before = _regular(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or _identity(before) != _identity(opened):
            raise GuardError('file changed before hashing')
        digest = hashlib.sha256()
        while chunk := os.read(fd, 1024 * 1024):
            digest.update(chunk)
        if (_identity(os.fstat(fd)) != _identity(opened)
                or _identity(_regular(path)) != _identity(opened)):
            raise GuardError('file changed during hashing')
        return digest.digest()
    finally:
        os.close(fd)


def _stored_path(library, relative, basename, file_format):
    if not all(isinstance(value, str) for value in (relative, basename, file_format)):
        raise GuardError('unsafe library database path')
    parts = PurePosixPath(relative)
    if (not relative or parts.is_absolute() or '..' in parts.parts
            or '\\' in relative or not basename or Path(basename).name != basename
            or '\\' in basename or basename in ('.', '..')
            or not re.fullmatch(r'[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*', file_format)):
        raise GuardError('unsafe library database path')
    library = Path(library).resolve(strict=True)
    candidate = library / relative / (basename + '.' + file_format.lower())
    # Resolve the candidate before checking containment so symlinks in a stored
    # Calibre path cannot redirect validation outside the configured library.
    try:
        resolved = candidate.resolve(strict=False)
    except RuntimeError as exc:
        raise GuardError('unsafe stored library path') from exc
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise GuardError('unsafe stored library path') from exc
        raise
    if not resolved.is_relative_to(library):
        raise GuardError('library path escape refused')
    # Reject symlinks within the library tree as well. The configured root may
    # itself be a symlink; UploadIndex stores its canonical target.
    try:
        return _safe_path(candidate)
    except GuardError as exc:
        raise GuardError('unsafe stored library path') from exc


def ensure_schema(connection):
    """Validate provenance columns by name and create its lookup index."""
    rows = connection.execute("PRAGMA table_info(cwa_original_uploads)").fetchall()
    actual = {row[1] for row in rows}
    expected = {
        "library_uuid", "book_id", "book_uuid", "format", "original_sha256",
        "original_size", "original_ext", "output_sha256", "role", "created_at",
    }
    if not rows or not expected.issubset(actual):
        raise sqlite3.OperationalError(
            "cwa_original_uploads schema mismatch: "
            f"missing={sorted(expected - actual)}"
        )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS cwa_original_uploads_lookup "
        "ON cwa_original_uploads(library_uuid, original_sha256)"
    )
    connection.commit()



@dataclass(frozen=True)
class Original:
    sha256: str
    size: int
    extension: str


def fingerprint(path):
    path = Path(path)
    before = _regular(path)
    digest = _sha256(path).hex()
    if _identity(_regular(path)) != _identity(before):
        raise GuardError("source changed while fingerprinting")
    return Original(digest, before.st_size, path.suffix[1:].upper())


def _metadata(metadata_db):
    path = Path(metadata_db).absolute()
    return sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=30)


def library_uuid(metadata_db):
    with closing(_metadata(metadata_db)) as con:
        row = con.execute("SELECT uuid FROM library_id").fetchone()
    if not row or not row[0]:
        raise GuardError("Calibre library UUID is unavailable")
    return row[0]


def _targets(metadata_db, book_id=None, file_format=None):
    query = ("SELECT books.id, books.uuid, books.path, data.name, data.format "
             "FROM books JOIN data ON data.book=books.id WHERE 1=1")
    args = []
    if book_id is not None:
        query += " AND books.id=?"
        args.append(book_id)
    if file_format is not None:
        query += " AND upper(data.format)=?"
        args.append(file_format.upper())
    with closing(_metadata(metadata_db)) as con:
        return con.execute(query + " ORDER BY books.id", args).fetchall()


class UploadIndex:
    def __init__(self, connection, metadata_db, library):
        self.connection = connection
        self.metadata_db = str(metadata_db)
        self.library = Path(library).resolve(strict=True)
        if not self.library.is_dir():
            raise GuardError("library directory is unavailable")
        ensure_schema(connection)
        self.library_uuid = library_uuid(metadata_db)

    def find(self, original):
        rows = self.connection.execute(
            "SELECT book_id, book_uuid, format FROM cwa_original_uploads "
            "WHERE library_uuid=? AND original_sha256=? AND original_size=?",
            (self.library_uuid, original.sha256, original.size)).fetchall()
        for book_id, book_uuid, file_format in rows:
            for target in _targets(self.metadata_db, book_id, file_format):
                if target[1] != book_uuid:
                    continue
                try:
                    _regular(_stored_path(self.library, target[2], target[3], target[4]))
                except (FileNotFoundError, GuardError):
                    continue
                return book_id
        return None

    def find_current(self, original):
        """Legacy libraries have no original provenance. Compare their current bytes."""
        for target in _targets(self.metadata_db, file_format=original.extension):
            try:
                candidate = _stored_path(self.library, target[2], target[3], target[4])
                info = _regular(candidate)
            except (FileNotFoundError, GuardError):
                continue
            if info.st_size == original.size and _sha256(candidate).hex() == original.sha256:
                return target[0]
        return None

    def forget_format(self, book_id, file_format):
        # Run BEFORE replacing an explicit format. A failed replacement may lose
        # an optimization, but must never leave a false positive for discarded bytes.
        with self.connection:
            self.connection.execute(
                "DELETE FROM cwa_original_uploads WHERE library_uuid=? AND book_id=? AND format=?",
                (self.library_uuid, book_id, file_format.upper()))

    def record(self, original, book_id, file_format, accepted_sha256, role="primary",
               replace_existing=False):
        """Record only a reported CLI target whose current bytes equal accepted bytes.

        This check precedes optional metadata fetch/enforcement. Later metadata
        changes intentionally do not invalidate the source relationship.
        """
        targets = _targets(self.metadata_db, book_id, file_format)
        if len(targets) != 1 or not targets[0][1]:
            return False
        target = targets[0]
        candidate = _stored_path(self.library, target[2], target[3], target[4])
        if _sha256(candidate).hex() != accepted_sha256:
            return False  # e.g. --automerge ignore kept another file
        with self.connection:
            if replace_existing:
                self.connection.execute(
                    "DELETE FROM cwa_original_uploads WHERE library_uuid=? AND book_uuid=? AND format=?",
                    (self.library_uuid, target[1], file_format.upper()))
            self.connection.execute(
                "INSERT INTO cwa_original_uploads "
                "(library_uuid, book_id, book_uuid, format, original_sha256, original_size, original_ext, output_sha256, role) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(library_uuid, original_sha256, book_uuid, format) DO UPDATE SET "
                "book_id=excluded.book_id, original_size=excluded.original_size, "
                "original_ext=excluded.original_ext, output_sha256=excluded.output_sha256, "
                "role=excluded.role, created_at=CURRENT_TIMESTAMP",
                (self.library_uuid, book_id, target[1], file_format.upper(), original.sha256,
                 original.size, original.extension, accepted_sha256, role))
        return True


def quarantine(incoming, config_dir=None):
    """Retain the exact skipped upload under a unique, recoverable directory."""
    incoming = Path(incoming)
    root = Path(config_dir or os.environ.get("CWA_DB_PATH", "/config"))
    destination = root / "processed_books" / "duplicates" / uuid.uuid4().hex
    destination.mkdir(parents=True)
    target = destination / incoming.name
    shutil.copy2(incoming, target)
    incoming.unlink()
    return str(target)


def _cwa_connection(config_dir):
    path = Path(config_dir or os.environ.get("CWA_DB_PATH", "/config")) / "cwa.db"
    # Lifecycle cleanup must not create a new database during upgrade/startup.
    return sqlite3.connect(path.absolute().as_uri() + "?mode=rw", uri=True, timeout=30)


def forget_uploads(metadata_db, book_uuid, file_format=None, config_dir=None):
    lib_uuid = library_uuid(metadata_db)
    with closing(_cwa_connection(config_dir)) as con, con:
        sql = "DELETE FROM cwa_original_uploads WHERE library_uuid=? AND book_uuid=?"
        args = [lib_uuid, book_uuid]
        if file_format:
            sql += " AND format=?"
            args.append(file_format.upper())
        con.execute(sql, args)


def transfer_uploads(metadata_db, source_uuid, target_uuid, formats, config_dir=None):
    if not formats:
        return
    lib_uuid = library_uuid(metadata_db)
    with closing(_metadata(metadata_db)) as meta:
        row = meta.execute("SELECT id FROM books WHERE uuid=?", (target_uuid,)).fetchone()
    if not row:
        return
    with closing(_cwa_connection(config_dir)) as con, con:
        for file_format in formats:
            # Only called for formats actually copied and committed to the target.
            con.execute(
                "UPDATE OR IGNORE cwa_original_uploads SET book_id=?, book_uuid=? "
                "WHERE library_uuid=? AND book_uuid=? AND format=?",
                (row[0], target_uuid, lib_uuid, source_uuid, file_format.upper()))
