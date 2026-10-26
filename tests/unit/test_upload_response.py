# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Regression tests for browser and XHR upload completion responses."""

import json

import pytest
from flask import Flask

from cps.editbooks import _upload_response


@pytest.fixture
def app():
    return Flask(__name__)


@pytest.mark.unit
def test_standard_upload_redirects_browser(app):
    with app.test_request_context("/upload", method="POST"):
        response = _upload_response("/tasks")

    assert response.status_code == 302
    assert response.headers["Location"] == "/tasks"


@pytest.mark.unit
def test_xhr_upload_keeps_json_location_contract(app):
    with app.test_request_context(
        "/upload",
        method="POST",
        headers={"X-Requested-With": "XMLHttpRequest"},
    ):
        response = _upload_response("/tasks")

    assert response.status_code == 200
    assert response.mimetype == "application/json"
    assert json.loads(response.get_data(as_text=True)) == {"location": "/tasks"}
