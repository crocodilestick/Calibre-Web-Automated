"""Regression: the book-detail page keeps its reclaimed spacing + lowered
stack breakpoint.

The detail-page layout is styled inline in cps/templates/detail.html, so these
are source-pins. They are RED on main (which ships a flat ``padding: 4rem`` card
and a 1400px stack breakpoint) and GREEN on this branch. Paired with live
multi-viewport verification on the running container; this guards against a
future refactor silently reverting the reclaimed gutters.
"""
import os

HERE = os.path.dirname(__file__)
DETAIL = os.path.normpath(
    os.path.join(HERE, "..", "..", "cps", "templates", "detail.html")
)


def _src():
    with open(DETAIL, encoding="utf-8") as fh:
        return fh.read()


def test_card_padding_is_fluid_and_reclaimed():
    src = _src()
    # Card padding reclaimed from a flat 4rem (40px every side, never reduced on
    # phones) to a fluid clamp with a ~14px phone floor.
    assert "clamp(1.4rem, 3.2vw, 3rem)" in src
    # The old flat 40px card padding is gone.
    assert "padding: 4rem;" not in src


def test_stack_breakpoint_lowered_to_1024():
    src = _src()
    # Cover + metadata sit side-by-side down to 1024px now (was only >1400px).
    assert "max-width: 1024px" in src
    assert "max-width: 1400px" not in src


def test_title_is_fluid():
    assert "clamp(2.1rem, 1.4rem + 1.8vw, 2.9rem)" in _src()


def test_rating_input_has_themed_fallback():
    # The raw numeric rating input is themed so the pre-init / no-JS fallback is
    # not a full-width white slab (the "white 0 box").
    assert "#detail-rating" in _src()
