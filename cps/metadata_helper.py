# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import json
import os
import re
import unicodedata
from difflib import SequenceMatcher

from cps import logger, db
from cps import book_evidence
from cps import metadata_match
from cps.search_metadata import cl as metadata_providers
import sys
sys.path.insert(1, '/app/calibre-web-automated/scripts/')
from cwa_db import CWA_DB

log = logger.create()

def fetch_and_apply_metadata(book_id: int, user_enabled: bool = False) -> bool:
    """
    Fetch metadata for a newly ingested book and apply it if settings allow.
    
    Args:
        book_id: The ID of the book to fetch metadata for
        user_enabled: Deprecated parameter - metadata fetching is now admin-controlled only
        
    Returns:
        bool: True if metadata was successfully fetched and applied, False otherwise
    """
    try:
        if not db.CalibreDB.session_factory:
            log.error("CalibreDB not initialized; skipping metadata fetch")
            return False

        # Check global settings (admin-controlled only)
        cwa_db = CWA_DB()
        cwa_settings = cwa_db.get_cwa_settings()
        
        if not cwa_settings.get('auto_metadata_fetch_enabled', False):
            log.debug("Auto metadata fetch disabled by administrator")
            return False
            
        # Get the book
        calibre_db_instance = db.CalibreDB(expire_on_commit=False, init=True)
        book = calibre_db_instance.get_book(book_id)
        if not book:
            log.error(f"Book with ID {book_id} not found")
            return False
            
        # Create search query from book title and author
        search_query = book.title
        if book.authors:
            author_names = [author.name for author in book.authors]
            search_query += " " + " ".join(author_names)

        # The book's existing ISBN is used to pick the matching edition from the
        # provider's results instead of blindly taking the first one (NextGen #402).
        book_isbn = _book_isbn(book)

        # Read the EPUB once. Every provider's results are checked against what
        # the book itself prints (title page, copyright page, labelled ISBNs).
        # Other formats, and image-only EPUBs, keep the title/author gate alone.
        evidence_mode, evidence, evidence_reason = _read_book_evidence(book)
        if evidence_mode == "skip":
            log.info(f"Not applying fetched metadata to book: {book.title}: {evidence_reason}")
            calibre_db_instance.session.close()
            return False
        if evidence_mode == "gate":
            log.debug(f"In-book check not used for {book.title}: {evidence_reason}")
        elif _is_junk_title(book.title):
            # An import titled with its own ISBN ("0062288431 (N)") can't be found
            # by its title. Search for the ISBN printed on its copyright page;
            # a result is still only applied if the book proves it.
            printed = _printed_isbns(evidence)
            if printed:
                search_query = printed[0]

        log.info(f"Fetching metadata for: {search_query}")
        
        # Get provider hierarchy
        try:
            provider_hierarchy = json.loads(cwa_settings.get('metadata_provider_hierarchy', '["google","douban","dnb","ibdb","comicvine"]'))
        except (json.JSONDecodeError, TypeError):
            provider_hierarchy = ["google", "douban", "dnb", "ibdb", "comicvine"]

        # Global provider enablement map
        enabled_map = _parse_metadata_providers_enabled(
            cwa_settings.get('metadata_providers_enabled', '{}')
        )
            
        # Try each provider in order
        metadata_found = False
        for provider_id in provider_hierarchy:
            # Check if explicitly disabled (default is enabled if not specified)
            is_enabled = enabled_map.get(provider_id, True)
            if not is_enabled:
                log.debug(f"Provider {provider_id} is globally disabled")
                continue
            try:
                # Find the provider
                provider = None
                for p in metadata_providers:
                    if p.__id__ == provider_id:
                        provider = p
                        break
                        
                if not provider or not provider.active:
                    continue
                    
                log.debug(f"Trying metadata provider: {provider.__name__}")
                
                # Search for metadata
                results = provider.search(search_query, "", "en")
                if not results or len(results) == 0:
                    continue
                    
                # Prefer the candidate whose ISBN matches the book's existing ISBN
                # over a blind first result (NextGen #402), and refuse a candidate
                # that isn't plausibly this book at all (NextGen #1164). With an
                # EPUB, the candidate must also be what the book prints.
                if evidence_mode == "evidence":
                    metadata = _select_with_book_evidence(
                        results, evidence, book_isbn,
                        book_title=book.title, book_authors=book.authors,
                    )
                else:
                    metadata = _select_metadata_result(
                        results, book_isbn,
                        book_title=book.title, book_authors=book.authors,
                    )
                if metadata is None:
                    log.info(
                        f"No confident match from {provider.__name__} for book: "
                        f"{book.title}, leaving its metadata untouched"
                    )
                    continue

                # Captured before the apply: _apply_metadata_to_book overwrites
                # book.title, so logging it afterwards named the book we fetched
                # rather than the book we changed (NextGen #1164).
                searched_title = book.title

                # Apply metadata to book
                # A junk title (an ISBN, a format marker) is only replaced when
                # the book printed the new one, which the in-book check requires.
                if _apply_metadata_to_book(book, metadata, calibre_db_instance,
                                           replace_junk_title=evidence_mode == "evidence"):
                    log.info(f"Successfully applied metadata from {provider.__name__} for book: {searched_title}")
                    metadata_found = True
                    break
                    
            except Exception as e:
                log.warning(f"Error fetching metadata from provider {provider_id}: {e}")
                continue
                
        calibre_db_instance.session.close()
        return metadata_found
        
    except Exception as e:
        log.error(f"Error in fetch_and_apply_metadata: {e}", exc_info=True)
        return False


