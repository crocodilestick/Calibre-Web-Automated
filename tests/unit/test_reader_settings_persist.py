"""Per-user web-reader display settings (task #31).

Reader settings (theme/font/fontSize/spread/reflow/margin) are persisted under
view_settings['reader'] so they follow a user across devices. sanitize_reader_settings()
is the gate that keeps a crafted POST from storing junk on the user row — pin
its whitelist + clamping. RED on main (the function doesn't exist there); GREEN
on the branch.
"""
import pytest

from cps.web import sanitize_reader_settings, _reader_setting_int


def test_keeps_each_valid_field():
    out = sanitize_reader_settings({
        "theme": "darkTheme", "font": "Arial", "spread": "nonespread",
        "fontSize": 150, "margin": 40, "reflow": True,
    })
    assert out == {
        "theme": "darkTheme", "font": "Arial", "spread": "nonespread",
        "fontSize": 150, "margin": 40, "reflow": True,
    }


def test_drops_unknown_keys_and_bad_enum_values():
    out = sanitize_reader_settings({
        "theme": "neonTheme", "font": "ComicSans", "spread": "triple",
        "evil": "<script>alert(1)</script>", "fontSize": 100,
    })
    # Only the valid fontSize survives; bad enums + unknown keys are dropped.
    assert out == {"fontSize": 100}


def test_clamps_numeric_ranges():
    assert sanitize_reader_settings({"fontSize": 9999})["fontSize"] == 200
    assert sanitize_reader_settings({"fontSize": 10})["fontSize"] == 75
    assert sanitize_reader_settings({"margin": -10})["margin"] == 0
    assert sanitize_reader_settings({"margin": 999})["margin"] == 80


def test_numeric_strings_accepted_booleans_rejected():
    assert sanitize_reader_settings({"fontSize": "125"})["fontSize"] == 125
    # A JSON `true` must not be coerced into fontSize=1 / margin=1.
    assert "fontSize" not in sanitize_reader_settings({"fontSize": True})
    assert "margin" not in sanitize_reader_settings({"margin": False})


def test_reflow_coercion():
    assert sanitize_reader_settings({"reflow": True})["reflow"] is True
    assert sanitize_reader_settings({"reflow": "true"})["reflow"] is True
    assert sanitize_reader_settings({"reflow": "false"})["reflow"] is False
    assert "reflow" not in sanitize_reader_settings({"reflow": 5})


def test_non_dict_payload_is_empty():
    assert sanitize_reader_settings("nope") == {}
    assert sanitize_reader_settings(None) == {}
    assert sanitize_reader_settings([1, 2]) == {}


def test_reader_setting_int_helper():
    assert _reader_setting_int(50, 75, 200) == 75      # clamp up to lo
    assert _reader_setting_int(300, 75, 200) == 200    # clamp down to hi
    assert _reader_setting_int(True, 0, 80) is None     # bool rejected
    assert _reader_setting_int("abc", 0, 80) is None
    assert _reader_setting_int(None, 0, 80) is None
    assert _reader_setting_int("40", 0, 80) == 40
