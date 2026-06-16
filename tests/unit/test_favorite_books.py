"""Regression: per-user favorite / starred books — fork #27.

Users can star a book (toggle), see a dedicated Favorites listing (filter), and a
gold star badge on starred covers. Built mirroring the existing per-user archived
/ hidden book features.

Source-pins across the layers (models, constants, routes, sidebar, templates).
RED on main (none of this exists), GREEN on this branch. Paired with live
verification on the running container (toggle insert/delete + per-user scoping,
Favorites view, grid badge, cold-boot migration idempotency, end-to-end click).
"""
import os

HERE = os.path.dirname(__file__)
ROOT = os.path.normpath(os.path.join(HERE, "..", ".."))


def _read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


def test_favoritebook_model_and_migration():
    src = _read("cps", "ub.py")
    assert "class FavoriteBook(Base):" in src
    assert "__tablename__ = 'favorite_book'" in src
    assert "uq_favorite_book" in src
    # New table is auto-created on startup (idempotent), like the sibling tables.
    assert 'has_table(engine.connect(), "favorite_book")' in src
    assert "FavoriteBook.__table__.create(bind=engine, checkfirst=True)" in src
    # Existing users get the new sidebar bit OR'd in (one-time, marker-guarded).
    assert "favorites_sidebar_v1" in src


def test_constants_favorites_sidebar_bit():
    src = _read("cps", "constants.py")
    assert "SIDEBAR_FAVORITES       = 1 << 19" in src
    assert '"sidebar_favorites": SIDEBAR_FAVORITES,' in src
    # The default sidebar mask must extend to include the new bit, else the entry
    # is off by default for new users.
    assert "ADMIN_USER_SIDEBAR      = (SIDEBAR_FAVORITES << 1) - 1" in src


def test_web_toggle_endpoint_and_render():
    src = _read("cps", "web.py")
    assert '@web.route("/ajax/togglefavorite/<int:book_id>", methods=[\'POST\'])' in src
    assert "def toggle_favorite(book_id):" in src
    # Presence-based toggle: delete the row to un-favorite, insert to favorite.
    assert "ub.session.delete(favorite)" in src
    assert "ub.FavoriteBook(user_id=int(current_user.id), book_id=book_id)" in src
    # Dedicated listing + dispatch.
    assert "def render_favorite_books(page, sort_param):" in src
    assert 'elif data == "favorites":' in src
    assert "return render_favorite_books(page, order)" in src


def test_sidebar_entry_and_grid_set():
    src = _read("cps", "render_template.py")
    assert '"id": "favorites"' in src
    assert "constants.SIDEBAR_FAVORITES" in src
    # Per-request favorited-id set powers the cover badge (O(1) lookup in the macro).
    assert "g.favorite_book_ids" in src


def test_detail_page_star_toggle():
    src = _read("cps", "templates", "detail.html")
    assert 'id="toggle-favorite-btn"' in src
    assert 'id="favorite_form"' in src
    assert "web.toggle_favorite" in src
    # JS handler flips the star icon in place.
    assert '$("#toggle-favorite-btn").on("click"' in src
    assert "glyphicon-star" in src


def test_cover_badge_star():
    src = _read("cps", "templates", "image.html")
    assert "cover-badge-favorite" in src
    assert "g.favorite_book_ids" in src
