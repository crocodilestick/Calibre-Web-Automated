"""
Reproduce the ratings UNIQUE constraint bug and verify the fix.

Uses a real SQLite database with the exact Calibre schema -- no mocking.
Demonstrates:
  1. Old code (mutate in-place) -> IntegrityError on commit
  2. Old code (blind insert)    -> IntegrityError on commit
  3. Old code (mutate to missing value) -> silently corrupts other books
  4. New code (find-or-create)  -> works correctly in all cases

Can be run as a standalone script (python test_ratings_unique_constraint.py)
or with pytest if sqlalchemy is available.
"""

from sqlalchemy import (
    create_engine, Column, Integer, String, Table, ForeignKey, CheckConstraint,
    event,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import declarative_base, relationship, Session

# ---------- minimal Calibre schema reproduction ----------

Base = declarative_base()

books_ratings_link = Table(
    "books_ratings_link",
    Base.metadata,
    Column("book", Integer, ForeignKey("books.id"), primary_key=True),
    Column("rating", Integer, ForeignKey("ratings.id"), primary_key=True),
)


class Ratings(Base):
    __tablename__ = "ratings"
    id = Column(Integer, primary_key=True)
    rating = Column(
        Integer,
        CheckConstraint("rating > -1 AND rating < 11"),
        unique=True,
    )

    def __init__(self, rating):
        super().__init__()
        self.rating = rating


class Books(Base):
    __tablename__ = "books"
    id = Column(Integer, primary_key=True)
    title = Column(String)
    ratings = relationship(Ratings, secondary=books_ratings_link, backref="books")


# ---------- helpers ----------

def fresh_db():
    """Fresh in-memory SQLite with two books sharing rating=8."""
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _set_fk(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    session = Session(engine)

    r8 = Ratings(rating=8)
    r6 = Ratings(rating=6)
    book_a = Books(title="Book A", ratings=[r8])
    book_b = Books(title="Book B", ratings=[r8])
    session.add_all([r6, book_a, book_b])
    session.commit()

    assert book_a.ratings[0].id == book_b.ratings[0].id, "Setup: both books share same row"
    return session, book_a, book_b, r8, r6


def find_or_create_rating(session, value):
    """The fix: find existing row or create new one."""
    existing = session.query(Ratings).filter(Ratings.rating == value).first()
    if not existing:
        existing = Ratings(rating=value)
    return existing


# ---------- tests ----------

def test_old_code_mutate_hits_unique_constraint():
    """Old code: book.ratings[0].rating = 6, but rating=6 already exists -> IntegrityError."""
    session, book_a, book_b, r8, r6 = fresh_db()
    book_a.ratings[0].rating = 6  # mutate shared row to a value that already exists
    try:
        session.commit()
        assert False, "Should have raised IntegrityError"
    except IntegrityError:
        session.rollback()
        print("  PASS: mutate to existing value -> IntegrityError (as expected)")
    session.close()


def test_old_code_mutate_corrupts_other_books():
    """Old code: book.ratings[0].rating = 1 (missing value) -> silently corrupts Book B."""
    session, book_a, book_b, r8, r6 = fresh_db()
    book_a.ratings[0].rating = 1  # value 1 doesn't exist yet, so UPDATE succeeds
    session.commit()

    session.refresh(book_b)
    assert book_b.ratings[0].rating == 1, "Book B should have been corrupted"
    print("  PASS: mutate to missing value -> Book B silently corrupted from 8 to 1")
    session.close()


def test_old_code_blind_insert_hits_unique_constraint():
    """Old code: Ratings(rating=8) for unrated book -> IntegrityError since 8 already exists."""
    session, book_a, book_b, r8, r6 = fresh_db()
    book_c = Books(title="Book C")
    session.add(book_c)
    session.commit()

    try:
        new_rating = Ratings(rating=8)
        session.add(new_rating)
        book_c.ratings = [new_rating]  # may trigger autoflush here
        session.commit()
        assert False, "Should have raised IntegrityError"
    except IntegrityError:
        session.rollback()
        print("  PASS: blind insert of existing value -> IntegrityError (as expected)")
    session.close()


def test_fix_reuses_existing_row():
    """Find-or-create: change rating 8 -> 6, reuses existing row."""
    session, book_a, book_b, r8, r6 = fresh_db()
    rating = find_or_create_rating(session, 6)
    book_a.ratings = [rating]
    session.commit()

    assert book_a.ratings[0].rating == 6
    assert book_a.ratings[0].id == r6.id, "Should reuse existing row"
    session.refresh(book_b)
    assert book_b.ratings[0].rating == 8, "Book B must be untouched"
    print("  PASS: find-or-create reuses existing row, Book B untouched")
    session.close()


def test_fix_creates_new_row():
    """Find-or-create: change to value 1 (doesn't exist yet), creates new row."""
    session, book_a, book_b, r8, r6 = fresh_db()
    rating = find_or_create_rating(session, 1)
    book_a.ratings = [rating]
    session.commit()

    assert book_a.ratings[0].rating == 1
    session.refresh(book_b)
    assert book_b.ratings[0].rating == 8, "Book B must be untouched"
    print("  PASS: find-or-create creates new row, Book B untouched")
    session.close()


def test_fix_unrated_book():
    """Find-or-create: assign rating to unrated book, reuses existing row."""
    session, book_a, book_b, r8, r6 = fresh_db()
    book_c = Books(title="Book C")
    session.add(book_c)
    session.commit()

    rating = find_or_create_rating(session, 8)
    book_c.ratings = [rating]
    session.commit()

    assert book_c.ratings[0].rating == 8
    assert book_c.ratings[0].id == r8.id, "Should reuse existing row"
    print("  PASS: unrated book gets rating via find-or-create, reuses existing row")
    session.close()


ALL_TESTS = [
    test_old_code_mutate_hits_unique_constraint,
    test_old_code_mutate_corrupts_other_books,
    test_old_code_blind_insert_hits_unique_constraint,
    test_fix_reuses_existing_row,
    test_fix_creates_new_row,
    test_fix_unrated_book,
]

if __name__ == "__main__":
    print("=" * 60)
    print("Ratings UNIQUE constraint: bug reproduction & fix proof")
    print("=" * 60)

    passed = 0
    failed = 0
    for test in ALL_TESTS:
        print(f"\n{test.__name__}:")
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"  FAIL: {e}")
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)
    exit(1 if failed else 0)
