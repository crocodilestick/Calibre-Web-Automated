# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Unit tests for cps/services/hardcover.py

Tests cover:
- escape_markdown function
"""

import pytest
from cps.services import hardcover


@pytest.mark.unit
class TestEscapeMarkdown:
    """Test escape_markdown function"""
    
    def test_escape_all_special_characters(self):
        """Test that all markdown special characters are escaped"""
        text = '\\`*_{}[]()#+-.!|'
        result = hardcover.escape_markdown(text)
        
        # Each special character should be prefixed with backslash
        expected = '\\\\\\`\\*\\_\\{\\}\\[\\]\\(\\)\\#\\+\\-\\.\\!\\|'
        assert result == expected
        
        # Individual character assertions for better failure diagnostics
        assert '\\\\' in result  # backslash
        assert '\\`' in result   # backtick
        assert '\\*' in result   # asterisk
        assert '\\_' in result   # underscore
        assert '\\{' in result   # left brace
        assert '\\}' in result   # right brace
        assert '\\[' in result   # left bracket
        assert '\\]' in result   # right bracket
        assert '\\(' in result   # left paren
        assert '\\)' in result   # right paren
        assert '\\#' in result   # hash
        assert '\\+' in result   # plus
        assert '\\-' in result   # minus
        assert '\\.' in result   # dot
        assert '\\!' in result   # exclamation
        assert '\\|' in result   # pipe
    
    def test_escape_text_with_special_chars(self):
        """Test escaping text containing special characters"""
        text = 'This is a *bold* statement with `code` and _italic_'
        result = hardcover.escape_markdown(text)
        
        assert '\\*bold\\*' in result
        assert '\\`code\\`' in result
        assert '\\_italic\\_' in result
    
    def test_plain_text_unchanged(self):
        """Test that plain text without special characters is unchanged"""
        text = 'This is plain text without special characters'
        result = hardcover.escape_markdown(text)
        
        assert result == text
    
    def test_empty_string_returns_empty(self):
        """Test that empty string returns empty string"""
        result = hardcover.escape_markdown('')
        assert result == ''
    
    def test_none_returns_none(self):
        """Test that None returns None"""
        result = hardcover.escape_markdown(None)
        assert result is None
    
    def test_escape_backslash(self):
        """Test that backslash is properly escaped"""
        text = 'This has a \\ backslash'
        result = hardcover.escape_markdown(text)
        
        # Backslash should be escaped
        assert '\\\\' in result
    
    def test_escape_brackets(self):
        """Test that brackets are escaped"""
        text = 'Link [text](url)'
        result = hardcover.escape_markdown(text)
        
        assert '\\[' in result
        assert '\\]' in result
        assert '\\(' in result
        assert '\\)' in result
    
    def test_escape_hash_in_text(self):
        """Test that hash symbols are escaped"""
        text = 'Heading #1 and #2'
        result = hardcover.escape_markdown(text)
        
        assert '\\#1' in result
        assert '\\#2' in result
    
    def test_escape_plus_and_minus(self):
        """Test that plus and minus are escaped"""
        text = 'Plus + and minus -'
        result = hardcover.escape_markdown(text)
        
        assert '\\+' in result
        assert '\\-' in result
    
    def test_escape_dot_and_exclamation(self):
        """Test that dot and exclamation are escaped"""
        text = 'Dot . and exclamation !'
        result = hardcover.escape_markdown(text)
        
        assert '\\.' in result
        assert '\\!' in result
    
    def test_escape_pipe(self):
        """Test that pipe character is escaped"""
        text = 'Column1 | Column2'
        result = hardcover.escape_markdown(text)
        
        assert '\\|' in result
    
    def test_escape_curly_braces(self):
        """Test that curly braces are escaped"""
        text = 'Value {value}'
        result = hardcover.escape_markdown(text)
        
        assert '\\{' in result
        assert '\\}' in result
    
    def test_escape_underscore(self):
        """Test that underscore is escaped"""
        text = 'Underscore _text_'
        result = hardcover.escape_markdown(text)
        
        assert '\\_' in result
    
    def test_escape_mixed_content(self):
        """Test escaping mixed content with normal and special characters"""
        text = 'Normal text with *bold* and `code` and [link](url)'
        result = hardcover.escape_markdown(text)
        
        # Verify special chars are escaped but normal text remains
        assert 'Normal text with' in result
        assert '\\*bold\\*' in result
        assert '\\`code\\`' in result
        assert '\\[link\\]' in result
        assert '\\(url\\)' in result

