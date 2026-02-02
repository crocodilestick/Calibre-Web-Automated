#!/usr/bin/env python3
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""
Simple test to verify basic EPUB ingest works.
"""

import pytest
import time
import shutil
import subprocess
from pathlib import Path


def test_simple_epub_ingest(cwa_container, ingest_folder, library_folder):
    """
    Drop an EPUB and verify it gets processed.
    """
    print("\n" + "="*80)
    print("🧪 SIMPLE EPUB INGEST TEST")
    print("="*80)
    
    # Create a minimal EPUB
    import sys
    tests_dir = Path(__file__).parent
    if str(tests_dir) not in sys.path:
        sys.path.insert(0, str(tests_dir))
    
    from fixtures.generate_synthetic import create_minimal_epub
    
    epub_path = Path("/tmp/simple_test.epub")
    create_minimal_epub(epub_path)
    print(f"✓ Created EPUB: {epub_path} ({epub_path.stat().st_size} bytes)")
    
    # Copy to ingest volume using helper
    ingest_folder.copy_to(epub_path, "simple_test.epub")
    print(f"✓ Copied to ingest volume")
    print(f"✓ File exists in ingest folder: {ingest_folder.file_exists('simple_test.epub')}")
    
    # Check what the container sees
    print("\n🔍 Checking container's view of /cwa-book-ingest:")
    result = subprocess.run(
        ["docker", "exec", "temp-cwa-test-suite", "ls", "-la", "/cwa-book-ingest"],
        capture_output=True, text=True
    )
    print(result.stdout)
    
    # Wait and watch
    print("\n⏳ Waiting for file to be processed...")
    for i in range(30):
        time.sleep(2)
        exists = ingest_folder.file_exists('simple_test.epub')
        print(f"[{(i+1)*2}s] File still exists: {exists}")
        
        if not exists:
            print("✅ File was consumed!")
            break
            
        # Check container view periodically
        if i % 5 == 0:
            result = subprocess.run(
                ["docker", "exec", "temp-cwa-test-suite", "ls", "-la", "/cwa-book-ingest"],
                capture_output=True, text=True
            )
            print(f"Container view:\n{result.stdout}")
    else:
        print("❌ File still exists after 60 seconds")
        
        # Check container logs
        print("\n📋 Container logs:")
        result = subprocess.run(
            ["docker", "logs", "--tail", "50", "temp-cwa-test-suite"],
            capture_output=True, text=True
        )
        print(result.stdout)
        
        pytest.fail("File was not processed")
    
    print("\n" + "="*80)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
