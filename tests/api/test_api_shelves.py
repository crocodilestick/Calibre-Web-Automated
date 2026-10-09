# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""/api/v1 shelves and magic shelves."""

import pytest

from conftest import login


def _user_id(ub, name):
    return ub.session.query(ub.User).filter(ub.User.name == name).one().id


@pytest.fixture
def shelves(api_app):
    """admin's private shelf (Emma, Dune, Dune Messiah in that order) and a public one
    holding Dune and the "Private"-tagged Secret Diary."""
    from cps import ub
    admin_id = _user_id(ub, "admin")
    private = ub.Shelf(name="Admin Private", is_public=0, user_id=admin_id)
    public = ub.Shelf(name="Everyone", is_public=1, user_id=admin_id)
    ub.session.add_all([private, public])
    ub.session.commit()
    for order, book_id in enumerate([3, 1, 2]):
        private.books.append(ub.BookShelf(book_id=book_id, order=order))
    for order, book_id in enumerate([1, 5]):
        public.books.append(ub.BookShelf(book_id=book_id, order=order))
    ub.session.commit()
    yield {"private": private.id, "public": public.id}
    ub.session.query(ub.BookShelf).filter(ub.BookShelf.shelf.in_([private.id, public.id])).delete()
    ub.session.query(ub.Shelf).filter(ub.Shelf.id.in_([private.id, public.id])).delete()
    ub.session.commit()


@pytest.fixture
def magic(api_app):
    """admin's public magic shelf of every title containing "e" (all five books) and a
    private one."""
    from cps import ub
    admin_id = _user_id(ub, "admin")
    rules = {"condition": "AND", "rules": [
        {"id": "title", "field": "title", "type": "string", "operator": "contains", "value": "e"}]}
    public = ub.MagicShelf(name="Has E", is_public=1, user_id=admin_id, icon="E", rules=rules)
    private = ub.MagicShelf(name="Admin Magic", is_public=0, user_id=admin_id, icon="M", rules=rules)
    ub.session.add_all([public, private])
    ub.session.commit()
    yield {"public": public.id, "private": private.id}
    ids = [public.id, private.id]
    ub.session.query(ub.MagicShelfCache).filter(ub.MagicShelfCache.shelf_id.in_(ids)).delete()
    ub.session.query(ub.MagicShelf).filter(ub.MagicShelf.id.in_(ids)).delete()
    ub.session.commit()


@pytest.mark.unit
class TestShelves:
    def test_requires_login(self, client):
        for path in ("/api/v1/shelves", "/api/v1/shelves/1", "/api/v1/magic-shelves",
                     "/api/v1/magic-shelves/1/books"):
            resp = client.get(path)
            assert resp.status_code == 401, path
            assert resp.get_json()["error"]["code"] == "unauthorized"

    def test_owner_sees_own_and_public_sorted_by_name(self, admin_client, shelves):
        items = admin_client.get("/api/v1/shelves").get_json()["items"]
        by_id = {s["id"]: s for s in items}
        assert by_id[shelves["private"]]["is_owner"] is True
        assert by_id[shelves["private"]]["is_public"] is False
        assert by_id[shelves["private"]]["count"] == 3
        assert by_id[shelves["public"]]["count"] == 2
        names = [s["name"] for s in items]
        assert names == sorted(names)

    def test_private_shelf_hidden_from_other_user(self, reader_client, shelves):
        ids = {s["id"] for s in reader_client.get("/api/v1/shelves").get_json()["items"]}
        assert shelves["private"] not in ids
        resp = reader_client.get(f"/api/v1/shelves/{shelves['private']}")
        assert resp.status_code == 404
        assert resp.get_json()["error"]["code"] == "not_found"

    def test_public_shelf_visible_with_filtered_count(self, reader_client, shelves):
        items = reader_client.get("/api/v1/shelves").get_json()["items"]
        public = next(s for s in items if s["id"] == shelves["public"])
        assert public["is_owner"] is False
        assert public["count"] == 1  # Secret Diary is tagged "Private", denied to reader
        data = reader_client.get(f"/api/v1/shelves/{shelves['public']}").get_json()
        assert [b["title"] for b in data["books"]["items"]] == ["Dune"]
        assert data["books"]["total"] == 1

    def test_missing_shelf_is_404(self, admin_client):
        assert admin_client.get("/api/v1/shelves/99999").status_code == 404

    def test_books_in_shelf_order(self, admin_client, shelves):
        data = admin_client.get(f"/api/v1/shelves/{shelves['private']}").get_json()
        assert data["name"] == "Admin Private"
        assert data["sort"] == "stored"
        assert [b["id"] for b in data["books"]["items"]] == [3, 1, 2]
        assert data["books"]["total"] == 3

    def test_sort_and_paging(self, admin_client, shelves):
        url = f"/api/v1/shelves/{shelves['private']}"
        data = admin_client.get(url + "?sort=abc&per_page=2").get_json()["books"]
        assert [b["title"] for b in data["items"]] == ["Dune", "Dune Messiah"]
        assert (data["page"], data["per_page"], data["total"], data["pages"]) == (1, 2, 3, 2)
        data = admin_client.get(url + "?sort=abc&per_page=2&page=2").get_json()["books"]
        assert [b["title"] for b in data["items"]] == ["Emma"]
        authors = admin_client.get(url + "?sort=authza").get_json()["books"]["items"]
        assert [b["id"] for b in authors] == [3, 2, 1]
        # Read-only: the stored order is unchanged.
        stored = admin_client.get(url).get_json()["books"]["items"]
        assert [b["id"] for b in stored] == [3, 1, 2]

    def test_unknown_sort_is_400(self, admin_client, shelves):
        resp = admin_client.get(f"/api/v1/shelves/{shelves['private']}?sort=nope")
        assert resp.status_code == 400


@pytest.mark.unit
class TestMagicShelves:
    def test_admin_list_includes_system_shelves(self, admin_client, magic):
        items = admin_client.get("/api/v1/magic-shelves").get_json()["items"]
        assert sum(1 for s in items if s["is_system"]) >= 5
        own = next(s for s in items if s["id"] == magic["public"])
        assert own == {"id": magic["public"], "name": "Has E", "icon": "E", "is_public": True,
                       "is_system": False, "is_owner": True, "count": 5}

    def test_other_user_sees_public_not_private(self, reader_client, magic):
        items = reader_client.get("/api/v1/magic-shelves").get_json()["items"]
        ids = {s["id"] for s in items}
        assert magic["public"] in ids
        assert magic["private"] not in ids
        assert not any(s["is_system"] and s["is_owner"] is False for s in items)
        resp = reader_client.get(f"/api/v1/magic-shelves/{magic['private']}/books")
        assert resp.status_code == 404

    def test_books_envelope(self, admin_client, magic):
        data = admin_client.get(f"/api/v1/magic-shelves/{magic['public']}/books?sort=abc&per_page=2").get_json()
        assert data["name"] == "Has E"
        books = data["books"]
        assert set(books) == {"items", "page", "per_page", "total", "pages"}
        assert (books["total"], books["pages"], len(books["items"])) == (5, 3, 2)
        assert [b["title"] for b in books["items"]] == ["Der Process", "Dune"]

    def test_books_respect_common_filters(self, client, magic):
        login(client, "reader")
        books = client.get(f"/api/v1/magic-shelves/{magic['public']}/books").get_json()["books"]
        titles = {b["title"] for b in books["items"]}
        assert books["total"] == 4
        assert "Secret Diary" not in titles

    def test_missing_magic_shelf_is_404(self, admin_client):
        assert admin_client.get("/api/v1/magic-shelves/99999/books").status_code == 404
