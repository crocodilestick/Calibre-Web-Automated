# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Auto metadata fetch checks provider results against the book file itself.

Every EPUB here is synthetic. Titles, author names and ISBNs are bibliographic
facts from real ingests (see test_metadata_wrong_book_cases.py); every sentence
of body text is filler from a fixed word list, so the files only match the
originals in structure and length.

The shapes are the wrong records auto fetch applied on a real library, plus the
cases the title/author gate alone gets wrong:

- a summary record that names the original author and the original title
- a wrong same-title record ranked first, which hid the right one
- the next volume in a series ("Night Shift 3" for "Night Shift 2")
- an ISBN in the file's own metadata that the book's copyright page contradicts
- an import titled with its ISBN, which the gate can never match
- tags and description that came with a wrong record
"""

import html
import zipfile
from types import SimpleNamespace as NS

import pytest

import cps.book_evidence as be
import cps.metadata_helper as m
import cps.metadata_match as mm

pytestmark = pytest.mark.unit


# --- synthetic EPUBs -----------------------------------------------------------

_FILLER = ("the river ran past the old mill and the wind moved through tall grass while she waited by the "
           "door for news that never came so he walked on toward the town with a map in his hand and a "
           "question he could not ask anyone there").split()


def _filler(n_words, seed=0):
    out, i = [], seed
    while len(out) < n_words:
        out.append(_FILLER[i % len(_FILLER)])
        i += 7
    return " ".join(out)


def _title_page(title, author, subtitle="", extra=""):
    sub = "<h2>%s</h2>" % html.escape(subtitle) if subtitle else ""
    return ("Title Page", "<h1>%s</h1>%s<p>%s</p>%s" % (html.escape(title), sub, html.escape(author), extra))


def _copyright_page(title, author, isbns=(), publisher="Example House"):
    lines = ["<p>%s</p>" % html.escape(title), "<p>Copyright © 2016 by %s</p>" % html.escape(author),
             "<p>All rights reserved.</p>", "<p>Published by %s</p>" % html.escape(publisher)]
    lines += ["<p>%s %s</p>" % (html.escape(label), num) for label, num in isbns]
    lines.append("<p>15 16 17 18 19 10 9 8 7 6 5 4 3 2 1</p>")
    return ("Copyright", "\n".join(lines))


def _chapters(n_words, n=10):
    per = max(1, n_words // n)
    return [("Chapter %d" % (i + 1), "<h2>Chapter %d</h2><p>%s</p>" % (i + 1, _filler(per, i))) for i in range(n)]


def _write_epub(path, title, creators, docs, isbns=(), entity=False, doc_title=None, encrypt=False):
    ids = "".join('<dc:identifier opf:scheme="ISBN">%s</dc:identifier>' % i for i in isbns)
    cr = "".join('<dc:creator opf:role="aut">%s</dc:creator>' % html.escape(c) for c in creators)
    items = "".join('<item id="d%d" href="text/d%d.xhtml" media-type="application/xhtml+xml"/>' % (k, k)
                    for k in range(len(docs)))
    refs = "".join('<itemref idref="d%d"/>' % k for k in range(len(docs)))
    dtd = '<!DOCTYPE package [<!ENTITY x "boom">]>' if entity else ""
    opf = ('<?xml version="1.0" encoding="utf-8"?>%s<package xmlns="http://www.idpf.org/2007/opf" version="2.0">'
           '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:opf="http://www.idpf.org/2007/opf">'
           '<dc:title>%s</dc:title>%s<dc:language>en</dc:language>%s</metadata>'
           '<manifest>%s</manifest><spine>%s</spine></package>') % (dtd, html.escape(title), cr, ids, items, refs)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml",
                   '<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                   '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
                   '</rootfiles></container>')
        z.writestr("OEBPS/content.opf", opf)
        for k, (_, body) in enumerate(docs):
            z.writestr("OEBPS/text/d%d.xhtml" % k,
                       '<?xml version="1.0" encoding="utf-8"?><html xmlns="http://www.w3.org/1999/xhtml">'
                       '<head><title>%s</title></head><body>%s</body></html>'
                       % (html.escape(title if doc_title is None else doc_title), body))
        if encrypt:
            # What Adobe DRM leaves: the chapters listed as encrypted, their bytes ciphertext.
            refs = "".join('<EncryptedData><CipherData><CipherReference URI="OEBPS/text/d%d.xhtml"/></CipherData>'
                           '</EncryptedData>' % k for k in range(len(docs)))
            z.writestr("META-INF/encryption.xml", '<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                       '%s</encryption>' % refs)
    return str(path)


def _book_file(path, title, author, words=70000, isbns_printed=(), opf_title=None, opf_creators=None, opf_isbns=(),
               subtitle="", copyright_at_back=False, front_extra=(), back_extra=(), title_page_extra=""):
    """A normal book: title page, copyright page (front or back), chapters of filler."""
    tp = _title_page(title, author, subtitle, title_page_extra)
    cp = _copyright_page(title + (": " + subtitle if subtitle else ""), author, isbns_printed)
    docs = ([tp] + list(front_extra) + ([] if copyright_at_back else [cp]) + _chapters(words) + list(back_extra)
            + ([cp] if copyright_at_back else []))
    return _write_epub(path, opf_title if opf_title is not None else title,
                       opf_creators if opf_creators is not None else [author], docs, opf_isbns)


def _evidence(path):
    return be.extract(path)


def _rec(title, authors, isbn=None, publisher=None, description="", tags=()):
    """A provider search result (MetaRecord-shaped)."""
    ids = {"isbn": isbn} if isbn else {}
    return NS(title=title, authors=list(authors), identifiers=ids, publisher=publisher, description=description,
              tags=list(tags), series=None, series_index=0, publishedDate=None, rating=0, cover=None,
              source=NS(id="test"))


def _pick(ev, results, book_title, book_authors, book_isbn=None):
    return m._select_with_book_evidence(results, ev, book_isbn, book_title=book_title, book_authors=book_authors)


# --- wrong records seen on a real ingest ---------------------------------------

class TestWrongRecordsFromARealIngest:
    def test_unofficial_summary_record(self, tmp_path):
        ev = _evidence(_book_file(tmp_path / "b.epub", "Outgrowing God", "Richard Dawkins", words=72569,
                                  isbns_printed=[("ISBN", "978-1-4735-6211-6")]))
        summary = _rec("SUMMARY: Outgrowing God (UNOFFICIAL SUMMARY: Lesson, Key Takeaways and Analysis)",
                       ["Powerful Insights"], "9798774364879")
        real = _rec("Outgrowing God", ["Richard Dawkins"], "9781473562116")
        assert _pick(ev, [summary], "Outgrowing God", ["Richard Dawkins"]) is None
        assert _pick(ev, [summary, real], "Outgrowing God", ["Richard Dawkins"]) is real

    def test_summary_of_record(self, tmp_path):
        ev = _evidence(_book_file(tmp_path / "b.epub", "Flights of Fancy", "Richard Dawkins", words=48514))
        summary = _rec("Summary of Richard Dawkins's Flights of Fancy", ["Irb Media"], "9798822532809")
        assert _pick(ev, [summary], "Flights of Fancy", ["Richard Dawkins"]) is None

    def test_beginners_guide_with_the_same_title_prefix(self, tmp_path):
        ev = _evidence(_book_file(tmp_path / "b.epub", "Outgrowing God", "Richard Dawkins", words=67827))
        guide = _rec("Outgrowing God? A Beginner's Guide to Richard Dawkins and the God Debate", ["Peter S. Williams"])
        assert _pick(ev, [guide], "Outgrowing God", ["Richard Dawkins"]) is None

    def test_books_llc_compilation(self, tmp_path):
        ev = _evidence(_book_file(tmp_path / "b.epub", "The Ancestor's Tale", "Richard Dawkins", words=305051,
                                  subtitle="A Pilgrimage to the Dawn of Evolution"))
        compilation = _rec("Books By Richard Dawkins: The Selfish Gene, The God Delusion, The Blind Watchmaker",
                           ["Books LLC"])
        assert _pick(ev, [compilation], "The Ancestor's Tale", ["Richard Dawkins"]) is None

    def test_readtrepreneur_summary(self, tmp_path):
        ev = _evidence(_book_file(tmp_path / "b.epub", "The Selfish Gene", "Richard Dawkins", words=169869,
                                  subtitle="40th Anniversary Edition"))
        summary = _rec("Summary of The Selfish Gene 40th Anniversary Edition", ["Readtrepreneur Publishing"],
                       description="Disclaimer: This is NOT the original book.")
        assert _pick(ev, [summary], "The Selfish Gene", ["Richard Dawkins"]) is None

    def test_comic_authors_on_a_prose_novel(self, tmp_path):
        ev = _evidence(_book_file(tmp_path / "b.epub", "Cross Down", "James Patterson", words=92842,
                                  opf_title="Alex Cross 32: Cross Down"))
        hulk = _rec("Cross Down", ["Al Ewing", "Alex Ross", "Joe Bennett"])
        assert _pick(ev, [hulk], "Alex Cross 32: Cross Down", ["James Patterson"]) is None

    def test_two_book_bundle(self, tmp_path):
        ev = _evidence(_book_file(tmp_path / "b.epub", "Start With Why", "Simon Sinek", words=77000))
        bundle = _rec("Start With Why By Simon Sinek ,The $100 Startup By Chris Guillebeau 2 Books Collection Set",
                      ["Simon Sinek", "Chris Guillebeau"])
        assert _pick(ev, [bundle], "Start With Why", ["Simon Sinek"]) is None


# --- what the title/author gate alone lets through ------------------------------

class TestGapsInTheTitleAuthorGate:
    def test_summary_record_naming_the_original_title_and_author(self, tmp_path):
        """Title and author both match the book, so the gate applies it. The
        publisher is a summary mill."""
        ev = _evidence(_book_file(tmp_path / "b.epub", "Outgrowing God", "Richard Dawkins", words=72000))
        mill = _rec("Outgrowing God", ["Richard Dawkins"], publisher="Readtrepreneur Publishing")
        assert m._select_metadata_result([mill], None, book_title="Outgrowing God",
                                         book_authors=["Richard Dawkins"]) is mill
        assert _pick(ev, [mill], "Outgrowing God", ["Richard Dawkins"]) is None

    def test_study_guide_in_brackets(self, tmp_path):
        """The gate drops bracketed asides, so this is 'Outgrowing God' to it."""
        ev = _evidence(_book_file(tmp_path / "b.epub", "Outgrowing God", "Richard Dawkins", words=72000))
        guide = _rec("Outgrowing God (Study Guide)", ["Richard Dawkins"])
        assert m._select_metadata_result([guide], None, book_title="Outgrowing God",
                                         book_authors=["Richard Dawkins"]) is guide
        assert _pick(ev, [guide], "Outgrowing God", ["Richard Dawkins"]) is None

    def test_one_word_author_proves_nothing(self, tmp_path):
        ev = _evidence(_book_file(tmp_path / "b.epub", "Outgrowing God", "Richard Dawkins", words=72000))
        assert _pick(ev, [_rec("Outgrowing God", ["Richard"])], "Outgrowing God", ["Richard Dawkins"]) is None

    def test_summary_record_known_only_by_its_disclaimer(self, tmp_path):
        ev = _evidence(_book_file(tmp_path / "b.epub", "Outgrowing God", "Richard Dawkins", words=72000))
        mill = _rec("Outgrowing God", ["Richard Dawkins"], publisher="Some New Press",
                    description="Disclaimer: This is an unofficial summary and not the original book.")
        assert _pick(ev, [mill], "Outgrowing God", ["Richard Dawkins"]) is None

    def test_wrong_same_title_record_first_no_longer_hides_the_right_one(self, tmp_path):
        ev = _evidence(_book_file(tmp_path / "b.epub", "The Secret", "Lee Child", words=81000))
        wrong = _rec("The Secret", ["Ann Writer"])
        right = _rec("The Secret", ["Lee Child"])
        assert m._select_metadata_result([wrong, right], None, book_title="The Secret",
                                         book_authors=["Lee Child"]) is None
        assert _pick(ev, [wrong, right], "The Secret", ["Lee Child"]) is right

    def test_different_author_sharing_a_given_name(self, tmp_path):
        """The gate counts any shared name word, so Lee Tobin McClain passes for
        Lee Child. A real ingest got this one."""
        ev = _evidence(_book_file(tmp_path / "b.epub", "The Secret", "Lee Child", words=81000))
        wrong = _rec("The Secret", ["Lee Tobin McClain"])
        right = _rec("The Secret", ["Lee Child"])
        assert m._select_metadata_result([wrong, right], None, book_title="The Secret",
                                         book_authors=["Lee Child"]) is wrong
        assert _pick(ev, [wrong], "The Secret", ["Lee Child"]) is None
        assert _pick(ev, [wrong, right], "The Secret", ["Lee Child"]) is right

    def test_next_volume_in_a_series(self, tmp_path):
        """'Night Shift 2' vs 'Night Shift 3' is 0.92 similar as text. #1589's volume-number
        check now rejects it on its own; the in-book check still agrees."""
        tp = ("Title", "<h1>Night Shift 2</h1><p>Ann Writer</p><p>Also by Ann Writer: Night Shift 3</p>")
        ev = _evidence(_write_epub(tmp_path / "b.epub", "Night Shift 2", ["Ann Writer"], [tp] + _chapters(60000)))
        next_one = _rec("Night Shift 3", ["Ann Writer"])
        assert m._select_metadata_result([next_one], None, book_title="Night Shift 2",
                                         book_authors=["Ann Writer"]) is None
        assert _pick(ev, [next_one], "Night Shift 2", ["Ann Writer"]) is None
        right = _rec("Night Shift 2", ["Ann Writer"])
        assert _pick(ev, [next_one, right], "Night Shift 2", ["Ann Writer"]) is right

    def test_isbn_from_the_files_metadata_that_the_book_contradicts(self, tmp_path):
        """The OPF carries an ISBN the copyright page doesn't print. The gate
        takes any result with that ISBN, whatever its title."""
        ev = _evidence(_book_file(tmp_path / "b.epub", "The Ancestor's Tale", "Richard Dawkins", words=305051,
                                  isbns_printed=[("ISBN", "978-0-544-85993-7"), ("e-ISBN", "978-0-547-52512-9")],
                                  opf_isbns=["9781474600576"],
                                  title_page_extra="<p>Also by Richard Dawkins: The Selfish Gene</p>"))
        other = _rec("The Selfish Gene", ["Richard Dawkins"], "9781474600576")
        assert m._select_metadata_result([other], "9781474600576", book_title="The Ancestor's Tale",
                                         book_authors=["Richard Dawkins"]) is other
        assert _pick(ev, [other], "The Ancestor's Tale", ["Richard Dawkins"], "9781474600576") is None

    def test_isbn_the_book_prints_still_picks_the_edition(self, tmp_path):
        ev = _evidence(_book_file(tmp_path / "b.epub", "The Selfish Gene", "Richard Dawkins", words=169869,
                                  subtitle="40th Anniversary Edition", isbns_printed=[("ISBN", "978-0-19-878860-7")]))
        edition = _rec("The Selfish Gene", ["Richard Dawkins"], "9780198788607")
        assert _pick(ev, [edition], "The Selfish Gene: 40th Anniversary Edition", ["Richard Dawkins"],
                     "9780198788607") is edition

    def test_subtitle_mismatch_resolved_by_a_printed_isbn(self, tmp_path):
        """The gate rejects 'The Selfish Gene' for 'The Selfish Gene: 40th
        Anniversary Edition'. The book printing the result's ISBN settles it."""
        ev = _evidence(_book_file(tmp_path / "b.epub", "The Selfish Gene", "Richard Dawkins", words=169869,
                                  subtitle="40th Anniversary Edition", isbns_printed=[("ISBN", "978-0-19-878860-7")]))
        edition = _rec("The Selfish Gene", ["Richard Dawkins"], "9780198788607")
        assert m._select_metadata_result([edition], None, book_title="The Selfish Gene: 40th Anniversary Edition",
                                         book_authors=["Richard Dawkins"]) is None
        assert _pick(ev, [edition], "The Selfish Gene: 40th Anniversary Edition", ["Richard Dawkins"]) is edition

    def test_isbn_title_import_takes_the_record_the_book_proves(self, tmp_path):
        """An import titled '0062288431 (N)'. Its copyright page is at the back."""
        tp = _title_page("Brief Candle in the Dark", "Richard Dawkins", "My Life in Science")
        cp = _copyright_page("Brief Candle in the Dark", "Richard Dawkins", [("FIRST US EDITION ISBN", "978-0-06-228843-1")])
        ev = _evidence(_write_epub(tmp_path / "b.epub", "0062288431 (N)", ["Richard Dawkins"],
                                   [tp] + _chapters(147000) + [cp]))
        right = _rec("Brief Candle in the Dark", ["Richard Dawkins"], "9780062288431")
        assert m._select_metadata_result([right], None, book_title="0062288431 (N)",
                                         book_authors=["Richard Dawkins"]) is None
        assert _pick(ev, [right], "0062288431 (N)", ["Richard Dawkins"]) is right
        # The ISBN alone is not enough: the title it comes with must be printed too.
        other = _rec("An Appetite for Wonder", ["Richard Dawkins"], "9780062288431")
        assert _pick(ev, [other], "0062288431 (N)", ["Richard Dawkins"]) is None


# --- what still isn't applied -----------------------------------------------------

class TestNothingAppliedWhenTheBookDoesNotBackIt:
    def test_junk_file_metadata_without_a_printed_isbn(self, tmp_path):
        """The file says 'ladyfire34'. The book prints the title and author, but
        with no ISBN to prove it the gate against the record still applies."""
        ev = _evidence(_book_file(tmp_path / "b.epub", "The Big Bad Wolf", "James Patterson", words=90000,
                                  opf_title="James Patterson - Alex Cross 09 - The Big Bad Wolf",
                                  opf_creators=["ladyfire34"]))
        right = _rec("The Big Bad Wolf", ["James Patterson"])
        assert _pick(ev, [right], "James Patterson - Alex Cross 09 - The Big Bad Wolf", ["ladyfire34"]) is None

    def test_another_book_in_the_also_by_list(self, tmp_path):
        ev = _evidence(_book_file(tmp_path / "b.epub", "Jack and Jill", "James Patterson", words=90000,
                                  title_page_extra="<p>Also by James Patterson: Kiss the Girls</p>"))
        other = _rec("Kiss the Girls", ["James Patterson"])
        assert _pick(ev, [other], "Jack and Jill", ["James Patterson"]) is None

    def test_coauthor_alone_is_not_the_books_author(self, tmp_path):
        ev = _evidence(_book_file(tmp_path / "b.epub", "The Ancestor's Tale", "Richard Dawkins with Yan Wong",
                                  words=305051))
        only_wong = _rec("The Ancestor's Tale", ["Yan Wong"])
        assert _pick(ev, [only_wong], "The Ancestor's Tale", ["Richard Dawkins"]) is None

    def test_isbn_in_a_back_matter_ad_proves_nothing(self, tmp_path):
        """Six pages of ads at the back, each with an ISBN. The last one is
        further than any copyright page and must not prove a record."""
        ads = [("Ad %d" % i, "<p>Coming soon from Ann Writer</p><p>ISBN %s</p>" % isbn) for i, isbn in enumerate(
            ["978-0-306-40615-7", "978-1-56619-909-4", "978-1-4028-9462-6", "978-0-596-52068-7", "978-0-13-110362-7"])]
        ev = _evidence(_book_file(tmp_path / "b.epub", "Real Book", "Ann Writer", words=60000,
                                  isbns_printed=[("ISBN", "978-1-4735-6211-6")], back_extra=ads,
                                  title_page_extra="<p>Also by Ann Writer: Other Book</p>"))
        assert any(i.get("where") == "body" for i in ev["isbns_in_text"])
        body_isbn = [i["isbn"] for i in ev["isbns_in_text"] if i.get("where") == "body"][0]
        other = _rec("Other Book", ["Ann Writer"], body_isbn)
        assert _pick(ev, [other], "Real Book", ["Ann Writer"]) is None
        sequel = _rec("Real Book: The Sequel", ["Ann Writer"], body_isbn)
        assert _pick(ev, [sequel], "Real Book", ["Ann Writer"]) is None

    def test_title_not_printed_in_the_book(self, tmp_path):
        docs = [("Copyright", "<p>Copyright © 2012 by Ann Writer. All rights reserved.</p>")] + _chapters(80000)
        ev = _evidence(_write_epub(tmp_path / "b.epub", "Some Novel", ["Ann Writer"], docs, doc_title=""))
        assert _pick(ev, [_rec("Some Novel", ["Ann Writer"])], "Some Novel", ["Ann Writer"]) is None

    def test_author_printed_only_by_surname(self, tmp_path):
        tp = ("Title", "<h1>The Secret Christmas Child</h1><p>a novel</p>")
        ev = _evidence(_write_epub(tmp_path / "b.epub", "The Secret Christmas Child", ["Lee Child"],
                                   [tp] + _chapters(80000)))
        assert _pick(ev, [_rec("The Secret Christmas Child", ["Lee Child"])], "The Secret Christmas Child",
                     ["Lee Child"]) is None

    def test_two_different_works_backed_equally(self, tmp_path):
        tp = ("Title", "<h1>The Secret</h1><p>Lee Child</p><p>The Secret Garden</p>")
        ev = _evidence(_write_epub(tmp_path / "b.epub", "The Secret", ["Lee Child"], [tp] + _chapters(50000)))
        a = _rec("The Secret", ["Lee Child"])
        b = _rec("The Secret", ["Lee Child", "Ann Writer"])
        assert _pick(ev, [a, b], "The Secret", ["Lee Child"]) is a          # same work: fine
        c = _rec("The Secret", ["Ann Child"])
        tp2 = ("Title", "<h1>The Secret</h1><p>Lee Child</p><p>Ann Child</p>")
        ev2 = _evidence(_write_epub(tmp_path / "c.epub", "The Secret", ["Lee Child"], [tp2] + _chapters(50000)))
        assert _pick(ev2, [a, c], "The Secret", ["Child"]) is None           # two people, nothing to choose by

    def test_two_people_with_the_same_given_name_and_title(self, tmp_path):
        tp = ("Title", "<h1>The Secret</h1><p>Lee Child</p><p>with a story by Lee Tobin McClain</p>")
        ev = _evidence(_write_epub(tmp_path / "b.epub", "The Secret", ["Lee Child"], [tp] + _chapters(50000)))
        mcclain = _rec("The Secret", ["Lee Tobin McClain"])
        child = _rec("The Secret", ["Lee Child"])
        assert _pick(ev, [mcclain, child], "The Secret", ["Lee Child"]) is None

    def test_the_file_is_itself_a_summary(self, tmp_path):
        ev = _evidence(_book_file(tmp_path / "b.epub", "Summary of Outgrowing God", "Quick Reads", words=4000,
                                  front_extra=[("Disclaimer", "<p>This is an unofficial summary and not the original book.</p>")]))
        assert ev["summary_file"]
        assert _pick(ev, [_rec("Summary of Outgrowing God", ["Quick Reads"])], "Summary of Outgrowing God",
                     ["Quick Reads"]) is None


class TestFoundOnARealLibrary:
    """Real books the first version of this check rejected."""

    def test_author_printed_surname_first(self, tmp_path):
        tp = ("Title", "<h1>The Magician's Nephew</h1><p>by Lewis, C. S.</p>")
        ev = _evidence(_write_epub(tmp_path / "b.epub", "The Magician's Nephew", ["C. S. Lewis"], [tp] + _chapters(42000)))
        right = _rec("The Magician's Nephew", ["C. S. Lewis"])
        assert _pick(ev, [right], "The Magician's Nephew", ["C. S. Lewis"]) is right

    def test_censored_title_matches_the_uncensored_page(self, tmp_path):
        tp = _title_page("The Subtle Art of Not Giving a Fuck", "Mark Manson")
        ev = _evidence(_write_epub(tmp_path / "b.epub", "The Subtle Art of Not Giving a F*ck", ["Mark Manson"],
                                   [tp] + _chapters(54000), doc_title=""))
        right = _rec("The Subtle Art of Not Giving a F*ck", ["Mark Manson"])
        assert _pick(ev, [right], "The Subtle Art of Not Giving a F*ck", ["Mark Manson"]) is right
        other = _rec("The Subtle Art of Not Giving a D*mn", ["Mark Manson"])
        assert _pick(ev, [other], "The Subtle Art of Not Giving a D*mn", ["Mark Manson"]) is None
        across_words = _rec("The Subtle Art of N*ck", ["Mark Manson"])     # a star never spans words
        assert mm.title_support(across_words.title, ev) < 0.9

    def test_image_title_page_backed_by_the_pages_own_title(self, tmp_path):
        """No title in the text, only in the <title> of every page."""
        cp = ("Copyright", "<p>Copyright © 2019 by James Patterson. All rights reserved.</p>")
        docs = [("Cover", '<img src="cover.jpg"/>'), cp] + _chapters(79000)
        ev = _evidence(_write_epub(tmp_path / "b.epub", "Criss Cross", ["James Patterson"], docs))
        right = _rec("Criss Cross", ["James Patterson"])
        assert _pick(ev, [right], "Criss Cross", ["James Patterson"]) is right
        other = _rec("Cross Kill", ["James Patterson"])
        assert _pick(ev, [other], "Cross Kill", ["James Patterson"]) is None

    def test_temp_path_page_title_backs_nothing_and_vetoes_nothing(self, tmp_path):
        tp = _title_page("Fitness After 40", "Vonda Wright", "How to Stay Strong at Any Age")
        cp = _copyright_page("Fitness After 40", "Vonda Wright")
        ev = _evidence(_write_epub(tmp_path / "b.epub", "Fitness After 40", ["Vonda Wright"], [tp, cp] + _chapters(70000),
                                   doc_title="/cwa-book-ingest/new_1_20260823_060533_5"))
        right = _rec("Fitness After 40", ["Vonda Wright"])
        assert _pick(ev, [right], "Fitness After 40", ["Vonda Wright"]) is right

    def test_box_set_that_prints_the_first_books_isbn(self, tmp_path):
        tp = _title_page("The Advocate", "Teresa Burrell")
        cp = _copyright_page("The Advocate", "Teresa Burrell", [("ISBN", "978-1-938680-03-8")])
        ev = _evidence(_write_epub(tmp_path / "b.epub", "The Advocate Series: Box Set", ["Teresa Burrell"],
                                   [tp, cp] + _chapters(300000)))
        first = _rec("The Advocate", ["Teresa Burrell"], "9781938680038")
        assert _pick(ev, [first], "The Advocate Series: Box Set", ["Teresa Burrell"]) is None
        boxed = _rec("The Advocate Series: Box Set", ["Teresa Burrell"])
        tp2 = _title_page("The Advocate Series: Box Set", "Teresa Burrell")
        ev2 = _evidence(_write_epub(tmp_path / "c.epub", "The Advocate Series: Box Set", ["Teresa Burrell"],
                                    [tp2, tp, cp] + _chapters(300000)))
        assert _pick(ev2, [first, boxed], "The Advocate Series: Box Set", ["Teresa Burrell"]) is boxed

    def test_box_set_marker_in_brackets(self, tmp_path):
        """Brackets are dropped before titles are compared, so only the marker
        itself tells the box set from book 1."""
        tp = _title_page("The Advocate", "Teresa Burrell")
        cp = _copyright_page("The Advocate", "Teresa Burrell", [("ISBN", "978-1-938680-03-8")])
        ev = _evidence(_write_epub(tmp_path / "b.epub", "The Advocate (Books 1-3 Box Set)", ["Teresa Burrell"],
                                   [tp, cp] + _chapters(300000)))
        first = _rec("The Advocate", ["Teresa Burrell"], "9781938680038")
        assert m._select_metadata_result([first], None, book_title="The Advocate (Books 1-3 Box Set)",
                                         book_authors=["Teresa Burrell"]) is first
        assert _pick(ev, [first], "The Advocate (Books 1-3 Box Set)", ["Teresa Burrell"]) is None

    def test_printed_isbn_does_not_let_a_shorter_title_in(self, tmp_path):
        """A provider record titled 'Kill' with the ISBN of 'Kill Alex Cross'."""
        ev = _evidence(_book_file(tmp_path / "b.epub", "Kill Alex Cross", "James Patterson", words=90000,
                                  isbns_printed=[("ISBN", "978-1-84605-764-9")]))
        truncated = _rec("Kill", ["James Patterson"], "9781846057649")
        assert _pick(ev, [truncated], "Kill Alex Cross", ["James Patterson"]) is None
        right = _rec("Kill Alex Cross", ["James Patterson"], "9781846057649")
        assert _pick(ev, [truncated, right], "Kill Alex Cross", ["James Patterson"]) is right

    def test_swapped_title_and_author_with_a_printed_isbn(self, tmp_path):
        ev = _evidence(_book_file(tmp_path / "b.epub", "Die Trying", "Lee Child", words=137000, opf_title="Lee Child",
                                  opf_creators=["Die Trying (txt)"], isbns_printed=[("ISBN", "978-0-593-04144-4")]))
        right = _rec("Die Trying", ["Lee Child"], "9780593041444")
        assert _pick(ev, [right], "Lee Child", ["Die Trying (txt)"]) is right
        assert _pick(ev, [_rec("Die Trying", ["Lee Child"])], "Lee Child", ["Die Trying (txt)"]) is None

    def test_drm_encrypted_epub_applies_nothing(self, monkeypatch, tmp_path):
        epub = _write_epub(tmp_path / "b.epub", "The 22-Day Revolution", ["Marco Borges"],
                           [_title_page("The 22-Day Revolution", "Marco Borges")] + _chapters(6000), encrypt=True)
        ev = _evidence(epub)
        assert ev["status"] == "drm" and ev["drm"]["encrypted"] > 0
        provider = _Provider("google", [_rec("The 22-Day Revolution", ["Marco Borges"], tags=["Diet"])])
        applied, book, _ = _ingest(monkeypatch, tmp_path, title="The 22-Day Revolution", authors=["Marco Borges"],
                                   epub=epub, providers=[provider])
        assert not applied and list(book.tags) == []

    def test_drm_names_the_scheme_and_logs_a_warning(self, monkeypatch, tmp_path, caplog):
        epub = _write_epub(tmp_path / "b.epub", "The 22-Day Revolution", ["Marco Borges"],
                           [_title_page("The 22-Day Revolution", "Marco Borges")] + _chapters(6000), encrypt=True)
        with zipfile.ZipFile(epub, "a") as z:
            z.writestr("META-INF/rights.xml", "<rights/>")
        assert _evidence(epub)["drm"]["scheme"] == "adobe-adept"
        warned = []
        monkeypatch.setattr(m.log, "warning", lambda msg, *a, **k: warned.append(str(msg)))
        provider = _Provider("google", [_rec("The 22-Day Revolution", ["Marco Borges"])])
        applied, _, _ = _ingest(monkeypatch, tmp_path, title="The 22-Day Revolution", authors=["Marco Borges"],
                                epub=epub, providers=[provider])
        assert not applied
        assert any("DRM-protected" in w and "adobe-adept" in w for w in warned), warned

    def test_obfuscated_fonts_are_not_drm(self, tmp_path):
        epub = _write_epub(tmp_path / "b.epub", "Real Book", ["Ann Writer"],
                           [_title_page("Real Book", "Ann Writer")] + _chapters(6000))
        with zipfile.ZipFile(epub, "a") as z:
            z.writestr("META-INF/encryption.xml", '<encryption><EncryptedData><CipherData>'
                       '<CipherReference URI="OEBPS/fonts/a.otf"/></CipherData></EncryptedData></encryption>')
        assert _evidence(epub)["status"] == "ok"


class TestRealBooksStillMatch:
    @pytest.mark.parametrize("phrase", ["This is my personal summary of the evidence.",
                                        "See the workbooks at the back.", "A companion to the earlier volume.",
                                        "The author is not affiliated with the publisher of the games described."])
    def test_summary_words_inside_a_real_book(self, tmp_path, phrase):
        ev = _evidence(_book_file(tmp_path / "b.epub", "Real Book", "Ann Writer", words=60000,
                                  front_extra=[("Preface", "<p>%s</p>" % phrase)]))
        right = _rec("Real Book", ["Ann Writer"])
        assert _pick(ev, [right], "Real Book", ["Ann Writer"]) is right

    def test_print_isbn_result_for_a_book_that_prints_its_ebook_isbn(self, tmp_path):
        ev = _evidence(_book_file(tmp_path / "b.epub", "Some Novel", "Ann Writer", words=80000,
                                  isbns_printed=[("eBook ISBN", "978-1-101-21198-4")]))
        print_ed = _rec("Some Novel", ["Ann Writer"], "9780451418449")
        assert _pick(ev, [print_ed], "Some Novel", ["Ann Writer"]) is print_ed

    def test_the_result_the_book_prints_the_isbn_of_ranks_first(self, tmp_path):
        ev = _evidence(_book_file(tmp_path / "b.epub", "Some Novel", "Ann Writer", words=80000,
                                  isbns_printed=[("eBook ISBN", "978-1-101-21198-4")]))
        plain = _rec("Some Novel", ["Ann Writer"])
        printed = _rec("Some Novel", ["Ann Writer"], "9781101211984")
        assert _pick(ev, [plain, printed], "Some Novel", ["Ann Writer"]) is printed

    def test_short_recipe_book(self, tmp_path):
        ev = _evidence(_book_file(tmp_path / "b.epub", "The 22-Day Revolution", "Marco Borges", words=6460))
        right = _rec("The 22-Day Revolution", ["Marco Borges"])
        assert _pick(ev, [right], "The 22-Day Revolution", ["Marco Borges"]) is right


# --- the EPUB reader's own rules ---------------------------------------------------

class TestPrintedIsbns:
    def test_printers_key_line_is_not_an_isbn(self):
        assert be.find_labelled_isbns("15 16 17 18 19 10 9 8 7 6 5 4 3 2 1") == []
        assert be.find_labelled_isbns("ISBN 9 7 8 0 0 6 2 2 8 8 4 3 1") == []
        assert be.find_labelled_isbns("ISBN\n0 0 6 2 2 8 8 4 3 1") == []    # checksum-valid ISBN-10 digits
        assert be.find_labelled_isbns("ISBN 978-0-06-228843-1")[0]["isbn"] == "9780062288431"

    def test_label_and_checksum_required(self):
        assert be.find_labelled_isbns("call 9780062288431 now") == []
        assert be.find_labelled_isbns("ISBN 978-0-06-228843-2") == []
        assert be.normalize_isbn("0000000000") is None


# --- fetch_and_apply_metadata end to end -----------------------------------------

class _List(list):
    pass


class _FakeSession:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


class _Provider:
    def __init__(self, pid, results):
        self.__id__ = pid
        self.__name__ = pid
        self.active = True
        self.results = results
        self.queries = []

    def search(self, query, cover="", locale="en"):
        self.queries.append(query)
        return list(self.results)


def _ingest(monkeypatch, tmp_path, *, title, authors, fmt="EPUB", epub=None, isbn=None, providers=(),
            smart=True, settings=None):
    """Run fetch_and_apply_metadata on a fake library holding one book."""
    lib = tmp_path / "library"
    (lib / "Author" / "Book (1)").mkdir(parents=True, exist_ok=True)
    if epub is not None:
        (lib / "Author" / "Book (1)" / ("Book - Author.%s" % fmt.lower())).write_bytes(open(epub, "rb").read())
    book = NS(id=1, title=title, path="Author/Book (1)", data=[NS(format=fmt, name="Book - Author")],
              authors=_List(NS(name=a) for a in authors), comments=_List(), publishers=_List(), tags=_List(),
              series=_List(), series_index="1.0", pubdate=None, ratings=_List(),
              identifiers=_List([NS(type="isbn", val=isbn)] if isbn else []))
    session = _FakeSession()

    class CalibreDB:
        session_factory = True
        config = NS(config_calibre_dir=str(lib))

        def __init__(self, *a, **k):
            self.session = session

        def get_book(self, book_id):
            return book

        def get_author_by_name(self, name):
            return NS(name=name)

        def get_publisher_by_name(self, name):
            return None

        def get_tag_by_name(self, name):
            return None

        def get_series_by_name(self, name):
            return None

    fake_db = NS(CalibreDB=CalibreDB, Authors=lambda name, sort: NS(name=name),
                 Comments=lambda text, book_id: NS(text=text), Publishers=lambda name, sort: NS(name=name),
                 Tags=lambda name: NS(name=name), Series=lambda name, sort: NS(name=name),
                 Identifiers=lambda val, typ, book_id: NS(type=typ, val=val), Ratings=lambda rating: NS(rating=rating))
    conf = {
        "auto_metadata_fetch_enabled": True, "auto_metadata_smart_application": smart,
        "auto_metadata_update_title": True, "auto_metadata_update_authors": True,
        "auto_metadata_update_description": True, "auto_metadata_update_publisher": True,
        "auto_metadata_update_tags": True, "auto_metadata_update_series": True,
        "auto_metadata_update_published_date": True, "auto_metadata_update_rating": True,
        "auto_metadata_update_identifiers": True, "auto_metadata_update_cover": False,
        "metadata_provider_hierarchy": '["%s"]' % '","'.join(p.__id__ for p in providers),
        "metadata_providers_enabled": "{}",
    }
    conf.update(settings or {})
    monkeypatch.setattr(m, "db", fake_db)
    monkeypatch.setattr(m, "metadata_providers", list(providers))
    monkeypatch.setattr(m, "CWA_DB", lambda: NS(get_cwa_settings=lambda: conf))
    applied = m.fetch_and_apply_metadata(1)
    return applied, book, session


def _descriptions(session):
    return [o.text for o in session.added if hasattr(o, "text")]


class TestIsbnLabels:
    def test_edition_note_between_label_and_number(self):
        found = be.find_labelled_isbns("ISBN (hardcover) 978-0-451-41844-9\nISBN [ebook]: 978-1-101-21198-4")
        assert [(x["isbn"], x["kind"]) for x in found] == [("9780451418449", "print"), ("9781101211984", "ebook")]

    def test_a_long_aside_is_not_an_edition_note(self):
        assert be.find_labelled_isbns(
            "ISBN (and a very long parenthetical that is not an edition note) 978-0-451-41844-9") == []

    def test_kind_comes_from_the_isbns_own_label(self):
        found = be.find_labelled_isbns("Hardcover ISBN 978-0-451-41844-9\neBook ISBN 978-1-101-21198-4")
        assert [x["kind"] for x in found] == ["print", "ebook"]


class TestIngest:
    def test_summary_record_tags_and_description_never_reach_the_book(self, monkeypatch, tmp_path):
        epub = _book_file(tmp_path / "b.epub", "Outgrowing God", "Richard Dawkins", words=72000)
        mill = _rec("Outgrowing God", ["Richard Dawkins"], publisher="Readtrepreneur Publishing",
                    description="An unofficial summary of Outgrowing God.", tags=["Study Aids"])
        applied, book, session = _ingest(monkeypatch, tmp_path, title="Outgrowing God", authors=["Richard Dawkins"],
                                         epub=epub, providers=[_Provider("ibdb", [mill])])
        assert not applied
        assert list(book.tags) == [] and _descriptions(session) == [] and list(book.publishers) == []

    def test_right_record_applies_its_tags_and_description(self, monkeypatch, tmp_path):
        epub = _book_file(tmp_path / "b.epub", "Outgrowing God", "Richard Dawkins", words=72000)
        mill = _rec("Outgrowing God", ["Richard Dawkins"], publisher="Readtrepreneur Publishing", tags=["Study Aids"])
        right = _rec("Outgrowing God", ["Richard Dawkins"], publisher="Transworld",
                     description="Richard Dawkins on why we no longer need God.", tags=["Religion"])
        applied, book, session = _ingest(monkeypatch, tmp_path, title="Outgrowing God", authors=["Richard Dawkins"],
                                         epub=epub, providers=[_Provider("ibdb", [mill, right])])
        assert applied
        assert [t.name for t in book.tags] == ["Religion"]
        assert _descriptions(session) == ["Richard Dawkins on why we no longer need God."]

    def test_a_provider_with_only_wrong_records_falls_through_to_the_next(self, monkeypatch, tmp_path):
        epub = _book_file(tmp_path / "b.epub", "Outgrowing God", "Richard Dawkins", words=72000)
        first = _Provider("ibdb", [_rec("Summary of Outgrowing God", ["Irb Media"], tags=["Study Aids"])])
        second = _Provider("google", [_rec("Outgrowing God", ["Richard Dawkins"], tags=["Religion"])])
        applied, book, _ = _ingest(monkeypatch, tmp_path, title="Outgrowing God", authors=["Richard Dawkins"],
                                   epub=epub, providers=[first, second])
        assert applied and [t.name for t in book.tags] == ["Religion"]

    def test_isbn_title_import_searches_by_the_printed_isbn_and_takes_the_proven_title(self, monkeypatch, tmp_path):
        tp = _title_page("Brief Candle in the Dark", "Richard Dawkins", "My Life in Science")
        cp = _copyright_page("Brief Candle in the Dark", "Richard Dawkins", [("ISBN", "978-0-06-228843-1")])
        epub = _write_epub(tmp_path / "b.epub", "0062288431 (N)", ["Richard Dawkins"], [tp] + _chapters(147000) + [cp])
        provider = _Provider("google", [_rec("Brief Candle in the Dark", ["Richard Dawkins"], "9780062288431")])
        applied, book, _ = _ingest(monkeypatch, tmp_path, title="0062288431 (N)", authors=["Richard Dawkins"],
                                   epub=epub, providers=[provider])
        assert provider.queries == ["9780062288431"]
        assert applied and book.title == "Brief Candle in the Dark"

    def test_smart_mode_keeps_a_real_title(self, monkeypatch, tmp_path):
        epub = _book_file(tmp_path / "b.epub", "Outgrowing God", "Richard Dawkins", words=72000,
                          isbns_printed=[("ISBN", "978-1-4735-6211-6")])
        provider = _Provider("google", [_rec("Outgrowing God", ["Richard Dawkins"], "9781473562116")])
        _, book, _ = _ingest(monkeypatch, tmp_path, title="Outgrowing God: A Beginner's Guide",
                             authors=["Richard Dawkins"], epub=epub, providers=[provider])
        assert book.title == "Outgrowing God: A Beginner's Guide"

    def test_other_formats_keep_the_title_author_gate_alone(self, monkeypatch, tmp_path):
        """No EPUB: same behaviour as before, including what the gate misses."""
        mill = _rec("Outgrowing God", ["Richard Dawkins"], publisher="Readtrepreneur Publishing", tags=["Study Aids"])
        monkeypatch.setattr(m.book_evidence, "extract", lambda *a, **k: pytest.fail("MOBI must not be read"))
        applied, book, _ = _ingest(monkeypatch, tmp_path, title="Outgrowing God", authors=["Richard Dawkins"],
                                   fmt="MOBI", epub=None, providers=[_Provider("ibdb", [mill])])
        assert applied and [t.name for t in book.tags] == ["Study Aids"]

    def test_gate_mode_never_replaces_a_junk_title_in_smart_mode(self, monkeypatch, tmp_path):
        rec = _rec("Brief Candle in the Dark", ["Richard Dawkins"], "9780062288431")
        applied, book, _ = _ingest(monkeypatch, tmp_path, title="0062288431 (N)", authors=["Richard Dawkins"],
                                   fmt="MOBI", isbn="9780062288431", providers=[_Provider("google", [rec])])
        assert book.title == "0062288431 (N)"

    def test_image_only_epub_keeps_the_gate(self, monkeypatch, tmp_path):
        docs = [("Page %d" % i, '<img src="p%d.jpg"/>' % i) for i in range(20)]
        epub = _write_epub(tmp_path / "b.epub", "Rodrick Rules", ["Jeff Kinney"], docs)
        right = _rec("Rodrick Rules", ["Jeff Kinney"], tags=["Humor"])
        applied, book, _ = _ingest(monkeypatch, tmp_path, title="Rodrick Rules", authors=["Jeff Kinney"],
                                   epub=epub, providers=[_Provider("google", [right])])
        assert applied and [t.name for t in book.tags] == ["Humor"]

    def test_epub_missing_from_the_library_keeps_the_gate(self, monkeypatch, tmp_path):
        right = _rec("Outgrowing God", ["Richard Dawkins"], tags=["Religion"])
        applied, _, _ = _ingest(monkeypatch, tmp_path, title="Outgrowing God", authors=["Richard Dawkins"],
                                epub=None, providers=[_Provider("google", [right])])
        assert applied

    @pytest.mark.parametrize("kind", ["not a zip", "xml entities"])
    def test_unreadable_epub_applies_nothing(self, monkeypatch, tmp_path, kind):
        if kind == "not a zip":
            epub = tmp_path / "b.epub"
            epub.write_bytes(b"this is not a zip file")
        else:
            epub = _write_epub(tmp_path / "b.epub", "Outgrowing God", ["Richard Dawkins"],
                               [_title_page("Outgrowing God", "Richard Dawkins")] + _chapters(5000), entity=True)
        provider = _Provider("google", [_rec("Outgrowing God", ["Richard Dawkins"], tags=["Religion"])])
        applied, book, _ = _ingest(monkeypatch, tmp_path, title="Outgrowing God", authors=["Richard Dawkins"],
                                   epub=str(epub), providers=[provider])
        assert not applied and list(book.tags) == [] and provider.queries == []

    def test_a_failing_check_applies_nothing(self, monkeypatch, tmp_path):
        epub = _book_file(tmp_path / "b.epub", "Outgrowing God", "Richard Dawkins", words=72000)

        def boom(*a, **k):
            raise RuntimeError("boom")

        monkeypatch.setattr(m.book_evidence, "extract", boom)
        provider = _Provider("google", [_rec("Outgrowing God", ["Richard Dawkins"], tags=["Religion"])])
        applied, book, _ = _ingest(monkeypatch, tmp_path, title="Outgrowing God", authors=["Richard Dawkins"],
                                   epub=epub, providers=[provider])
        assert not applied and list(book.tags) == [] and provider.queries == []

    def test_the_book_is_read_once_per_ingest(self, monkeypatch, tmp_path):
        epub = _book_file(tmp_path / "b.epub", "Outgrowing God", "Richard Dawkins", words=72000)
        calls = []
        real = m.book_evidence.extract

        def counting(*a, **k):
            calls.append(a)
            return real(*a, **k)

        monkeypatch.setattr(m.book_evidence, "extract", counting)
        providers = [_Provider(p, [_rec("Summary of Outgrowing God", ["Irb Media"])]) for p in ("ibdb", "google", "kobo")]
        _ingest(monkeypatch, tmp_path, title="Outgrowing God", authors=["Richard Dawkins"], epub=epub,
                providers=providers)
        assert len(calls) == 1 and all(p.queries for p in providers)


def test_core_modules_import_nothing_from_cps():
    """book_evidence and metadata_match must stay stdlib only, so the same
    files can run outside CWA (a review tool keeps a copy of them)."""
    import ast
    import inspect
    for mod in (be, mm):
        tree = ast.parse(inspect.getsource(mod))
        names = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
        names += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
        assert not [n for n in names if n.startswith("cps") or n in ("flask", "sqlalchemy", "lxml")], (mod, names)