def _apply_metadata_to_book(book, metadata, calibre_db_instance, replace_junk_title=False) -> bool:
    """
    Apply fetched metadata to a book record.
    
    Args:
        book: The book database record
        metadata: The metadata record from provider
        calibre_db_instance: Database instance
        replace_junk_title: smart mode also replaces a title that is an ISBN or
            a file name ("0062288431 (N)"); only set when the book file printed
            the new title
        
    Returns:
        bool: True if metadata was successfully applied
    """
    try:
        # Get CWA settings to check smart application preference and field selections
        cwa_db = CWA_DB()
        cwa_settings = cwa_db.get_cwa_settings()
        use_smart_application = cwa_settings.get('auto_metadata_smart_application', False)
        
        updated = False
        
        # Update title - only if enabled in settings. Smart mode only fills a
        # missing title. It used to take the longer one, and a summary or study
        # guide's title is nearly always longer than the book's.
        if (cwa_settings.get('auto_metadata_update_title', True) and 
            metadata.title and metadata.title.strip()):
            if use_smart_application:
                if not _has_meaningful_title(book) or (replace_junk_title and _is_junk_title(book.title)):
                    book.title = metadata.title.strip()
                    updated = True
            else:
                book.title = metadata.title.strip()
                updated = True
            
        # Update authors - only if enabled in settings. In smart mode, never clear
        # an existing meaningful author (NextGen #403): a weak match must not replace a
        # correct author with a foreign edition's translator.
        if (cwa_settings.get('auto_metadata_update_authors', True) and
            metadata.authors and len(metadata.authors) > 0 and
            not (use_smart_application and _has_meaningful_authors(book))):
            # Clear existing authors
            book.authors.clear()
            for author_name in metadata.authors:
                if author_name and author_name.strip():
                    author = calibre_db_instance.get_author_by_name(author_name.strip())
                    if not author:
                        author = db.Authors(author_name.strip(), author_name.strip())
                        calibre_db_instance.session.add(author)
                    book.authors.append(author)
            updated = True
            
        # Update description - only if enabled in settings
        if (cwa_settings.get('auto_metadata_update_description', True) and 
            metadata.description and metadata.description.strip()):
            current_description = book.comments[0].text if book.comments else ""
            # Smart mode only fills a missing description, for the same reason as
            # the title: the longer text is often a summary's disclaimer.
            if use_smart_application:
                if not (current_description or "").strip():
                    if book.comments:
                        book.comments[0].text = metadata.description.strip()
                    else:
                        comment = db.Comments(metadata.description.strip(), book.id)
                        calibre_db_instance.session.add(comment)
                    updated = True
            else:
                if book.comments:
                    book.comments[0].text = metadata.description.strip()
                else:
                    comment = db.Comments(metadata.description.strip(), book.id)
                    calibre_db_instance.session.add(comment)
                updated = True
            
        # Update publisher - only if enabled in settings
        if (cwa_settings.get('auto_metadata_update_publisher', True) and 
            metadata.publisher and metadata.publisher.strip()):
            if use_smart_application:
                if not book.publishers or len(book.publishers) == 0:
                    publisher = calibre_db_instance.get_publisher_by_name(metadata.publisher.strip())
                    if not publisher:
                        publisher = db.Publishers(metadata.publisher.strip(), metadata.publisher.strip())
                        calibre_db_instance.session.add(publisher)
                    book.publishers = [publisher]
                    updated = True
            else:
                # Clear existing publishers and add new one
                book.publishers.clear()
                publisher = calibre_db_instance.get_publisher_by_name(metadata.publisher.strip())
                if not publisher:
                    publisher = db.Publishers(metadata.publisher.strip(), metadata.publisher.strip())
                    calibre_db_instance.session.add(publisher)
                book.publishers = [publisher]
                updated = True
                
        # Update tags if available and enabled in settings
        if (cwa_settings.get('auto_metadata_update_tags', True) and 
            hasattr(metadata, 'tags') and metadata.tags):
            for tag_name in metadata.tags:
                if tag_name and tag_name.strip():
                    tag = calibre_db_instance.get_tag_by_name(tag_name.strip())
                    if not tag:
                        tag = db.Tags(name=tag_name.strip())
                        calibre_db_instance.session.add(tag)
                    if tag not in book.tags:
                        book.tags.append(tag)
            updated = True
            
        # Update series if available and enabled in settings. Smart mode keeps an
        # existing series rather than overwriting it (NextGen #403).
        if (cwa_settings.get('auto_metadata_update_series', True) and
            hasattr(metadata, 'series') and metadata.series and metadata.series.strip() and
            not (use_smart_application and book.series)):
            series = calibre_db_instance.get_series_by_name(metadata.series.strip())
            if not series:
                series = db.Series(metadata.series.strip(), metadata.series.strip())
                calibre_db_instance.session.add(series)
            book.series.clear()
            book.series.append(series)
            
            # Set series index if available
            if hasattr(metadata, 'series_index') and metadata.series_index:
                try:
                    # Convert to float first to validate, then store as string (DB column is String)
                    float_value = float(metadata.series_index)
                    book.series_index = str(float_value)
                except (ValueError, TypeError):
                    book.series_index = '1.0'
            updated = True
            
        # Update published date if available and enabled in settings. Smart mode
        # keeps an existing publication date (NextGen #403).
        if (cwa_settings.get('auto_metadata_update_published_date', True) and
            hasattr(metadata, 'publishedDate') and metadata.publishedDate and
            not (use_smart_application and _has_pubdate(book))):
            try:
                from datetime import datetime
                if isinstance(metadata.publishedDate, str):
                    # Try to parse various date formats
                    for fmt in ['%Y-%m-%d', '%Y-%m', '%Y']:
                        try:
                            book.pubdate = datetime.strptime(metadata.publishedDate, fmt).date()
                            updated = True
                            break
                        except ValueError:
                            continue
                elif hasattr(metadata.publishedDate, 'date'):
                    book.pubdate = metadata.publishedDate.date()
                    updated = True
            except Exception as e:
                log.warning(f"Error parsing published date: {e}")
                
        # Update rating if available and enabled in settings. Smart mode keeps an
        # existing rating (NextGen #403).
        if (cwa_settings.get('auto_metadata_update_rating', True) and
            hasattr(metadata, 'rating') and metadata.rating and
            not (use_smart_application and book.ratings)):
            try:
                rating_value = float(metadata.rating)
                if 0 <= rating_value <= 10:  # Calibre uses 0-10 scale
                    if book.ratings:
                        book.ratings[0].rating = int(rating_value * 2)  # Convert to Calibre's 0-10 scale
                    else:
                        rating = db.Ratings(rating=int(rating_value * 2))
                        calibre_db_instance.session.add(rating)
                        book.ratings = [rating]
                    updated = True
            except (ValueError, TypeError):
                pass
                
        # Update identifiers if available and enabled in settings. Smart mode fills
        # in identifier types the book is missing but never overwrites an existing
        # value, so a correct ISBN is not clobbered by a foreign edition's (NextGen #403).
        if (cwa_settings.get('auto_metadata_update_identifiers', True) and
            hasattr(metadata, 'identifiers') and metadata.identifiers):
            for identifier_type, identifier_value in metadata.identifiers.items():
                if identifier_type and identifier_value:
                    # Check if identifier already exists
                    existing = False
                    for identifier in book.identifiers:
                        if identifier.type == identifier_type:
                            if not use_smart_application:
                                identifier.val = identifier_value
                                updated = True
                            existing = True
                            break
                    if not existing:
                        new_identifier = db.Identifiers(identifier_value, identifier_type, book.id)
                        calibre_db_instance.session.add(new_identifier)
                        book.identifiers.append(new_identifier)
                        updated = True
        
        # Handle cover image - only if enabled in settings
        if (cwa_settings.get('auto_metadata_update_cover', True) and 
            hasattr(metadata, 'cover') and metadata.cover):
            # TODO: Implement cover resolution checking for smart mode
            # For now, just apply the cover in normal mode
            if not use_smart_application:
                # Apply cover (implementation depends on how covers are handled in Calibre-Web)
                pass
        
        if updated:
            calibre_db_instance.session.commit()
            
        return updated
        
    except Exception as e:
        log.error(f"Error applying metadata to book {getattr(book, 'id', 'unknown')}: {e}")
        calibre_db_instance.session.rollback()
        return False


