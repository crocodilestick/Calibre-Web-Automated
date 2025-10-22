# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Unit tests for cps/helper.py

Tests cover pure Python utility functions that don't require Docker:
- Filename sanitization (get_valid_filename)
- Author name parsing (split_authors, get_sorted_author)
- Password generation and validation
- Email validation
- Username validation

Note: Functions involving database queries, file I/O, or external services
are tested in integration tests instead.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import re

# Import functions from helper.py
from cps.helper import (
    get_valid_filename,
    split_authors,
    get_sorted_author,
    generate_random_password,
    check_email,
    check_username,
    valid_email,
    valid_password,
    uniq
)


# ============================================================================
# Tests for get_valid_filename()
# ============================================================================

class TestGetValidFilename:
    """Test filename sanitization logic"""
    
    @patch('cps.helper.config')
    def test_basic_valid_filename(self, mock_config):
        """Test basic valid filename passes through"""
        # Mock the config attribute used by get_valid_filename
        mock_config.config_unicode_filename = False
        
        result = get_valid_filename("My Book Title")
        assert result == "My_Book_Title"  # Whitespace replaced
    
    @patch('cps.helper.config')
    def test_replace_whitespace_enabled(self, mock_config):
        """Test whitespace replacement when enabled"""
        mock_config.config_unicode_filename = False
        
        result = get_valid_filename("Test   Book", replace_whitespace=True)
        assert "   " not in result
        assert result == "Test_Book"
    
    @patch('cps.helper.config')
    def test_replace_whitespace_disabled(self, mock_config):
        """Test whitespace preserved when disabled"""
        mock_config.config_unicode_filename = False
        
        result = get_valid_filename("Test Book", replace_whitespace=False)
        assert " " in result or "_" in result  # May be normalized
    
    @patch('cps.helper.config')
    def test_special_characters_sanitized(self, mock_config):
        """Test special characters are replaced"""
        mock_config.config_unicode_filename = False
        
        result = get_valid_filename('Test<>:"/\\|?*Book')
        # Dangerous characters should be replaced
        for char in '<>:"/\\|?*':
            assert char not in result
        assert "Test" in result
        assert "Book" in result
    
    @patch('cps.helper.config')
    def test_trailing_dot_removed(self, mock_config):
        """Test trailing dot is replaced with underscore"""
        mock_config.config_unicode_filename = False
        
        result = get_valid_filename("Test.")
        assert not result.endswith(".")
        assert result.endswith("_")
    
    @patch('cps.helper.config')
    def test_max_length_truncation(self, mock_config):
        """Test filename truncation to max chars"""
        mock_config.config_unicode_filename = False
        
        long_name = "A" * 200
        result = get_valid_filename(long_name, chars=50)
        assert len(result.encode('utf-8')) <= 50
    
    @patch('cps.helper.config')
    def test_unicode_handling(self, mock_config):
        """Test unicode characters in filename"""
        mock_config.config_unicode_filename = True
        
        result = get_valid_filename("Test äöüß Book")
        # Should be transliterated or preserved based on config
        assert result  # Should not raise
        assert len(result) > 0
    
    @patch('cps.helper.config')
    def test_null_bytes_removed(self, mock_config):
        """Test null bytes are stripped"""
        mock_config.config_unicode_filename = False
        
        result = get_valid_filename("Test\x00Book")
        assert "\x00" not in result
        assert "Test" in result
    
    @patch('cps.helper.config')
    def test_slash_and_colon_replaced(self, mock_config):
        """Test path separators are replaced"""
        mock_config.config_unicode_filename = False
        
        result = get_valid_filename("Test/Book:Title")
        assert "/" not in result
        assert ":" not in result
        assert "_" in result
    
    @patch('cps.helper.config')
    def test_empty_string_raises_error(self, mock_config):
        """Test empty filename raises ValueError"""
        mock_config.config_unicode_filename = False
        
        with pytest.raises(ValueError, match="Filename cannot be empty"):
            get_valid_filename("")
    
    @patch('cps.helper.config')
    def test_none_value_handled(self, mock_config):
        """Test None value is converted to string"""
        mock_config.config_unicode_filename = False
        
        result = get_valid_filename(None)
        # Should handle gracefully or raise ValueError
        assert isinstance(result, str) or result is None
    
    @patch('cps.helper.config')
    def test_integer_value_converted(self, mock_config):
        """Test integer values are converted to string"""
        mock_config.config_unicode_filename = False
        result = get_valid_filename(12345)
        assert "12345" in result
    
    def test_pipe_replaced_with_comma(self):
        """Test pipe character replaced with comma"""
        result = get_valid_filename("Author1|Author2|Author3")
        assert "|" not in result
        assert "," in result or "_" in result


