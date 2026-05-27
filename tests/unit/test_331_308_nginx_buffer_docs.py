# SPDX-License-Identifier: GPL-3.0-or-later
"""Regression tests for fork issues #308 (@Glennza1962) + #331 (@Gusdezup)
— both confirmed independently that the Kobo "Sync failed" symptom
through an nginx reverse proxy is caused by nginx's default
`proxy_buffer_size` (4 KB) being too small for CWA's
`/v1/library/sync` response headers. nginx silently drops the
response. The CWA log shows no error.

The fix is documentation + a reference nginx config. These tests pin:

* the README's Kobo-sync section calls out the buffer-size requirement
  with a concrete proxy_buffer_size value
* the README's "Sync failed" troubleshooting entry references the
  buffer-size cause (so a user search lands here)
* the reference `examples/nginx-reverse-proxy.conf` exists and contains
  the proxy_buffer_size + proxy_buffers + proxy_busy_buffers_size lines
  with values that match the README's recommendation

This is the lowest-leverage layer of the fix — once the docs land, a
future user who hits the same nginx-default symptom finds the
guidance in one search and doesn't need to GitHub-thread their way to
a 30-comment debug session like #308.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
README = REPO_ROOT / "README.md"
NGINX_REF = REPO_ROOT / "examples" / "nginx-reverse-proxy.conf"


@pytest.fixture(scope="module")
def readme() -> str:
    assert README.exists()
    return README.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def nginx_ref() -> str:
    assert NGINX_REF.exists(), (
        f"examples/nginx-reverse-proxy.conf is missing — the README links "
        f"to it and users will hit a 404. {NGINX_REF}"
    )
    return NGINX_REF.read_text(encoding="utf-8")


@pytest.mark.unit
class TestReadmeBufferGuidance:
    def test_kobo_section_mentions_proxy_buffer_size(self, readme):
        # Find the Kobo sync section and the buffer-size guidance
        # near it. We don't care about the exact wording but the
        # directive name must appear.
        assert "proxy_buffer_size" in readme, (
            "README must mention `proxy_buffer_size` in the Kobo sync "
            "context (fork #308 + #331). Without it, users hit the silent "
            "nginx-drops-response symptom and have nowhere to look."
        )

    def test_kobo_section_mentions_proxy_buffers(self, readme):
        assert "proxy_buffers" in readme, (
            "README must mention `proxy_buffers` alongside "
            "`proxy_buffer_size` — both directives are needed."
        )

    def test_kobo_section_calls_out_silent_failure(self, readme):
        """The most common debugging mistake: users grep the CWA log for
        errors and find nothing. The README must explicitly warn that
        nginx drops the response *before* CWA sees it."""
        lower = readme.lower()
        assert any(phrase in lower for phrase in [
            "silently drop",
            "silently dropped",
            "silently dropping",
            "no error in the cwa log",
            "no error in cwa log",
            "no error in your cwa log",
        ]), (
            "README must explicitly warn that the CWA log shows no "
            "error in this failure mode — that's the single biggest "
            "diagnostic mistake. Without this warning, users assume "
            "their CWA install is broken when it's the proxy."
        )

    def test_troubleshooting_entry_for_sync_failed_includes_buffer_cause(self, readme):
        # Locate the "Sync failed, please try again" entry and confirm
        # buffer-cause is one of the listed causes.
        match = re.search(
            r"#+\s*Kobo says \"Sync failed[^\n]*\n(.*?)(?=\n#+\s|\Z)",
            readme,
            re.DOTALL,
        )
        assert match, "expected a `### Kobo says \"Sync failed...\"` troubleshooting entry"
        body = match.group(1)
        assert "buffer" in body.lower(), (
            "the 'Sync failed' troubleshooting entry must include the "
            "nginx-buffer cause so a user searching the symptom in the "
            "README finds it: " + body[:400]
        )


@pytest.mark.unit
class TestReferenceNginxConfig:
    def test_contains_proxy_buffer_directives(self, nginx_ref):
        for directive in ("proxy_buffer_size", "proxy_buffers", "proxy_busy_buffers_size"):
            assert directive in nginx_ref, (
                f"reference nginx config must include `{directive}` — "
                f"that's the load-bearing part for Kobo sync."
            )

    def test_buffer_sizes_are_at_least_32k(self, nginx_ref):
        """Recommended floor: 32k. Smaller values may not be enough for
        even moderate libraries. The reference config's COMMENTS may
        mention nginx's 4k default — strip comments out first, then
        check the actual directive value."""
        uncommented = re.sub(r"#[^\n]*", "", nginx_ref)
        match = re.search(r"proxy_buffer_size\s+(\d+)k", uncommented)
        assert match, (
            f"could not parse proxy_buffer_size directive in "
            f"non-comment text: {uncommented[:200]!r}"
        )
        assert int(match.group(1)) >= 32, (
            f"proxy_buffer_size should be at least 32k (fork #308 + #331); "
            f"got {match.group(0)}"
        )

    def test_explains_why_buffers_matter(self, nginx_ref):
        """A future maintainer who skims this file should be able to tell
        WHY the buffer values are non-default."""
        lower = nginx_ref.lower()
        assert "kobo" in lower and "sync" in lower and "buffer" in lower, (
            "reference nginx config must explain the Kobo-sync motivation "
            "for the non-default buffer values — otherwise a future "
            "maintainer 'cleans up' the file back to nginx defaults and "
            "breaks the user-facing flow."
        )

    def test_includes_forwarded_headers(self, nginx_ref):
        """Other reverse-proxy guidance in the README depends on these."""
        for header in ("X-Forwarded-Proto", "X-Forwarded-For", "X-Forwarded-Host"):
            assert header in nginx_ref, (
                f"reference nginx config must set `{header}` — CWA's "
                f"middleware depends on it for cookie domain + scheme."
            )

    def test_uses_modern_http2_directive_not_deprecated_listen_form(self, nginx_ref):
        """`listen ... http2;` combined form was deprecated in nginx
        1.25.1 (2023). Users on modern nginx see a warning when they
        validate the config. Use the standalone `http2 on;` directive
        instead (Greptile review on fork PR #335)."""
        # Strip comments first so we don't false-match the deprecation
        # note explaining the deprecation.
        body = re.sub(r"#[^\n]*", "", nginx_ref)
        assert not re.search(r"listen\s+\d+\s+ssl\s+http2", body), (
            "reference nginx config must not use the deprecated "
            "`listen ... http2;` combined form. Use `listen ... ssl;` "
            "+ standalone `http2 on;` instead."
        )
        assert "http2 on" in body, (
            "reference nginx config must enable HTTP/2 via the "
            "standalone `http2 on;` directive (nginx ≥1.25.1 standard)."
        )


@pytest.mark.unit
def test_readme_links_to_reference_config():
    body = README.read_text(encoding="utf-8")
    assert "examples/nginx-reverse-proxy.conf" in body, (
        "README's Kobo-sync section must link to the reference nginx "
        "config so a user copy-pastes a working template instead of "
        "stitching one together from prose."
    )
