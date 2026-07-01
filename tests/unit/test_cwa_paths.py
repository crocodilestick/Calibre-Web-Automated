# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""
Unit Tests for cwa_paths module

These tests verify that every path function:
  - returns the correct default when the env var is absent
  - re-reads the env var on every call (lazy evaluation / no module-level caching)
  - derives child paths from the correct base

The lazy-evaluation property is the critical invariant: it lets
monkeypatch.setenv() work in tests without any module reloading.
"""

import os
import pytest
import cps.cwa_paths as p


@pytest.mark.unit
class TestDefaultValues:
    """Base functions return their documented defaults when env vars are unset."""

    def test_config_path_default(self, monkeypatch):
        monkeypatch.delenv("CWA_CONFIG_PATH", raising=False)
        assert p.GET_CONFIG_PATH() == "/config"

    def test_library_path_default(self, monkeypatch):
        monkeypatch.delenv("CWA_LIBRARY_PATH", raising=False)
        assert p.GET_LIBRARY_PATH() == "/calibre-library"

    def test_ingest_path_default(self, monkeypatch):
        monkeypatch.delenv("CWA_INGEST_PATH", raising=False)
        assert p.GET_INGEST_PATH() == "/cwa-book-ingest"

    def test_app_path_default(self, monkeypatch):
        monkeypatch.delenv("CWA_APP_PATH", raising=False)
        assert p.GET_APP_PATH() == "/app/calibre-web-automated"

    def test_app_root_default(self, monkeypatch):
        monkeypatch.delenv("CWA_APP_PATH", raising=False)
        assert p.GET_APP_ROOT() == "/app"


@pytest.mark.unit
class TestEnvVarOverride:
    """Setting an env var redirects the corresponding function."""

    def test_config_path_override(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CWA_CONFIG_PATH", str(tmp_path))
        assert p.GET_CONFIG_PATH() == str(tmp_path)

    def test_library_path_override(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CWA_LIBRARY_PATH", str(tmp_path))
        assert p.GET_LIBRARY_PATH() == str(tmp_path)

    def test_ingest_path_override(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CWA_INGEST_PATH", str(tmp_path))
        assert p.GET_INGEST_PATH() == str(tmp_path)

    def test_app_path_override(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CWA_APP_PATH", str(tmp_path))
        assert p.GET_APP_PATH() == str(tmp_path)


@pytest.mark.unit
class TestLazyEvaluation:
    """
    Functions re-read os.environ on every call — no module-level caching.

    This is the critical property that makes monkeypatch.setenv() work in tests.
    If any function captured its value at import time this class would detect it.
    """

    def test_config_path_updates_after_env_change(self, monkeypatch):
        monkeypatch.delenv("CWA_CONFIG_PATH", raising=False)
        assert p.GET_CONFIG_PATH() == "/config"
        monkeypatch.setenv("CWA_CONFIG_PATH", "/new-config")
        assert p.GET_CONFIG_PATH() == "/new-config"

    def test_library_path_updates_after_env_change(self, monkeypatch):
        monkeypatch.delenv("CWA_LIBRARY_PATH", raising=False)
        assert p.GET_LIBRARY_PATH() == "/calibre-library"
        monkeypatch.setenv("CWA_LIBRARY_PATH", "/new-library")
        assert p.GET_LIBRARY_PATH() == "/new-library"

    def test_ingest_path_updates_after_env_change(self, monkeypatch):
        monkeypatch.delenv("CWA_INGEST_PATH", raising=False)
        assert p.GET_INGEST_PATH() == "/cwa-book-ingest"
        monkeypatch.setenv("CWA_INGEST_PATH", "/new-ingest")
        assert p.GET_INGEST_PATH() == "/new-ingest"

    def test_app_path_updates_after_env_change(self, monkeypatch):
        monkeypatch.delenv("CWA_APP_PATH", raising=False)
        assert p.GET_APP_PATH() == "/app/calibre-web-automated"
        monkeypatch.setenv("CWA_APP_PATH", "/opt/cwa")
        assert p.GET_APP_PATH() == "/opt/cwa"

    def test_derived_path_updates_when_base_changes(self, monkeypatch):
        """A derived function re-evaluates its base on every call."""
        monkeypatch.setenv("CWA_CONFIG_PATH", "/first")
        assert p.GET_APP_DB() == "/first/app.db"
        monkeypatch.setenv("CWA_CONFIG_PATH", "/second")
        assert p.GET_APP_DB() == "/second/app.db"


@pytest.mark.unit
class TestDerivedConfigPaths:
    """Derived config-dir paths are all rooted under GET_CONFIG_PATH()."""

    def test_app_db(self, monkeypatch):
        monkeypatch.setenv("CWA_CONFIG_PATH", "/cfg")
        assert p.GET_APP_DB() == "/cfg/app.db"

    def test_cwa_db_path(self, monkeypatch):
        monkeypatch.setenv("CWA_CONFIG_PATH", "/cfg")
        assert p.GET_CWA_DB_PATH() == "/cfg/cwa.db"

    def test_processed_books(self, monkeypatch):
        monkeypatch.setenv("CWA_CONFIG_PATH", "/cfg")
        assert p.GET_PROCESSED_BOOKS() == "/cfg/processed_books"

    def test_log_archive(self, monkeypatch):
        monkeypatch.setenv("CWA_CONFIG_PATH", "/cfg")
        assert p.GET_LOG_ARCHIVE() == "/cfg/log_archive"

    def test_convert_log(self, monkeypatch):
        monkeypatch.setenv("CWA_CONFIG_PATH", "/cfg")
        assert p.GET_CONVERT_LOG() == "/cfg/convert-library.log"

    def test_epub_fixer_log(self, monkeypatch):
        monkeypatch.setenv("CWA_CONFIG_PATH", "/cfg")
        assert p.GET_EPUB_FIXER_LOG() == "/cfg/epub-fixer.log"

    def test_user_profiles(self, monkeypatch):
        monkeypatch.setenv("CWA_CONFIG_PATH", "/cfg")
        assert p.GET_USER_PROFILES() == "/cfg/user_profiles.json"

    def test_ingest_status(self, monkeypatch):
        monkeypatch.setenv("CWA_CONFIG_PATH", "/cfg")
        assert p.GET_INGEST_STATUS() == "/cfg/cwa_ingest_status"

    def test_ingest_retry_queue(self, monkeypatch):
        monkeypatch.setenv("CWA_CONFIG_PATH", "/cfg")
        assert p.GET_INGEST_RETRY_QUEUE() == "/cfg/cwa_ingest_retry_queue"

    def test_cwa_db_debug(self, monkeypatch):
        monkeypatch.setenv("CWA_CONFIG_PATH", "/cfg")
        assert p.GET_CWA_DB_DEBUG() == "/cfg/.cwa_db_debug"

    def test_tmp_conversion_dir(self, monkeypatch):
        monkeypatch.setenv("CWA_CONFIG_PATH", "/cfg")
        assert p.GET_TMP_CONVERSION_DIR() == "/cfg/.cwa_conversion_tmp"


@pytest.mark.unit
class TestDerivedLibraryPaths:
    """Derived library-dir paths are rooted under GET_LIBRARY_PATH()."""

    def test_metadata_db(self, monkeypatch):
        monkeypatch.setenv("CWA_LIBRARY_PATH", "/lib")
        assert p.GET_METADATA_DB() == "/lib/metadata.db"


@pytest.mark.unit
class TestDerivedAppPaths:
    """Derived app-dir paths are rooted under GET_APP_PATH() or GET_APP_ROOT()."""

    def test_change_logs_dir(self, monkeypatch):
        monkeypatch.setenv("CWA_APP_PATH", "/app/cwa")
        assert p.GET_CHANGE_LOGS_DIR() == "/app/cwa/metadata_change_logs"

    def test_metadata_temp_dir(self, monkeypatch):
        monkeypatch.setenv("CWA_APP_PATH", "/app/cwa")
        assert p.GET_METADATA_TEMP_DIR() == "/app/cwa/metadata_temp"

    def test_empty_library_app_db(self, monkeypatch):
        monkeypatch.setenv("CWA_APP_PATH", "/app/cwa")
        assert p.GET_EMPTY_LIBRARY_APP_DB() == "/app/cwa/empty_library/app.db"

    def test_empty_library_metadata_db(self, monkeypatch):
        monkeypatch.setenv("CWA_APP_PATH", "/app/cwa")
        assert p.GET_EMPTY_LIBRARY_METADATA_DB() == "/app/cwa/empty_library/metadata.db"

    def test_ingest_script(self, monkeypatch):
        monkeypatch.setenv("CWA_APP_PATH", "/app/cwa")
        assert p.GET_INGEST_SCRIPT() == "/app/cwa/scripts/ingest_processor.py"

    def test_convert_script(self, monkeypatch):
        monkeypatch.setenv("CWA_APP_PATH", "/app/cwa")
        assert p.GET_CONVERT_SCRIPT() == "/app/cwa/scripts/convert_library.py"

    def test_epub_fixer_script(self, monkeypatch):
        monkeypatch.setenv("CWA_APP_PATH", "/app/cwa")
        assert p.GET_EPUB_FIXER_SCRIPT() == "/app/cwa/scripts/kindle_epub_fixer.py"

    def test_check_services_script(self, monkeypatch):
        monkeypatch.setenv("CWA_APP_PATH", "/app/cwa")
        assert p.GET_CHECK_SERVICES_SCRIPT() == "/app/cwa/scripts/check-cwa-services.sh"


@pytest.mark.unit
class TestAppRootInvariant:
    """GET_APP_ROOT() is always os.path.dirname(GET_APP_PATH())."""

    def test_app_root_is_parent_of_app_path(self, monkeypatch):
        monkeypatch.setenv("CWA_APP_PATH", "/app/calibre-web-automated")
        assert p.GET_APP_ROOT() == os.path.dirname(p.GET_APP_PATH())

    def test_app_root_tracks_app_path_change(self, monkeypatch):
        monkeypatch.setenv("CWA_APP_PATH", "/opt/cwa/app")
        assert p.GET_APP_ROOT() == "/opt/cwa"

    def test_app_root_derived_paths(self, monkeypatch):
        monkeypatch.setenv("CWA_APP_PATH", "/opt/cwa/app")
        assert p.GET_CWA_RELEASE_FILE() == "/opt/cwa/CWA_RELEASE"
        assert p.GET_CWA_STABLE_RELEASE_FILE() == "/opt/cwa/CWA_STABLE_RELEASE"
        assert p.GET_KEPUBIFY_RELEASE_FILE() == "/opt/cwa/KEPUBIFY_RELEASE"
        assert p.GET_CWA_UPDATE_NOTICE() == "/opt/cwa/cwa_update_notice"
        assert p.GET_THEME_MIGRATION_NOTICE() == "/opt/cwa/theme_migration_notice"
        assert p.GET_CALIBRE_DIR() == "/opt/cwa/calibre"
