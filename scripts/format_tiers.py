# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Format ranking shared by duplicate resolution and ingest.

Ranks come from the "Duplicate Format Priority" setting. A format CWA produced by
converting another one ranks as the format it was converted from: an EPUB made from
a MOBI is only as good as the MOBI.
"""

import json

DEFAULT_FORMAT_PRIORITY = {
    'EPUB': 100,
    'KEPUB': 95,
    'AZW3': 90,
    'MOBI': 80,
    'AZW': 75,
    'PDF': 60,
    'TXT': 40,
    'CBZ': 35,
    'CBR': 35,
    'FB2': 30,
    'DJVU': 25,
    'HTML': 20,
    'RTF': 15,
    'DOC': 10,
    'DOCX': 10,
}


def format_priority_from_settings(settings) -> dict[str, int]:
    """Parse duplicate_format_priority from CWA settings, falling back to the defaults."""
    try:
        priority = json.loads(settings.get('duplicate_format_priority') or '{}')
        if isinstance(priority, dict) and priority:
            return {str(fmt).upper(): int(rank) for fmt, rank in priority.items()}
    except (TypeError, ValueError, AttributeError):
        pass
    return dict(DEFAULT_FORMAT_PRIORITY)


def format_rank(book_format: str, priority: dict[str, int], original_format: str | None = None) -> int:
    """Rank of one format, judged by what it was converted from when it was converted."""
    return priority.get((original_format or book_format).upper(), 0)


def best_format_rank(formats, priority: dict[str, int], origins: dict[str, str] | None = None) -> int:
    """Highest rank among a book's formats. origins maps FORMAT -> ORIGINAL_FORMAT for converted ones."""
    origins = origins or {}
    ranks = [format_rank(fmt, priority, origins.get(fmt.upper())) for fmt in formats if fmt]
    return max(ranks, default=0)
