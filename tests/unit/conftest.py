# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Pre-load real cps.constants before any test file is collected.

Several unit-test files (test_apple_books_provider.py, test_cover_extract.py,
test_cover_picker_*.py, test_cover_url_validator.py, test_cover_booster.py)
use a stub-installation pattern of the shape::

    constants = sys.modules.get("cps.constants") or types.ModuleType("cps.constants")
    constants.STATIC_DIR = ...
    sys.modules["cps.constants"] = constants

The `or types.ModuleType(...)` branch fires when nothing has imported the real
cps.constants yet. The resulting bare ModuleType lacks `ROLE_USER` and the
other role-flag constants that `cps/ub.py` references at class-definition
time, so any *later* test file that imports `cps.ub` (via cps.db,
cps.progress_syncing, cps.editbooks, cps.helper, etc.) crashes collection
with `AttributeError: module 'cps.constants' has no attribute 'ROLE_USER'`.

We pre-load the real `cps/constants.py` via `spec_from_file_location` so it
exists in `sys.modules` *before* any collection-time stub-install fires. The
real module has all the role flags, plus everything those callers add to it
(STATIC_DIR, USER_AGENT) — neither use breaks the other. Loading via
spec_from_file_location bypasses `cps/__init__.py`, avoiding the Flask /
SQLAlchemy / scheduler heavy startup that import-time test code can't afford.
"""

import importlib.util
import sys
import types
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]


def _preload_real_constants() -> None:
    """Top-up sys.modules['cps.constants'] so it has ROLE_USER + STATIC_DIR
    + USER_AGENT (every attribute downstream tests need). If a stub is already
    installed and is missing role flags, replace it with the real module loaded
    via spec_from_file_location — that bypasses cps/__init__.py so the full
    Flask startup isn't forced before pytest is ready.

    Does NOT pre-create `cps` as a bare namespace module; that would prevent
    the real `cps/__init__.py` from running when the first non-stub test does
    `from cps import editbooks` and the chain `from cps import cli_param`
    would then fail. We only touch `cps.constants` here.
    """
    existing = sys.modules.get("cps.constants")
    if existing is not None and hasattr(existing, "ROLE_USER"):
        return  # real or already-good stub; nothing to do

    constants_path = _REPO_ROOT / "cps" / "constants.py"
    spec = importlib.util.spec_from_file_location(
        "cps.constants", str(constants_path)
    )
    if spec is None or spec.loader is None:
        return
    module = importlib.util.module_from_spec(spec)
    # Carry over stub-set attributes (STATIC_DIR, USER_AGENT) that test
    # files added before us, so loading the real module is purely additive.
    if existing is not None:
        for name in dir(existing):
            if not name.startswith("_"):
                setattr(module, name, getattr(existing, name))
    sys.modules["cps.constants"] = module
    spec.loader.exec_module(module)

    cps_pkg = sys.modules.get("cps")
    if cps_pkg is not None:
        cps_pkg.constants = module


def _preload_real_cps_package() -> None:
    """Force the real cps/__init__.py to run *before* any unit test file's
    module-level stub installer fires. Otherwise the first test file to
    install `sys.modules['cps'] = types.ModuleType('cps')` (with __path__
    but no execution of __init__) wins, and later test files importing
    `from cps.editbooks import ...` or `from cps import config, db, app, lm,
    cli_param, calibre_db` fail with ImportError (unknown location).

    cps/__init__.py is heavyweight (Flask app, blueprints, SQLAlchemy
    engines, scheduler) but only ~0.5s — acceptable as a one-time pytest
    collection cost so the rest of tests/unit/ can collect cleanly.

    Skips silently if anything goes wrong (cwa_db not on path in some
    minimal test runs, etc.) so this doesn't itself become a collection
    blocker."""
    cps_pkg = sys.modules.get("cps")
    if cps_pkg is not None and hasattr(cps_pkg, "cli_param") and hasattr(cps_pkg, "app"):
        return  # already fully loaded

    if cps_pkg is not None and not hasattr(cps_pkg, "cli_param"):
        stashed_constants = getattr(cps_pkg, "constants", None)
        sys.modules.pop("cps", None)
        for name in list(sys.modules):
            if name.startswith("cps.") and name != "cps.constants":
                mod = sys.modules[name]
                if not hasattr(mod, "__file__") or mod.__file__ is None:
                    sys.modules.pop(name, None)
        try:
            import cps as _real_cps  # noqa: F401
            if stashed_constants is not None and not hasattr(_real_cps, "constants"):
                _real_cps.constants = stashed_constants
        except Exception:
            pass
        return

    try:
        import cps as _real_cps  # noqa: F401
    except Exception:
        pass


def _preload_cps_services() -> None:
    """Pre-import `cps.services` so its `ldap`/`kobo`/`goodreads_support`
    attributes are set before any test file's stub-install pattern fires.
    Real `cps/__init__.py` only imports services from inside `create_app()`,
    so a bare `import cps` doesn't populate it."""
    existing = sys.modules.get("cps.services")
    if existing is not None and hasattr(existing, "ldap"):
        return
    if existing is not None and not hasattr(existing, "ldap"):
        sys.modules.pop("cps.services", None)
    try:
        import cps.services  # noqa: F401
    except Exception:
        pass


_preload_real_constants()
_preload_real_cps_package()
_preload_cps_services()
