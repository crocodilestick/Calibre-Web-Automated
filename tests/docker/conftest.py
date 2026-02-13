# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""
Docker-specific pytest fixtures using testcontainers.

These fixtures spin up actual CWA Docker containers for integration
and E2E testing using the production docker-compose.yml configuration.

Note: Most Docker fixtures have been moved to tests/conftest.py to be
shared between docker/ and integration/ test directories.
"""

import pytest
import sys
from pathlib import Path

# Add parent tests directory to path
_tests_dir = Path(__file__).parent.parent
if str(_tests_dir) not in sys.path:
    sys.path.insert(0, str(_tests_dir))

# Import and re-export from parent conftest (avoids circular import)
import importlib.util
spec = importlib.util.spec_from_file_location("parent_conftest", _tests_dir / "conftest.py")
parent_conftest = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parent_conftest)

# Re-export for imports
volume_copy = parent_conftest.volume_copy
get_db_path = parent_conftest.get_db_path

# All fixtures are now in tests/conftest.py and automatically available
# This file is kept for potential docker-specific test configuration

