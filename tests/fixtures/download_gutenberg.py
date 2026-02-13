#!/usr/bin/env python3
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""
Download public domain ebooks from Project Gutenberg for testing.

This script downloads a curated set of small public domain books
in multiple formats (EPUB, MOBI, HTML, TXT) for use in CWA tests.

Usage:
    python download_gutenberg.py
"""

import urllib.request
import urllib.error
from pathlib import Path
import sys
import hashlib

# Project Gutenberg mirror (official)
BASE_URL = "https://www.gutenberg.org/cache/epub"

# Curated list of small, well-formatted public domain books
# Format: (gutenberg_id, title, author, formats_to_download)
BOOKS = [
    (11, "alice_in_wonderland", "Lewis Carroll", ["epub", "mobi", "txt"]),
    (5200, "metamorphosis", "Franz Kafka", ["epub", "kindle", "txt"]),
    (46, "christmas_carol", "Charles Dickens", ["epub", "kindle", "txt"]),
    (1661, "sherlock_holmes", "Arthur Conan Doyle", ["epub", "kindle"]),
    (1342, "pride_and_prejudice", "Jane Austen", ["epub", "kindle"]),
]

# Expected file sizes (approximate, for validation)
EXPECTED_SIZES = {
    "epub": (50_000, 2_000_000),    # 50KB - 2MB
    "mobi": (50_000, 2_000_000),    # 50KB - 2MB
    "kindle": (50_000, 2_000_000),  # 50KB - 2MB (AZW3 format)
    "txt": (10_000, 1_000_000),     # 10KB - 1MB
    "html": (20_000, 3_000_000),    # 20KB - 3MB
}


def download_file(url: str, dest: Path, max_retries: int = 3) -> bool:
    """Download a file with retry logic and validation."""
    for attempt in range(max_retries):
        try:
            print(f"  Downloading from {url}... (attempt {attempt + 1}/{max_retries})")
            
            # Set user agent (required by some servers)
            req = urllib.request.Request(
                url,
                headers={
                    'User-Agent': 'CWA-Test-Suite/1.0 (https://github.com/crocodilestick/Calibre-Web-Automated)'
                }
            )
            
            with urllib.request.urlopen(req, timeout=30) as response:
                data = response.read()
                
            # Validate file size
            file_size = len(data)
            file_ext = dest.suffix[1:]  # Remove leading dot
            
            if file_ext in EXPECTED_SIZES:
                min_size, max_size = EXPECTED_SIZES[file_ext]
                if not (min_size <= file_size <= max_size):
                    print(f"  WARNING: File size {file_size} bytes outside expected range {min_size}-{max_size}")
            
            # Write to disk
            dest.write_bytes(data)
            
            print(f"  ✓ Downloaded {dest.name} ({file_size:,} bytes)")
            return True
            
        except urllib.error.HTTPError as e:
            if e.code == 404:
                print(f"  ✗ File not found (404): {url}")
                return False
            elif e.code == 403:
                print(f"  ✗ Access forbidden (403): {url}")
                return False
            else:
                print(f"  ✗ HTTP error {e.code}: {e.reason}")
                if attempt == max_retries - 1:
                    return False
                    
        except urllib.error.URLError as e:
            print(f"  ✗ Network error: {e.reason}")
            if attempt == max_retries - 1:
                return False
                
        except Exception as e:
            print(f"  ✗ Unexpected error: {e}")
            if attempt == max_retries - 1:
                return False
    
    return False


def download_book(gutenberg_id: int, slug: str, author: str, formats: list[str], output_dir: Path) -> int:
    """Download a book in specified formats. Returns count of successful downloads."""
    print(f"\n📚 Downloading: {slug} by {author} (ID: {gutenberg_id})")
    
    success_count = 0
    
    for fmt in formats:
        # Construct Gutenberg URL
        # Pattern: https://www.gutenberg.org/cache/epub/{id}/pg{id}.{format}
        # Exception: EPUB uses .epub.noimages for smaller size
        
        if fmt == "epub":
            # Try noimages version first (smaller), fallback to images version
            urls = [
                f"{BASE_URL}/{gutenberg_id}/pg{gutenberg_id}-images.epub",
                f"{BASE_URL}/{gutenberg_id}/pg{gutenberg_id}.epub",
            ]
        elif fmt == "mobi":
            # MOBI format (older Kindle format)
            urls = [f"{BASE_URL}/{gutenberg_id}/pg{gutenberg_id}.mobi"]
        elif fmt == "kindle":
            # Kindle format (AZW3) - Project Gutenberg uses .kf8.book extension
            # We'll rename to .azw3 for consistency
            urls = [
                f"{BASE_URL}/{gutenberg_id}/pg{gutenberg_id}.kf8.book",
            ]
        elif fmt == "txt":
            # UTF-8 encoded text
            urls = [f"{BASE_URL}/{gutenberg_id}/pg{gutenberg_id}.txt"]
        elif fmt == "html":
            urls = [
                f"{BASE_URL}/{gutenberg_id}/pg{gutenberg_id}-h.zip",  # HTML with images
                f"{BASE_URL}/{gutenberg_id}/pg{gutenberg_id}.html",
            ]
        else:
            print(f"  ⚠ Unsupported format: {fmt}")
            continue
        
        # Try each URL variant
        downloaded = False
        for url in urls:
            # Special handling for Kindle format - rename .kf8.book to .azw3
            if fmt == "kindle":
                dest_file = output_dir / f"{slug}.azw3"
            else:
                dest_file = output_dir / f"{slug}.{fmt}"
            
            if dest_file.exists():
                print(f"  ⏭ Already exists: {dest_file.name}")
                success_count += 1
                downloaded = True
                break
            
            if download_file(url, dest_file):
                success_count += 1
                downloaded = True
                break
        
        if not downloaded:
            print(f"  ⚠ Failed to download {fmt} format for {slug}")
    
    return success_count


def main():
    """Main entry point."""
    print("=" * 70)
    print("CWA Test Fixture Downloader")
    print("Downloading public domain ebooks from Project Gutenberg")
    print("=" * 70)
    
    # Get output directory
    script_dir = Path(__file__).parent
    output_dir = script_dir / "sample_books"
    output_dir.mkdir(exist_ok=True)
    
    print(f"\n📂 Output directory: {output_dir}")
    print(f"📖 Books to download: {len(BOOKS)}")
    
    # Download all books
    total_downloaded = 0
    total_failed = 0
    
    for gutenberg_id, slug, author, formats in BOOKS:
        count = download_book(gutenberg_id, slug, author, formats, output_dir)
        total_downloaded += count
        total_failed += len(formats) - count
    
    # Summary
    print("\n" + "=" * 70)
    print("📊 Download Summary")
    print("=" * 70)
    print(f"✓ Successfully downloaded: {total_downloaded} files")
    print(f"✗ Failed downloads: {total_failed} files")
    
    # List downloaded files
    files = sorted(output_dir.glob("*"))
    if files:
        print(f"\n📁 Downloaded files ({len(files)}):")
        total_size = 0
        for f in files:
            size = f.stat().st_size
            total_size += size
            print(f"  - {f.name:<40} {size:>10,} bytes")
        print(f"\n💾 Total size: {total_size:,} bytes ({total_size / 1024 / 1024:.2f} MB)")
    
    print("\n✅ Download complete!")
    print("\nNext steps:")
    print("  1. Run: python generate_synthetic.py")
    print("  2. Run tests: pytest tests/")
    
    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
