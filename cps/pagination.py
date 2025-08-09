# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

from math import ceil


# simple pagination for the feed
class Pagination(object):
    def __init__(self, page, per_page, total_count):
        self.page = int(page)
        self.per_page = int(per_page)
        self.total_count = int(total_count)

    @property
    def next_offset(self):
        return int(self.page * self.per_page)

    @property
    def previous_offset(self):
        return int((self.page - 2) * self.per_page)

    @property
    def last_offset(self):
        last = int(self.total_count) - int(self.per_page)
        if last < 0:
            last = 0
        return int(last)

    @property
    def pages(self):
        return int(ceil(self.total_count / float(self.per_page)))

    @property
    def has_prev(self):
        return self.page > 1

    @property
    def has_next(self):
        return self.page < self.pages

    # Only show: first page, last page, current page, page before and after current page (if valid)
    def iter_pages(self):
        pages = self.pages
        current = self.page
        shown = set()
        
        # Always show first page
        yield 1
        shown.add(1)
        
        # Show ellipsis if needed before previous page
        if current - 1 > 2:
            yield None
        
        # Show previous page if it's not first or last
        if current - 1 > 1 and current - 1 < pages:
            yield current - 1
            shown.add(current - 1)
        
        # Show current page if it's not first or last
        if current != 1 and current != pages:
            yield current
            shown.add(current)
        
        # Show next page if it's not first or last
        if current + 1 < pages:
            yield current + 1
            shown.add(current + 1)
        
        # Show ellipsis if needed after next page
        if current + 1 < pages - 1:
            yield None
        
        # Always show last page if more than one page
        if pages > 1:
            yield pages