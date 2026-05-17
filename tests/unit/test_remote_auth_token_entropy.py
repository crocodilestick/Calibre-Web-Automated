# Calibre-Web Automated - fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Regression test for janeczku/calibre-web PR #3623 (jvoisin):
RemoteAuthToken (the /remote/login magic-link token) must be generated
from 16 bytes of entropy (128 bits, 32 hex chars), not 4 bytes (32 bits,
8 hex chars).

The 8-hex-char form was brute-forceable in the 10-minute validity window
against the unrate-limited /ajax/verify_token endpoint: ~4B token space,
~6M tokens reachable at 10k req/s. Bumping to 128 bits puts the token
space out of brute-force reach (matches the Kobo permanent device token,
which already uses urandom(16) — see cps/kobo_auth.py:99).

Two-pronged regression pin:

1. AST source-pin on cps/ub.py:RemoteAuthToken.__init__ — assert the
   urandom call literal is `urandom(16)`. Catches a refactor that
   reintroduces 4 (or any other short width).
2. Behavioral assertion — instantiate RemoteAuthToken() and assert
   len(auth_token) == 32 and all-hex. Catches a fix that changes the
   AST shape (e.g. switches to secrets.token_hex) but accidentally
   keeps the byte width wrong.
"""

import ast
import re
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
UB_PY = REPO_ROOT / "cps" / "ub.py"

# Ensure scripts/ on path for cwa_db (cps/cw_login imports it transitively)
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


def _remote_auth_token_init():
    tree = ast.parse(UB_PY.read_text(encoding="utf-8"))
    for cls in ast.walk(tree):
        if isinstance(cls, ast.ClassDef) and cls.name == "RemoteAuthToken":
            for item in cls.body:
                if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                    return item
            raise AssertionError("RemoteAuthToken.__init__ not found")
    raise AssertionError("class RemoteAuthToken not found in cps/ub.py")


def test_source_pin_uses_16_bytes_of_entropy():
    """Source-pin: RemoteAuthToken.__init__ must call urandom with 16."""
    init_func = _remote_auth_token_init()
    urandom_widths = []
    for node in ast.walk(init_func):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        is_urandom = (
            (isinstance(func, ast.Name) and func.id == "urandom")
            or (isinstance(func, ast.Attribute) and func.attr == "urandom")
        )
        if not is_urandom:
            continue
        if not node.args:
            continue
        arg = node.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, int):
            urandom_widths.append(arg.value)

    assert urandom_widths, (
        "Expected RemoteAuthToken.__init__ to call urandom(N) with a literal "
        "int width. Found no urandom(...) call with a constant arg."
    )
    assert all(w == 16 for w in urandom_widths), (
        f"RemoteAuthToken.__init__ must use urandom(16) for 128 bits of entropy. "
        f"Found urandom widths: {urandom_widths}. The 4-byte form (32 bits) is "
        f"brute-forceable in the 10-minute validity window. See "
        f"janeczku/calibre-web#3623 for the threat model."
    )


def test_generated_token_has_32_hex_chars():
    """Behavioral: a fresh RemoteAuthToken().auth_token is 32 lowercase hex chars."""
    from cps import ub

    token = ub.RemoteAuthToken()
    assert len(token.auth_token) == 32, (
        f"RemoteAuthToken.auth_token must be 32 hex chars (16 bytes of entropy). "
        f"Got {len(token.auth_token)} chars: {token.auth_token!r}. "
        f"See janeczku/calibre-web#3623."
    )
    assert re.fullmatch(r"[0-9a-f]{32}", token.auth_token), (
        f"RemoteAuthToken.auth_token must be all-lowercase-hex (hexlify(urandom(16))). "
        f"Got: {token.auth_token!r}"
    )


def test_generated_tokens_are_distinct():
    """Sanity: two fresh tokens are not equal (entropy is real, not a constant)."""
    from cps import ub

    a = ub.RemoteAuthToken().auth_token
    b = ub.RemoteAuthToken().auth_token
    assert a != b, (
        f"Two fresh RemoteAuthToken values must differ. Got a={a!r}, b={b!r}. "
        f"This would indicate urandom returning constant or being stubbed."
    )
