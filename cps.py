#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import os
import sys


# Add local path to sys.path, so we can import cps
path = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, path)

from cps.main import main


def hide_console_windows():
    import ctypes

    kernel32 = ctypes.WinDLL('kernel32')
    user32 = ctypes.WinDLL('user32')

    SW_HIDE = 0

    hWnd = kernel32.GetConsoleWindow()
    if hWnd:
        user32.ShowWindow(hWnd, SW_HIDE)


if __name__ == '__main__':
    if os.name == "nt":
        hide_console_windows()
    main()



