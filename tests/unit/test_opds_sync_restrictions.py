import types

import pytest
from sqlalchemy import select
from werkzeug.exceptions import Forbidden, NotFound

from cps import app
import cps.magic_shelf as magic_shelf
import cps.opds as opds


class DummyUser:
    def __init__(self, *, user_id=1, restricted=False, anonymous=False):
        self.id = user_id
        self.opds_only_shelves_sync = 1 if restricted else 0
        self.is_anonymous = anonymous
        self.is_authenticated = not anonymous

    def role_download(self):
        return True

    def check_visibility(self, _value):
        return True

    def filter_language(self):
        return "all"


class FilterableListQuery:
    def __init__(self, items, *, attr_name=None):
        self.items = list(items)
        self.attr_name = attr_name
        self.filter_calls = 0

    def join(self, entity, *_args, **_kwargs):
        if self.attr_name and entity in (opds.ub.OpdsShelfExposure, opds.ub.OpdsMagicShelfExposure):
            self.items = [item for item in self.items if getattr(item, self.attr_name)]
        return self

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def all(self):
        return list(self.items)

    def first(self):
        return self.items[0] if self.items else None

    def __iter__(self):
        return iter(self.items)


def test_get_opds_visible_shelves_filters_to_exposed_when_restricted(monkeypatch):
    user = DummyUser(restricted=True)
    shelves = [
        types.SimpleNamespace(id=1, name="Mine", opds_expose=True, is_public=0, user_id=user.id),
        types.SimpleNamespace(id=2, name="Public", opds_expose=True, is_public=1, user_id=99),
        types.SimpleNamespace(id=3, name="Hidden", opds_expose=False, is_public=1, user_id=99),
    ]

    class SessionStub:
        def query(self, entity):
            assert entity is opds.ub.Shelf
            return FilterableListQuery(shelves, attr_name="opds_expose")

    monkeypatch.setattr(opds.ub, "session", SessionStub())

    with app.test_request_context("/opds/shelfindex"):
        visible = opds.get_opds_visible_shelves(user).all()

    assert [shelf.name for shelf in visible] == ["Mine", "Public"]


def test_authorize_opds_entity_enforces_visibility_and_exposure(monkeypatch):
    owner = DummyUser(user_id=7, restricted=True)
    public_hidden = types.SimpleNamespace(id=1, user_id=99, is_public=1)
    private_other = types.SimpleNamespace(id=2, user_id=99, is_public=0)

    with app.test_request_context("/opds"):
        opds.g.allow_anonymous = False
        monkeypatch.setattr(opds, "is_opds_entity_exposed", lambda entity, **_kwargs: entity.id != 1)
        with pytest.raises(NotFound):
            opds.authorize_opds_entity(public_hidden, owner)
        with pytest.raises(Forbidden):
            opds.authorize_opds_entity(private_other, owner)


def test_get_opds_book_filter_does_not_materialize_all_ids(monkeypatch):
    user = DummyUser(restricted=True)
    sentinel_query = select(opds.db.Books.id).where(opds.false())
    monkeypatch.setattr(opds, "build_opds_allowed_book_ids_query", lambda user=None: sentinel_query)

    with app.test_request_context("/opds"):
        book_filter = opds.get_opds_book_filter(user)

    assert book_filter is not None


def test_build_opds_allowed_book_ids_query_unions_shelf_and_magic_queries(monkeypatch):
    user = DummyUser(restricted=True)
    magic_shelves = [types.SimpleNamespace(id=7)]
    union_inputs = []

    class ShelfBooksQuery:
        def join(self, *_args, **_kwargs):
            return self

        def filter(self, *_args, **_kwargs):
            return self

        def union(self, other):
            union_inputs.append(other)
            return self

    shelf_books_query = ShelfBooksQuery()

    class SessionStub:
        def query(self, entity):
            assert entity is opds.ub.BookShelf.book_id
            return shelf_books_query

    class MagicBooksQuery:
        def with_entities(self, entity):
            assert entity is opds.db.Books.id
            return "magic-subquery"

    monkeypatch.setattr(opds.ub, "session", SessionStub())
    monkeypatch.setattr(opds, "get_opds_visible_magic_shelves", lambda user=None: FilterableListQuery(magic_shelves))
    monkeypatch.setattr(opds.magic_shelf, "build_book_query_for_magic_shelf", lambda *_args, **_kwargs: (MagicBooksQuery(), magic_shelves[0]))

    with app.test_request_context("/opds"):
        result = opds.build_opds_allowed_book_ids_query(user)

    assert result is shelf_books_query
    assert union_inputs == ["magic-subquery"]


def test_feed_shelfindex_lists_visible_public_and_private_exposed_shelves(monkeypatch):
    user = DummyUser(restricted=True)
    shelves = [
        types.SimpleNamespace(id=1, name="Mine", opds_expose=True),
        types.SimpleNamespace(id=2, name="Public", opds_expose=True),
    ]
    monkeypatch.setattr(opds, "get_opds_visible_shelves", lambda user=None: FilterableListQuery(shelves))
    monkeypatch.setattr(opds.auth, "current_user", lambda: user)
    monkeypatch.setattr(opds, "render_xml_template", lambda *_args, **kwargs: kwargs["listelements"])
    monkeypatch.setattr(opds.config, "config_books_per_page", 20, raising=False)

    with app.test_request_context("/opds/shelfindex"):
        opds.g.allow_anonymous = False
        result = opds.feed_shelfindex.__wrapped__()

    assert [shelf.name for shelf in result] == ["Mine", "Public"]


