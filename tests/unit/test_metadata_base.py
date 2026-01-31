import pytest

from cps.metadata_provider.amazon import Amazon
from tests.unit.metadata_base import MetadataProviderTestBase


@pytest.mark.unit
class TestMetadataBase(MetadataProviderTestBase):
    """Tests for the functionality provided by the Metadata base class"""

    # Nothing should need state, and it shouldn't matter which provider we use, so instantiate an Amazon provider for
    # all tests to use.
    provider = Amazon()

    def test_normalize_date(self) -> None:
        """Test the date normalization method"""

        # Map test string to expected normalized output
        test_cases = {
            "2023-09-15": "2023-09-15",
            "2023-09": "2023-09",
            "2023/09/15": "2023-09-15",
            "2023/09": "2023-09",
            "2023": "2023",
            "15 September 2023": "2023-09-15",
            "15 Sep 2023": "2023-09-15",
            "9 September 2023": "2023-09-09",
            "9 Sep 2023": "2023-09-09",
            "September 15, 2023": "2023-09-15",
            "Sep 15, 2023": "2023-09-15",
            "Sep 2023": "2023-09",
            "September 2023": "2023-09",
            "2023-09-15T01:23:45+04:00": "2023-09-15",
            "2023-09-15 01:23:45+04:00": "2023-09-15",
            "2023-09-15T01:23:45Z": "2023-09-15",
            "2023-09-15 01:23:45": "2023-09-15",
            "Not gonna parse but should be 2023-09-15 or else": "2023-09-15",
            "Not gonna parse but should be 2023 or else": "2023",
        }

        for input_date, expected_output in test_cases.items():
            assert self.provider._normalize_date(input_date) == expected_output

        # An entirely invalid string should return None
        assert self.provider._normalize_date("Completely invalid date string") is None

    def test_set_status(self) -> None:
        """Test the status setting method"""

        assert self.provider.active
        self.provider.set_status(False)
        assert not self.provider.active
        self.provider.set_status(True)
        assert self.provider.active

    def test_primary_language(self) -> None:
        """Test the primary language extraction method"""

        assert self.provider.language_codes()[0].startswith(
            self.provider.primary_language
        )

    def test_title_tokens(self) -> None:
        """Test the title tokenization method"""

        # Map test titles to expected token lists
        test_cases = {
            "The Great Gatsby": ["Great", "Gatsby"],
            "The Great Gatsby (Hardcover)": ["Great", "Gatsby"],
            "The Great Gatsby -Annotated Edition": [
                "Great",
                "Gatsby",
                "Annotated",
                "Edition",
            ],
            "A Tale of Two Cities": ["Tale", "of", "Two", "Cities"],
            "1984": ["1984"],
            "1984 (Special Edition)": ["1984"],
            "1984 (Special 2025 Panopticon Edition How-To Guide)": ["1984"],
            "19,84 (AudiOBooK)": ["1984"],
            "To Kill a Mockingbird": ["To", "Kill", "Mockingbird"],
            "Pride and Prejudice": ["Pride", "Prejudice"],
            "Pride & Prejudice": ["Pride", "Prejudice"],
            "Where in the world is Carmen Sandiego?": [
                "Where",
                "in",
                "world",
                "is",
                "Carmen",
                "Sandiego?",
            ],
            "Where in the world is Carmen Sandiego? - Adult Edition": [
                "Where",
                "in",
                "world",
                "is",
                "Carmen",
                "Sandiego?",
                "Adult",
                "Edition",
            ],
        }

        for title, expected_tokens in test_cases.items():
            assert list(self.provider.get_title_tokens(title)) == expected_tokens

    def test_validate_isbn(self) -> None:
        """Test the ISBN validation method"""

        # Map test ISBNs to expected validity
        test_cases = {
            "978 3161 484,100": "9783161484100",
            "316148410_X": "316148410X",
            "978-3-16-148.410-0": "9783161484100",
            "3-16-148410-X": "316148410X",
            "123,456,789,01_23": None,
            "123456789X": "123456789X",
            "123456789x": "123456789X",
            "9783161484101": None,
            "3161484100": None,
            "InvalidISBN": None,
            "": None,
        }

        for isbn, expected_validity in test_cases.items():
            assert self.provider.validate_isbn(isbn) == expected_validity

    def test_clean_description(self) -> None:
        """Test the Kobo description cleaning"""

        # Empty string should be empty
        assert self.provider.clean_description("") == ""
        assert self.provider.clean_description("   ") == ""

        # Whitespace is normalized
        messy_desc = "This   is a \t\t test.\tWith  irregular   spacing."
        assert (
            self.provider.clean_description(messy_desc)
            == "This is a test. With irregular spacing."
        )
        assert (
            self.provider.clean_description(
                "Non-breaking space,\u00a0 thin space,\u2009and zero-width space are\u200bhandled."
            )
            == "Non-breaking space, thin space, and zero-width space arehandled."
        )

        # Excessive newlines are reduced to paragraph breaks
        desc_with_newlines = (
            "Paragraph one.\n \n\t\nParagraph two.\n \n \nParagraph three."
        )
        assert (
            self.provider.clean_description(desc_with_newlines)
            == "Paragraph one.\n\nParagraph two.\n\nParagraph three."
        )

        # Commonly escaped characters are unescaped
        assert self.provider.clean_description("\\@") == "@"

        # Assert HTML is only stripped when specified
        html_desc = "<p>This is a <b>bold</b> move.</p>"
        assert self.provider.clean_description(html_desc, strip_html=False) == html_desc
        assert (
            self.provider.clean_description(html_desc, strip_html=True)
            == "This is a bold move."
        )

        # Max 5000 characters only when stripping HTML
        long_desc = "A" * 6000
        assert self.provider.clean_description(long_desc) == long_desc
        assert len(self.provider.clean_description(long_desc, strip_html=True)) == 5000

    def test_safe_get(self) -> None:
        """Test the safe get method"""

        sample_dict = {"level1": {"level2": {"level3": "final_value"}}}

        # Valid path should return the value
        assert (
            self.provider.safe_get(sample_dict, "level1", "level2", "level3")
            == "final_value"
        )

        # Invalid paths should return None without raising exceptions
        assert (
            self.provider.safe_get(sample_dict, "level1", "nonexistent", "level3")
            is None
        )
        assert (
            self.provider.safe_get(sample_dict, "level1", "level2", "nonexistent")
            is None
        )
        assert (
            self.provider.safe_get(sample_dict, "nonexistent", "level2", "level3")
            is None
        )

        # Empty path should return the dictionary itself
        assert self.provider.safe_get(sample_dict) == sample_dict

        # Partial path should return the sub-dictionary
        assert self.provider.safe_get(sample_dict, "level1", "level2") == {
            "level3": "final_value"
        }

    def test_get_language_name(self) -> None:
        """Test Hardcover language parsing"""
        provider = Amazon()

        test_cases = {
            "en": {
                "eng": "English",
                "fra": "French",
                "en": "English",
                "fr": "French",
                "ja": "Japanese",
                "xyz": "Unknown",
                "English": "",
            },
            "de": {
                "eng": "Englisch",
                "fra": "Französisch",
                "en": "Englisch",
                "fr": "Französisch",
                "ja": "Japanisch",
                "xyz": "Unknown",
                "English": "",
            },
            "ja": {
                "eng": "英語",
                "fra": "フランス語",
                "en": "英語",
                "fr": "フランス語",
                "ja": "日本語",
                "xyz": "Unknown",
                "English": "",
            },
        }

        for locale, cases in test_cases.items():
            for code, expected_name in cases.items():
                assert provider.get_language_name(code, locale) == expected_name