def _normalize_isbn(value):
    """Strip separators and upper-case so ISBNs compare regardless of formatting."""
    return "".join(ch for ch in str(value) if ch.isalnum()).upper()


def _book_isbn(book):
    """Return the book's existing ISBN (preferring ISBN-13) or None (NextGen #402)."""
    isbn13 = isbn = None
    for ident in (getattr(book, "identifiers", None) or []):
        itype = (getattr(ident, "type", "") or "").lower()
        if itype in ("isbn13", "isbn_13"):
            isbn13 = ident.val
        elif itype == "isbn":
            isbn = ident.val
    return isbn13 or isbn


# How close two titles must be, when their identifying words are NOT identical,
# before metadata is applied. Deliberately near-exact: this path exists only to
# absorb spelling/diacritic noise, not to judge whether two different titles are
# "close enough". Applying nothing is recoverable; silently overwriting a book
# with a different book's metadata is not (NextGen #1164).
#
# A plain character-similarity bar cannot do this job on its own: series titles
# share a long prefix, so "Harry Potter and the Chamber of Secrets" scores 0.78
# against "...and the Goblet of Fire", high enough to pass any threshold loose
# enough to accept real-world title variance. Identifying-word equality is what
# separates "same book, different edition" from "next book in the series".
_TITLE_FUZZY_MATCH_MIN = 0.92

