# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regression test pinning janeczku/calibre-web#3585's sister fix:
``library_sync`` must be rewritten to point at the local Flask app in
``HandleInitRequest``. Without it, Kobo devices behind a reverse proxy
fetch sync from ``storeapi.kobo.com`` instead of our server, and no
books are delivered.

Upstream commit: a9713bd4 (Noé Sierra-Velasquez).

The ``HandleInitRequest`` function rewrites a handful of Kobo resource
URLs to point at the local server. ``image_host`` and the cover
templates were already rewritten; ``library_sync`` was left at its
``storeapi.kobo.com`` default. The fix adds the rewrite in both
branches (proxied vs unproxied request shape).

Source-inspection rather than live HTTP because ``HandleInitRequest``
needs a Flask request context, kobo auth headers, and config setup
that aren't available at unit scope. The point of this test is to
ensure the assignment lines aren't accidentally removed in a future
refactor of the resource-rewriting block.
"""

import inspect

import pytest


@pytest.mark.unit
class TestHandleInitLibrarySyncRewrite:
    def test_proxied_branch_rewrites_library_sync(self):
        from cps.kobo import HandleInitRequest
        src = inspect.getsource(HandleInitRequest)
        assert (
            'kobo_resources["library_sync"] = calibre_web_url + url_for(' in src
        ), (
            "Proxied branch of HandleInitRequest must rewrite "
            "library_sync to point at the local HandleSyncRequest. "
            "Without it Kobo devices behind a reverse proxy hit "
            "storeapi.kobo.com and no books sync. See "
            "janeczku/calibre-web a9713bd4."
        )

    def test_unproxied_branch_rewrites_library_sync(self):
        from cps.kobo import HandleInitRequest
        src = inspect.getsource(HandleInitRequest)
        assert 'kobo_resources["library_sync"] = url_for(' in src, (
            "Unproxied branch of HandleInitRequest must rewrite "
            "library_sync to a local _external=True URL. See "
            "janeczku/calibre-web a9713bd4."
        )

    def test_default_resource_table_still_has_storeapi_default(self):
        """The default resource table is intentionally seeded with the
        upstream Kobo URL -- this is the value that HandleInitRequest
        overrides. If the default disappears, the upstream Kobo store
        passthrough breaks for users who enable kobo_proxy."""
        from cps.kobo import NATIVE_KOBO_RESOURCES
        defaults = NATIVE_KOBO_RESOURCES()
        assert defaults.get("library_sync") == (
            "https://storeapi.kobo.com/v1/library/sync"
        )


@pytest.mark.unit
class TestHandleInitReadingServicesRedirect:
    """Regression: reading_services_host (where the Kobo sends annotations
    + reading state) must be redirected to CWNG whenever Kobo sync is on,
    NOT only when Hardcover annotation sync is enabled.

    Real-device test 2026-05-24: Maggie's Kobo synced fine but CWNG
    captured 0 annotations because reading_services_host was gated on
    `config_hardcover_annotations_sync and bool(hardcover)`. With
    Hardcover off, the Init response left reading_services_host at
    readingservices.kobo.com, so annotations went straight to Kobo and
    never reached CWNG's capture handler — the #305 sub-project (2)
    "live Kobo capture" was a no-op on the wire. Fix gates the redirect
    on `config.config_kobo_sync` (the annotation handler already proxies
    every request on to Kobo's real reading services, so device-side
    data is never withheld).
    """

    def test_redirect_gated_on_kobo_sync_not_only_hardcover(self):
        from cps.kobo import HandleInitRequest
        src = inspect.getsource(HandleInitRequest)
        # The reading_services_host assignment must be reachable when
        # config_kobo_sync is true. Pin that config_kobo_sync appears in
        # the guard for the reading_services_host rewrite.
        assert src.count('kobo_resources["reading_services_host"]') >= 2, (
            "both proxied + unproxied branches must rewrite reading_services_host"
        )
        # The guard immediately preceding each rewrite must reference
        # config_kobo_sync (so capture works without Hardcover).
        for chunk in src.split('kobo_resources["reading_services_host"]')[:-1]:
            guard = chunk.rsplit("if ", 1)[-1]
            assert "config_kobo_sync" in guard, (
                "reading_services_host redirect must be gated on "
                "config.config_kobo_sync (not solely Hardcover), or live "
                "Kobo annotation capture is a no-op when Hardcover is off"
            )

    def test_redirect_not_solely_hardcover_gated(self):
        from cps.kobo import HandleInitRequest
        src = inspect.getsource(HandleInitRequest)
        # The exact pre-fix guard must be gone (it bypassed capture when
        # Hardcover was off).
        assert (
            "if config.config_hardcover_annotations_sync and bool(hardcover):\n"
            '            kobo_resources["reading_services_host"]'
            not in src
        ), "reading_services_host must not be solely Hardcover-gated (#305 sp2 real-device fix)"
