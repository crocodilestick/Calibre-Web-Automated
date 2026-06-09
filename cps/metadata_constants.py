# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# SPDX-License-Identifier: GPL-3.0-or-later
"""Single source of truth for metadata auto-fetch defaults (fork #405).

Before this module the default provider order was hard-coded in four places that
disagreed (cps/metadata_helper.py, the now-deleted cps/auto_metadata.py,
cps/cwa_functions.py, and scripts/cwa_schema.sql + cps/templates/cwa_settings.html),
so the order a user configured was not reliably the order that ran, and Open Library
— a strong general provider that ships in this fork — was in none of them. Every
Python fallback now imports these constants; the SQL schema default and the template
fallback are kept byte-identical to DEFAULT_METADATA_PROVIDER_HIERARCHY_JSON (a unit
test pins the agreement).
"""

# Ordered strongest-general-first. Open Library sits right after Google because it
# resolves clean editions + cross-identifiers for a wide catalogue; ibdb/dnb/douban
# are the regional/fallback providers. Keep this list and the JSON form in sync.
DEFAULT_METADATA_PROVIDER_HIERARCHY = ["google", "openlibrary", "ibdb", "dnb", "douban"]

# Compact JSON form (no spaces) so it matches the SQL schema default and the Jinja
# template fallback literally — the agreement is asserted in
# tests/unit/test_metadata_autofetch_safety.py.
DEFAULT_METADATA_PROVIDER_HIERARCHY_JSON = '["google","openlibrary","ibdb","dnb","douban"]'
