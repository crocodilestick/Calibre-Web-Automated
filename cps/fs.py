# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

from . import logger
from .constants import CACHE_DIR
from os import makedirs, remove
from os.path import isdir, isfile, join
from shutil import rmtree


class FileSystem:
    _instance = None
    _cache_dir = CACHE_DIR

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(FileSystem, cls).__new__(cls)
            cls.log = logger.create()
        return cls._instance

    def get_cache_dir(self, cache_type=None):
        if not isdir(self._cache_dir):
            try:
                makedirs(self._cache_dir)
            except OSError:
                self.log.info(f'Failed to create path {self._cache_dir} (Permission denied).')
                raise

        path = join(self._cache_dir, cache_type)
        if cache_type and not isdir(path):
            try:
                makedirs(path)
            except OSError:
                self.log.info(f'Failed to create path {path} (Permission denied).')
                raise

        return path if cache_type else self._cache_dir

    def get_cache_file_dir(self, filename, cache_type=None):
        path = join(self.get_cache_dir(cache_type), filename[:2])
        if not isdir(path):
            try:
                makedirs(path)
            except OSError:
                self.log.info(f'Failed to create path {path} (Permission denied).')
                raise

        return path

    def get_cache_file_path(self, filename, cache_type=None):
        return join(self.get_cache_file_dir(filename, cache_type), filename) if filename else None

    def get_cache_file_exists(self, filename, cache_type=None):
        path = self.get_cache_file_path(filename, cache_type)
        return isfile(path)

    def delete_cache_dir(self, cache_type=None):
        if not cache_type and isdir(self._cache_dir):
            try:
                rmtree(self._cache_dir)
            except OSError:
                self.log.info(f'Failed to delete path {self._cache_dir} (Permission denied).')
                raise

        path = join(self._cache_dir, cache_type)
        if cache_type and isdir(path):
            try:
                rmtree(path)
            except OSError:
                self.log.info(f'Failed to delete path {path} (Permission denied).')
                raise

    def delete_cache_file(self, filename, cache_type=None):
        path = self.get_cache_file_path(filename, cache_type)
        if isfile(path):
            try:
                remove(path)
            except OSError:
                self.log.info(f'Failed to delete path {path} (Permission denied).')
                raise
