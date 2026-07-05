# -*- coding: utf-8 -*-
# Test for settings drift detection (Roadmap-Punkt 2)

import os
import re
import pytest

# Regex patterns to parse settings calls in cps/admin.py
CONFIG_PATTERN = re.compile(
    r'_(config_checkbox|config_checkbox_int|config_string|config_int|config_checkbox_int_default)\(\s*to_save\s*,\s*["\']([^"\']+)["\']'
)

# Regex to parse cwa_settings columns in scripts/cwa_schema.sql
CWA_SCHEMA_PATTERN = re.compile(
    r'^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s+(?:SMALLINT|INTEGER|TEXT|REAL)',
    re.MULTILINE
)

# Regex to find direct subscripts or get lookups on to_save (e.g. to_save["..."] or to_save.get("..."))
TOSAVE_SUBSCRIPT_PATTERN = re.compile(
    r'to_save(?:\["([^"]+)"\]|\.get\(\s*["\']([^"\']+)["\']\s*,\s*["\']([^"\']*)["\']\))'
)

# Regex to find dynamic oauth fields in cps/admin.py
DYNAMIC_OAUTH_PATTERN = re.compile(
    r'to_save\[\s*["\']config_["\']\s*\+\s*str\(element\[[\'"]id[\'"]\]\)\s*\+\s*["\'](_oauth_client_(?:id|secret))["\']\s*\]'
)

def test_settings_fields_not_empty():
    from cps import settings_ui
    assert len(settings_ui.AJAXCONFIG_FIELDS) > 0
    assert len(settings_ui.VIEWCONFIG_FIELDS) > 0
    assert len(settings_ui.MAILSETTINGS_FIELDS) > 0
    assert len(settings_ui.SCHEDULEDTASKS_FIELDS) > 0
    assert len(settings_ui.CWA_FIELDS) > 0

def test_config_drift_admin_py(monkeypatch):
    """Scans cps/admin.py for configuration variables and asserts they are mapped in settings_ui.py."""
    # Mock oauthblueprints in test so that settings_ui includes the dynamic OAuth fields
    from cps import oauth_bb
    mock_blueprints = [
        {"provider_name": "github", "id": 1, "oauth_client_id": "", "oauth_client_secret": ""},
        {"provider_name": "google", "id": 2, "oauth_client_id": "", "oauth_client_secret": ""},
        {"provider_name": "generic", "id": 3, "oauth_client_id": "", "oauth_client_secret": ""}
    ]
    monkeypatch.setattr(oauth_bb, "oauthblueprints", mock_blueprints)

    from cps import settings_ui

    admin_py_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cps", "admin.py")
    assert os.path.isfile(admin_py_path)

    with open(admin_py_path, "r", encoding="utf-8") as f:
        content = f.read()

    found_settings = set()

    # 1. Parse standard helper calls
    for match in CONFIG_PATTERN.finditer(content):
        found_settings.add(match.group(2))

    # 2. Parse direct subscripts (like in Oauth helper)
    for match in TOSAVE_SUBSCRIPT_PATTERN.finditer(content):
        val = match.group(1) or match.group(2)
        if val and val.startswith("config_"):
            found_settings.add(val)

    # 3. Parse and resolve dynamic oauth client fields
    for match in DYNAMIC_OAUTH_PATTERN.finditer(content):
        suffix = match.group(1)
        for bp in mock_blueprints:
            if bp["provider_name"] != "generic":
                found_settings.add(f"config_{bp['id']}{suffix}")

    # Exclude certain settings which are internal, handled elsewhere or non-user facing
    ignored_settings = {
        "mail_password",              # processed directly in mail settings
        "config_calibre_uuid",         # Auto-generated
        "config_google_drive_folder",  # Google Drive settings (fully removed from consolidated UI)
        "config_calibre_dir",          # DB configuration page settings
        "config_calibre_split",        # DB configuration page settings
        "config_calibre_split_dir",    # DB configuration page settings
    }

    all_mapped_fields = settings_ui.get_all_mapped_fields()

    unmapped = found_settings - all_mapped_fields - ignored_settings

    assert not unmapped, f"Found settings in cps/admin.py that are not mapped in settings_ui.py: {unmapped}"