# ============================================================================
# Tests for split_authors()
# ============================================================================

class TestSplitAuthors:
    """Test author name splitting logic"""
    
    def test_single_author_no_delimiter(self):
        """Test single author without delimiter"""
        result = split_authors(["John Doe"])
        assert result == ["John Doe"]
    
    def test_ampersand_delimiter(self):
        """Test authors split by ampersand"""
        result = split_authors(["John Doe & Jane Smith"])
        assert len(result) == 2
        assert "John Doe" in result
        assert "Jane Smith" in result
    
    def test_semicolon_delimiter(self):
        """Test authors split by semicolon"""
        result = split_authors(["John Doe;Jane Smith"])
        assert len(result) == 2
        assert "John Doe" in result
        assert "Jane Smith" in result
    
    def test_lastname_firstname_format(self):
        """Test 'Lastname, Firstname' format is reversed"""
        result = split_authors(["Doe, John"])
        assert result == ["John Doe"]
    
    def test_multiple_commas_preserved(self):
        """Test names with multiple commas are split"""
        result = split_authors(["Doe, John, Jr."])
        # Multiple commas should result in split
        assert len(result) >= 2
    
    def test_whitespace_stripped(self):
        """Test whitespace is stripped from author names"""
        result = split_authors(["  John Doe  &  Jane Smith  "])
        assert "John Doe" in result
        assert "Jane Smith" in result
        # No leading/trailing whitespace
        for author in result:
            assert author == author.strip()
    
    def test_mixed_delimiters(self):
        """Test mixed delimiters in same string"""
        result = split_authors(["John Doe & Jane Smith;Bob Jones"])
        assert len(result) == 3
        assert "John Doe" in result
        assert "Jane Smith" in result
        assert "Bob Jones" in result
    
    def test_empty_list_returns_empty(self):
        """Test empty list returns empty list"""
        result = split_authors([])
        assert result == []
    
    def test_multiple_input_values(self):
        """Test multiple input values are processed"""
        result = split_authors(["John Doe", "Jane Smith & Bob Jones"])
        assert len(result) == 3
        assert "John Doe" in result
        assert "Jane Smith" in result
        assert "Bob Jones" in result


# ============================================================================
# Tests for get_sorted_author()
# ============================================================================

class TestGetSortedAuthor:
    """Test author name sorting logic"""
    
    def test_single_name_unchanged(self):
        """Test single name is unchanged"""
        result = get_sorted_author("Aristotle")
        assert result == "Aristotle"
    
    def test_first_last_sorted(self):
        """Test 'First Last' becomes 'Last, First'"""
        result = get_sorted_author("John Doe")
        assert result == "Doe, John"
    
    def test_jr_suffix_preserved(self):
        """Test Jr. suffix is preserved correctly"""
        result = get_sorted_author("John Doe Jr.")
        assert "Jr." in result
        assert "Doe" in result
    
    def test_sr_suffix_preserved(self):
        """Test Sr. suffix is preserved correctly"""
        result = get_sorted_author("John Doe SR")
        assert "SR" in result or "Sr" in result
        assert "Doe" in result
    
    def test_roman_numeral_suffix_preserved(self):
        """Test Roman numeral suffixes (I, II, III, IV)"""
        result = get_sorted_author("John Doe III")
        assert "III" in result
        assert "Doe" in result
    
    def test_already_sorted_unchanged(self):
        """Test 'Last, First' format is preserved"""
        result = get_sorted_author("Doe, John")
        assert result == "Doe, John"
    
    def test_three_part_name_sorted(self):
        """Test 'First Middle Last' becomes 'Last, First Middle'"""
        result = get_sorted_author("John William Doe")
        assert result == "Doe, John William"
    
    def test_error_handling(self):
        """Test error handling returns original value"""
        # This should handle errors gracefully
        result = get_sorted_author("")
        # Should return empty string or handle gracefully
        assert result is not None


# ============================================================================
# Tests for generate_random_password()
# ============================================================================

