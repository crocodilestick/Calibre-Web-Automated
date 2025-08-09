# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import os

try:
    from wand.image import Image
    use_IM = True
except (ImportError, RuntimeError) as e:
    use_IM = False


NO_JPEG_EXTENSIONS = ['.png', '.webp', '.bmp']
COVER_EXTENSIONS = ['.png', '.webp', '.bmp', '.jpg', '.jpeg']


def cover_processing(tmp_file_name, img, extension):
    tmp_cover_name = os.path.join(os.path.dirname(tmp_file_name), 'cover.jpg')
    if extension in NO_JPEG_EXTENSIONS:
        if use_IM:
            with Image(blob=img) as imgc:
                imgc.format = 'jpeg'
                imgc.transform_colorspace('srgb')
                imgc.save(filename=tmp_cover_name)
                return tmp_cover_name
        else:
            return None
    if img:
        with open(tmp_cover_name, 'wb') as f:
            f.write(img)
        return tmp_cover_name
    else:
        return None
