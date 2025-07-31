# -*- coding: utf-8 -*-

#  This file is part of the Calibre-Web (https://github.com/janeczku/calibre-web)
#    Copyright (C) 2018-2019 OzzieIsaacs, cervinko, jkrehm, bodybybuddha, ok11,
#                            andy29485, idalin, Kyosfonica, wuqi, Kennyl, lemmsh,
#                            falgh1, grunjol, csitko, ytils, xybydy, trasba, vrabe,
#                            ruben-herold, marblepebble, JackED42, SiphonSquirrel,
#                            apetresc, nanu-c, mutschler
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program. If not, see <http://www.gnu.org/licenses/>.

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