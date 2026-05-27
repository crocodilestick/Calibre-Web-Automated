# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression tests for fork issue #312 — Tier 2: log-line sanitizer.

Even with secrets stripped from `settings.txt`, the log files inside
the debug zip carry their own PII: failed-login attempts include the
remote IP, kosync logs include usernames, and the app logs the full
library / config paths. A non-technical user pasting the zip into a
public issue would expose all of that.

Pin the new contract: `_sanitize_log_line()` is a pure function that
runs over every log line on the way INTO the zip (not over the live
log on disk). It must:

* replace IPv4 + IPv6 addresses with `<ip>`
* replace `/config/...` with `<config>/...`
* replace `/calibre-library/...` with `<library>/...`
* replace `Authorization: Bearer <token>` and Basic auth headers with `<redacted>`
* preserve book titles, error messages, line numbers, timestamps
* be cheap enough to run over a 10 MiB log without measurable user delay
"""

from __future__ import annotations

import pytest


def _sanitizer():
    from cps.debug_info import _sanitize_log_line
    return _sanitize_log_line


@pytest.mark.unit
class TestSanitizerStripsIps:
    def test_ipv4_redacted(self):
        s = _sanitizer()(
            "[2026-05-26 12:00:00] WARN {cps.web:2521} Login failed for user \"maggie\" IP-address: 192.168.1.42"
        )
        assert "192.168.1.42" not in s
        assert "<ip>" in s, s

    def test_ipv4_with_port_redacted(self):
        s = _sanitizer()("connection from 10.0.30.36:54321 succeeded")
        assert "10.0.30.36" not in s

    def test_ipv6_redacted(self):
        s = _sanitizer()("Login from 2001:db8::1 failed")
        assert "2001:db8::1" not in s
        assert "<ip>" in s

    def test_ipv4_mapped_ipv6_loopback_preserved(self):
        """`::ffff:127.0.0.1` is the form Flask emits for IPv6-mapped
        IPv4 loopback (see the kosync gate WARNING). Preserve it as
        loopback so admin diagnostics remain useful."""
        s = _sanitizer()("rejecting /kosync/users/auth from ::ffff:127.0.0.1.")
        assert "::ffff:127.0.0.1" in s, (
            f"v4-mapped loopback must survive sanitization: {s!r}"
        )
        assert "<ip>" not in s

    def test_ipv4_mapped_ipv6_public_redacted(self):
        s = _sanitizer()("connection from ::ffff:8.8.8.8 closed")
        assert "8.8.8.8" not in s
        assert "::ffff" not in s, (
            f"public IPv4-mapped IPv6 must be fully redacted, not "
            f"leak the mapping prefix: {s!r}"
        )
        assert "<ip>" in s

    def test_bare_double_colon_preserved(self):
        """`::` alone is not an IPv6 address (it's the wildcard/unspec
        binding, e.g. `Starting server on [::]:8083`). Pattern must
        not redact bare `::` — keeps that startup line readable."""
        s = _sanitizer()("Starting Gevent server on [::]:8083")
        assert "::" in s, (
            f"bare `::` must survive sanitization: {s!r}"
        )

    # Python slice notation `arr[1::2]` is technically indistinguishable
    # from compressed IPv6 `1::2` by regex alone. We accept this false
    # positive — CWNG logs don't contain Python REPL output in
    # production, so the risk is theoretical. The bare `::` case above
    # IS realistic (Flask's "Starting server on [::]:8083") and is
    # preserved.

    def test_localhost_ipv4_preserved(self):
        """127.0.0.1 is not PII — keep it for ops diagnostics."""
        s = _sanitizer()("connecting to 127.0.0.1:8083 (internal)")
        assert "127.0.0.1" in s, "localhost should be preserved as a useful diagnostic value"


@pytest.mark.unit
class TestSanitizerStripsPaths:
    def test_calibre_library_path_redacted(self):
        s = _sanitizer()("Importing /calibre-library/Author/Book/file.epub")
        assert "/calibre-library/" not in s
        assert "<library>/Author/Book/file.epub" in s

    def test_config_dir_path_redacted(self):
        s = _sanitizer()("Opening /config/app.db read-only")
        assert "/config/" not in s
        assert "<config>/app.db" in s

    def test_other_paths_preserved(self):
        """Generic /tmp or /var paths are NOT user-identifying; keep them."""
        s = _sanitizer()("Writing /tmp/scratch.txt for conversion")
        assert "/tmp/scratch.txt" in s


@pytest.mark.unit
class TestSanitizerStripsAuthHeaders:
    def test_bearer_token_redacted(self):
        s = _sanitizer()("upstream call: Authorization: Bearer eyJhbGciOi.thing.sig")
        assert "eyJhbGciOi.thing.sig" not in s
        assert "Bearer <redacted>" in s

    def test_basic_auth_header_redacted(self):
        # base64("user:pass") = dXNlcjpwYXNz — common leak shape
        s = _sanitizer()("auth_header=Basic dXNlcjpwYXNz from device")
        assert "dXNlcjpwYXNz" not in s
        assert "Basic <redacted>" in s


@pytest.mark.unit
class TestSanitizerPreservesUsefulSignal:
    def test_timestamp_preserved(self):
        s = _sanitizer()("[2026-05-26 12:00:00] INFO {cps.kobo:850} hello")
        assert "[2026-05-26 12:00:00]" in s
        assert "INFO" in s
        assert "{cps.kobo:850}" in s

    def test_book_title_preserved(self):
        s = _sanitizer()("Cover boost succeeded for 'The Great Book' by Author")
        assert "The Great Book" in s

    def test_log_level_preserved(self):
        for level in ("DEBUG", "INFO", "WARN", "WARNING", "ERROR", "CRIT", "CRITICAL"):
            s = _sanitizer()(f"[2026-05-26] {level} {{x:1}} msg")
            assert level in s


@pytest.mark.unit
class TestSanitizerIdempotent:
    def test_double_sanitize_is_safe(self):
        line = "Login from 192.168.1.42 to /config/x.db Bearer abc"
        once = _sanitizer()(line)
        twice = _sanitizer()(once)
        assert once == twice, "double-sanitize must be a no-op"
