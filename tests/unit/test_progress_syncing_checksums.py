# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""
Unit Tests for Progress Syncing Checksum Module

Tests verify KOReader partial MD5 algorithm compatibility.
Algorithm must match LuaJIT's bit.lshift behavior exactly.
"""

import pytest
import hashlib

from cps.progress_syncing.checksums import calculate_koreader_partial_md5


@pytest.mark.unit
class TestCalculatePartialMD5:
    """Test calculate_koreader_partial_md5 function."""

    def test_returns_32_char_hex(self, tmp_path):
        file = tmp_path / "test.txt"
        file.write_bytes(b"test")
        assert len(calculate_koreader_partial_md5(str(file))) == 32

    def test_empty_file_matches_standard_md5(self, tmp_path):
        file = tmp_path / "empty.txt"
        file.write_bytes(b"")
        assert calculate_koreader_partial_md5(str(file)) == hashlib.md5(b"").hexdigest()

    def test_identical_files_match(self, tmp_path):
        content = b"Test content" * 1000
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_bytes(content)
        file2.write_bytes(content)

        assert calculate_koreader_partial_md5(str(file1)) == calculate_koreader_partial_md5(str(file2))

    def test_different_files_differ(self, tmp_path):
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_bytes(b"Content A" * 1000)
        file2.write_bytes(b"Content B" * 1000)

        assert calculate_koreader_partial_md5(str(file1)) != calculate_koreader_partial_md5(str(file2))

    def test_deterministic(self, tmp_path):
        file = tmp_path / "test.bin"
        file.write_bytes(b"X" * (10 * 1024 * 1024))

        assert calculate_koreader_partial_md5(str(file)) == calculate_koreader_partial_md5(str(file))

    def test_nonexistent_file_returns_none(self, tmp_path):
        assert calculate_koreader_partial_md5(str(tmp_path / "missing.txt")) is None

    def test_none_input_returns_none(self):
        assert calculate_koreader_partial_md5(None) is None

    def test_empty_string_returns_none(self):
        assert calculate_koreader_partial_md5("") is None


@pytest.mark.unit
class TestKOReaderCompatibility:
    """Test KOReader algorithm compatibility."""

    def test_luajit_lshift_behavior_negative_shift(self):
        """
        LuaJIT's bit.lshift only uses lower 5 bits of shift count.

        For i=-1: shift_count=-2, masked=30, lshift(1024,30) overflows to 0.
        """
        shift_count = -2
        masked_shift = shift_count & 0x1F  # Lower 5 bits: 30
        result = (1024 << masked_shift) & 0xFFFFFFFF

        assert masked_shift == 30
        assert result == 0

    def test_luajit_lshift_behavior_positive_shifts(self):
        """Verify positive shifts work as expected."""
        test_cases = [
            (0, 1024),      # i=0: lshift(1024, 0) = 1024
            (2, 4096),      # i=1: lshift(1024, 2) = 4096
            (4, 16384),     # i=2: lshift(1024, 4) = 16384
            (6, 65536),     # i=3: lshift(1024, 6) = 65536
        ]

        for shift, expected in test_cases:
            masked = shift & 0x1F
            result = (1024 << masked) & 0xFFFFFFFF
            assert result == expected

    def test_samples_at_koreader_positions(self, tmp_path):
        """
        Verify sampling at positions matching KOReader's algorithm.

        Expected sample positions:
        i=-1: 0, i=0: 1024, i=1: 4096, i=2: 16384, i=3: 65536
        """
        # Create file with distinct markers at each sample position
        file = tmp_path / "position_test.bin"
        with open(file, 'wb') as f:
            # Position 0: Write "ZERO" marker
            f.write(b"ZERO" * 256)  # 0-1023
            # Position 1024: Write "1K__" marker
            f.write(b"1K__" * 256)  # 1024-2047
            # Fill until 4096
            f.write(b"\x00" * 2048)  # 2048-4095
            # Position 4096: Write "4K__" marker
            f.write(b"4K__" * 256)  # 4096-5119
            # Fill until 16384
            f.write(b"\x11" * (16384 - 5120))
            # Position 16384: Write "16K_" marker
            f.write(b"16K_" * 256)  # 16384-17407
            # Fill until 65536
            f.write(b"\x22" * (65536 - 17408))
            # Position 65536: Write "64K_" marker
            f.write(b"64K_" * 256)
            # Fill rest
            f.write(b"\xFF" * (1024 * 100))

        checksum = calculate_koreader_partial_md5(str(file))

        # Expected checksum verified against LuaJIT implementation
        EXPECTED_CHECKSUM = "2674126f0e2399f2e79453a1e49ebb74"

        assert checksum == EXPECTED_CHECKSUM

    def test_first_sample_at_position_zero(self, tmp_path):
        """First sample (i=-1) must be at position 0."""
        file = tmp_path / "marker.bin"

        # Write marker at position 0
        with open(file, 'wb') as f:
            f.write(b"MARKER_AT_ZERO" + b"\x00" * 1010)  # 1024 bytes total
            f.write(b"\xFF" * 1024)  # Position 1024

        # Our checksum MUST include the marker at position 0
        checksum = calculate_koreader_partial_md5(str(file))

        # Calculate alternative checksum starting at position 256
        wrong_md5 = hashlib.md5()
        with open(file, 'rb') as f:
            f.seek(256)
            wrong_md5.update(f.read(1024))
            f.seek(1024)
            wrong_md5.update(f.read(1024))
        wrong_checksum = wrong_md5.hexdigest()

        # Must differ - verifies we start at position 0
        assert checksum != wrong_checksum

    def test_matches_known_koreader_checksum(self, tmp_path):
        """Verify checksum matches LuaJIT output for test file."""
        import shutil

        # Use actual test file that we verified with LuaJIT
        test_file_src = "tests/fixtures/sample_books/sherlock_holmes.epub"
        test_file_dst = tmp_path / "sherlock_holmes.epub"

        # Copy to tmp_path for test isolation
        shutil.copy(test_file_src, test_file_dst)

        checksum = calculate_koreader_partial_md5(str(test_file_dst))

        # Checksum verified against LuaJIT implementation
        KNOWN_CORRECT_CHECKSUM = "751342416fcb981d36d24732b5497f9d"

        assert checksum == KNOWN_CORRECT_CHECKSUM

    def test_regression_negative_shift_position(self, tmp_path):
        """Verify negative shift behavior matches LuaJIT."""
        file = tmp_path / "regression.bin"
        with open(file, 'wb') as f:
            f.write(b"ZERO" * 256)      # Position 0-1023
            f.write(b"ONE_K" * 205)     # Position 1024+

        checksum = calculate_koreader_partial_md5(str(file))

        # Correct: samples from position 0
        correct = hashlib.md5()
        with open(file, 'rb') as f:
            f.seek(0)
            correct.update(f.read(1024))
            f.seek(1024)
            correct.update(f.read(1024))

        # Alternative: samples from position 256
        alternative = hashlib.md5()
        with open(file, 'rb') as f:
            f.seek(256)
            alternative.update(f.read(1024))
            f.seek(1024)
            alternative.update(f.read(1024))

        # Must match correct algorithm
        assert checksum == correct.hexdigest()
        assert checksum != alternative.hexdigest()
