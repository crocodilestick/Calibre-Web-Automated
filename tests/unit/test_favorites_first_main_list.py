"""The main library list floats the user's starred books to the top (#34).

Favorites (app.db) and books (metadata.db) can't be JOINed, so the main-list
ordering fetches favorite ids and prepends a CASE. Pin that the helper exists,
is anonymous-safe, and that ONLY the main-list branch prepends it (other views
keep their own ordering). The live float-to-top behaviour is verified with
Playwright. RED on main; GREEN on branch.
"""
import inspect
import re

from cps import web


def test_favorites_first_helper_exists():
    src = inspect.getsource(web._favorites_first_order)
    assert "FavoriteBook" in src, "helper must read the FavoriteBook table"
    assert "case(" in src, "helper must build a CASE ordering"
    assert "is_authenticated" in src, "anonymous users must be a no-op (return None)"


def test_main_list_prepends_favorites_first():
    src = inspect.getsource(web.render_books_list)
    assert "_favorites_first_order()" in src, "main list must call the helper"
    # favorites prepended -> they sort first, then the user's chosen order
    assert re.search(r"\[\s*favorites_first\s*\]\s*\+\s*book_order", src), \
        "favorites_first must be PREPENDED to the order (top of the list)"