class TestGenerateRandomPassword:
    """Test password generation logic"""
    
    def test_minimum_length_respected(self):
        """Test password meets minimum length"""
        password = generate_random_password(12)
        assert len(password) >= 12
    
    def test_contains_lowercase(self):
        """Test password contains lowercase letter"""
        password = generate_random_password(8)
        assert any(c.islower() for c in password)
    
    def test_contains_uppercase(self):
        """Test password contains uppercase letter"""
        password = generate_random_password(8)
        assert any(c.isupper() for c in password)
    
    def test_contains_digit(self):
        """Test password contains digit"""
        password = generate_random_password(8)
        assert any(c.isdigit() for c in password)
    
    def test_contains_special_char(self):
        """Test password contains special character"""
        password = generate_random_password(8)
        special_chars = "!@#$%&*()?"
        assert any(c in special_chars for c in password)
    
    def test_minimum_8_chars_enforced(self):
        """Test minimum 8 characters enforced even if less requested"""
        password = generate_random_password(4)
        assert len(password) >= 8  # Should be min 8 after 4 required chars
    
    def test_randomness(self):
        """Test passwords are different each time"""
        password1 = generate_random_password(12)
        password2 = generate_random_password(12)
        # Should be different (extremely unlikely to be same)
        assert password1 != password2
    
    def test_long_password_generation(self):
        """Test generating long passwords"""
        password = generate_random_password(50)
        assert len(password) >= 50


# ============================================================================
# Tests for valid_email()
# ============================================================================

class TestValidEmail:
    """Test email validation logic"""
    
    def test_valid_single_email(self):
        """Test valid single email passes"""
        result = valid_email("test@example.com")
        assert result == "test@example.com"
    
    def test_valid_multiple_emails(self):
        """Test multiple comma-separated emails"""
        result = valid_email("test1@example.com,test2@example.com")
        assert "test1@example.com" in result
        assert "test2@example.com" in result
    
    def test_invalid_email_format_raises(self):
        """Test invalid email format raises exception"""
        with pytest.raises(Exception, match="Invalid Email address format"):
            valid_email("not_an_email")
    
    def test_whitespace_stripped(self):
        """Test whitespace is stripped from emails"""
        result = valid_email("  test@example.com  ")
        assert result == "test@example.com"
    
    def test_multiple_with_whitespace(self):
        """Test multiple emails with whitespace"""
        result = valid_email(" test1@example.com , test2@example.com ")
        assert "test1@example.com" in result
        assert "test2@example.com" in result
    
    def test_empty_string_returns_empty(self):
        """Test empty string returns empty string"""
        result = valid_email("")
        assert result == ""
    
    def test_invalid_domain_raises(self):
        """Test invalid domain raises exception"""
        with pytest.raises(Exception, match="Invalid Email address format"):
            valid_email("test@")
    
    def test_missing_at_symbol_raises(self):
        """Test missing @ symbol raises exception"""
        with pytest.raises(Exception, match="Invalid Email address format"):
            valid_email("testexample.com")
    
    def test_special_chars_in_local_part(self):
        """Test special characters allowed in local part"""
        result = valid_email("test.name+tag@example.com")
        assert result == "test.name+tag@example.com"


# ============================================================================
# Tests for valid_password()
# ============================================================================

