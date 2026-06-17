# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Unit tests for year-only / partial publication-date parsing (issue #472).

The user-edit handler must accept a bare year ("2020") or a year-month
("2020-05") in the Published Date field and default the missing parts to
January 1st, while still rejecting genuinely malformed input the way the old
strict ``%Y-%m-%d`` parse did.

The module under test is pure (only stdlib), so we load the file directly
without importing the heavy ``cps`` package.
"""

from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path

import pytest


def _load_pubdate_parse():
    module_path = (
        Path(__file__).resolve().parents[2]
        / "cps" / "services" / "pubdate_parse.py"
    )
    spec = importlib.util.spec_from_file_location("pubdate_parse_under_test", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


parse_partial_pubdate = _load_pubdate_parse().parse_partial_pubdate


def test_year_only_defaults_to_jan_1():
    assert parse_partial_pubdate("2020") == datetime(2020, 1, 1)


def test_year_month_defaults_day_to_1():
    assert parse_partial_pubdate("2020-05") == datetime(2020, 5, 1)


def test_full_date_is_preserved():
    assert parse_partial_pubdate("2020-05-15") == datetime(2020, 5, 15)


def test_surrounding_whitespace_is_tolerated():
    assert parse_partial_pubdate("  1999  ") == datetime(1999, 1, 1)


def test_single_digit_month_full_date_still_parses():
    # strptime's %m accepts single-digit months, so a hand-typed "2021-3-4"
    # must not be rejected.
    assert parse_partial_pubdate("2021-3-4") == datetime(2021, 3, 4)


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "   ",
        "not-a-date",
        "2020-13",      # impossible month
        "2020-02-30",   # impossible day
        "20200515",     # no separators
        "2020/05/15",   # wrong separator
        "May 2020",     # textual month
    ],
)
def test_malformed_input_raises_valueerror(bad):
    with pytest.raises(ValueError):
        parse_partial_pubdate(bad)


def test_none_raises_valueerror():
    with pytest.raises(ValueError):
        parse_partial_pubdate(None)
