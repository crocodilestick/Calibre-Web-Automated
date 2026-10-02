# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Unit tests for KOSync protocol route registration.

The KOSync protocol fixes its endpoints at the server root, so a KOReader client
configured with the CWA base URL requests ``/users/auth`` — not ``/kosync/users/auth``.
Before these aliases existed that path fell through to ``web.books_list``, whose
``/<data>/<sort_param>/`` rule matches it with ``data="users"``, and its login
requirement turned the request into a 302 to ``/login`` (#1468).

These tests pin both halves: the protocol paths must reach KOSync, and the generic
browse route must keep matching everything it matched before.
"""

import pytest
from flask import Flask

from cps.progress_syncing.protocols.kosync import kosync


def _url_adapter():
    """A URL map holding the KOSync blueprint and a stand-in for web.books_list.

    The stand-in mirrors the real rules in cps/web.py rather than importing the web
    blueprint, which would drag in the database and config layers. Matching is decided
    by the rules themselves, so the two are equivalent for this test.
    """
    app = Flask(__name__)
    app.register_blueprint(kosync)
    app.add_url_rule("/<data>/<sort_param>", endpoint="web.books_list")
    app.add_url_rule("/<data>/<sort_param>/", endpoint="web.books_list")
    return app.url_map.bind("localhost")


@pytest.mark.unit
class TestProtocolPathsReachKosync:
    """A client pointed at the server root must reach the KOSync handlers."""

    @pytest.mark.parametrize("path", ["/users/auth", "/users/auth/"])
    def test_auth_endpoint(self, path):
        endpoint, _ = _url_adapter().match(path, method="GET")
        assert endpoint == "kosync.auth_user"

    @pytest.mark.parametrize("path", ["/syncs/progress", "/syncs/progress/"])
    def test_progress_update_endpoint(self, path):
        endpoint, _ = _url_adapter().match(path, method="PUT")
        assert endpoint == "kosync.update_progress"

    def test_progress_read_endpoint(self):
        endpoint, args = _url_adapter().match("/syncs/progress/abc123", method="GET")
        assert endpoint == "kosync.get_progress"
        assert args["document"] == "abc123"


@pytest.mark.unit
class TestExistingRoutesAreUnaffected:
    """The aliases must not take paths away from anything that already worked."""

    @pytest.mark.parametrize("path", ["/kosync/users/auth", "/kosync/syncs/progress"])
    def test_prefixed_paths_still_route_to_kosync(self, path):
        method = "GET" if path.endswith("auth") else "PUT"
        endpoint, _ = _url_adapter().match(path, method=method)
        assert endpoint.startswith("kosync.")

    @pytest.mark.parametrize(
        "path", ["/series/new", "/authors/stored/", "/category/new", "/publisher/stored"]
    )
    def test_browse_urls_still_reach_books_list(self, path):
        endpoint, _ = _url_adapter().match(path, method="GET")
        assert endpoint == "web.books_list"