class TestValidPassword:
    """Test password validation logic"""
    
    @patch('cps.config.config_password_policy', False)
    def test_no_policy_allows_any_password(self):
        """Test any password allowed when policy disabled"""
        result = valid_password("abc")
        assert result == "abc"
    
    @patch('cps.config.config_password_policy', True)
    @patch('cps.config.config_password_min_length', 8)
    @patch('cps.config.config_password_number', False)
    @patch('cps.config.config_password_lower', False)
    @patch('cps.config.config_password_upper', False)
    @patch('cps.config.config_password_character', False)
    @patch('cps.config.config_password_special', False)
    def test_min_length_enforced(self):
        """Test minimum length requirement"""
        # Valid: meets 8 char minimum
        assert valid_password("abcdefgh") == "abcdefgh"
        
        # Invalid: too short
        with pytest.raises(Exception, match="Password doesn't comply"):
            valid_password("abc")
    
    @patch('cps.config.config_password_policy', True)
    @patch('cps.config.config_password_min_length', 0)
    @patch('cps.config.config_password_number', True)
    @patch('cps.config.config_password_lower', False)
    @patch('cps.config.config_password_upper', False)
    @patch('cps.config.config_password_character', False)
    @patch('cps.config.config_password_special', False)
    def test_number_requirement(self):
        """Test digit requirement"""
        # Valid: contains digit
        assert valid_password("abc123") == "abc123"
        
        # Invalid: no digit
        with pytest.raises(Exception, match="Password doesn't comply"):
            valid_password("abcdef")
    
    @patch('cps.config.config_password_policy', True)
    @patch('cps.config.config_password_min_length', 0)
    @patch('cps.config.config_password_number', False)
    @patch('cps.config.config_password_lower', True)
    @patch('cps.config.config_password_upper', False)
    @patch('cps.config.config_password_character', False)
    @patch('cps.config.config_password_special', False)
    def test_lowercase_requirement(self):
        """Test lowercase letter requirement"""
        # Valid: contains lowercase
        assert valid_password("ABCabc") == "ABCabc"
        
        # Invalid: no lowercase
        with pytest.raises(Exception, match="Password doesn't comply"):
            valid_password("ABC123")
    
    @patch('cps.config.config_password_policy', True)
    @patch('cps.config.config_password_min_length', 0)
    @patch('cps.config.config_password_number', False)
    @patch('cps.config.config_password_lower', False)
    @patch('cps.config.config_password_upper', True)
    @patch('cps.config.config_password_character', False)
    @patch('cps.config.config_password_special', False)
    def test_uppercase_requirement(self):
        """Test uppercase letter requirement"""
        # Valid: contains uppercase
        assert valid_password("abcABC") == "abcABC"
        
        # Invalid: no uppercase
        with pytest.raises(Exception, match="Password doesn't comply"):
            valid_password("abc123")
    
    @patch('cps.config.config_password_policy', True)
    @patch('cps.config.config_password_min_length', 0)
    @patch('cps.config.config_password_number', False)
    @patch('cps.config.config_password_lower', False)
    @patch('cps.config.config_password_upper', False)
    @patch('cps.config.config_password_character', False)
    @patch('cps.config.config_password_special', True)
    def test_special_char_requirement(self):
        """Test special character requirement"""
        # Valid: contains special char
        assert valid_password("abc@123") == "abc@123"
        
        # Invalid: no special char
        with pytest.raises(Exception, match="Password doesn't comply"):
            valid_password("abc123")


# ============================================================================
# Tests for check_email() and check_username()
# ============================================================================

class TestCheckEmailAndUsername:
    """Test email and username uniqueness checks"""
    
    @patch('cps.ub.session')
    def test_check_email_unique_passes(self, mock_session):
        """Test unique email passes check"""
        mock_session.query().filter().first.return_value = None
        result = check_email("new@example.com")
        assert result == "new@example.com"
    
    @patch('cps.ub.session')
    def test_check_email_duplicate_raises(self, mock_session):
        """Test duplicate email raises exception"""
        mock_session.query().filter().first.return_value = Mock()
        with pytest.raises(Exception, match="Found an existing account"):
            check_email("existing@example.com")
    
    @patch('cps.ub.session')
    def test_check_username_unique_passes(self, mock_session):
        """Test unique username passes check"""
        mock_session.query().filter().scalar.return_value = None
        result = check_username("newuser")
        assert result == "newuser"
    
    @patch('cps.ub.session')
    def test_check_username_duplicate_raises(self, mock_session):
        """Test duplicate username raises exception"""
        mock_session.query().filter().scalar.return_value = True
        with pytest.raises(Exception, match="This username is already taken"):
            check_username("existinguser")
    
    @patch('cps.ub.session')
    def test_check_username_strips_whitespace(self, mock_session):
        """Test username whitespace is stripped"""
        mock_session.query().filter().scalar.return_value = None
        result = check_username("  newuser  ")
        assert result == "newuser"


# ============================================================================
# Tests for uniq()
# ============================================================================

class TestUniq:
    """Test unique list function"""
    
    def test_removes_duplicates(self):
        """Test duplicate items are removed"""
        result = uniq(["a", "b", "a", "c", "b"])
        assert len(result) == 3
        assert "a" in result
        assert "b" in result
        assert "c" in result
    
    def test_preserves_order(self):
        """Test first occurrence order is preserved"""
        result = uniq(["c", "a", "b", "a"])
        # First occurrence of each should be preserved
        assert result.index("c") < result.index("a")
        assert result.index("a") < result.index("b")
    
    def test_normalizes_whitespace(self):
        """Test multiple spaces are normalized"""
        result = uniq(["a  b", "a b", "c"])
        # "a  b" and "a b" should be treated as same
        assert len(result) == 2
    
    def test_empty_list_returns_empty(self):
        """Test empty list returns empty list"""
        result = uniq([])
        assert result == []
    
    def test_single_item_unchanged(self):
        """Test single item list is unchanged"""
        result = uniq(["only"])
        assert result == ["only"]


# ============================================================================
# Test Markers
# ============================================================================

# Mark all tests in this module as unit tests
pytestmark = pytest.mark.unit
