# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit and integration tests for Kobo Book Override Detail Page Slice."""

import pytest
from unittest.mock import patch, MagicMock
from werkzeug.exceptions import BadRequest, NotFound

from cps import ub, db
from cps.kobo import get_kobo_book_sync_explanation


@pytest.mark.unit
class TestKoboDetailOverride:

    def _setup_app_with_blueprint(self):
        from flask import Flask, Blueprint
        app = Flask("test_app")
        app.secret_key = "test_secret"

        web_bp = Blueprint("web", "web")
        @web_bp.route("/book/<int:book_id>")
        def show_book(book_id):
            return "book"
        app.register_blueprint(web_bp)
        return app

    @patch('cps.kobo_auth._', new=lambda x: x)
    @patch('cps.kobo_auth.db.CalibreDB')
    @patch('cps.kobo_auth.ub.session')
    def test_set_override_always(self, mock_session, mock_calibredb_cls):
        """POST to set_kobo_book_override with 'always' sets KoboBookOverride in DB."""
        from cps.kobo_auth import set_kobo_book_override

        fake_book = MagicMock()
        fake_book.id = 42
        mock_cdb = MagicMock()
        mock_calibredb_cls.return_value = mock_cdb
        mock_cdb.session.query().filter().filter().first.return_value = fake_book

        fake_user = MagicMock()
        fake_user.id = 1

        mock_query = mock_session.query().filter_by
        mock_query.return_value.first.return_value = None  # No existing override

        app = self._setup_app_with_blueprint()
        with app.test_request_context(method="POST", data={"reader_override": "always"}):
            with patch('cps.kobo_auth.current_user', fake_user):
                with patch('cps.magic_shelf.invalidate_magic_shelf_cache') as mock_invalidate:
                    res = set_kobo_book_override.__wrapped__(42)

                    # Verify DB addition
                    mock_session.add.assert_called_once()
                    added_override = mock_session.add.call_args[0][0]
                    assert added_override.user_id == 1
                    assert added_override.book_id == 42
                    assert added_override.reader_override == "always"

                    mock_invalidate.assert_called_once()
                    mock_session.commit.assert_called_once()
                    assert res.status_code == 302
                    assert res.headers["Location"] == "/book/42"

    @patch('cps.kobo_auth._', new=lambda x: x)
    @patch('cps.kobo_auth.db.CalibreDB')
    @patch('cps.kobo_auth.ub.session')
    def test_set_override_never(self, mock_session, mock_calibredb_cls):
        """POST to set_kobo_book_override with 'never' sets KoboBookOverride in DB."""
        from cps.kobo_auth import set_kobo_book_override

        fake_book = MagicMock()
        fake_book.id = 42
        mock_cdb = MagicMock()
        mock_calibredb_cls.return_value = mock_cdb
        mock_cdb.session.query().filter().filter().first.return_value = fake_book

        fake_user = MagicMock()
        fake_user.id = 1

        mock_query = mock_session.query().filter_by
        mock_query.return_value.first.return_value = None  # No existing override

        app = self._setup_app_with_blueprint()
        with app.test_request_context(method="POST", data={"reader_override": "never"}):
            with patch('cps.kobo_auth.current_user', fake_user):
                with patch('cps.magic_shelf.invalidate_magic_shelf_cache') as mock_invalidate:
                    res = set_kobo_book_override.__wrapped__(42)

                    # Verify DB addition
                    mock_session.add.assert_called_once()
                    added_override = mock_session.add.call_args[0][0]
                    assert added_override.reader_override == "never"

                    mock_invalidate.assert_called_once()
                    mock_session.commit.assert_called_once()
                    assert res.status_code == 302

    @patch('cps.kobo_auth._', new=lambda x: x)
    @patch('cps.kobo_auth.db.CalibreDB')
    @patch('cps.kobo_auth.ub.session')
    def test_set_override_auto_deletes_existing(self, mock_session, mock_calibredb_cls):
        """POST to set_kobo_book_override with 'auto' deletes existing KoboBookOverride in DB."""
        from cps.kobo_auth import set_kobo_book_override

        fake_book = MagicMock()
        fake_book.id = 42
        mock_cdb = MagicMock()
        mock_calibredb_cls.return_value = mock_cdb
        mock_cdb.session.query().filter().filter().first.return_value = fake_book

        fake_user = MagicMock()
        fake_user.id = 1

        existing_override = MagicMock()
        mock_query = mock_session.query().filter_by
        mock_query.return_value.first.return_value = existing_override

        app = self._setup_app_with_blueprint()
        with app.test_request_context(method="POST", data={"reader_override": "auto"}):
            with patch('cps.kobo_auth.current_user', fake_user):
                with patch('cps.magic_shelf.invalidate_magic_shelf_cache') as mock_invalidate:
                    res = set_kobo_book_override.__wrapped__(42)

                    mock_session.delete.assert_called_once_with(existing_override)
                    mock_invalidate.assert_called_once()
                    mock_session.commit.assert_called_once()
                    assert res.status_code == 302

    @patch('cps.kobo_auth._', new=lambda x: x)
    def test_set_override_invalid_value(self):
        """POST to set_kobo_book_override with invalid value returns 400 BadRequest."""
        from cps.kobo_auth import set_kobo_book_override
        from flask import Flask

        fake_user = MagicMock()
        fake_user.id = 1

        app = Flask("test_app")
        app.secret_key = "test_secret"
        with app.test_request_context(method="POST", data={"reader_override": "invalid"}):
            with patch('cps.kobo_auth.current_user', fake_user):
                with pytest.raises(BadRequest):
                    set_kobo_book_override.__wrapped__(42)

    @patch('cps.kobo_auth._', new=lambda x: x)
    @patch('cps.kobo_auth.db.CalibreDB')
    def test_set_override_invisible_book_returns_404(self, mock_calibredb_cls):
        """POST to set_kobo_book_override for a book not matching common_filters returns 404 NotFound."""
        from cps.kobo_auth import set_kobo_book_override
        from flask import Flask

        mock_cdb = MagicMock()
        mock_calibredb_cls.return_value = mock_cdb
        mock_cdb.session.query().filter().filter().first.return_value = None  # Invisible/Not found

        fake_user = MagicMock()
        fake_user.id = 1

        app = Flask("test_app")
        app.secret_key = "test_secret"
        with app.test_request_context(method="POST", data={"reader_override": "always"}):
            with patch('cps.kobo_auth.current_user', fake_user):
                with pytest.raises(NotFound):
                    set_kobo_book_override.__wrapped__(42)

    def test_route_decorations(self):
        """Ensure route is decorated with user_login_required."""
        from cps.kobo_auth import set_kobo_book_override
        # Check if function is wrapped by user_login_required
        assert hasattr(set_kobo_book_override, '__wrapped__')

    @patch('cps.kobo.config')
    @patch('cps.ub.session')
    @patch('cps.kobo.db.CalibreDB')
    def test_explanation_returns_reader_override(self, mock_calibre_db_class, mock_session, mock_config):
        """Explanation dictionary contains reader_override field."""
        fake_user = MagicMock()
        fake_user.id = 1
        fake_user.kobo_only_shelves_sync = True
        mock_config.config_kobo_sync_magic_shelves = False

        fake_book = MagicMock()
        fake_book.id = 42

        # 1. Test when no override is set (default "auto")
        mock_user_query = MagicMock()
        mock_user_query.filter.return_value.first.return_value = fake_user
        mock_archived_query = MagicMock()
        mock_archived_query.filter_by.return_value.first.return_value = None
        mock_override_query = MagicMock()
        mock_override_query.filter_by.return_value.first.return_value = None
        mock_shelf_query = MagicMock()
        mock_shelf_query.filter.return_value.all.return_value = []
        mock_synced_query = MagicMock()
        mock_synced_query.filter_by.return_value.first.return_value = None

        def session_query_side_effect(model):
            if model is ub.User:
                return mock_user_query
            elif model is ub.ArchivedBook:
                return mock_archived_query
            elif model is ub.KoboBookOverride:
                return mock_override_query
            elif model is ub.Shelf:
                return mock_shelf_query
            elif model is ub.KoboSyncedBooks:
                return mock_synced_query
            return MagicMock()

        mock_session.query.side_effect = session_query_side_effect

        mock_cdb = MagicMock()
        mock_cdb.session.query().filter().filter().first.return_value = fake_book
        mock_calibre_db_class.return_value = mock_cdb

        res = get_kobo_book_sync_explanation(1, 42)
        assert res["reader_override"] == "auto"

        # 2. Test when override is "always"
        always_override = MagicMock(reader_override="always")
        mock_override_query.filter_by.return_value.first.return_value = always_override
        res2 = get_kobo_book_sync_explanation(1, 42)
        assert res2["reader_override"] == "always"

        # 3. Test when book does not exist
        mock_cdb.session.query().filter().filter().first.return_value = None
        res3 = get_kobo_book_sync_explanation(1, 42)
        assert res3["exists"] is False
        assert res3["reader_override"] == "auto"

    @patch('cps.web.CWA_DB')
    @patch('cps.web.calibre_db')
    @patch('cps.kobo.config')
    @patch('cps.web.config')
    @patch('cps.web.render_title_template')
    @patch('cps.kobo.db.CalibreDB')
    @patch('cps.ub.session')
    def test_show_book_passes_kobo_explanation_to_template(self, mock_session, mock_kobo_cdb, mock_render, mock_web_config, mock_kobo_config, mock_calibre_db, mock_cwa_db):
        """show_book passes kobo_explanation in the template context."""
        from cps.web import show_book
        from flask import Flask

        mock_web_config.config_kobo_sync = True
        mock_web_config.config_allow_reverse_proxy_header_login = False
        mock_web_config.config_read_column = ""

        mock_kobo_config.config_kobo_sync_magic_shelves = False

        fake_user = MagicMock()
        fake_user.id = 1
        fake_user.is_authenticated = True
        fake_user.kobo_only_shelves_sync = True

        fake_book = MagicMock()
        fake_book.id = 42
        fake_book.title = "Dune"
        fake_book.languages = []
        fake_book.tags = []
        fake_book.data = []

        mock_calibre_db.get_book_read_archived.return_value = (fake_book, ub.ReadBook.STATUS_UNREAD, False)
        mock_calibre_db.get_cc_columns.return_value = []
        mock_calibre_db.order_authors.return_value = []

        mock_user_query = MagicMock()
        mock_user_query.filter.return_value.first.return_value = fake_user
        mock_archived_query = MagicMock()
        mock_archived_query.filter_by.return_value.first.return_value = None
        mock_override_query = MagicMock()
        mock_override_query.filter_by.return_value.first.return_value = None
        mock_shelf_query = MagicMock()
        mock_shelf_query.filter.return_value.all.return_value = []
        mock_synced_query = MagicMock()
        mock_synced_query.filter_by.return_value.first.return_value = None

        def session_query_side_effect(model):
            if model is ub.User:
                return mock_user_query
            elif model is ub.ArchivedBook:
                return mock_archived_query
            elif model is ub.KoboBookOverride:
                return mock_override_query
            elif model is ub.Shelf:
                return mock_shelf_query
            elif model is ub.KoboSyncedBooks:
                return mock_synced_query
            elif model is ub.BookShelf:
                # return empty shelves list
                mock_bs = MagicMock()
                mock_bs.filter.return_value.all.return_value = []
                return mock_bs
            return MagicMock()

        mock_session.query.side_effect = session_query_side_effect

        mock_cdb = MagicMock()
        mock_cdb.session.query().filter().filter().first.return_value = fake_book
        mock_kobo_cdb.return_value = mock_cdb

        app = Flask("test_app")
        with app.test_request_context():
            with patch('cps.web.current_user', fake_user):
                # Call show_book using __wrapped__ to avoid usermanagement/login decorators dependencies
                show_book.__wrapped__(42)
                mock_render.assert_called_once()
                kwargs = mock_render.call_args[1]
                assert "kobo_explanation" in kwargs
                assert kwargs["kobo_explanation"] is not None
                assert kwargs["kobo_explanation"]["book_id"] == 42
                assert kwargs["kobo_explanation"]["reader_override"] == "auto"

    @patch('cps.kobo_auth._', new=lambda x: x)
    @patch('cps.kobo_auth.current_user')
    @patch('cps.usermanagement.config')
    def test_anonymous_user_is_redirected(self, mock_usermanagement_config, mock_current_user):
        """POST to set_kobo_book_override without login redirects to login view."""
        from cps.kobo_auth import kobo_auth
        from flask import Flask, Blueprint
        from cps.cw_login import LoginManager

        mock_current_user.is_authenticated = False
        mock_usermanagement_config.config_allow_reverse_proxy_header_login = False

        app = Flask("test_app")
        app.secret_key = "test_secret"
        app.config["WTF_CSRF_ENABLED"] = False

        login_manager = LoginManager()
        login_manager.init_app(app)
        login_manager.login_view = "web.login"

        @login_manager.user_loader
        def load_user(user_id):
            return None

        web_bp = Blueprint("web", "web")
        @web_bp.route("/login")
        def login():
            return "login"
        app.register_blueprint(web_bp)
        app.register_blueprint(kobo_auth)

        client = app.test_client()
        res = client.post("/kobo_auth/book/42/override", data={"reader_override": "always"})

        assert res.status_code == 302
        assert "/login" in res.headers["Location"]

    @patch('cps.kobo_auth._', new=lambda x: x)
    @patch('cps.kobo_auth.current_user')
    def test_csrf_protection_blocks_post_without_token(self, mock_current_user):
        """POST to set_kobo_book_override without CSRF token is blocked with HTTP 400."""
        from cps.kobo_auth import kobo_auth
        from flask import Flask
        from flask_wtf.csrf import CSRFProtect
        from cps.cw_login import LoginManager

        mock_current_user.is_authenticated = True
        mock_current_user.id = 1
        mock_current_user.is_anonymous = False
        mock_current_user.get_id = lambda: "1"

        app = Flask("test_app")
        app.secret_key = "test_secret"
        app.config["WTF_CSRF_ENABLED"] = True

        login_manager = LoginManager()
        login_manager.init_app(app)

        @login_manager.user_loader
        def load_user(user_id):
            return mock_current_user

        CSRFProtect(app)
        app.register_blueprint(kobo_auth)

        client = app.test_client()
        res = client.post("/kobo_auth/book/42/override", data={"reader_override": "always"})

        assert res.status_code == 400

    @patch('cps.kobo_auth._', new=lambda x: x)
    @patch('cps.kobo_auth.db.CalibreDB')
    @patch('cps.kobo_auth.ub.session')
    @patch('cps.kobo.get_kobo_book_sync_explanation')
    def test_ajax_set_override_success(self, mock_explanation, mock_session, mock_calibredb_cls):
        """AJAX POST to set_kobo_book_override returns JSON on success."""
        from cps.kobo_auth import set_kobo_book_override

        fake_book = MagicMock()
        fake_book.id = 42
        mock_cdb = MagicMock()
        mock_calibredb_cls.return_value = mock_cdb
        mock_cdb.session.query().filter().filter().first.return_value = fake_book

        fake_user = MagicMock()
        fake_user.id = 1

        mock_query = mock_session.query().filter_by
        mock_query.return_value.first.return_value = None  # No existing override

        mock_explanation.return_value = {"book_id": 42, "is_allowed_on_device": True, "reader_override": "always"}

        app = self._setup_app_with_blueprint()
        with app.test_request_context(method="POST",
                                     headers={"X-Requested-With": "XMLHttpRequest"},
                                     data={"reader_override": "always"}):
            with patch('cps.kobo_auth.current_user', fake_user):
                with patch('cps.magic_shelf.invalidate_magic_shelf_cache') as mock_invalidate:
                    res = set_kobo_book_override.__wrapped__(42)

                    assert res.status_code == 200
                    data = res.get_json()
                    assert data["success"] is True
                    assert data["reader_override"] == "always"
                    assert data["explanation"]["is_allowed_on_device"] is True
                    mock_session.add.assert_called_once()
                    mock_invalidate.assert_called_once()
                    mock_session.commit.assert_called_once()

    @patch('cps.kobo_auth._', new=lambda x: x)
    def test_ajax_set_override_invalid_value(self):
        """AJAX POST to set_kobo_book_override with invalid value returns JSON 400."""
        from cps.kobo_auth import set_kobo_book_override
        from flask import Flask

        fake_user = MagicMock()
        fake_user.id = 1

        app = Flask("test_app")
        app.secret_key = "test_secret"
        with app.test_request_context(method="POST",
                                     headers={"X-Requested-With": "XMLHttpRequest"},
                                     data={"reader_override": "invalid"}):
            with patch('cps.kobo_auth.current_user', fake_user):
                res = set_kobo_book_override.__wrapped__(42)
                if isinstance(res, tuple):
                    res_obj, status_code = res
                    assert status_code == 400
                    assert res_obj.get_json()["error"] is not None
                else:
                    assert res.status_code == 400
                    assert res.get_json()["error"] is not None

    @patch('cps.kobo_auth._', new=lambda x: x)
    @patch('cps.kobo_auth.db.CalibreDB')
    def test_ajax_set_override_not_found(self, mock_calibredb_cls):
        """AJAX POST to set_kobo_book_override for non-existent book returns JSON 404."""
        from cps.kobo_auth import set_kobo_book_override
        from flask import Flask

        mock_cdb = MagicMock()
        mock_calibredb_cls.return_value = mock_cdb
        mock_cdb.session.query().filter().filter().first.return_value = None  # Not found

        fake_user = MagicMock()
        fake_user.id = 1

        app = Flask("test_app")
        app.secret_key = "test_secret"
        with app.test_request_context(method="POST",
                                     headers={"X-Requested-With": "XMLHttpRequest"},
                                     data={"reader_override": "always"}):
            with patch('cps.kobo_auth.current_user', fake_user):
                res = set_kobo_book_override.__wrapped__(42)
                if isinstance(res, tuple):
                    res_obj, status_code = res
                    assert status_code == 404
                    assert res_obj.get_json()["error"] is not None
                else:
                    assert res.status_code == 404
                    assert res.get_json()["error"] is not None

    @patch('cps.kobo_auth._', new=lambda x: x)
    @patch('cps.kobo_auth.db.CalibreDB')
    @patch('cps.kobo_auth.ub.session')
    def test_ajax_set_override_db_error(self, mock_session, mock_calibredb_cls):
        """AJAX POST to set_kobo_book_override with database error does rollback and returns JSON 500."""
        from cps.kobo_auth import set_kobo_book_override
        from flask import Flask

        fake_book = MagicMock()
        fake_book.id = 42
        mock_cdb = MagicMock()
        mock_calibredb_cls.return_value = mock_cdb
        mock_cdb.session.query().filter().filter().first.return_value = fake_book

        fake_user = MagicMock()
        fake_user.id = 1

        mock_session.query.side_effect = Exception("DB error")

        app = Flask("test_app")
        app.secret_key = "test_secret"
        with app.test_request_context(method="POST",
                                     headers={"X-Requested-With": "XMLHttpRequest"},
                                     data={"reader_override": "always"}):
            with patch('cps.kobo_auth.current_user', fake_user):
                res = set_kobo_book_override.__wrapped__(42)
                if isinstance(res, tuple):
                    res_obj, status_code = res
                    assert status_code == 500
                    assert res_obj.get_json()["error"] is not None
                else:
                    assert res.status_code == 500
                    assert res.get_json()["error"] is not None
                mock_session.rollback.assert_called_once()

    @patch('cps.kobo_auth._', new=lambda x: x)
    @patch('cps.kobo_auth.db.CalibreDB')
    @patch('cps.kobo_auth.ub.session')
    @patch('cps.kobo.get_kobo_book_sync_explanation')
    def test_ajax_set_override_never(self, mock_explanation, mock_session, mock_calibredb_cls):
        """AJAX POST to set_kobo_book_override with 'never' sets KoboBookOverride in DB and returns JSON."""
        from cps.kobo_auth import set_kobo_book_override

        fake_book = MagicMock()
        fake_book.id = 42
        mock_cdb = MagicMock()
        mock_calibredb_cls.return_value = mock_cdb
        mock_cdb.session.query().filter().filter().first.return_value = fake_book

        fake_user = MagicMock()
        fake_user.id = 1

        mock_query = mock_session.query().filter_by
        mock_query.return_value.first.return_value = None  # No existing override

        mock_explanation.return_value = {"book_id": 42, "is_allowed_on_device": False, "reader_override": "never"}

        app = self._setup_app_with_blueprint()
        with app.test_request_context(method="POST",
                                     headers={"X-Requested-With": "XMLHttpRequest"},
                                     data={"reader_override": "never"}):
            with patch('cps.kobo_auth.current_user', fake_user):
                with patch('cps.magic_shelf.invalidate_magic_shelf_cache') as mock_invalidate:
                    res = set_kobo_book_override.__wrapped__(42)

                    assert res.status_code == 200
                    data = res.get_json()
                    assert data["success"] is True
                    assert data["reader_override"] == "never"
                    assert data["explanation"]["is_allowed_on_device"] is False
                    mock_session.add.assert_called_once()
                    mock_invalidate.assert_called_once()
                    mock_session.commit.assert_called_once()

    @patch('cps.kobo_auth._', new=lambda x: x)
    @patch('cps.kobo_auth.db.CalibreDB')
    @patch('cps.kobo_auth.ub.session')
    @patch('cps.kobo.get_kobo_book_sync_explanation')
    def test_ajax_set_override_auto_deletes_existing(self, mock_explanation, mock_session, mock_calibredb_cls):
        """AJAX POST to set_kobo_book_override with 'auto' deletes existing KoboBookOverride in DB and returns JSON."""
        from cps.kobo_auth import set_kobo_book_override

        fake_book = MagicMock()
        fake_book.id = 42
        mock_cdb = MagicMock()
        mock_calibredb_cls.return_value = mock_cdb
        mock_cdb.session.query().filter().filter().first.return_value = fake_book

        fake_user = MagicMock()
        fake_user.id = 1

        existing_override = MagicMock()
        mock_query = mock_session.query().filter_by
        mock_query.return_value.first.return_value = existing_override

        mock_explanation.return_value = {"book_id": 42, "is_allowed_on_device": False, "reader_override": "auto"}

        app = self._setup_app_with_blueprint()
        with app.test_request_context(method="POST",
                                     headers={"X-Requested-With": "XMLHttpRequest"},
                                     data={"reader_override": "auto"}):
            with patch('cps.kobo_auth.current_user', fake_user):
                with patch('cps.magic_shelf.invalidate_magic_shelf_cache') as mock_invalidate:
                    res = set_kobo_book_override.__wrapped__(42)

                    assert res.status_code == 200
                    data = res.get_json()
                    assert data["success"] is True
                    assert data["reader_override"] == "auto"
                    mock_session.delete.assert_called_once_with(existing_override)
                    mock_invalidate.assert_called_once()
                    mock_session.commit.assert_called_once()

    @patch('cps.kobo_auth._', new=lambda x: x)
    @patch('cps.kobo_auth.db.CalibreDB')
    @patch('cps.kobo_auth.ub.session')
    @patch('cps.kobo.get_kobo_book_sync_explanation')
    def test_ajax_set_override_explanation_fails_returns_success_with_fallback(self, mock_explanation, mock_session, mock_calibredb_cls):
        """AJAX POST returns success even if generating explanation fails post-commit."""
        from cps.kobo_auth import set_kobo_book_override

        fake_book = MagicMock()
        fake_book.id = 42
        mock_cdb = MagicMock()
        mock_calibredb_cls.return_value = mock_cdb
        mock_cdb.session.query().filter().filter().first.return_value = fake_book

        fake_user = MagicMock()
        fake_user.id = 1

        mock_query = mock_session.query().filter_by
        mock_query.return_value.first.return_value = None

        # Simulate exception in get_kobo_book_sync_explanation
        mock_explanation.side_effect = Exception("Explanation generation failed")

        app = self._setup_app_with_blueprint()
        with app.test_request_context(method="POST",
                                     headers={"X-Requested-With": "XMLHttpRequest"},
                                     data={"reader_override": "always"}):
            with patch('cps.kobo_auth.current_user', fake_user):
                with patch('cps.magic_shelf.invalidate_magic_shelf_cache') as mock_invalidate:
                    res = set_kobo_book_override.__wrapped__(42)

                    assert res.status_code == 200
                    data = res.get_json()
                    assert data["success"] is True
                    assert data["reader_override"] == "always"
                    assert data["explanation"]["error_generating_explanation"] is True
                    mock_session.add.assert_called_once()
                    mock_invalidate.assert_called_once()
                    mock_session.commit.assert_called_once()
