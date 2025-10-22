# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
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

# All fixtures are now in tests/conftest.py and automatically available
# This file is kept for potential docker-specific test configuration

