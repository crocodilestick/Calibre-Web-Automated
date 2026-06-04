# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Regression pins for the "Kobo Sync Failed on modern firmware, no Kobo
account" handshake — the highest-reach Kobo symptom cluster across both
upstreams:

  - janeczku/calibre-web#3364 (Kobo Libra 2, no account, firmware probes
    OAuth before sync; reporter also saw the red-herring DEBUG line
    ``Could not parse locale "*"`` which is caught at DEBUG in every build)
  - janeczku/calibre-web#3218 (shelves not syncing)
  - crocodilestick/Calibre-Web-Automated#1264 ("Sync Failed")

Two invariants make fully-local sync work and are NOT covered by
``test_kobo_init_library_sync_rewrite.py`` (which pins ``library_sync`` and
``reading_services_host``):

1. ``HandleInitRequest`` must rewrite ``oauth_host`` to a *local* URL when
   ``config.config_kobo_proxy`` is off. Newer Kobo firmware (4.45+) performs
   an OAuth round-trip before sync. If ``oauth_host`` stays at the
   ``https://oauth.kobo.com`` default (from ``NATIVE_KOBO_RESOURCES``), a
   device with no Kobo account is bounced to Kobo's cloud, auth fails, and
   the user sees "Sync failed. Please try again." Pointing it at the local
   server lets the device complete OAuth against CWNG's dummy responder.

2. The ``/oauth/.well-known/openid-configuration`` discovery route must be
   registered. Modern firmware fetches this before OAuth; stock CW 0.6.24
   (#3364's version) has no such route and 404s. Upstream fix: CWA PR #1144
   by @mihneabulu, shipped in our build at v4.0.25 (commit d8300288).

Live-verified on cwn-local in fully-local mode (config_kobo_proxy=0,
config_kobo_sync=1) the same tick this test was written:
  GET /kobo/<token>/v1/initialization -> 200, Resources.oauth_host =
    http://<local>/kobo/<token>/oauth (NOT oauth.kobo.com)
  GET /kobo/<token>/oauth/.well-known/openid-configuration -> 200 with
    issuer / token_endpoint / authorization_endpoint.

Source-inspection rather than live HTTP because the handshake needs a Flask
request context, Kobo auth headers, and config setup that aren't available
at unit scope. The point is to ensure a future refactor of the
resource-rewriting block can't silently drop the no-account fix.
"""

import inspect

import pytest


@pytest.mark.unit
class TestOauthHostLocalRewrite:
    def test_oauth_host_rewritten_when_not_proxying(self):
        from cps.kobo import HandleInitRequest
        src = inspect.getsource(HandleInitRequest)
        assert 'kobo_resources["oauth_host"]' in src, (
            "HandleInitRequest must rewrite oauth_host. Without it a "
            "no-account Kobo on firmware 4.45+ is bounced to "
            "oauth.kobo.com and sync fails (janeczku#3364, CWA#1264)."
        )

    def test_oauth_host_rewrite_is_guarded_on_not_proxy_and_local(self):
        from cps.kobo import HandleInitRequest
        src = inspect.getsource(HandleInitRequest)
        guard = "if not config.config_kobo_proxy:"
        assert guard in src, (
            "oauth_host rewrite must be gated on `not config.config_kobo_proxy` "
            "so fully-local (no Kobo account) devices get a local OAuth host."
        )
        guard_pos = src.index(guard)
        oauth_pos = src.index('kobo_resources["oauth_host"]')
        assert guard_pos < oauth_pos, (
            "oauth_host rewrite must live inside the `not config_kobo_proxy` "
            "branch — moving it out would re-bounce no-account devices to "
            "Kobo's cloud."
        )
        # Within the guarded block, oauth_host must be built from a LOCAL
        # url_for(kobo.HandleOauthRequest), not a hardcoded Kobo store URL.
        block = src[guard_pos:oauth_pos + 200]
        assert 'url_for("kobo.HandleOauthRequest"' in block or \
               "url_for('kobo.HandleOauthRequest'" in block, (
            "oauth_host must be built from a local url_for(kobo.HandleOauthRequest), "
            "not a hardcoded Kobo store URL."
        )

    def test_native_oauth_host_default_is_kobo_store(self):
        """The default table seeds oauth_host with the upstream Kobo URL —
        the value HandleInitRequest overrides in fully-local mode. If this
        default silently changes, the rewrite's contract is unclear."""
        from cps.kobo import NATIVE_KOBO_RESOURCES
        defaults = NATIVE_KOBO_RESOURCES()
        assert defaults.get("oauth_host") == "https://oauth.kobo.com", (
            "NATIVE_KOBO_RESOURCES.oauth_host is the kobo.com default that "
            "HandleInitRequest overrides locally when not proxying."
        )

    def test_init_falls_back_to_native_resources(self):
        from cps.kobo import HandleInitRequest
        src = inspect.getsource(HandleInitRequest)
        assert "NATIVE_KOBO_RESOURCES()" in src, (
            "HandleInitRequest must fall back to NATIVE_KOBO_RESOURCES so "
            "no-account devices still receive a resource table to rewrite."
        )


@pytest.mark.unit
class TestOpenIdDiscoveryRoute:
    def test_discovery_route_registered(self):
        from cps.kobo import HandleOidcDiscovery
        src = inspect.getsource(HandleOidcDiscovery)
        assert "/oauth/.well-known/openid-configuration" in src, (
            "The openid-configuration discovery route must stay registered — "
            "newer Kobo firmware fetches it before OAuth. Stock CW 0.6.24 "
            "404s here (janeczku#3364). Upstream fix CWA#1144 @mihneabulu."
        )

    def test_discovery_payload_contract(self):
        from cps.kobo import HandleOidcDiscovery
        src = inspect.getsource(HandleOidcDiscovery)
        for key in ("issuer", "authorization_endpoint", "token_endpoint"):
            assert f"'{key}'" in src or f'"{key}"' in src, (
                f"openid-configuration discovery payload must advertise "
                f"'{key}' — Kobo firmware reads it to locate the OAuth flow."
            )
