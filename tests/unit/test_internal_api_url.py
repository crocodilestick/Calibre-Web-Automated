# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import os
from unittest import mock
from cps import helper, config

def test_get_internal_api_url_http():
    with mock.patch.dict(os.environ, {'CWA_PORT_OVERRIDE': '8083'}):
        with mock.patch.object(config, 'get_config_certfile', return_value=None):
            with mock.patch.object(config, 'get_config_keyfile', return_value=None):
                url = helper.get_internal_api_url("/test")
                assert url == "http://127.0.0.1:8083/test"

def test_get_internal_api_url_https():
    with mock.patch.dict(os.environ, {'CWA_PORT_OVERRIDE': '8083'}):
        with mock.patch.object(config, 'get_config_certfile', return_value="/path/to/cert"):
            with mock.patch.object(config, 'get_config_keyfile', return_value="/path/to/key"):
                with mock.patch('os.path.isfile', return_value=True):
                    url = helper.get_internal_api_url("/test")
                    assert url == "https://127.0.0.1:8083/test"

def test_get_internal_api_url_custom_port():
    with mock.patch.dict(os.environ, {'CWA_PORT_OVERRIDE': '9090'}):
        with mock.patch.object(config, 'get_config_certfile', return_value=None):
            with mock.patch.object(config, 'get_config_keyfile', return_value=None):
                url = helper.get_internal_api_url("/test")
                assert url == "http://127.0.0.1:9090/test"

def test_get_internal_api_url_missing_slash():
    with mock.patch.dict(os.environ, {'CWA_PORT_OVERRIDE': '8083'}):
        with mock.patch.object(config, 'get_config_certfile', return_value=None):
            with mock.patch.object(config, 'get_config_keyfile', return_value=None):
                url = helper.get_internal_api_url("test")
                assert url == "http://127.0.0.1:8083/test"
