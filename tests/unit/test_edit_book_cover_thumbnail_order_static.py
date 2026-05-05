# Calibre-Web Automated - fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_cover_thumbnail_regeneration_runs_after_edit_book_commit():
    source = (PROJECT_ROOT / "cps/editbooks.py").read_text(encoding="utf-8")
    edit_body = source.split("def do_edit_book", 1)[1].split("def render_edit_book", 1)[0]
    before_commit = edit_body.split("# Stage 3: Commit all changes to the database", 1)[0]
    after_commit = edit_body.split("calibre_db.session.commit()", 1)[1]

    assert "helper.replace_cover_thumbnail_cache(" not in before_commit
    assert "helper.replace_cover_thumbnail_cache(thumbnail_refresh_book_id)" in after_commit
