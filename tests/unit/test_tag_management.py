# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Tag rename / merge / delete (cps/tag_management.py).

Loads the module against stubbed cps package members and a real in-memory
SQLite session with the parts of the Calibre schema it touches, so it runs
without the rest of the app.
"""

import importlib.util
import json
import pathlib
import sys
from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace

import pytest
from flask import Flask
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Table, create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

pytestmark = pytest.mark.unit

REPO = pathlib.Path(__file__).resolve().parents[2]

Base = declarative_base()

books_tags_link = Table(
    "books_tags_link", Base.metadata,
    Column("book", Integer, ForeignKey("books.id"), primary_key=True),
    Column("tag", Integer, ForeignKey("tags.id"), primary_key=True),
)
books_authors_link = Table(
    "books_authors_link", Base.metadata,
    Column("book", Integer, ForeignKey("books.id"), primary_key=True),
    Column("author", Integer, ForeignKey("authors.id"), primary_key=True),
)


class Tags(Base):
    __tablename__ = "tags"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(collation="NOCASE"), unique=True, nullable=False)

    def __init__(self, name):
        super().__init__()
        self.name = name

    # Same comparison as cps.db.Tags
    def __eq__(self, other):
        return self.name == other


class Authors(Base):
    __tablename__ = "authors"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)


class Books(Base):
    __tablename__ = "books"
    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    last_modified = Column(DateTime)
    tags = relationship(Tags, secondary=books_tags_link, backref="books", order_by="Tags.name", lazy="selectin")
    authors = relationship(Authors, secondary=books_authors_link, lazy="selectin")


class _Logger:
    def __init__(self):
        self.errors = []

    def debug(self, *args, **kwargs):
        return None

    def error_or_exception(self, message, *args, **kwargs):
        self.errors.append(str(message))


class _FakeCalibreDB:
    def __init__(self, session, events):
        self.session = session
        self.dirty = []
        self._events = events

    def set_metadata_dirty(self, book_id):
        self.dirty.append(book_id)


class _User:
    def __init__(self, edit=True, admin=False, anonymous=False):
        self.is_authenticated = not anonymous
        self.is_anonymous = anonymous
        self._edit = edit
        self._admin = admin

    def role_edit(self):
        return self._edit

    def role_admin(self):
        return self._admin


def _load(path, name, monkeypatch):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    module.__package__ = "cps"
    monkeypatch.setitem(sys.modules, name, module)
    spec.loader.exec_module(module)
    return module


class Env:
    pass


@pytest.fixture
def env(monkeypatch, tmp_path):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()

    e = Env()
    e.events = []
    e.session = session
    e.calibre_db = _FakeCalibreDB(session, e.events)
    e.logger = _Logger()

    cps = ModuleType("cps")
    cps.__path__ = [str(REPO / "cps")]
    db_mod = ModuleType("cps.db")
    db_mod.Tags, db_mod.Books = Tags, Books
    logger_mod = ModuleType("cps.logger")
    logger_mod.create = lambda: e.logger
    cw_login = ModuleType("cps.cw_login")
    cw_login.current_user = _User()
    babel = ModuleType("flask_babel")
    babel.gettext = lambda s, **kw: s % kw if kw else s
    for name, mod in (("cps", cps), ("cps.calibre_db", e.calibre_db), ("cps.db", db_mod),
                      ("cps.logger", logger_mod), ("cps.cw_login", cw_login), ("flask_babel", babel)):
        monkeypatch.setitem(sys.modules, name, mod)
    cps.calibre_db, cps.db, cps.logger = e.calibre_db, db_mod, logger_mod

    e.change_log = _load(REPO / "cps" / "metadata_change_log.py", "cps.metadata_change_log", monkeypatch)
    monkeypatch.setattr(e.change_log, "CHANGE_LOGS_DIR", str(tmp_path))
    e.tm = _load(REPO / "cps" / "tag_management.py", "cps.tag_management", monkeypatch)
    e.log_dir = tmp_path

    # Record ordering of commits and change-log writes.
    real_commit = session.commit

    def commit():
        real_commit()
        e.events.append("commit")

    monkeypatch.setattr(session, "commit", commit)
    real_write = e.tm.write_metadata_change_log

    def write(book, payload):
        e.events.append(("log", book.id))
        return real_write(book, payload)

    monkeypatch.setattr(e.tm, "write_metadata_change_log", write)

    e.app = Flask("tag_test")

    # Library: Sci-Fi on 1,2; Science Fiction on 2,3; Fantasy on 3.
    author = Authors(id=1, name="Ursula K. Le Guin")
    scifi, sf, fantasy = Tags("Sci-Fi"), Tags("Science Fiction"), Tags("Fantasy")
    old = datetime(2020, 1, 1)
    b1 = Books(id=1, title="One", last_modified=old, tags=[scifi], authors=[author])
    b2 = Books(id=2, title="Two", last_modified=old, tags=[scifi, sf], authors=[author])
    b3 = Books(id=3, title="Three", last_modified=old, tags=[sf, fantasy], authors=[author])
    session.add_all([b1, b2, b3])
    real_commit()
    e.ids = {"Sci-Fi": scifi.id, "Science Fiction": sf.id, "Fantasy": fantasy.id}
    yield e
    session.close()


def _call(e, fn, tag_id, payload=None):
    with e.app.test_request_context(method="POST", json=payload):
        rv = fn(tag_id)
        if isinstance(rv, tuple):
            resp, status = rv
        else:
            resp, status = rv, rv.status_code
        return status, resp.get_json()


def _tag_names(e, book_id):
    e.session.expire_all()
    return sorted(t.name for t in e.session.get(Books, book_id).tags)


def _logs(e):
    out = {}
    for path in e.log_dir.glob("*.json"):
        book_id = int(path.stem.split("-")[1])
        out[book_id] = json.loads(path.read_text(encoding="utf-8"))
    return out


def test_rename_in_place_touches_every_book(env):
    status, body = _call(env, env.tm.rename_tag, env.ids["Fantasy"], {"name": "  High Fantasy "})
    assert status == 200
    assert body == {"id": env.ids["Fantasy"], "name": "High Fantasy"}
    assert _tag_names(env, 3) == ["High Fantasy", "Science Fiction"]
    assert env.calibre_db.dirty == [3]
    book = env.session.get(Books, 3)
    assert book.last_modified.replace(tzinfo=timezone.utc) > datetime(2025, 1, 1, tzinfo=timezone.utc)
    assert env.session.get(Books, 1).last_modified == datetime(2020, 1, 1)
    logs = _logs(env)
    assert set(logs) == {3}
    assert logs[3]["tags"] == "High Fantasy, Science Fiction"
    assert logs[3]["title"] == "Three"
    assert logs[3]["authors"] == "Ursula K. Le Guin"
    assert logs[3]["_cwa_meta"]["modify_date"] is True
    assert logs[3]["_cwa_meta"]["change_count"] == 3


def test_rename_case_only_is_a_rename_not_a_conflict(env):
    status, body = _call(env, env.tm.rename_tag, env.ids["Fantasy"], {"name": "fantasy"})
    assert status == 200
    assert body["name"] == "fantasy"


def test_rename_same_name_is_noop(env):
    status, body = _call(env, env.tm.rename_tag, env.ids["Fantasy"], {"name": "Fantasy"})
    assert status == 200
    assert body == {"id": env.ids["Fantasy"], "name": "Fantasy"}
    assert env.events == []
    assert env.calibre_db.dirty == []
    assert _logs(env) == {}


@pytest.mark.parametrize("payload, message", [
    ({"name": "   "}, "Tag name cannot be empty"),
    ({"name": "a,b"}, "Tag name cannot contain commas"),
    ({"name": 5}, "Tag name must be text"),
    (None, "Tag name must be text"),
])
def test_rename_rejects_bad_names(env, payload, message):
    status, body = _call(env, env.tm.rename_tag, env.ids["Fantasy"], payload)
    assert status == 400
    assert body["error"]["message"] == message
    assert _tag_names(env, 3) == ["Fantasy", "Science Fiction"]


def test_rename_unknown_tag_is_404(env):
    status, _body = _call(env, env.tm.rename_tag, 999, {"name": "x"})
    assert status == 404


@pytest.mark.parametrize("merge", [None, False, "true", 1])
def test_rename_onto_existing_tag_conflicts_without_explicit_merge(env, merge):
    payload = {"name": "science fiction"}
    if merge is not None:
        payload["merge"] = merge
    status, body = _call(env, env.tm.rename_tag, env.ids["Sci-Fi"], payload)
    assert status == 409
    assert body["error"]["code"] == "conflict"
    assert body["error"]["conflict"] == {"id": env.ids["Science Fiction"], "name": "Science Fiction", "count": 2}
    assert _tag_names(env, 1) == ["Sci-Fi"]
    assert env.events == []


def test_merge_moves_books_without_duplicate_links_and_drops_old_tag(env):
    status, body = _call(env, env.tm.rename_tag, env.ids["Sci-Fi"], {"name": "science fiction", "merge": True})
    assert status == 200
    assert body == {"id": env.ids["Science Fiction"], "name": "Science Fiction", "merged": True, "books": 2}
    assert _tag_names(env, 1) == ["Science Fiction"]
    assert _tag_names(env, 2) == ["Science Fiction"]
    assert _tag_names(env, 3) == ["Fantasy", "Science Fiction"]
    assert env.session.get(Tags, env.ids["Sci-Fi"]) is None
    links = env.session.execute(books_tags_link.select().where(books_tags_link.c.book == 2)).fetchall()
    assert len(links) == 1
    assert sorted(env.calibre_db.dirty) == [1, 2]
    logs = _logs(env)
    assert set(logs) == {1, 2}
    assert logs[1]["tags"] == "Science Fiction"
    assert logs[2]["tags"] == "Science Fiction"


def test_delete_removes_tag_from_all_books(env):
    status, body = _call(env, env.tm.delete_tag, env.ids["Science Fiction"])
    assert status == 200
    assert body == {"id": env.ids["Science Fiction"], "name": "Science Fiction", "deleted": True, "books": 2}
    assert _tag_names(env, 1) == ["Sci-Fi"]
    assert _tag_names(env, 2) == ["Sci-Fi"]
    assert _tag_names(env, 3) == ["Fantasy"]
    assert env.session.get(Tags, env.ids["Science Fiction"]) is None
    assert env.session.get(Books, 2).title == "Two"
    assert sorted(env.calibre_db.dirty) == [2, 3]
    logs = _logs(env)
    assert set(logs) == {2, 3}
    assert logs[3]["tags"] == "Fantasy"


def test_delete_last_tag_logs_empty_tags(env):
    status, _body = _call(env, env.tm.delete_tag, env.ids["Sci-Fi"])
    assert status == 200
    assert _tag_names(env, 1) == []
    assert _logs(env)[1]["tags"] == ""


def test_delete_unknown_tag_is_404(env):
    status, _body = _call(env, env.tm.delete_tag, 999)
    assert status == 404


@pytest.mark.parametrize("user, status", [
    (_User(edit=False), 403),
    (_User(edit=False, anonymous=True), 401),
])
@pytest.mark.parametrize("action", ["rename", "delete"])
def test_non_editors_are_refused(env, monkeypatch, user, status, action):
    monkeypatch.setattr(env.tm, "current_user", user)
    if action == "rename":
        got, _body = _call(env, env.tm.rename_tag, env.ids["Fantasy"], {"name": "Other"})
    else:
        got, _body = _call(env, env.tm.delete_tag, env.ids["Fantasy"])
    assert got == status
    assert _tag_names(env, 3) == ["Fantasy", "Science Fiction"]
    assert env.events == []


def test_admin_without_edit_role_is_allowed(env, monkeypatch):
    # Matches editbooks.edit_required, which lets admins edit.
    monkeypatch.setattr(env.tm, "current_user", _User(edit=False, admin=True))
    status, _body = _call(env, env.tm.delete_tag, env.ids["Fantasy"])
    assert status == 200


@pytest.mark.parametrize("action", ["rename", "merge", "delete"])
def test_change_logs_follow_the_commit_one_per_book(env, action):
    if action == "rename":
        _call(env, env.tm.rename_tag, env.ids["Science Fiction"], {"name": "SF"})
    elif action == "merge":
        _call(env, env.tm.rename_tag, env.ids["Sci-Fi"], {"name": "Science Fiction", "merge": True})
    else:
        _call(env, env.tm.delete_tag, env.ids["Science Fiction"])
    assert env.events[0] == "commit"
    log_events = env.events[1:]
    assert len(log_events) == 2
    assert len({book_id for _kind, book_id in log_events}) == 2


@pytest.mark.parametrize("exc, status", [
    (IntegrityError("stmt", {}, Exception("UNIQUE constraint failed")), 409),
    (RuntimeError("disk full"), 500),
])
@pytest.mark.parametrize("action", ["rename", "merge", "delete"])
def test_errors_roll_back_and_write_no_logs(env, monkeypatch, exc, status, action):
    def boom():
        raise exc

    monkeypatch.setattr(env.session, "commit", boom)
    if action == "rename":
        got, body = _call(env, env.tm.rename_tag, env.ids["Science Fiction"], {"name": "SF"})
    elif action == "merge":
        got, body = _call(env, env.tm.rename_tag, env.ids["Sci-Fi"], {"name": "Science Fiction", "merge": True})
    else:
        got, body = _call(env, env.tm.delete_tag, env.ids["Science Fiction"])
    assert got == status
    assert "error" in body
    assert _tag_names(env, 1) == ["Sci-Fi"]
    assert _tag_names(env, 2) == ["Sci-Fi", "Science Fiction"]
    assert _tag_names(env, 3) == ["Fantasy", "Science Fiction"]
    assert env.session.get(Books, 2).last_modified == datetime(2020, 1, 1)
    assert _logs(env) == {}
    assert not any(isinstance(ev, tuple) for ev in env.events)


def test_bulk_edit_uses_shared_change_log_writer():
    source = (REPO / "cps" / "editbooks.py").read_text(encoding="utf-8")
    body = source[source.index("def edit_selected_books"):source.index("def _validate_uploaded_file")]
    assert "write_metadata_change_log(book, log_payload)" in body
    assert "metadata_change_logs" not in body


def test_tag_routes_require_login_and_edit_rights():
    source = (REPO / "cps" / "editbooks.py").read_text(encoding="utf-8")
    for route, func in (('"/ajax/tag/<int:tag_id>/rename", methods=[\'POST\']', "def rename_tag"),
                        ('"/ajax/tag/<int:tag_id>/delete", methods=[\'POST\']', "def delete_tag")):
        block = source[source.index(route):source.index(func)]
        assert "@user_login_required" in block
        assert "@edit_required" in block
