# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""/api/v1/browse lists and per-entity book lists."""

import pytest

from conftest import login


def _counts(client, kind):
    resp = client.get(f"/api/v1/browse/{kind}")
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return {item["name"]: item["count"] for item in resp.get_json()["items"]}


def _item_id(client, kind, name):
    return next(item["id"] for item in client.get(f"/api/v1/browse/{kind}").get_json()["items"]
                if item["name"] == name)


def _titles(resp):
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return [item["title"] for item in resp.get_json()["items"]]


@pytest.fixture
def german_client(client):
    login(client, "german")
    return client


@pytest.mark.unit
class TestBrowseLists:
    def test_authors(self, admin_client):
        resp = admin_client.get("/api/v1/browse/authors")
        names = [item["name"] for item in resp.get_json()["items"]]
        assert names == ["Anne Nonymous", "Frank Herbert", "Franz Kafka", "Jane Austen"]
        assert _counts(admin_client, "authors")["Frank Herbert"] == 2

    def test_series_counts_books_without_series(self, admin_client):
        assert _counts(admin_client, "series") == {"Dune": 2, "None": 3}

    def test_tags(self, admin_client):
        assert _counts(admin_client, "tags") == {"Classic": 2, "Private": 1, "Science Fiction": 2}

    def test_publishers(self, admin_client):
        items = admin_client.get("/api/v1/browse/publishers").get_json()["items"]
        assert [(i["name"], i["count"]) for i in items] == [("None", 4), ("Chilton", 1)]
        assert items[0]["id"] == -1

    def test_languages(self, admin_client):
        items = admin_client.get("/api/v1/browse/languages").get_json()["items"]
        assert {i["id"]: i["count"] for i in items} == {"eng": 4, "deu": 1}

    def test_ratings(self, admin_client):
        assert _counts(admin_client, "ratings") == {"None": 4, "4★": 1}

    def test_formats(self, admin_client):
        items = admin_client.get("/api/v1/browse/formats").get_json()["items"]
        assert [(i["id"], i["count"]) for i in items] == [("EPUB", 4), ("PDF", 2)]

    def test_reader_does_not_see_denied_tag(self, reader_client):
        assert _counts(reader_client, "tags") == {"Classic": 2, "Science Fiction": 2}
        assert "Anne Nonymous" not in _counts(reader_client, "authors")
        assert _counts(reader_client, "series") == {"Dune": 2, "None": 2}
        assert _counts(reader_client, "formats") == {"EPUB": 3, "PDF": 2}

    def test_language_filter(self, german_client):
        assert _counts(german_client, "authors") == {"Franz Kafka": 1}
        assert _counts(german_client, "tags") == {"Classic": 1}
        assert _counts(german_client, "formats") == {"PDF": 1}
        assert _counts(german_client, "series") == {"None": 1}

    def test_language_overview_hidden_for_restricted_user(self, german_client):
        # Same as the classic /language page.
        assert german_client.get("/api/v1/browse/languages").status_code == 404

    def test_hidden_sidebar_entry_is_404(self, api_app, reader_client):
        from cps import constants, ub
        user = ub.session.query(ub.User).filter(ub.User.name == "reader").one()
        saved = user.sidebar_view
        user.sidebar_view = saved & ~constants.SIDEBAR_AUTHOR
        ub.session.commit()
        try:
            assert reader_client.get("/api/v1/browse/authors").status_code == 404
            assert reader_client.get("/api/v1/browse/tags").status_code == 200
        finally:
            user.sidebar_view = saved
            ub.session.commit()

    def test_unknown_kind(self, admin_client):
        resp = admin_client.get("/api/v1/browse/nope")
        assert resp.status_code == 404
        assert resp.get_json()["error"]["code"] == "not_found"

    def test_unauthenticated(self, client):
        resp = client.get("/api/v1/browse/authors")
        assert resp.status_code == 401
        assert client.get("/api/v1/browse/series/1/books").status_code == 401


@pytest.mark.unit
class TestBrowseBooks:
    def test_series_in_index_order(self, admin_client):
        sid = _item_id(admin_client, "series", "Dune")
        resp = admin_client.get(f"/api/v1/browse/series/{sid}/books")
        assert _titles(resp) == ["Dune", "Dune Messiah"]
        data = resp.get_json()
        assert data["total"] == 2 and data["name"] == "Dune" and data["sort"] == "seriesasc"
        assert data["items"][0]["read"] is False and data["items"][0]["archived"] is False
        resp = admin_client.get(f"/api/v1/browse/series/{sid}/books?sort=seriesdesc")
        assert _titles(resp) == ["Dune Messiah", "Dune"]

    def test_paging(self, admin_client):
        sid = _item_id(admin_client, "series", "Dune")
        data = admin_client.get(f"/api/v1/browse/series/{sid}/books?per_page=1&page=2").get_json()
        assert [i["title"] for i in data["items"]] == ["Dune Messiah"]
        assert data["pages"] == 2

    def test_none_bucket(self, admin_client):
        resp = admin_client.get("/api/v1/browse/series/-1/books?sort=abc")
        assert _titles(resp) == ["Der Process", "Emma", "Secret Diary"]
        assert len(_titles(admin_client.get("/api/v1/browse/publishers/-1/books"))) == 4

    def test_author(self, admin_client):
        aid = _item_id(admin_client, "authors", "Frank Herbert")
        assert sorted(_titles(admin_client.get(f"/api/v1/browse/authors/{aid}/books"))) == ["Dune", "Dune Messiah"]

    def test_tag_language_rating_format(self, admin_client):
        tid = _item_id(admin_client, "tags", "Classic")
        assert sorted(_titles(admin_client.get(f"/api/v1/browse/tags/{tid}/books"))) == ["Der Process", "Emma"]
        assert _titles(admin_client.get("/api/v1/browse/languages/deu/books")) == ["Der Process"]
        rid = _item_id(admin_client, "ratings", "4★")
        assert _titles(admin_client.get(f"/api/v1/browse/ratings/{rid}/books")) == ["Dune"]
        assert sorted(_titles(admin_client.get("/api/v1/browse/formats/pdf/books"))) == ["Der Process",
                                                                                         "Dune Messiah"]

    def test_reader_filters_apply(self, api_app, admin_client):
        aid = _item_id(admin_client, "authors", "Anne Nonymous")
        tid = _item_id(admin_client, "tags", "Private")
        reader = api_app.test_client()
        login(reader, "reader")
        # The classic author page treats an author without visible books as unavailable.
        assert reader.get(f"/api/v1/browse/authors/{aid}/books").status_code == 404
        assert _titles(reader.get(f"/api/v1/browse/tags/{tid}/books")) == []

    def test_german_sees_only_deu_books(self, german_client):
        assert _titles(german_client.get("/api/v1/browse/formats/pdf/books")) == ["Der Process"]
        assert _titles(german_client.get("/api/v1/browse/languages/eng/books")) == []

    @pytest.mark.parametrize("path", ["series/9999", "series/abc", "authors/9999", "tags/9999",
                                      "publishers/9999", "ratings/9999", "formats/mobi",
                                      "languages/xx", "nope/1"])
    def test_unknown_id(self, admin_client, path):
        resp = admin_client.get(f"/api/v1/browse/{path}/books")
        assert resp.status_code == 404
        assert resp.get_json()["error"]["code"] == "not_found"
