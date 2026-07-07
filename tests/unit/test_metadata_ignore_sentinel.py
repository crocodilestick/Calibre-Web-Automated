# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""
Unit Tests for Auto-Metadata Ignore Sentinel Feature

Tests verify that books whose description contains a configured sentinel
string are skipped by the automatic metadata fetch pipeline.

The sentinel logic in fetch_and_apply_metadata() is tested by mocking the
cps module tree (Flask, flask_babel, etc. are not required) and exercising
the function through its public interface.
"""

import pytest
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_book(description="", title="Test Book", book_id=1):
    """Create a mock book with the given description in comments."""
    book = MagicMock()
    book.title = title
    book.id = book_id
    if description:
        comment = MagicMock()
        comment.text = description
        book.comments = [comment]
    else:
        book.comments = []
    book.authors = []
    return book


def _make_cwa_settings(sentinel="", fetch_enabled=True):
    """Create a CWA settings dict with the given sentinel value."""
    return {
        'auto_metadata_fetch_enabled': fetch_enabled,
        'auto_metadata_ignore_sentinel': sentinel,
        'metadata_provider_hierarchy': '["google"]',
        'metadata_providers_enabled': '{}',
    }


_STUBBED_MODULES = ['cps', 'cps.logger', 'cps.db', 'cps.search_metadata',
                     'cps.metadata_helper', 'cwa_db']


def _import_metadata_helper():
    """Import cps.metadata_helper with cps module tree mocked out.

    The cps package normally pulls in Flask, flask_babel, SQLAlchemy, etc.
    We stub just enough of the module tree so that metadata_helper can be
    imported and its functions exercised.

    Returns (module, db_stub, mock_log, saved_modules).
    """
    # Snapshot modules we're about to overwrite so we can restore them later
    saved_modules = {name: sys.modules.get(name) for name in _STUBBED_MODULES}

    # Remove any previously-cached import so we get a fresh module
    for mod_name in list(sys.modules):
        if mod_name == 'cps.metadata_helper' or mod_name.startswith('cps.metadata_helper.'):
            del sys.modules[mod_name]

    # Ensure the cps package stub exists with __path__ pointing to the real
    # cps/ directory so importlib can locate cps.metadata_helper on disk.
    cps_dir = str(Path(__file__).parent.parent.parent / "cps")
    cps_stub = types.ModuleType('cps')
    cps_stub.__path__ = [cps_dir]  # type: ignore[attr-defined]
    sys.modules['cps'] = cps_stub

    # Stub cps.logger
    logger_stub = types.ModuleType('cps.logger')
    mock_log = MagicMock()
    logger_stub.create = MagicMock(return_value=mock_log)  # type: ignore[attr-defined]
    sys.modules['cps.logger'] = logger_stub

    # Stub cps.db
    db_stub = types.ModuleType('cps.db')
    db_stub.CalibreDB = MagicMock()  # type: ignore[attr-defined]
    sys.modules['cps.db'] = db_stub

    # Stub cps.search_metadata
    sm_stub = types.ModuleType('cps.search_metadata')
    sm_stub.cl = []  # type: ignore[attr-defined]
    sys.modules['cps.search_metadata'] = sm_stub

    # Stub cwa_db (scripts/)
    cwa_db_stub = types.ModuleType('cwa_db')
    cwa_db_stub.CWA_DB = MagicMock  # type: ignore[attr-defined]
    sys.modules['cwa_db'] = cwa_db_stub

    # Now import the real module
    import importlib
    mod = importlib.import_module('cps.metadata_helper')
    return mod, db_stub, mock_log, saved_modules


def _cleanup_metadata_helper(saved_modules):
    """Restore sys.modules entries that were overwritten by _import_metadata_helper."""
    for name, original in saved_modules.items():
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original


# ---------------------------------------------------------------------------
# Sentinel logic tests (no Flask/Docker required)
# ---------------------------------------------------------------------------

@pytest.fixture
def metadata_helper():
    """Import metadata_helper with stubbed dependencies; clean up sys.modules after."""
    mod, db_stub, mock_log, saved = _import_metadata_helper()
    yield mod, db_stub, mock_log
    _cleanup_metadata_helper(saved)


@pytest.mark.unit
class TestMetadataIgnoreSentinel:
    """Test the ignore-sentinel check in fetch_and_apply_metadata."""

    def test_sentinel_in_description_skips_fetch(self, metadata_helper):
        """When the sentinel string is present in the book description, metadata fetch is skipped."""
        mod, db_stub, mock_log = metadata_helper

        sentinel = "[no-metadata-fetch]"
        book = _make_book(description=f"A web article about testing. {sentinel}")

        db_stub.CalibreDB.session_factory = True
        mock_calibre = MagicMock()
        mock_calibre.get_book.return_value = book
        db_stub.CalibreDB.return_value = mock_calibre

        mock_cwa_db = MagicMock()
        mock_cwa_db.get_cwa_settings.return_value = _make_cwa_settings(sentinel=sentinel)
        mod.CWA_DB = MagicMock(return_value=mock_cwa_db)

        result = mod.fetch_and_apply_metadata(book_id=1)

        assert result is False
        mock_calibre.session.close.assert_not_called()

    def test_sentinel_not_in_description_proceeds(self, metadata_helper):
        """When the sentinel is configured but NOT in the description, fetch proceeds normally."""
        mod, db_stub, mock_log = metadata_helper

        sentinel = "[no-metadata-fetch]"
        book = _make_book(description="A perfectly normal book description.")

        db_stub.CalibreDB.session_factory = True
        mock_calibre = MagicMock()
        mock_calibre.get_book.return_value = book
        db_stub.CalibreDB.return_value = mock_calibre

        mock_cwa_db = MagicMock()
        mock_cwa_db.get_cwa_settings.return_value = _make_cwa_settings(sentinel=sentinel)
        mod.CWA_DB = MagicMock(return_value=mock_cwa_db)

        result = mod.fetch_and_apply_metadata(book_id=1)

        assert result is False
        mock_calibre.session.close.assert_called_once()

    def test_empty_sentinel_disables_feature(self, metadata_helper):
        """When the sentinel setting is empty, the check is disabled entirely."""
        mod, db_stub, mock_log = metadata_helper

        book = _make_book(description="Description with [no-metadata-fetch] in it.")

        db_stub.CalibreDB.session_factory = True
        mock_calibre = MagicMock()
        mock_calibre.get_book.return_value = book
        db_stub.CalibreDB.return_value = mock_calibre

        mock_cwa_db = MagicMock()
        mock_cwa_db.get_cwa_settings.return_value = _make_cwa_settings(sentinel="")
        mod.CWA_DB = MagicMock(return_value=mock_cwa_db)

        mod.fetch_and_apply_metadata(book_id=1)

        mock_calibre.session.close.assert_called_once()

    def test_sentinel_substring_match(self, metadata_helper):
        """Sentinel uses substring matching, not exact token matching."""
        mod, db_stub, mock_log = metadata_helper

        sentinel = "CWA_IGNORE"
        book = _make_book(description="Metadata: CWA_IGNORE_THIS_BOOK please")

        db_stub.CalibreDB.session_factory = True
        mock_calibre = MagicMock()
        mock_calibre.get_book.return_value = book
        db_stub.CalibreDB.return_value = mock_calibre

        mock_cwa_db = MagicMock()
        mock_cwa_db.get_cwa_settings.return_value = _make_cwa_settings(sentinel=sentinel)
        mod.CWA_DB = MagicMock(return_value=mock_cwa_db)

        result = mod.fetch_and_apply_metadata(book_id=1)

        assert result is False

    def test_book_with_no_comments_not_skipped(self, metadata_helper):
        """A book with no description/comments is never skipped by the sentinel."""
        mod, db_stub, mock_log = metadata_helper

        sentinel = "[no-metadata-fetch]"
        book = _make_book(description="")

        db_stub.CalibreDB.session_factory = True
        mock_calibre = MagicMock()
        mock_calibre.get_book.return_value = book
        db_stub.CalibreDB.return_value = mock_calibre

        mock_cwa_db = MagicMock()
        mock_cwa_db.get_cwa_settings.return_value = _make_cwa_settings(sentinel=sentinel)
        mod.CWA_DB = MagicMock(return_value=mock_cwa_db)

        mod.fetch_and_apply_metadata(book_id=1)

        mock_calibre.session.close.assert_called_once()

    def test_whitespace_only_sentinel_disables_feature(self, metadata_helper):
        """A sentinel that is only whitespace is treated as empty (feature disabled)."""
        mod, db_stub, mock_log = metadata_helper

        book = _make_book(description="Some description with spaces")

        db_stub.CalibreDB.session_factory = True
        mock_calibre = MagicMock()
        mock_calibre.get_book.return_value = book
        db_stub.CalibreDB.return_value = mock_calibre

        mock_cwa_db = MagicMock()
        mock_cwa_db.get_cwa_settings.return_value = _make_cwa_settings(sentinel="   ")
        mod.CWA_DB = MagicMock(return_value=mock_cwa_db)

        mod.fetch_and_apply_metadata(book_id=1)

        mock_calibre.session.close.assert_called_once()

    def test_fetch_disabled_globally_returns_false(self, metadata_helper):
        """When auto_metadata_fetch_enabled is False, sentinel is never checked."""
        mod, db_stub, mock_log = metadata_helper

        db_stub.CalibreDB.session_factory = True

        mock_cwa_db = MagicMock()
        mock_cwa_db.get_cwa_settings.return_value = _make_cwa_settings(
            sentinel="[no-metadata-fetch]", fetch_enabled=False
        )
        mod.CWA_DB = MagicMock(return_value=mock_cwa_db)

        result = mod.fetch_and_apply_metadata(book_id=1)

        assert result is False
        db_stub.CalibreDB.assert_not_called()