def test_cwa_settings_drift():
    """Scans cwa_settings columns in cwa_schema.sql and asserts they are mapped in settings_ui.py."""
    from cps import settings_ui

    schema_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "cwa_schema.sql")
    assert os.path.isfile(schema_path)

    with open(schema_path, "r", encoding="utf-8") as f:
        content = f.read()

    table_match = re.search(r'CREATE TABLE IF NOT EXISTS cwa_settings\((.*?)\);', content, re.DOTALL)
    assert table_match, "Could not find cwa_settings table in schema"

    table_content = table_match.group(1)
    found_columns = set()
    for match in CWA_SCHEMA_PATTERN.finditer(table_content):
        found_columns.add(match.group(1))

    # Exclude columns not directly submitted by matching form names
    ignored_columns = {
        "default_settings",               # Internal flag
        "auto_convert_retained_formats",  # Populated from dynamic convert_retained_* fields
        "auto_convert_ignored_formats",   # Populated from dynamic ignore_convert_* fields
        "auto_ingest_ignored_formats",    # Populated from dynamic ignore_ingest_* fields
    }

    all_mapped_fields = settings_ui.get_all_mapped_fields()

    unmapped = found_columns - all_mapped_fields - ignored_columns

    assert not unmapped, f"Found cwa_settings columns in schema that are not mapped in settings_ui.py: {unmapped}"

def test_integer_settings_drift():
    """Verifies the known integer_settings drift (cooldown minutes)."""
    cwa_db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts", "cwa_db.py")
    cwa_functions_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cps", "cwa_functions.py")

    assert os.path.isfile(cwa_db_path)
    assert os.path.isfile(cwa_functions_path)

    with open(cwa_db_path, "r", encoding="utf-8") as f:
        db_content = f.read()

    with open(cwa_functions_path, "r", encoding="utf-8") as f:
        func_content = f.read()

    # Regex to find integer_settings list in both files
    list_pattern = re.compile(r'integer_settings\s*=\s*\[(.*?)\]')

    db_match = list_pattern.search(db_content)
    func_match = list_pattern.search(func_content)

    assert db_match, "Could not find integer_settings list in scripts/cwa_db.py"
    assert func_match, "Could not find integer_settings list in cps/cwa_functions.py"

    def parse_list(list_str):
        return {item.strip().strip("'\"") for item in list_str.split(",") if item.strip()}

    db_integers = parse_list(db_match.group(1))
    func_integers = parse_list(func_match.group(1))

    diff = func_integers - db_integers

    # The only expected mismatch is duplicate_auto_resolve_cooldown_minutes
    expected_mismatch = {"duplicate_auto_resolve_cooldown_minutes"}
    assert diff == expected_mismatch, f"Unexpected mismatch in integer_settings: {diff} (expected exactly {expected_mismatch})"

def test_model_properties_existence():
    """Verifies that all mapped fields in settings_ui.py correspond to actual database/runtime model attributes."""
    from cps import settings_ui
    from cps import ub
    from cps import config_sql

    settings_cls = config_sql._Settings

    # 1. Verify scheduled tasks fields exist on _Settings class
    for field in settings_ui.SCHEDULEDTASKS_FIELDS:
        assert hasattr(settings_cls, field), f"Scheduled task field '{field}' does not exist on _Settings class"

    # 2. Verify viewconfig (roles and show settings) exist on User model or _Settings class
    for field in settings_ui.VIEWCONFIG_FIELDS:
        if field.endswith('_role'):
            if field == 'delete_role':
                role_attr = 'role_delete_books'
            elif field == 'edit_shelf_role':
                role_attr = 'role_edit_shelfs'
            else:
                role_attr = 'role_' + field[:-5]
            assert hasattr(ub.User, role_attr), f"User role attribute '{role_attr}' does not exist on User model"
        else:
            # show_X settings correspond to config_default_show in _Settings
            assert hasattr(settings_cls, 'config_default_show'), "config_default_show does not exist on _Settings class"

    # 3. Verify mail settings fields exist on _Settings class
    for field in settings_ui.MAILSETTINGS_FIELDS:
        if field == 'mail_password_e':
            assert hasattr(settings_cls, 'mail_password'), "mail_password does not exist on _Settings class"
        else:
            assert hasattr(settings_cls, field), f"Mail setting '{field}' does not exist on _Settings class"
