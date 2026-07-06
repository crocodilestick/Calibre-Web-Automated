# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit and integration tests for the Netflix-style book preview overlay."""

import os
import pytest
from unittest.mock import MagicMock, patch
from flask import Flask, render_template
from cps import web, ub


class TestPreviewOverlay:

    def test_preview_book_route_registered(self):
        """Smoke test to ensure the preview_book route is registered in the web blueprint."""
        from flask import url_for
        app = Flask("test_app")
        app.secret_key = "test_secret"
        app.register_blueprint(web.web)

        with app.test_request_context():
            url = url_for("web.preview_book", book_id=42)
            assert url == "/book/42/preview"

    def test_preview_fragment_rendering(self):
        """Test rendering of preview_fragment.html with mock data to catch template/filter errors."""
        template_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "cps", "templates"))
        app = Flask("test_app", template_folder=template_dir)
        app.secret_key = "test_secret"

        # Mock translate function
        @app.template_global()
        def _(text, **kwargs):
            return text

        # Mock url_for to avoid route-checking exceptions
        @app.template_global()
        def url_for(endpoint, **values):
            return f"/{endpoint}/{values.get('book_id', '')}"

        # Mock current_user
        mock_user = MagicMock()
        mock_user.is_anonymous = False
        mock_user.role_viewer.return_value = True
        mock_user.role_download.return_value = True
        mock_user.role_edit.return_value = True
        mock_user.kindle_mail = "kindle@example.com"

        # Mock entry (book)
        mock_entry = MagicMock()
        mock_entry.id = 42
        mock_entry.title = "Dune"
        mock_entry.comments = [MagicMock(text="A great sci-fi novel")]
        mock_entry.ordered_authors = [MagicMock(name="Frank Herbert")]
        mock_entry.reader_list = ["epub"]
        mock_entry.data = [MagicMock(format="EPUB")]
        mock_entry.read_status = True
        mock_entry.email_share_list = [{"format": "EPUB", "convert": 0}]
        mock_entry.series = [MagicMock(name="Dune")]

        # Mock series books
        mock_s_book1 = MagicMock()
        mock_s_book1.id = 43
        mock_s_book1.title = "Dune Messiah"

        with app.test_request_context():
            rendered = render_template(
                "preview_fragment.html",
                entry=mock_entry,
                series_books=[mock_s_book1],
                current_user=mock_user
            )

            # Assert key sections are rendered
            assert "cwa-preview-overlay" in rendered
            assert "Dune" in rendered
            assert "Frank Herbert" in rendered
            assert "A great sci-fi novel" in rendered
            assert "cwa-quick-actions-toolbar" in rendered
            assert "cwa-quick-send-ereader" in rendered
            assert "Dune Messiah" in rendered
            assert "cwa-view-toggle" in rendered

    def test_shelf_contains_preview_triggers(self):
        """Test that index/shelf templates contain the preview modal data-target markup."""
        template_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "cps", "templates"))
        app = Flask("test_app", template_folder=template_dir)
        app.secret_key = "test_secret"

        @app.template_global()
        def _(text, **kwargs):
            return text

        @app.template_global()
        def url_for(endpoint, **values):
            return f"/{endpoint}"

        # Mock macro dependencies for shelf.html
        @app.template_global()
        def delete_book(*args, **kwargs):
            return ""

        # We will load and compile the template to see if it parses and has correct data-target
        # of #previewOverlayModal for cover links.
        with open(os.path.join(template_dir, "shelf.html"), "r", encoding="utf-8") as f:
            template_content = f.read()

        assert "#previewOverlayModal" in template_content
        assert "data-target=\"#previewOverlayModal\"" in template_content

    def test_main_js_contains_caliblur_guard(self):
        """Test that main.js has the delegated click handler with the caliBlur guard and simple check."""
        js_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "cps", "static", "js", "main.js"))
        with open(js_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Ensure the handler targets links with data-target (which are omitted when simple == true)
        assert ".book-cover-link[data-target='#previewOverlayModal']" in content
        # Ensure the handler has the guard against double-firing when caliBlur is not active
        assert "if (!$(this).attr(\"data-toggle\"))" in content

    def test_templates_respect_simple_flag(self):
        """Ensure that data-target and data-toggle are conditionally rendered based on simple flag."""
        template_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "cps", "templates"))
        for template in ["index.html", "author.html", "search.html", "shelf.html"]:
            with open(os.path.join(template_dir, template), "r", encoding="utf-8") as f:
                content = f.read()
                # If the template has book-cover-link, it should guard the modal attributes
                if "class=\"book-cover-link\"" in content:
                    assert "{% if simple==false %}data-toggle=\"modal\" data-target=\"#previewOverlayModal\"" in content

    @patch('cps.web.render_template')
    @patch('cps.web.calibre_db')
    @patch('cps.web.current_user')
    @patch('cps.web.config')
    @patch('cps.web.ub')
    def test_preview_book_controller_calls_render_template(self, mock_ub, mock_config, mock_current_user, mock_calibre_db, mock_render):
        """Test that preview_book controller queries database and calls render_template."""
        from cps.web import preview_book

        # Setup mock user
        mock_current_user.is_authenticated = True
        mock_current_user.list_allowed_tags.return_value = []
        mock_current_user.list_denied_tags.return_value = []

        # Setup mock book entry
        mock_book = MagicMock()
        mock_book.id = 42
        mock_book.title = "Dune"
        mock_book.languages = []
        mock_book.tags = []
        mock_book.series = []

        # Setup mock calibre_db returns
        mock_calibre_db.get_book_read_archived.return_value = (mock_book, ub.ReadBook.STATUS_UNREAD, False)
        mock_calibre_db.order_authors.return_value = []

        # Create minimal flask app context
        app = Flask("test_app")
        app.secret_key = "test_secret"

        with app.test_request_context():
            func = preview_book
            while hasattr(func, '__wrapped__'):
                func = func.__wrapped__
            func(42)

            # Verify database query was made
            mock_calibre_db.get_book_read_archived.assert_called_once_with(
                42, mock_config.config_read_column, allow_show_archived=True
            )

            # Verify render_template was called with correct fragment and context
            mock_render.assert_called_once_with(
                'preview_fragment.html',
                entry=mock_book,
                series_books=[]
            )
