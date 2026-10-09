# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Boots the real app against a small seeded Calibre library for /api/v1 tests.

The app object is a process-wide singleton, so it is created once per test process.
Users (all passwords are "secret123" except admin's "admin123"):
  admin   - admin, all roles
  reader  - default roles, denied tag "Private"
  german  - default roles, language filter "deu"
"""

import os
import shutil
import sqlite3
import sys
import tempfile
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
for p in (str(REPO), str(REPO / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

PASSWORD = "secret123"

# id, title, author, series (name, index) or None, tags, lang, formats, has_cover
BOOKS = [
    (1, "Dune", "Frank Herbert", ("Dune", 1.0), ["Science Fiction"], "eng", ["EPUB"], 1),
    (2, "Dune Messiah", "Frank Herbert", ("Dune", 2.0), ["Science Fiction"], "eng", ["EPUB", "PDF"], 0),
    (3, "Emma", "Jane Austen", None, ["Classic"], "eng", ["EPUB"], 0),
    (4, "Der Process", "Franz Kafka", None, ["Classic"], "deu", ["PDF"], 0),
    (5, "Secret Diary", "Anne Nonymous", None, ["Private"], "eng", ["EPUB"], 0),
]


def _seed_library(metadata_db):
    con = sqlite3.connect(metadata_db)
    con.create_function("title_sort", 1, lambda t: t)
    con.create_function("uuid4", 0, lambda: str(uuid.uuid4()))
    ids = {}

    def get_id(table, name, extra_cols=""):
        key = (table, name)
        if key not in ids:
            if table == "languages":
                cur = con.execute("INSERT INTO languages (lang_code) VALUES (?)", (name,))
            elif table == "tags":
                cur = con.execute("INSERT INTO tags (name) VALUES (?)", (name,))
            else:
                cur = con.execute(f"INSERT INTO {table} (name, sort) VALUES (?, ?)", (name, name))
            ids[key] = cur.lastrowid
        return ids[key]

    for book_id, title, author, series, tags, lang, formats, has_cover in BOOKS:
        path = f"{author}/{title} ({book_id})"
        con.execute("INSERT INTO books (id, title, author_sort, timestamp, pubdate, series_index, path, "
                    "has_cover, last_modified) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (book_id, title, author, f"2026-01-0{book_id} 10:00:00+00:00", "2001-05-01 00:00:00+00:00",
                     series[1] if series else 1.0, path, has_cover, f"2026-02-0{book_id} 10:00:00+00:00"))
        con.execute("INSERT INTO books_authors_link (book, author) VALUES (?, ?)", (book_id, get_id("authors", author)))
        if series:
            con.execute("INSERT INTO books_series_link (book, series) VALUES (?, ?)",
                        (book_id, get_id("series", series[0])))
        for tag in tags:
            con.execute("INSERT INTO books_tags_link (book, tag) VALUES (?, ?)", (book_id, get_id("tags", tag)))
        con.execute("INSERT INTO books_languages_link (book, lang_code, item_order) VALUES (?, ?, 0)",
                    (book_id, get_id("languages", lang)))
        for fmt in formats:
            con.execute("INSERT INTO data (book, format, uncompressed_size, name) VALUES (?, ?, ?, ?)",
                        (book_id, fmt, 1000 * book_id, title))
    # Extra metadata on Dune for the detail serializer.
    con.execute("INSERT INTO comments (book, text) VALUES (1, ?)",
                ("<p>Spice <b>must</b> flow</p><script>alert(1)</script>",))
    con.execute("INSERT INTO ratings (id, rating) VALUES (1, 8)")
    con.execute("INSERT INTO books_ratings_link (book, rating) VALUES (1, 1)")
    con.execute("INSERT INTO identifiers (book, type, val) VALUES (1, 'isbn', '9780441013593')")
    con.execute("INSERT INTO books_publishers_link (book, publisher) VALUES (1, ?)",
                (get_id("publishers", "Chilton"),))
    con.commit()
    con.close()


def _add_user(ub, name, denied_tags="", language="all", role=None):
    from werkzeug.security import generate_password_hash
    from cps import constants
    user = ub.User()
    user.name = name
    user.email = f"{name}@example.com"
    user.password = generate_password_hash(PASSWORD)
    user.role = constants.ROLE_DOWNLOAD | constants.ROLE_VIEWER if role is None else role
    user.sidebar_view = constants.ADMIN_USER_SIDEBAR
    user.denied_tags = denied_tags
    user.allowed_tags = ""
    user.denied_column_value = ""
    user.allowed_column_value = ""
    user.default_language = language
    user.locale = "en"
    ub.session.add(user)
    ub.session.commit()
    return user


@pytest.fixture(scope="session")
def api_app():
    tmp = tempfile.mkdtemp(prefix="cwa-api-test-")
    library = os.path.join(tmp, "library")
    shutil.copytree(REPO / "empty_library", library)
    os.remove(os.path.join(library, "app.db"))
    _seed_library(os.path.join(library, "metadata.db"))
    os.environ["CALIBRE_DBPATH"] = tmp
    os.environ["CACHE_DIR"] = os.path.join(tmp, "cache")
    os.environ["CWA_DB_PATH"] = tmp
    settings = os.path.join(tmp, "app.db")
    saved_argv = sys.argv
    sys.argv = ["cps.py", "-p", settings]
    try:
        import cps
        cps.dependency_check = lambda *a, **k: []  # optional deps such as python-ldap may be absent
        cps.updater_thread.start = lambda: None  # its non-daemon thread would hold the process open
        app = cps.create_app()
    finally:
        sys.argv = saved_argv
    from cps import config, db, ub, limiter
    config.config_calibre_dir = library
    config.save()
    db.CalibreDB.setup_db(library, settings)

    from cps.web import web
    from cps.shelf import shelf
    from cps.jinjia import jinjia
    from cps.api import api_v1
    for bp in (web, shelf, jinjia, api_v1):
        if bp.name not in app.blueprints:
            app.register_blueprint(bp)
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    limiter.enabled = False

    _add_user(ub, "reader", denied_tags="Private")
    _add_user(ub, "german", language="deu")
    yield app
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def client(api_app):
    return api_app.test_client()


def login(client, name="admin", password=None):
    password = password or ("admin123" if name == "admin" else PASSWORD)
    resp = client.post("/api/v1/auth/login", json={"username": name, "password": password})
    assert resp.status_code == 200, resp.get_data(as_text=True)
    return resp


@pytest.fixture
def admin_client(client):
    login(client, "admin")
    return client


@pytest.fixture
def reader_client(client):
    login(client, "reader")
    return client


@pytest.fixture
def csrf_enabled(api_app):
    api_app.config["WTF_CSRF_ENABLED"] = True
    yield
    api_app.config["WTF_CSRF_ENABLED"] = False
