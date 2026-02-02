# Test Fixtures for Calibre-Web Automated

This directory contains test data used by the CWA test suite.

## Sample Books

All sample books in `sample_books/` are in the **public domain** and sourced from:

### Project Gutenberg
- **License**: Public domain (copyright expired in the United States)
- **URL**: https://www.gutenberg.org/
- **Terms**: These works are free to use, modify, and distribute

Books included from Project Gutenberg:
- "Alice's Adventures in Wonderland" by Lewis Carroll (1865) - EPUB, MOBI, TXT
- "Metamorphosis" by Franz Kafka (1915) - EPUB, TXT
- "A Christmas Carol" by Charles Dickens (1843) - EPUB, TXT
- "The Adventures of Sherlock Holmes" by Arthur Conan Doyle (1892) - EPUB
- "Pride and Prejudice" by Jane Austen (1813) - EPUB (24MB, includes images)

### Standard Ebooks
- **License**: Public domain + CC0 (no copyright)
- **URL**: https://standardebooks.org/
- **Quality**: High-quality formatting and metadata

### Synthetic Test Files
Files prefixed with `test_` are programmatically generated minimal files for testing:
- `test_minimal_valid.epub` - Smallest valid EPUB (for fast tests)
- `test_corrupted.epub` - Invalid file structure (for error handling)
- `test_empty.epub` - Zero-byte file (edge case)
- `test_huge_filename_*.epub` - Filename length limit testing
- `test_special_chars !@#$.epub` - Path handling with ASCII special characters
- `test_international_äöüß_éèêë_áéíóú_ñ_åøæ_książka.epub` - Unicode/international characters (German, French, Spanish, Polish, Nordic)

## Usage

### Download Sample Books
```bash
cd tests/fixtures
python download_gutenberg.py
```

This will download ~5-10 small public domain books in multiple formats (EPUB, MOBI, HTML, TXT).

### Generate Synthetic Test Files
```bash
cd tests/fixtures
python generate_synthetic.py
```

This creates minimal valid and intentionally corrupted files for edge case testing.

## File Size Considerations

- Total fixture size: ~5-10 MB
- Individual books: 200KB - 1MB each
- Synthetic files: <50KB each
- **These files ARE committed to the repository** for reproducible tests

## Copyright Notice

All ebook files in this directory are in the **public domain** in the United States and most other countries. However, some countries may still have copyright restrictions on these works. If you're outside the US, please verify the copyright status in your jurisdiction before redistributing these files.

The test fixture scripts (`download_gutenberg.py`, `generate_synthetic.py`) are:
- Copyright (C) 2024-2025 Calibre-Web Automated contributors
- SPDX-License-Identifier: GPL-3.0-or-later

## Attribution

We are grateful to:
- **Project Gutenberg** for preserving and digitizing public domain literature
- **Standard Ebooks** for producing high-quality public domain ebooks
- All volunteers who contribute to these projects
