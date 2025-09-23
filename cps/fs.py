# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

from . import logger
from .constants import CACHE_DIR, CONFIG_DIR, CACHE_TYPE_THUMBNAILS
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
        # Use /config/thumbnails for thumbnail cache to persist across container rebuilds
        if cache_type == CACHE_TYPE_THUMBNAILS:
            cache_dir = join(CONFIG_DIR, 'thumbnails')
        else:
            cache_dir = self._cache_dir
            
        if not isdir(cache_dir):
            try:
                makedirs(cache_dir)
            except OSError:
                self.log.info(f'Failed to create path {cache_dir} (Permission denied).')
                raise

        path = join(cache_dir, cache_type) if cache_type and cache_type != CACHE_TYPE_THUMBNAILS else cache_dir
        if cache_type and cache_type != CACHE_TYPE_THUMBNAILS and not isdir(path):
            try:
                makedirs(path)
            except OSError:
                self.log.info(f'Failed to create path {path} (Permission denied).')
                raise

        return path if cache_type else cache_dir

    def get_cache_file_dir(self, filename, cache_type=None):
        # For thumbnails with deterministic naming, store directly in cache dir
        # instead of creating subdirectories based on first 2 characters
        if cache_type == CACHE_TYPE_THUMBNAILS:
            return self.get_cache_dir(cache_type)
        
        # For other cache types, maintain subdirectory structure
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

        # Handle special case for thumbnails stored in /config/thumbnails
        if cache_type == CACHE_TYPE_THUMBNAILS:
            path = join(CONFIG_DIR, 'thumbnails')
        else:
            path = join(self._cache_dir, cache_type)
            
        if cache_type and isdir(path):
            try:
                rmtree(path)
            except OSError:
                self.log.info(f'Failed to delete path {path} (Permission denied).')
                raise

    def delete_cache_file(self, filename, cache_type=None):
        # Skip if no filename provided (defensive guard)
        if not filename:
            return
        path = self.get_cache_file_path(filename, cache_type)
        if isfile(path):
            try:
                remove(path)
            except OSError:
                self.log.info(f'Failed to delete path {path} (Permission denied).')
                raise
