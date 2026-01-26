# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

import json
import time
from datetime import datetime
from os import getenv
from typing import List, Optional

from cps import config, db, logger, ub
from cps.services.worker import CalibreTask, STAT_FAIL, STAT_FINISH_SUCCESS
from flask_babel import lazy_gettext as N_
from sqlalchemy import not_

# Import the Hardcover provider
try:
    from cps.metadata_provider.hardcover import Hardcover
except ImportError:
    Hardcover = None


class TaskAutoHardcoverID(CalibreTask):
    """
    Background task to automatically fetch Hardcover IDs for books in the library.
    
    This task:
    1. Queries all books without hardcover-id, hardcover-slug, or hardcover-edition identifiers
    2. Processes books in configurable batches with rate limiting
    3. Searches Hardcover API for each book using title + authors
    4. Calculates confidence scores for matches
    5. Auto-applies high-confidence matches (>=threshold, default 0.85)
    6. Queues low-confidence matches for manual review
    7. Implements exponential backoff on API errors
    """

    def __init__(self, 
                 min_confidence: float = 0.85,
                 batch_size: int = 50,
                 rate_limit_delay: float = 5.0,
                 max_backoff_errors: int = 5,
                 task_message=N_('Auto-fetching Hardcover IDs')):
        super(TaskAutoHardcoverID, self).__init__(task_message)
        self.log = logger.create()
        self.calibre_db = db.CalibreDB(expire_on_commit=False, init=True)
        self.min_confidence = min_confidence
        self.batch_size = batch_size
        self.rate_limit_delay = rate_limit_delay
        self.max_backoff_errors = max_backoff_errors
        
        # Stats tracking
        self.books_processed = 0
        self.auto_matched = 0
        self.queued_for_review = 0
        self.skipped_no_results = 0
        self.errors = 0
        self.total_confidence = 0.0
        
        # Error tracking for exponential backoff
        self.consecutive_errors = 0
        self.current_delay = rate_limit_delay

    def run(self, worker_thread):
        # Check if Hardcover provider is available
        if Hardcover is None:
            self._handleError("Hardcover provider not available")
            return
        
        # Check if valid token exists
        token = self._get_hardcover_token()
        if not token:
            self._handleError("No valid Hardcover token found. Set HARDCOVER_TOKEN environment variable or configure token in settings.")
            return
        
        try:
            # Query books without hardcover identifiers
            books = self._get_books_without_hardcover_id()
            total_books = len(books)
            
            if total_books == 0:
                self.log.info("No books found without Hardcover IDs")
                self._handleSuccess()
                return
            
            self.log.info(f"Found {total_books} books without Hardcover IDs. Processing in batches of {self.batch_size}...")
            
            # Process books in batches
            batch_count = (total_books + self.batch_size - 1) // self.batch_size
            for batch_num in range(batch_count):
                # Check if task was cancelled
                if self.stat == 5:  # STAT_CANCELLED
                    self.log.info("Task cancelled by user")
                    return
                
                start_idx = batch_num * self.batch_size
                end_idx = min(start_idx + self.batch_size, total_books)
                batch = books[start_idx:end_idx]
                
                self.log.info(f"Processing batch {batch_num + 1}/{batch_count} ({len(batch)} books)")
                
                for book in batch:
                    # Check if cancelled
                    if self.stat == 5:
                        self.log.info("Task cancelled by user")
                        return
                    
                    # Check if we've hit too many consecutive errors
                    if self.consecutive_errors >= self.max_backoff_errors:
                        error_msg = f"Exceeded maximum consecutive errors ({self.max_backoff_errors}). Stopping to protect API key."
                        self.log.error(error_msg)
                        self._save_stats()
                        self._handleError(error_msg)
                        return
                    
                    try:
                        self._process_book(book)
                        self.books_processed += 1
                        
                        # Reset consecutive errors on success
                        self.consecutive_errors = 0
                        self.current_delay = self.rate_limit_delay
                        
                        # Update progress
                        self.progress = self.books_processed / total_books
                        
                        # Rate limiting: wait between requests
                        if self.books_processed < total_books:
                            time.sleep(self.current_delay)
                            
                    except Exception as e:
                        self.log.error(f"Error processing book {book.id} '{book.title}': {e}")
                        self.errors += 1
                        self.consecutive_errors += 1
                        
                        # Exponential backoff
                        self.current_delay = min(self.current_delay * 2, 60.0)
                        self.log.warning(f"Consecutive errors: {self.consecutive_errors}. Increasing delay to {self.current_delay}s")
                        time.sleep(self.current_delay)
            
            # Save final stats
            self._save_stats()
            
            # Log summary
            self.log.info(f"Hardcover auto-fetch completed: {self.books_processed} processed, "
                         f"{self.auto_matched} auto-matched, {self.queued_for_review} queued for review, "
                         f"{self.skipped_no_results} skipped (no results), {self.errors} errors")
            
            self._handleSuccess()
            
        except Exception as ex:
            self.log.error(f"Fatal error in TaskAutoHardcoverID: {ex}")
            self._handleError(str(ex))
        finally:
            self.calibre_db.session.close()

    def _get_hardcover_token(self) -> Optional[str]:
        """Get Hardcover token from environment or config"""
        token = (
            getattr(config, "config_hardcover_token", None)
            or getenv("HARDCOVER_TOKEN")
        )
        return token

    def _get_books_without_hardcover_id(self) -> List[db.Books]:
        """
        Query all books that don't have any Hardcover identifiers.
        Excludes books with hardcover-id, hardcover-slug, or hardcover-edition.
        """
        books = self.calibre_db.session.query(db.Books).filter(
            ~db.Books.identifiers.any(
                db.Identifiers.type.in_(['hardcover-id', 'hardcover-slug', 'hardcover-edition'])
            )
        ).limit(10000).all()  # Safety limit
        
        return books

    def _process_book(self, book: db.Books):
        """
        Process a single book: search Hardcover API, calculate confidence, apply or queue.
        """
        # Build search query from book metadata
        authors = [author.name for author in book.authors] if book.authors else []
        author_str = ", ".join(authors[:3]) if authors else ""  # Limit to first 3 authors
        
        # Build search query
        if author_str:
            search_query = f"{book.title} {author_str}"
        else:
            search_query = book.title
        
        self.log.debug(f"Searching Hardcover for: {search_query}")
        
        # Initialize Hardcover provider
        provider = Hardcover()
        
        # Search Hardcover API
        results = provider.search(search_query)
        
        if not results:
            self.log.debug(f"No Hardcover results for book {book.id} '{book.title}'")
            self.skipped_no_results += 1
            return
        
        self.log.debug(f"Found {len(results)} Hardcover results for book {book.id}")
        
        # Calculate confidence scores for each result
        scored_results = []
        for result in results[:10]:  # Limit to top 10 results
            # Get book's ISBN for matching
            book_isbn = None
            for identifier in book.identifiers:
                if identifier.type.lower() == 'isbn':
                    book_isbn = identifier.val
                    break
            
            # Get book's series info
            book_series = book.series[0].name if book.series else None
            book_series_index = book.series_index if book.series else None
            
            # Get publisher
            book_publisher = book.publishers[0].name if book.publishers else None
            
            # Get publication year
            book_year = str(book.pubdate)[:4] if book.pubdate else None
            
            # Calculate confidence score
            score, reason = Hardcover.calculate_confidence_score(
                result=result,
                query_title=book.title,
                query_authors=authors,
                query_isbn=book_isbn,
                query_series=book_series,
                query_series_index=book_series_index,
                query_publisher=book_publisher,
                query_year=book_year
            )
            
            scored_results.append({
                'result': result,
                'score': score,
                'reason': reason
            })
        
        # Sort by confidence score (highest first)
        scored_results.sort(key=lambda x: x['score'], reverse=True)
        
        if not scored_results:
            self.skipped_no_results += 1
            return
        
        # Get best match
        best_match = scored_results[0]
        best_score = best_match['score']
        best_result = best_match['result']
        
        self.log.debug(f"Best match for book {book.id}: score={best_score:.3f}, reason={best_match['reason']}")
        
        # Track average confidence
        self.total_confidence += best_score
        
        # Auto-apply if confidence is high enough
        if best_score >= self.min_confidence:
            self._apply_hardcover_id(book, best_result)
            self.auto_matched += 1
            self.log.info(f"Auto-matched book {book.id} '{book.title}' to Hardcover ID {best_result.id} (confidence: {best_score:.3f})")
        else:
            # Queue for manual review
            self._queue_for_review(book, search_query, scored_results)
            self.queued_for_review += 1
            self.log.debug(f"Queued book {book.id} '{book.title}' for manual review (confidence: {best_score:.3f})")

    def _apply_hardcover_id(self, book: db.Books, result):
        """Apply Hardcover identifiers to a book"""
        try:
            # Add hardcover-id
            if 'hardcover-id' in result.identifiers:
                hardcover_id = str(result.identifiers['hardcover-id'])
                new_identifier = db.Identifiers(hardcover_id, 'hardcover-id', book.id)
                self.calibre_db.session.add(new_identifier)
            
            # Add hardcover-slug
            if 'hardcover-slug' in result.identifiers:
                hardcover_slug = str(result.identifiers['hardcover-slug'])
                new_identifier = db.Identifiers(hardcover_slug, 'hardcover-slug', book.id)
                self.calibre_db.session.add(new_identifier)
            
            # Add hardcover-edition (if available)
            if 'hardcover-edition' in result.identifiers:
                hardcover_edition = str(result.identifiers['hardcover-edition'])
                new_identifier = db.Identifiers(hardcover_edition, 'hardcover-edition', book.id)
                self.calibre_db.session.add(new_identifier)
            
            self.calibre_db.session.commit()
            
        except Exception as e:
            self.log.error(f"Error applying Hardcover ID to book {book.id}: {e}")
            self.calibre_db.session.rollback()
            raise

    def _queue_for_review(self, book: db.Books, search_query: str, scored_results: List[dict]):
        """Queue ambiguous match for manual review"""
        try:
            # Initialize user session for ub database
            ub.init_db_thread()
            
            # Prepare results for JSON storage (top 5 candidates)
            results_json = []
            scores_json = []
            
            for item in scored_results[:5]:
                result = item['result']
                results_json.append({
                    'id': str(result.id),
                    'title': result.title,
                    'authors': result.authors,
                    'url': result.url,
                    'cover': result.cover,
                    'description': result.description or "",
                    'series': result.series or "",
                    'series_index': str(result.series_index) if result.series_index else "",
                    'publisher': result.publisher or "",
                    'publishedDate': result.publishedDate or "",
                    'identifiers': {k: str(v) for k, v in result.identifiers.items()}
                })
                scores_json.append([item['score'], item['reason']])
            
            # Create queue entry
            queue_entry = ub.HardcoverMatchQueue(
                book_id=book.id,
                book_title=book.title,
                book_authors=", ".join([author.name for author in book.authors]) if book.authors else "",
                search_query=search_query,
                hardcover_results=json.dumps(results_json),
                confidence_scores=json.dumps(scores_json),
                created_at=datetime.utcnow().isoformat(),
                reviewed=0
            )
            
            ub.session.add(queue_entry)
            ub.session.commit()
            
        except Exception as e:
            self.log.error(f"Error queuing book {book.id} for review: {e}")
            ub.session.rollback()
            raise

    def _save_stats(self):
        """Save statistics to CWA database"""
        try:
            from scripts.cwa_db import CWA_DB
            cwa_db = CWA_DB()
            
            avg_confidence = (self.total_confidence / self.auto_matched) if self.auto_matched > 0 else 0.0
            
            query = """
                INSERT INTO hardcover_auto_fetch_stats 
                (timestamp, books_processed, auto_matched, queued_for_review, 
                 skipped_no_results, errors, avg_confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """
            
            cwa_db.execute_write(
                query,
                (
                    datetime.utcnow().isoformat(),
                    self.books_processed,
                    self.auto_matched,
                    self.queued_for_review,
                    self.skipped_no_results,
                    self.errors,
                    avg_confidence
                )
            )
            
            self.log.debug("Saved Hardcover auto-fetch stats to database")
            
        except Exception as e:
            self.log.warning(f"Error saving stats to database: {e}")

    @property
    def name(self):
        return "Auto-fetch Hardcover IDs"

    @property
    def is_cancellable(self):
        return True

    def _handleSuccess(self):
        self.stat = STAT_FINISH_SUCCESS
        self.progress = 1.0

    def _handleError(self, error_message):
        self.stat = STAT_FAIL
        self.progress = 1.0
        self.error = error_message
