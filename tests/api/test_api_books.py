# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""/api/v1/books list and detail."""

import pytest

from conftest import login


def _ids(resp):
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return [item["id"] for item in resp.get_json()["items"]]


@pytest.fixture
def admin_state(api_app):
    """Adds ReadBook/ArchivedBook rows for admin and removes them afterwards."""
    from cps import ub
    admin = ub.session.query(ub.User).filter(ub.User.name == "admin").one()
    added = []

    def add(row):
        row.user_id = admin.id
        ub.session.add(row)
        ub.session.commit()
        added.append(row)

    yield add
    for row in added:
        ub.session.delete(row)
    ub.session.commit()


@pytest.mark.unit
class TestBookList:
    def test_envelope(self, admin_client):
        data = admin_client.get("/api/v1/books").get_json()
        assert set(data) >= {"items", "page", "per_page", "total", "pages", "sort"}
        assert data["total"] == 5
        assert data["page"] == 1
        assert data["sort"] == "new"
        item = next(i for i in data["items"] if i["id"] == 1)
        assert item["title"] == "Dune"
        assert item["authors"] == ["Frank Herbert"]
        assert item["series"] == "Dune"
        assert item["formats"] == ["EPUB"]
        assert item["read"] is False and item["archived"] is False

    def test_paging(self, admin_client):
        first = admin_client.get("/api/v1/books?per_page=2&page=1&sort=old").get_json()
        third = admin_client.get("/api/v1/books?per_page=2&page=3&sort=old").get_json()
        assert first["pages"] == 3 and first["per_page"] == 2
        assert [i["id"] for i in first["items"]] == [1, 2]
        assert [i["id"] for i in third["items"]] == [5]

    @pytest.mark.parametrize("sort, expected", [
        ("new", [5, 4, 3, 2, 1]),
        ("old", [1, 2, 3, 4, 5]),
        ("abc", [4, 1, 2, 3, 5]),
        ("zyx", [5, 3, 2, 1, 4]),
        ("authaz", [5, 1, 2, 4, 3]),
        ("authza", [3, 4, 2, 1, 5]),
    ])
    def test_sort(self, admin_client, sort, expected):
        resp = admin_client.get(f"/api/v1/books?sort={sort}")
        assert _ids(resp) == expected
        assert resp.get_json()["sort"] == sort

    def test_series_sort(self, admin_client):
        ids = _ids(admin_client.get("/api/v1/books?sort=seriesdesc"))
        assert ids.index(2) < ids.index(1)

    def test_unknown_sort_falls_back(self, admin_client):
        resp = admin_client.get("/api/v1/books?sort=nonsense")
        assert resp.get_json()["sort"] == "new"
        assert _ids(resp) == [5, 4, 3, 2, 1]

    def test_denied_tag_hidden(self, reader_client):
        data = reader_client.get("/api/v1/books").get_json()
        assert data["total"] == 4
        assert 5 not in [i["id"] for i in data["items"]]

    def test_language_filter(self, client):
        login(client, "german")
        assert _ids(client.get("/api/v1/books")) == [4]

    def test_read_and_archived(self, admin_client, admin_state):
        from cps import ub
        admin_state(ub.ReadBook(book_id=3, read_status=ub.ReadBook.STATUS_FINISHED))
        admin_state(ub.ArchivedBook(book_id=2, is_archived=True))
        data = admin_client.get("/api/v1/books").get_json()
        items = {i["id"]: i for i in data["items"]}
        assert items[3]["read"] is True and items[3]["read_status"] == "finished"
        # Archived books leave the library list, as in the classic index.
        assert 2 not in items and data["total"] == 4


@pytest.mark.unit
class TestBookDetail:
    def test_fields(self, admin_client):
        resp = admin_client.get("/api/v1/books/1")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["title"] == "Dune"
        assert data["authors"][0]["name"] == "Frank Herbert"
        assert data["series"]["name"] == "Dune" and data["series_index"] == 1.0
        assert data["rating"] == 8
        assert "<script>" not in data["description_html"]
        assert "Spice" in data["description_html"]
        assert data["identifiers"][0]["type"] == "isbn"
        assert data["identifiers"][0]["val"] == "9780441013593"
        assert data["publishers"][0]["name"] == "Chilton"
        assert data["languages"] == [{"id": "eng", "name": "English"}]
        assert [t["name"] for t in data["tags"]] == ["Science Fiction"]
        assert data["formats"][0]["format"] == "EPUB"
        assert data["formats"][0]["download_url"] == "/download/1/epub/Dune"
        assert data["custom_columns"] == []
        assert data["read"] is False and data["archived"] is False

    def test_missing_book(self, admin_client):
        resp = admin_client.get("/api/v1/books/999")
        assert resp.status_code == 404
        assert resp.get_json()["error"]["code"] == "not_found"

    def test_denied_tag_is_404(self, reader_client):
        assert reader_client.get("/api/v1/books/5").status_code == 404
        assert reader_client.get("/api/v1/books/1").status_code == 200

    def test_language_filter_is_404(self, client):
        login(client, "german")
        assert client.get("/api/v1/books/1").status_code == 404
        assert client.get("/api/v1/books/4").get_json()["languages"][0]["id"] == "deu"

    def test_read_and_archived(self, admin_client, admin_state):
        from cps import ub
        admin_state(ub.ReadBook(book_id=2, read_status=ub.ReadBook.STATUS_IN_PROGRESS))
        admin_state(ub.ArchivedBook(book_id=2, is_archived=True))
        data = admin_client.get("/api/v1/books/2").get_json()
        assert data["read_status"] == "in_progress" and data["read"] is False
        # Archived books stay reachable by id, as on the classic detail page.
        assert data["archived"] is True

    def test_requires_login(self, client):
        assert client.get("/api/v1/books/1").status_code == 401