# Joining words carry no identifying weight and inflate similarity between
# unrelated titles in the same series.
_TITLE_STOPWORDS = frozenset((
    "and", "or", "the", "a", "an", "of", "in", "on", "to", "for", "with",
    "from", "at", "by", "its", "his", "her", "their",
))

# Generic descriptors publishers append to a title. Stripped so "The Devils"
# still matches "The Devils: A Novel". Deliberately a short curated list of
# non-identifying words. A substantive subtitle ("Dune: Messiah") must NOT be
# stripped, or every book in a series collapses onto its sibling.
_GENERIC_TITLE_TAILS = (
    "a novel", "an novel", "novel", "a memoir", "a story", "stories",
    "a biography", "an autobiography", "unabridged", "abridged",
)

_LEADING_ARTICLES = ("the ", "a ", "an ")


def _normalize_title(value):
    """Casefold and strip accents, bracketed asides, punctuation, a leading
    article and any generic publisher tail, so titles compare on the words that
    actually identify the book (NextGen #1164)."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    # Series markers and format notes: "(First Law World)", "[Unabridged]".
    text = re.sub(r"[(\[{][^)\]}]*[)\]}]", " ", text)
    text = "".join(ch if ch.isalnum() else " " for ch in text)
    text = " ".join(text.split())
    for article in _LEADING_ARTICLES:
        if text.startswith(article):
            text = text[len(article):]
            break
    for tail in _GENERIC_TITLE_TAILS:
        if text.endswith(" " + tail):
            stripped = text[: -(len(tail) + 1)].strip()
            if stripped:
                text = stripped
                break
    return text


def _title_content_words(value):
    """The identifying words of a title, in order, with joining words removed
    (NextGen #1164). Order is kept so "Blood and Iron" doesn't match "Iron and
    Blood"."""
    return tuple(w for w in _normalize_title(value).split()
                 if w not in _TITLE_STOPWORDS)


# Words that announce a volume number. A roman numeral or number word is only
# read as a number straight after one of these ("Part I", "Book Two"), because
# "I" and "one" are ordinary words everywhere else.
_VOLUME_MARKERS = frozenset((
    "vol", "volume", "part", "pt", "book", "bk", "no", "number", "issue",
    "episode", "season", "chapter", "tome",
))

_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
}

_ROMAN_NUMERALS = {
    "i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8,
    "ix": 9, "x": 10, "xi": 11, "xii": 12, "xiii": 13, "xiv": 14, "xv": 15,
    "xvi": 16, "xvii": 17, "xviii": 18, "xix": 19, "xx": 20,
}


def _title_numbers(value):
    """Volume-like numbers in a title, as a set of ints (digits anywhere, plus
    roman numerals and number words right after a marker such as "vol" or
    "part")."""
    words = _normalize_title(value).split()
    numbers = set()
    for i, word in enumerate(words):
        if word.isdigit():
            numbers.add(int(word))
        elif i and words[i - 1] in _VOLUME_MARKERS:
            if word in _NUMBER_WORDS:
                numbers.add(_NUMBER_WORDS[word])
            elif word in _ROMAN_NUMERALS:
                numbers.add(_ROMAN_NUMERALS[word])
    return numbers


