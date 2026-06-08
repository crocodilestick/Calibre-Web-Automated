# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Theme enforcement must be airtight: the deprecated default theme must never
reach a user.

The light/default theme is deprecated; caliBlur (dark) is the only supported
theme. ``cps.admin.before_request`` (an ``@admi.before_app_request`` handler,
so it runs for every request) forces ``g.current_theme = 1`` and templates gate
their caliBlur ``<link>`` tags on ``{% if g.current_theme == 1 %}``.

The escape this guards against: ``g.current_theme`` is set partway through a
handler that does *unguarded* work first (``config.*`` reads, a DB
autoconfig/recovery block) — and two other ``@app.before_request`` handlers in
``cps/__init__.py`` run *before* this one. If any of them raises, the theme is
never set, ``g.current_theme`` is undefined, and ``{% if g.current_theme == 1 %}``
evaluates False — so the page (typically the standalone ``http_error.html``)
renders the deprecated default theme. That is the root cause behind the class of
"default-theme-only" display bugs, e.g. #320's oversized shelf-reorder covers,
which a caliBlur-only repro could not see.

Two invariants make it airtight:
  1. The force is the FIRST thing ``before_request`` does (before any unguarded
     work), and is a single unconditional assignment — so a later exception in
     the handler body still leaves caliBlur forced on whatever page renders.
  2. ``http_error.html`` (standalone — it does not extend ``layout.html``, and
     renders on exactly the failures where the before_request chain may not have
     completed) defaults an undefined ``g.current_theme`` to caliBlur.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
ADMIN_SRC = (REPO_ROOT / "cps" / "admin.py").read_text()


def _before_request_src() -> str:
    """Slice the body of the ``@admi.before_app_request`` ``before_request()``
    handler out of the file text. Anchored on the decorator (not just the
    function name) so a rename — or a second ``before_request`` added elsewhere
    in the file — can't make the pin analyze the wrong function. File-based, no
    import, matching the other UI regression tests."""
    lines = ADMIN_SRC.splitlines()
    dec = next(
        (i for i, ln in enumerate(lines) if ln.strip() == "@admi.before_app_request"),
        None,
    )
    assert dec is not None, "@admi.before_app_request decorator not found in cps/admin.py"
    start = next((j for j in range(dec + 1, len(lines)) if lines[j].startswith("def ")), None)
    assert start is not None, "no def follows the @admi.before_app_request decorator"
    assert lines[start].startswith("def before_request():"), (
        f"the @admi.before_app_request handler is not before_request(): {lines[start]!r}"
    )
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if re.match(r"^(@|def |class )", lines[j]):
            end = j
            break
    return "\n".join(lines[start:end])


class TestThemeForcedFirstAndUnconditional:
    def test_force_precedes_any_unguarded_config_access(self):
        src = _before_request_src()
        force_idx = src.find("g.current_theme = 1")
        assert force_idx != -1, "before_request must force g.current_theme = 1"
        cfg_idx = src.find("config.config_")
        assert cfg_idx != -1, "expected a config.config_* access in before_request"
        assert force_idx < cfg_idx, (
            "g.current_theme = 1 must be forced BEFORE the unguarded config.* "
            "accesses (and the DB autoconfig block) — otherwise an exception "
            "there skips the theme and the rendered (error) page falls back to "
            "the deprecated default theme. This is the #320 default-theme escape."
        )

    def test_single_unconditional_theme_assignment(self):
        src = _before_request_src()
        # `=(?!=)` counts assignments only, not `==` comparisons (the comment
        # documenting the template check contains a literal g.current_theme == 1).
        n = len(re.findall(r"g\.current_theme\s*=(?!=)", src))
        assert n == 1, (
            f"expected exactly one g.current_theme assignment in before_request "
            f"(single source of truth), found {n}. The old per-user/config "
            f"compute that the force immediately discarded is dead code."
        )

    def test_force_is_body_level_not_nested(self):
        src = _before_request_src()
        for line in src.splitlines():
            if re.match(r"\s*g\.current_theme\s*=\s*1\b", line):
                indent = len(line) - len(line.lstrip())
                assert indent == 4, (
                    f"the theme force must be unconditional at function-body "
                    f"indent (4), not nested under a try/if that could skip it; "
                    f"got indent={indent}"
                )
                return
        pytest.fail("no 'g.current_theme = 1' assignment found in before_request")


# Standalone templates (no `{% extends "layout.html" %}`) can render on paths
# where before_request may not have completed — so each must default an unset
# theme to caliBlur. layout.html keeps its bare checks intentionally: it renders
# only after a completed request, where before_request has already forced the
# theme as its first statement.
STANDALONE_THEME_TEMPLATES = ["http_error.html", "shelfdown.html"]


class TestStandaloneTemplatesDefaultToCaliblur:
    @pytest.mark.parametrize("name", STANDALONE_THEME_TEMPLATES)
    def test_uses_resilient_default(self, name):
        html = (REPO_ROOT / "cps" / "templates" / name).read_text()
        assert "{% extends" not in html, (
            f"{name} is expected to be standalone (the reason it needs the "
            f"resilient default); if it now extends a base template, revisit this."
        )
        assert (
            "g.get('current_theme', 1)" in html or 'g.get("current_theme", 1)' in html
        ), (
            f"{name} must default an unset theme to caliBlur via "
            f"g.get('current_theme', 1) — it can render when before_request never "
            f"set the theme, and the light/default theme is deprecated."
        )

    @pytest.mark.parametrize("name", STANDALONE_THEME_TEMPLATES)
    def test_no_bare_nonresilient_check(self, name):
        html = (REPO_ROOT / "cps" / "templates" / name).read_text()
        assert "g.current_theme == 1" not in html, (
            f"{name} still has a bare g.current_theme == 1 check, which falls back "
            f"to the deprecated default theme when the theme is unset."
        )
