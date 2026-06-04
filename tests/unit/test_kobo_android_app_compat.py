# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regression test pinning crocodilestick/Calibre-Web-Automated#1343
(upstream author @shavitmichael), backported into the fork as PR #221.

The Kobo Android app shares the sync protocol with Kobo devices but has
stricter expectations for a few small fields. Without the four fixes in
this PR the Android app refuses to sync or renders books incorrectly:

1. Downloads must route through an indirect redirect endpoint (Android
   chokes on the direct ``/download/...`` URL).
2. ``DrmType`` must be set explicitly to ``"None"`` in the metadata
   payload (it was commented out as "not required" but Android treats
   it as required).
3. ``Series`` must be present in the metadata response — even an empty
   dict — or the Android app fails to render the row.
4. The image-URL templates must use Pascal-case ``{Width}``/``{Height}``
   placeholders rather than lowercase ``{width}``/``{height}``; Android
   does case-sensitive substitution.

Source-inspection rather than live HTTP because these functions need a
Flask app context, kobo auth headers, and request context that aren't
available at unit scope. The point is to catch a future refactor that
silently drops one of the four behaviors.
"""

import inspect
from pathlib import Path

import pytest


@pytest.mark.unit
class TestKoboAndroidAppCompat:
    def test_download_url_branches_on_android_device_header(self):
        from cps.kobo import get_download_url_for_book
        src = inspect.getsource(get_download_url_for_book)
        assert 'x-kobo-deviceos' in src, (
            "get_download_url_for_book must branch on the x-kobo-deviceos "
            "request header to detect Kobo Android app clients. See "
            "crocodilestick/Calibre-Web-Automated#1343."
        )
        assert '"Android"' in src, (
            "get_download_url_for_book must compare x-kobo-deviceos to "
            '"Android" specifically (case-sensitive Kobo header value). '
            "See crocodilestick/Calibre-Web-Automated#1343."
        )
        assert 'kobo.redirect_download_book' in src, (
            "Android-device branch must route to the redirect_download_book "
            "endpoint, not the direct download_book endpoint. The Kobo "
            "Android app refuses direct /download/<id>/<format> URLs."
        )
        assert 'redirect_download' in src, (
            "Android-device unproxied branch must build a URL whose path "
            "segment is 'redirect_download', not 'download'. See "
            "crocodilestick/Calibre-Web-Automated#1343."
        )

    def test_redirect_download_book_route_registered(self):
        from cps import kobo as kobo_mod
        assert hasattr(kobo_mod, "redirect_download_book"), (
            "redirect_download_book view function must exist in cps.kobo. "
            "It's the Android-compat indirection added by "
            "crocodilestick/Calibre-Web-Automated#1343."
        )
        view = kobo_mod.redirect_download_book
        src = inspect.getsource(view)
        assert "/redirect_download/" in inspect.getsource(kobo_mod).split(
            "def redirect_download_book"
        )[0].rsplit("@kobo.route(", 1)[-1], (
            "redirect_download_book must be registered at "
            "'/redirect_download/<book_id>/<book_format>'."
        )
        assert "kobo.download_book" in src, (
            "redirect_download_book must redirect to the real "
            "kobo.download_book endpoint via url_for. Without that the "
            "indirection is a 404."
        )
        assert "redirect(" in src, (
            "redirect_download_book must call flask.redirect — that's the "
            "whole point of the indirection. A 200 response here breaks "
            "the Android app."
        )

    def test_metadata_payload_includes_drmtype_none(self):
        # The Android-compat invariant is "DrmType=None ships in the
        # per-format download_url dict". The dict construction may live
        # in get_metadata directly or in a helper it calls
        # (build_download_url, introduced by PR #350's refactor). Inspect
        # the whole module to keep the pin valid across helper extraction.
        import cps.kobo
        src = Path(cps.kobo.__file__).read_text(encoding="utf-8")
        assert '"DrmType": "None"' in src, (
            "cps.kobo must include 'DrmType': 'None' in the per-format "
            "download_url block (get_metadata directly or a helper it "
            "calls). The field was previously commented out as 'not "
            "required' but the Kobo Android app rejects payloads without "
            "it. See crocodilestick/Calibre-Web-Automated#1343."
        )

    def test_metadata_payload_defaults_series_to_empty_dict(self):
        from cps.kobo import get_metadata
        src = inspect.getsource(get_metadata)
        assert '"Series": {}' in src, (
            "get_metadata must seed 'Series' with an empty dict by default. "
            "The Kobo Android app refuses to render books whose metadata "
            "lacks the Series key entirely (Kobo devices tolerate absence). "
            "See crocodilestick/Calibre-Web-Automated#1343."
        )

    def test_init_request_image_url_template_uses_pascal_case_placeholders(self):
        """The Kobo Android app does case-sensitive substitution on
        ``{Width}``/``{Height}`` placeholders. Lowercase ``{width}``/
        ``{height}`` (the upstream calibre-web bug) leaves the placeholder
        un-substituted in the request URL and the cover fetch 404s.
        """
        from cps.kobo import HandleInitRequest
        src = inspect.getsource(HandleInitRequest)
        # The Pascal-case form is what the Kobo Android app expects.
        assert 'width="{Width}"' in src, (
            "HandleInitRequest must emit Pascal-case '{Width}' in the "
            "image-URL templates so the Kobo Android app substitutes the "
            "actual width. See crocodilestick/Calibre-Web-Automated#1343."
        )
        assert 'height="{Height}"' in src, (
            "HandleInitRequest must emit Pascal-case '{Height}' in the "
            "image-URL templates so the Kobo Android app substitutes the "
            "actual height. See crocodilestick/Calibre-Web-Automated#1343."
        )
        # And the lowercase form (the bug) must be gone from every
        # image-URL template emission. The lowercase ``isGreyscale`` lower-
        # camel placeholder stays — that one Kobo accepts in either form
        # historically — so we narrow the check to the width/height pair.
        assert 'width="{width}"' not in src, (
            "Lowercase '{width}' placeholder regressed into HandleInitRequest. "
            "The Kobo Android app does case-sensitive substitution and the "
            "placeholder ends up un-substituted. See "
            "crocodilestick/Calibre-Web-Automated#1343."
        )
        assert 'height="{height}"' not in src, (
            "Lowercase '{height}' placeholder regressed into HandleInitRequest. "
            "The Kobo Android app does case-sensitive substitution and the "
            "placeholder ends up un-substituted. See "
            "crocodilestick/Calibre-Web-Automated#1343."
        )