def _volume_numbers_conflict(left, right):
    """True when both titles carry volume numbers and they are not the same.
    "One Piece, Vol. 12" and "Vol. 13" are 0.94 similar as text but are
    different books, and the author is the same. A title with no number on one
    side is left to the other checks."""
    a, b = _title_numbers(left), _title_numbers(right)
    return bool(a and b and a != b)


def _title_similarity(left, right):
    """0.0-1.0 similarity of two titles after normalization (NextGen #1164).

    1.0 exactly when the identifying words are the same in the same order.
    That is the only signal trusted to mean "the same book". Anything else is
    scored on character similarity and must clear ``_TITLE_FUZZY_MATCH_MIN``,
    which is set high enough that a sibling in the same series cannot pass.
    """
    a, b = _normalize_title(left), _normalize_title(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    words_a, words_b = _title_content_words(left), _title_content_words(right)
    if words_a and words_a == words_b:
        return 1.0
    if _volume_numbers_conflict(left, right):
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


_PLACEHOLDER_AUTHORS = frozenset(("", "unknown"))


def _author_name_tokens(authors):
    """Normalized name words for a book's or candidate's authors (NextGen #1164).

    Every word is kept rather than just the last one, because name ORDER is not
    dependable here: Calibre stores and sorts authors as "King, Stephen" while
    providers return "Stephen King", so keying on the final word would make
    those two disagree and reject a correct match for most of a library. Words
    of one or two characters are dropped so initials ("J.") neither match nor
    block.

    Accepts ORM author objects and the plain strings providers return. A bare
    string is wrapped rather than iterated, which would otherwise walk it one
    character at a time.
    """
    if isinstance(authors, str):
        authors = [authors]
    tokens = set()
    for author in (authors or []):
        name = author if isinstance(author, str) else getattr(author, "name", "")
        # Calibre's "Unknown" placeholder is not a name, same rule as
        # _has_meaningful_authors. Counting it would make a book with no real
        # author reject every candidate.
        if (name or "").strip().lower() in _PLACEHOLDER_AUTHORS:
            continue
        tokens.update(w for w in _normalize_title(name).split() if len(w) > 2)
    return tokens


def _authors_agree(book_authors, candidate_authors):
    """True when the book and candidate share any author name word (NextGen #1164).
    Absence of author information on either side is not agreement.

    Deliberately generous: this signal is only ever used to REJECT an otherwise
    matching title, so a shared given name costing us a rejection is far cheaper
    than a name-order mismatch costing every correct match in a library.
    """
    return bool(_author_name_tokens(book_authors) & _author_name_tokens(candidate_authors))


def _select_metadata_result(results, book_isbn, book_title=None, book_authors=None):
    """Pick the provider result that is actually the same book.

    ISBN wins outright when the book carries one (NextGen #402). Otherwise (the
    normal case for a freshly ingested EPUB, which has no ISBN) the candidates
    are scored on title similarity and the BEST one is returned, but only if it
    clears the confidence bar. ``None`` means "no candidate is plausibly this
    book"; the caller must then apply nothing rather than fall back to a guess.

    Before NextGen #1164 this fell through to ``results[0]`` whenever ISBN could not
    decide, so whatever the provider ranked first was applied unconditionally,
    which is how a search for "The Devils" overwrote the book with "The Heretics".

    ``book_title``/``book_authors`` default to ``None`` for backwards
    compatibility; when no title is supplied the legacy first-result behaviour is
    kept, so the gate is only ever as strong as the caller. ``fetch_and_apply_
    metadata`` always passes them and a test pins that call site.
    """
    if book_isbn:
        target = _normalize_isbn(book_isbn)
        for result in results:
            identifiers = getattr(result, "identifiers", None) or {}
            for key in ("isbn", "isbn13", "isbn_13", "isbn10"):
                candidate = identifiers.get(key)
                if candidate and _normalize_isbn(candidate) == target:
                    return result

    if not book_title:
        return results[0]

    best = None
    best_score = 0.0
    for result in results:
        score = _title_similarity(book_title, getattr(result, "title", ""))
        if score > best_score:
            best, best_score = result, score

    if best is None:
        return None

    if best_score < 1.0 and best_score < _TITLE_FUZZY_MATCH_MIN:
        log.info(
            "Rejected metadata for %r: closest candidate %r scored %.2f, below "
            "the confidence bar, applying nothing rather than a different book",
            book_title, getattr(best, "title", ""), best_score,
        )
        return None

    # Titles can collide across genuinely different books. When both sides name
    # an author and none of them agree, that's a different book, not an edition.
    candidate_authors = getattr(best, "authors", None)
    if (_author_name_tokens(book_authors) and _author_name_tokens(candidate_authors)
            and not _authors_agree(book_authors, candidate_authors)):
        log.info(
            "Rejected metadata for %r: candidate %r matches on title but its "
            "author differs, applying nothing rather than a different book",
            book_title, getattr(best, "title", ""),
        )
        return None

    return best


# --- In-book check ---------------------------------------------------------
#
# The gate above compares a provider result with the book's database record. On
# a fresh ingest that record is whatever the EPUB's own metadata said, which can
# be junk ("0062288431 (N)", a "Die Trying (txt)" author), and a summary record
# that lists the original author passes it. These compare the result with the
# text of the book instead: its title page, its copyright page and the ISBNs
# printed there. The rules are in cps/metadata_match.py and the EPUB reader in
# cps/book_evidence.py, both stdlib only.

_EVIDENCE_FORMATS = ("EPUB", "KEPUB")
# Only the first few results are named in the log when nothing is applied.
_LOGGED_REJECTIONS = 3


def _library_roots():
    """Directories the book's relative path may sit under, most specific first."""
    roots = []
    try:
        from cps import config as cps_config
        try:
            roots.append(cps_config.get_book_path())
        except Exception:
            pass
        roots.append(getattr(cps_config, "config_calibre_dir", None))
    except Exception:
        pass
    roots.append(getattr(getattr(db.CalibreDB, "config", None), "config_calibre_dir", None))
    out = []
    for root in roots:
        if root and isinstance(root, str) and root not in out:
            out.append(root)
    return out


def _book_epub_path(book):
    """(path, "") for the book's EPUB in the library, or (None, why not)."""
    data = list(getattr(book, "data", None) or [])
    for fmt in _EVIDENCE_FORMATS:
        for entry in data:
            if (getattr(entry, "format", "") or "").upper() != fmt:
                continue
            rel = os.path.join(getattr(book, "path", "") or "", "%s.%s" % (entry.name, fmt.lower()))
            for root in _library_roots():
                full = os.path.join(root, rel)
                if os.path.isfile(full):
                    return full, ""
            return None, "its %s was not found in the library (%s)" % (fmt, rel)
    formats = sorted({(getattr(e, "format", "") or "").upper() for e in data})
    return None, "no EPUB to read (formats: %s)" % (", ".join(formats) or "none")


def _read_book_evidence(book):
    """Read the book file once, before any provider is asked.

    Returns (mode, evidence, reason):
      "evidence": check every result against ``evidence``
      "gate":     no EPUB (or an image-only one): the title/author gate alone,
                  exactly as before
      "skip":     the EPUB is there but can't be read (including DRM-protected
                  ones, which are also logged as a warning), or the check
                  failed: apply nothing
    """
    try:
        path, why = _book_epub_path(book)
        if not path:
            return "gate", None, why
        evidence = book_evidence.extract(path)
        if evidence.get("status") == "drm":
            log.warning(f"Book {getattr(book, 'id', '?')} ({getattr(book, 'title', '')}) is a DRM-protected EPUB "
                        f"({evidence['drm']['scheme']}). Its text can't be read here or by most readers; remove it "
                        f"and add a DRM-free copy.")
            return "skip", None, "its EPUB is DRM-protected (%s), so nothing can be checked" % evidence["drm"]["scheme"]
        if evidence.get("status") != "ok":
            return "skip", None, "its EPUB could not be read (%s), so nothing can be checked" % evidence.get("reason")
        words = evidence.get("words") or 0
        if words < metadata_match.MIN_WORDS_TO_JUDGE:
            return "gate", None, "its EPUB has %d words of text (image-based?)" % words
        return "evidence", evidence, ""
    except Exception as e:
        log.warning(f"In-book check failed for book {getattr(book, 'id', '?')}: {e}")
        return "skip", None, "the in-book check failed (%s)" % e


def _printed_isbns(evidence):
    """ISBNs printed next to an ISBN label in the front matter or on a
    copyright page, checksum-valid. ISBNs further into the body (ads for other
    books) don't count."""
    return [i["isbn"] for i in (evidence.get("isbns_in_text") or []) if i.get("where") != "body"]


_ISBN_IN_TITLE = re.compile(r"\b\d{9}[\dXx]\b|\b97[89]\d{10}\b")


def _is_junk_title(title):
    """A title that is an ISBN or carries a file-format / download-site marker."""
    text = (title or "").strip()
    if not text:
        return False
    if book_evidence.normalize_isbn(re.sub(r"\(.*?\)|\[.*?\]", "", text)):
        return True
    return bool(_ISBN_IN_TITLE.search(text) or metadata_match._FORMAT_JUNK.search(text))


# A document <title> like "/cwa-book-ingest/new_1_20260823_060533_5" is a
# temp path some conversion wrote, not a title. Its digits must not veto
# anything.
_PATH_LIKE_TITLE = re.compile(r"^\s*[/\\]|_\d{8}_\d{6}")


def _book_title_claims(evidence):
    """Titles the file claims for itself (OPF title, and the <title> most of its
    pages carry), without temp paths."""
    return [t for _, t in metadata_match.claim_titles(evidence) if not _PATH_LIKE_TITLE.search(t)]


def _title_in_book(title, evidence):
    """The title is printed on the title or copyright page, or it is the
    <title> most of the book's own pages carry. Plenty of real books have an
    image title page and a copyright page that never spells the title out."""
    if metadata_match.title_support(title, evidence) >= metadata_match.PRINTED:
        return True
    doc_title = evidence.get("doc_title") or ""
    return bool(doc_title) and (
        metadata_match.title_similarity(title, metadata_match.clean_claim_title(doc_title))
        >= metadata_match.TITLE_SIM_SAME)


def _candidate_from_result(result):
    """The plain dict metadata_match works on, from a provider's MetaRecord."""
    isbns = []
    for key, value in (getattr(result, "identifiers", None) or {}).items():
        if str(key).lower().replace("-", "").replace("_", "").startswith("isbn"):
            isbn = book_evidence.normalize_isbn(value)
            if isbn and isbn not in isbns:
                isbns.append(isbn)
    authors = getattr(result, "authors", None) or []
    if isinstance(authors, str):
        authors = [authors]
    publisher = getattr(result, "publisher", None)
    return {
        "title": (getattr(result, "title", "") or "").strip(),
        "subtitle": "",
        "authors": [a.strip() for a in authors if a and str(a).strip()],
        "publishers": [publisher] if publisher else [],
        "isbns": isbns,
        "pages": None,
        "source": getattr(getattr(result, "source", None), "id", ""),
    }


def _collection_markers(title):
    """Box set / omnibus / summary / study guide markers in a title."""
    return [r for r in metadata_match.junk_title_reasons(title or "")
            if not r.startswith("marketing or audio-product text")]


def _description_vetoes(description):
    """A summary product's record, whatever its title and author say."""
    text = (description or "")[:4000]
    out = ["description says %r" % d["phrase"]
           for d in book_evidence.find_disclaimers(text, 4000) if d["strength"] == "strong"]
    return out + ["description: " + r for r in metadata_match.junk_name_reasons([text])]


def _select_with_book_evidence(results, evidence, book_isbn, book_title=None, book_authors=None):
    """Pick the result that the book file itself backs, or None.

    A result is applied only when all of these hold:

    - nothing in it contradicts the book (``metadata_match.assess_candidate``:
      summary/guide/compilation titles, known summary publishers, an author
      the book never prints, a different volume number, a book that is itself
      a summary), and its description is not a summary's disclaimer
    - its title is printed in the book's front matter or copyright page (or is
      the <title> of the book's own pages), and one of its authors is printed
      on those pages in full
    - it passes the title/author gate against the book's record (NextGen
      #1164), unless the book proves it: one of its ISBNs is printed with an
      ISBN label on the title or copyright pages. Then only the main title has
      to match (a subtitle may differ), and nothing has to match when the
      record's title is junk. That is what lets an import titled
      "0062288431 (N)" take the record for the book it is.
    - if the file's own title says it is a box set, collection or summary,
      the result has to say so too

    Every result is checked, then the survivors are ranked by how much of the
    book backs them, so a wrong record ranked first by the provider no longer
    hides a right one further down. If the two best survivors are different
    works and neither is clearly better, nothing is applied.
    """
    printed = set(_printed_isbns(evidence))
    target = book_evidence.normalize_isbn(book_isbn) if book_isbn else None
    if target and printed and target not in printed:
        # The record's ISBN came from the file's own metadata. The book prints
        # others, so this one doesn't get the ISBN shortcut.
        log.info(
            "ISBN %s of %r is not one the book prints (%s); not matching on it",
            target, book_title, ", ".join(sorted(printed)),
        )
        target = None

    book_titles = _book_title_claims(evidence)
    # The record's title is junk, or the file's own title claim is (swapped
    # fields: title "Lee Child", author "Die Trying (txt)").
    junk_title = _is_junk_title(book_title) or bool(metadata_match.claim_junk(evidence)["title"])
    # A file whose own title says it's a box set, a summary or a collection is
    # that product. It often prints the first book's ISBN and title page, so a
    # record for the single book would otherwise look proven.
    file_is_product = any(_collection_markers(t) for t in [book_title or ""] + book_titles)
    ranked = []
    for index, result in enumerate(results):
        cand = _candidate_from_result(result)
        score, vetoes, _ = metadata_match.assess_candidate(evidence, cand, book_titles)
        vetoes = list(vetoes) + _description_vetoes(getattr(result, "description", ""))
        if not _title_in_book(cand["title"], evidence):
            vetoes.append("title %r is not printed in the book" % cand["title"])
        if metadata_match.author_support(cand["authors"], evidence) < 1.0:
            vetoes.append("no author of %s is printed in full in the book" % (cand["authors"][:3],))
        if file_is_product and not _collection_markers(cand["title"]):
            vetoes.append("the file's own title says it is a collection or summary, %r does not" % cand["title"])
        proven = bool(printed & set(cand["isbns"]))
        isbn_match = bool(target and target in cand["isbns"])
        if proven and not junk_title and (
                metadata_match.title_similarity(book_title or "", cand["title"]) < metadata_match.TITLE_SIM_SAME):
            # The printed ISBN lets a subtitle differ ("The Selfish Gene" for
            # "The Selfish Gene: 40th Anniversary Edition"), not the title.
            vetoes.append("title %r is not the book's %r, ISBN or not" % (cand["title"], book_title))
        if not (proven or isbn_match):
            similarity = _title_similarity(book_title, cand["title"])
            if similarity < 1.0 and similarity < _TITLE_FUZZY_MATCH_MIN:
                vetoes.append("title %r does not match the book's %r (%.2f)" % (cand["title"], book_title, similarity))
            if (_author_name_tokens(book_authors) and _author_name_tokens(cand["authors"])
                    and not _authors_agree(book_authors, cand["authors"])):
                vetoes.append("authors %s do not match the book's" % (cand["authors"][:3],))
        ranked.append({"result": result, "cand": cand, "score": score, "vetoes": vetoes, "index": index})

    alive = sorted((r for r in ranked if not r["vetoes"]), key=lambda r: (-r["score"], r["index"]))
    if not alive:
        for r in ranked[:_LOGGED_REJECTIONS]:
            log.info("Rejected metadata %r for %r: %s", r["cand"]["title"], book_title, "; ".join(r["vetoes"][:2]))
        return None

    best = alive[0]
    others = [r for r in alive[1:]
              if metadata_match.title_key(r["cand"]["title"]) != metadata_match.title_key(best["cand"]["title"])
              or not metadata_match.authors_agree(r["cand"]["authors"], best["cand"]["authors"])]
    if others and best["score"] - others[0]["score"] < metadata_match.MARGIN:
        log.info(
            "Rejected metadata for %r: the book backs %r and %r about equally, applying nothing",
            book_title, best["cand"]["title"], others[0]["cand"]["title"],
        )
        return None

    log.info(
        "Book file backs %r by %s for %r (score %.2f%s)",
        best["cand"]["title"], ", ".join(best["cand"]["authors"][:3]), book_title, best["score"],
        ", ISBN printed in the book" if printed & set(best["cand"]["isbns"]) else "",
    )
    return best["result"]


def _has_meaningful_authors(book):
    """True if the book already has a real author (not empty / not the Calibre
    'Unknown' placeholder), so smart mode won't overwrite it (NextGen #403)."""
    authors = getattr(book, "authors", None) or []
    return any((getattr(a, "name", "") or "").strip().lower() not in ("", "unknown")
               for a in authors)


def _has_meaningful_title(book):
    """True if the book has a title other than empty or Calibre's 'Unknown'."""
    title = (getattr(book, "title", "") or "").strip().lower()
    return title not in ("", "unknown")


def _has_pubdate(book):
    """True if the book already has a real publication date (not the Calibre
    'undefined' sentinel year 101), so smart mode won't overwrite it (NextGen #403)."""
    pubdate = getattr(book, "pubdate", None)
    return bool(pubdate) and getattr(pubdate, "year", 0) > 101


def _parse_metadata_providers_enabled(raw_value):
    """Lightweight parser for metadata_providers_enabled without importing cwa_functions."""
    try:
        if raw_value is None:
            return {}
        if isinstance(raw_value, bytes):
            raw_value = raw_value.decode('utf-8', errors='ignore')
        if isinstance(raw_value, str):
            s = raw_value.strip()
            if not s:
                return {}
            if s.startswith("'") and s.endswith("'"):
                s = s[1:-1]
            if not s:
                return {}
            data = json.loads(s)
            return data if isinstance(data, dict) else {}
        if isinstance(raw_value, dict):
            return raw_value
        return {}
    except (json.JSONDecodeError, ValueError, TypeError, AttributeError):
        return {}
