# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""/api/v1/search, /search/advanced and /search/suggest."""

import pytest

from conftest import login


def titles(resp):
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return sorted(item["title"] for item in resp.get_json()["items"])


@pytest.fixture
def tag_id(api_app):
    def lookup(name):
        from cps import calibre_db, db
        with api_app.app_context():
            return calibre_db.session.query(db.Tags).filter(db.Tags.name == name).one().id
    return lookup


@pytest.mark.unit
class TestSimpleSearch:
    def test_unauthenticated(self, client):
        for path in ("/api/v1/search?q=dune", "/api/v1/search/advanced", "/api/v1/search/suggest?kind=tags"):
            resp = client.get(path)
            assert resp.status_code == 401
            assert resp.get_json()["error"]["code"] == "unauthorized"

    def test_title(self, admin_client):
        resp = admin_client.get("/api/v1/search?q=dune")
        assert titles(resp) == ["Dune", "Dune Messiah"]
        data = resp.get_json()
        assert data["total"] == 2 and data["page"] == 1 and data["pages"] == 1
        assert {"read", "read_status", "archived"} <= set(data["items"][0])

    def test_author(self, admin_client):
        assert titles(admin_client.get("/api/v1/search?q=austen")) == ["Emma"]

    def test_empty_query(self, admin_client):
        data = admin_client.get("/api/v1/search?q=").get_json()
        assert data["items"] == [] and data["total"] == 0

    def test_paging(self, admin_client):
        data = admin_client.get("/api/v1/search?q=dune&per_page=1&page=2&sort=abc").get_json()
        assert [i["title"] for i in data["items"]] == ["Dune Messiah"]
        assert data["total"] == 2 and data["pages"] == 2

    def test_denied_tag_hidden(self, client):
        login(client, "admin")
        assert titles(client.get("/api/v1/search?q=secret")) == ["Secret Diary"]
        client.post("/api/v1/auth/logout")
        login(client, "reader")
        assert titles(client.get("/api/v1/search?q=secret")) == []

    def test_language_filter(self, client):
        login(client, "german")
        assert titles(client.get("/api/v1/search?q=e")) == ["Der Process"]


@pytest.mark.unit
class TestAdvancedSearch:
    def test_include_tag(self, admin_client, tag_id):
        resp = admin_client.get("/api/v1/search/advanced?tag={}".format(tag_id("Classic")))
        assert titles(resp) == ["Der Process", "Emma"]

    def test_exclude_tag(self, admin_client, tag_id):
        resp = admin_client.get("/api/v1/search/advanced?exclude_tag={}&exclude_tag={}".format(
            tag_id("Classic"), tag_id("Private")))
        assert titles(resp) == ["Dune", "Dune Messiah"]

    def test_title_and_format(self, admin_client):
        assert titles(admin_client.get("/api/v1/search/advanced?title=dune&format=pdf")) == ["Dune Messiah"]

    def test_author_and_language(self, admin_client):
        assert titles(admin_client.get("/api/v1/search/advanced?author=franz")) == ["Der Process"]
        assert titles(admin_client.get("/api/v1/search/advanced?exclude_language=eng")) == ["Der Process"]

    def test_rating_and_publisher(self, admin_client):
        assert titles(admin_client.get("/api/v1/search/advanced?rating_min=4")) == ["Dune"]
        assert titles(admin_client.get("/api/v1/search/advanced?publisher=chilton")) == ["Dune"]

    def test_permission_filters_apply(self, reader_client):
        assert "Secret Diary" not in titles(reader_client.get("/api/v1/search/advanced"))

    def test_bad_parameter(self, admin_client):
        resp = admin_client.get("/api/v1/search/advanced?pubdate_from=yesterday")
        assert resp.status_code == 400
        assert resp.get_json()["error"]["code"] == "invalid_parameter"


@pytest.mark.unit
class TestSuggest:
    def test_authors(self, admin_client):
        data = admin_client.get("/api/v1/search/suggest?kind=authors&q=herb").get_json()
        assert data["items"] == [{"name": "Frank Herbert"}]

    def test_tags_respect_denied(self, client):
        login(client, "admin")
        assert client.get("/api/v1/search/suggest?kind=tags&q=priv").get_json()["items"] == [
            {"name": "Private"}]
        client.post("/api/v1/auth/logout")
        login(client, "reader")
        assert client.get("/api/v1/search/suggest?kind=tags&q=priv").get_json()["items"] == []

    def test_series_and_languages(self, admin_client):
        assert admin_client.get("/api/v1/search/suggest?kind=series&q=du").get_json()["items"] == [
            {"name": "Dune"}]
        items = admin_client.get("/api/v1/search/suggest?kind=languages&q=germ").get_json()["items"]
        assert {"id": "deu", "name": "German"} in items

    def test_unknown_kind(self, admin_client):
        assert admin_client.get("/api/v1/search/suggest?kind=nope").status_code == 400
