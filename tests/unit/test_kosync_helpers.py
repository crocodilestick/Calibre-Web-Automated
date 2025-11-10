# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Unit tests for KOSync helper functions"""

import pytest
from cps.progress_syncing.protocols.kosync import (
    is_valid_field,
    is_valid_key_field,
    KOSyncError,
    create_sync_response,
    handle_sync_error,
    MAX_DOCUMENT_LENGTH,
    MAX_PROGRESS_LENGTH,
    MAX_DEVICE_LENGTH,
    MAX_DEVICE_ID_LENGTH,
    ERROR_INVALID_FIELDS,
)


@pytest.mark.unit
class TestIsValidField:
    """Test is_valid_field validation"""

    def test_accepts_non_empty_string(self):
        assert is_valid_field("test") is True

    def test_accepts_long_string(self):
        assert is_valid_field("a" * 1000) is True

    def test_accepts_unicode_string(self):
        assert is_valid_field("café ☕") is True

    def test_rejects_empty_string(self):
        assert is_valid_field("") is False

    def test_rejects_none(self):
        assert is_valid_field(None) is False

    def test_rejects_integer(self):
        assert is_valid_field(123) is False

    def test_rejects_list(self):
        assert is_valid_field(["test"]) is False

    def test_rejects_dict(self):
        assert is_valid_field({"key": "value"}) is False


@pytest.mark.unit
class TestIsValidKeyField:
    """Test is_valid_key_field validation"""

    def test_accepts_valid_string(self):
        assert is_valid_key_field("abc123") is True

    def test_accepts_md5_hash(self):
        assert is_valid_key_field("a" * 32) is True

    def test_accepts_string_at_max_length(self):
        max_string = "a" * MAX_DOCUMENT_LENGTH
        assert is_valid_key_field(max_string) is True

    def test_accepts_underscore(self):
        assert is_valid_key_field("test_123") is True

    def test_accepts_hyphen(self):
        assert is_valid_key_field("test-123") is True

    def test_rejects_string_with_colon(self):
        assert is_valid_key_field("abc:123") is False

    def test_rejects_string_exceeding_max_length(self):
        long_string = "a" * (MAX_DOCUMENT_LENGTH + 1)
        assert is_valid_key_field(long_string) is False

    def test_rejects_empty_string(self):
        assert is_valid_key_field("") is False

    def test_rejects_colon_at_start(self):
        assert is_valid_key_field(":abc") is False

    def test_rejects_colon_at_end(self):
        assert is_valid_key_field("abc:") is False

    def test_rejects_multiple_colons(self):
        assert is_valid_key_field("a:b:c") is False

    def test_respects_custom_max_length(self):
        assert is_valid_key_field("a" * 50, max_length=100) is True
        assert is_valid_key_field("a" * 150, max_length=100) is False


@pytest.mark.unit
class TestKOSyncError:
    """Test KOSyncError exception"""

    def test_stores_error_code(self):
        error = KOSyncError(ERROR_INVALID_FIELDS, "Test message")
        assert error.error_code == ERROR_INVALID_FIELDS

    def test_stores_message(self):
        error = KOSyncError(ERROR_INVALID_FIELDS, "Test message")
        assert error.message == "Test message"

    def test_is_exception(self):
        error = KOSyncError(ERROR_INVALID_FIELDS, "Test message")
        assert isinstance(error, Exception)


@pytest.mark.unit
class TestValidationConstants:
    """Test validation constant values are reasonable"""

    def test_max_document_length_reasonable(self):
        assert MAX_DOCUMENT_LENGTH == 255
        assert MAX_DOCUMENT_LENGTH >= 32  # MD5 hash length

    def test_max_progress_length_reasonable(self):
        assert MAX_PROGRESS_LENGTH == 255
        assert MAX_PROGRESS_LENGTH > 0

    def test_max_device_length_reasonable(self):
        assert MAX_DEVICE_LENGTH == 100
        assert MAX_DEVICE_LENGTH > 0

    def test_max_device_id_length_reasonable(self):
        assert MAX_DEVICE_ID_LENGTH == 100
        assert MAX_DEVICE_ID_LENGTH > 0
