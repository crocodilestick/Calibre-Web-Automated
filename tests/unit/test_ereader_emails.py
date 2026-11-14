# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""Unit tests for optional labels on Send-to-eReader addresses (issues #486, #787)."""

import pytest

from cps.ereader_emails import (
    parse_ereader_email,
    parse_ereader_emails,
    ereader_addresses,
    bare_address,
)
from cps.helper import valid_email

pytestmark = pytest.mark.unit

IPHONE = "reader-phone@kindle.com"
PAPERWHITE = "reader-paperwhite@kindle.com"


class TestParseEreaderEmails:
    def test_plain_address(self):
        assert parse_ereader_email(IPHONE) == ("", IPHONE)

    def test_labelled_address(self):
        assert parse_ereader_email("My Paperwhite <%s>" % PAPERWHITE) == ("My Paperwhite", PAPERWHITE)

    def test_mixed_list(self):
        value = " iPhone <%s> , %s ," % (IPHONE, PAPERWHITE)
        assert parse_ereader_emails(value) == [("iPhone", IPHONE), ("", PAPERWHITE)]

    def test_empty(self):
        assert parse_ereader_emails("") == []
        assert parse_ereader_emails(None) == []

    @pytest.mark.parametrize("entry", [
        "not_an_email",
        "Label <not_an_email>",
        "Label <a@b.com> trailing",
        "<<a@b.com>>",
        "Evil <x> <a@b.com>",
        '"Quoted" <a@b.com>',
        "Two Words a@b.com",
        "Label <a@b.com",
    ])
    def test_invalid_entries(self, entry):
        with pytest.raises(ValueError):
            parse_ereader_email(entry)

    def test_bare_addresses(self):
        assert ereader_addresses("Phone <%s>,%s" % (IPHONE, PAPERWHITE)) == [IPHONE, PAPERWHITE]
        assert bare_address("Phone <%s>" % IPHONE) == IPHONE
        assert bare_address(IPHONE) == IPHONE


class TestValidEmailWithLabels:
    def test_plain_unchanged(self):
        assert valid_email("%s,%s" % (IPHONE, PAPERWHITE)) == "%s,%s" % (IPHONE, PAPERWHITE)

    def test_labels_preserved_and_normalized(self):
        value = "  My iPhone   <%s>  ,%s " % (IPHONE, PAPERWHITE)
        assert valid_email(value) == "My iPhone <%s>,%s" % (IPHONE, PAPERWHITE)

    def test_label_with_bad_address_rejected(self):
        with pytest.raises(Exception, match="Invalid Email address format"):
            valid_email("Phone <nope>")

    def test_angle_bracket_abuse_rejected(self):
        with pytest.raises(Exception, match="Invalid Email address format"):
            valid_email("A <b> <%s>" % IPHONE)
