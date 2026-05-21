# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web-NextGen contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""File-move helpers that survive cross-ownership filesystem mounts.

Container deployments commonly bind-mount the temp upload area
(`/tmp/calibre_web`) and the library storage (`/books`) onto filesystems with
different ownership semantics — LinuxServer-style PUID/PGID containers, NFS
shares mounted with squashed root, SMB shares with mode restrictions. When
`shutil.move` falls back from `os.rename` (Errno 18 EXDEV) to `shutil.copy2`,
the `copystat` step's `os.chmod` can fail with Errno 1 EPERM (or Errno 13
EACCES on some network filesystems) even though the file data was copied
successfully. This module's :func:`copy_with_metadata_fallback` retries the
data-only :func:`shutil.copyfile` when `copy2` raises, so the upload completes
instead of surfacing a confusing permission error to the user.

Canonical report: ``janeczku/calibre-web#3437``.
"""

from __future__ import annotations

import shutil

from .. import logger

log = logger.create()


def copy_with_metadata_fallback(src: str, dst: str) -> None:
    """Copy ``src`` to ``dst``, preserving metadata when the filesystem allows.

    Tries :func:`shutil.copy2` first (data + mode + atime/mtime + xattr). If
    the copy2 metadata step raises :class:`OSError` — typically EPERM on chmod
    when ``dst`` lives on a differently-owned filesystem — falls back to
    :func:`shutil.copyfile`, which copies the bytes only. The destination then
    receives default permissions from the calling process's umask, which is
    acceptable for the upload path because the file is about to be re-processed
    by the Calibre ingest pipeline.

    Raises whatever the fallback :func:`shutil.copyfile` raises if the data
    copy itself fails (e.g., ENOSPC on dst filesystem, EACCES on dst dir).
    """
    try:
        shutil.copy2(src, dst)
    except OSError as ex:
        log.info(
            "copy2 metadata preservation failed (%s); falling back to data-only copy",
            ex,
        )
        shutil.copyfile(src, dst)
