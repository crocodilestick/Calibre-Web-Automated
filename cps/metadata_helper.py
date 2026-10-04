# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import json
import re
import unicodedata
from difflib import SequenceMatcher

from cps import logger, db
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
                # that isn't plausibly this book at all (NextGen #1164).
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
                if _apply_metadata_to_book(book, metadata, calibre_db_instance):
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


def _apply_metadata_to_book(book, metadata, calibre_db_instance) -> bool:
    """
    Apply fetched metadata to a book record.
    
    Args:
        book: The book database record
        metadata: The metadata record from provider
        calibre_db_instance: Database instance
        
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
                if not _has_meaningful_title(book):
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