def test_feed_shelf_rejects_non_exposed_shelf_when_restricted(monkeypatch):
    user = DummyUser(restricted=True)
    shelf = types.SimpleNamespace(id=5, user_id=user.id, is_public=0)

    class SessionStub:
        def query(self, entity):
            assert entity is opds.ub.Shelf
            return FilterableListQuery([shelf])

    monkeypatch.setattr(opds.ub, "session", SessionStub())
    monkeypatch.setattr(opds.auth, "current_user", lambda: user)
    monkeypatch.setattr(opds, "is_opds_entity_exposed", lambda *_args, **_kwargs: False)

    with app.test_request_context("/opds/shelf/5"):
        opds.g.allow_anonymous = False
        with pytest.raises(NotFound):
            opds.feed_shelf.__wrapped__(5)


def test_feed_magic_shelf_filters_books_with_central_opds_filter(monkeypatch):
    user = DummyUser(restricted=True)
    shelf = types.SimpleNamespace(id=9, user_id=99, is_public=1)
    book_two = types.SimpleNamespace(id=2)
    book_three = types.SimpleNamespace(id=3)

    class MagicShelfLookupQuery:
        def get(self, shelf_id):
            assert shelf_id == 9
            return shelf

    class BooksQuery:
        def __init__(self):
            self.offset_value = None
            self.limit_value = None

        def order_by(self, *_args, **_kwargs):
            return self

        def count(self):
            return 5000

        def limit(self, value):
            self.limit_value = value
            return self

        def offset(self, value):
            self.offset_value = value
            return self

        def all(self):
            return [book_two, book_three]

    books_query = BooksQuery()

    class SessionStub:
        def query(self, entity):
            if entity is opds.ub.MagicShelf:
                return MagicShelfLookupQuery()
            raise AssertionError(f"Unexpected query entity: {entity}")

    monkeypatch.setattr(opds.ub, "session", SessionStub())
    monkeypatch.setattr(opds.auth, "current_user", lambda: user)
    monkeypatch.setattr(opds, "is_opds_entity_exposed", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(opds.magic_shelf, "get_book_ids_for_magic_shelf", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not load all ids")))
    monkeypatch.setattr(opds.magic_shelf, "build_book_query_for_magic_shelf", lambda *_args, **_kwargs: (books_query, shelf))
    monkeypatch.setattr(opds, "get_opds_book_filter", lambda user=None: opds.true())
    monkeypatch.setattr(opds, "render_xml_template", lambda *_args, **kwargs: kwargs["entries"])
    monkeypatch.setattr(opds.config, "config_books_per_page", 20, raising=False)

    with app.test_request_context("/opds/magicshelf/9"):
        opds.g.allow_anonymous = False
        entries = opds.feed_magic_shelf.__wrapped__(9)

    assert [entry.Books.id for entry in entries] == [2, 3]
    assert books_query.limit_value == 20
    assert books_query.offset_value == 0


def test_get_books_for_magic_shelf_loads_page_objects(monkeypatch):
    book_one = types.SimpleNamespace(id=101)
    book_two = types.SimpleNamespace(id=202)

    class BooksQuery:
        def filter(self, *_args, **_kwargs):
            return self

        def all(self):
            return [book_two, book_one]

    class SessionStub:
        def query(self, entity):
            assert entity is magic_shelf.db.Books
            return BooksQuery()

    class CalibreDBStub:
        def __init__(self, init=True):
            self.session = SessionStub()

    monkeypatch.setattr(magic_shelf, "get_book_ids_for_magic_shelf", lambda *_args, **_kwargs: ([101, 202], 2))
    monkeypatch.setattr(magic_shelf.db, "CalibreDB", CalibreDBStub)

    books, total_count = magic_shelf.get_books_for_magic_shelf(1, page=1, page_size=2)

    assert total_count == 2
    assert [book.id for book in books] == [101, 202]


def test_opds_download_link_404s_for_hidden_book(monkeypatch):
    user = DummyUser(restricted=True)
    monkeypatch.setattr(opds.auth, "current_user", lambda: user)
    monkeypatch.setattr(opds, "is_opds_book_exposed", lambda book_id, user=None: False)

    with app.test_request_context("/opds/download/12/epub"):
        with pytest.raises(NotFound):
            opds.opds_download_link.__wrapped__("12", "epub")


def test_feed_search_passes_opds_filter_to_search_results(monkeypatch):
    captured = {}

    class FakeSearchQuery:
        def filter(self, value):
            captured["extra_filter"] = value
            return self

        def order_by(self, *_args, **_kwargs):
            return self

        def all(self):
            return [types.SimpleNamespace(Books=types.SimpleNamespace(id=1))]

    def fake_search_query(term, config):
        captured["term"] = term
        return FakeSearchQuery()

    monkeypatch.setattr(opds.calibre_db, "search_query", fake_search_query)
    monkeypatch.setattr(opds, "get_opds_book_filter", lambda user=None: "FILTER")
    monkeypatch.setattr(opds, "render_xml_template", lambda *_args, **kwargs: kwargs)

    result = opds.feed_search("space")

    assert captured == {"term": "space", "extra_filter": "FILTER"}
    assert result["searchterm"] == "space"
