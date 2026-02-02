#!/usr/bin/env python3
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""
Comprehensive script to fix all types of duplicate msgid entries in .po files.
Handles:
1. Regular duplicate msgid entries
2. Duplicates between active and obsolete (#~) entries  
3. Multiline msgid duplicates (both regular and obsolete)
"""

import sys
import re

class POEntry:
    def __init__(self, msgid, msgstr, line_start, line_end, is_obsolete=False, is_fuzzy=False):
        self.msgid = msgid
        self.msgstr = msgstr
        self.line_start = line_start
        self.line_end = line_end
        self.is_obsolete = is_obsolete
        self.is_fuzzy = is_fuzzy

def normalize_string(s):
    """Normalize a string by removing quotes and whitespace"""
    return s.strip().strip('"')

def parse_po_file(filename):
    """Parse a .po file and return all entries including obsolete ones"""
    with open(filename, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    entries = []
    i = 0
    
    while i < len(lines):
        line = lines[i].strip()
        
        # Skip empty lines and pure comments (not obsolete entries)
        if not line or (line.startswith('#') and not line.startswith('#~')):
            i += 1
            continue
        
        # Check for fuzzy flag
        is_fuzzy = False
        if line.startswith('#, fuzzy'):
            is_fuzzy = True
            i += 1
            if i >= len(lines):
                break
            line = lines[i].strip()
        
        # Check for msgid (both regular and obsolete)
        if line.startswith('msgid ') or line.startswith('#~ msgid '):
            entry_start = i
            is_obsolete = line.startswith('#~')
            
            # Extract msgid content
            if is_obsolete:
                msgid_content = line[9:].strip()  # Remove '#~ msgid '
            else:
                msgid_content = line[6:].strip()  # Remove 'msgid '
            
            msgid_content = normalize_string(msgid_content)
            
            # Handle multiline msgids
            i += 1
            while i < len(lines):
                next_line = lines[i].strip()
                if is_obsolete and next_line.startswith('#~ "'):
                    msgid_content += normalize_string(next_line[3:])
                elif not is_obsolete and next_line.startswith('"'):
                    msgid_content += normalize_string(next_line)
                else:
                    break
                i += 1
            
            # Look for corresponding msgstr
            msgstr_content = ""
            if i < len(lines):
                msgstr_line = lines[i].strip()
                if msgstr_line.startswith('msgstr ') or msgstr_line.startswith('#~ msgstr '):
                    if is_obsolete:
                        msgstr_content = msgstr_line[10:].strip() if msgstr_line.startswith('#~ msgstr ') else ""
                    else:
                        msgstr_content = msgstr_line[7:].strip() if msgstr_line.startswith('msgstr ') else ""
                    
                    msgstr_content = normalize_string(msgstr_content)
                    i += 1
                    
                    # Handle multiline msgstr
                    while i < len(lines):
                        next_line = lines[i].strip()
                        if is_obsolete and next_line.startswith('#~ "'):
                            msgstr_content += normalize_string(next_line[3:])
                        elif not is_obsolete and next_line.startswith('"'):
                            msgstr_content += normalize_string(next_line)
                        else:
                            break
                        i += 1
            
            # Create entry
            entry = POEntry(
                msgid=msgid_content,
                msgstr=msgstr_content,
                line_start=entry_start,
                line_end=i - 1,
                is_obsolete=is_obsolete,
                is_fuzzy=is_fuzzy
            )
            entries.append(entry)
        else:
            i += 1
    
    return entries, lines

def find_duplicates(entries):
    """Find all types of duplicate msgid entries"""
    msgid_map = {}
    duplicates = []
    
    for entry in entries:
        if not entry.msgid or entry.msgid == '""':  # Skip empty msgids
            continue
            
        if entry.msgid in msgid_map:
            # Found duplicate
            original = msgid_map[entry.msgid]
            duplicates.append({
                'msgid': entry.msgid,
                'original': original,
                'duplicate': entry
            })
        else:
            msgid_map[entry.msgid] = entry
    
    return duplicates

def fix_po_file(filename):
    """Fix all types of duplicate entries in a .po file"""
    print(f"Checking {filename} for all types of duplicates...")
    
    entries, lines = parse_po_file(filename)
    duplicates = find_duplicates(entries)
    
    if not duplicates:
        print("No duplicates found.")
        return
    
    print(f"Found {len(duplicates)} duplicate msgid entries:")
    
    # Create backup
    backup_filename = filename + '.backup'
    with open(backup_filename, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    print(f"Creating backup: {backup_filename}")
    
    # Collect all line ranges to remove (in reverse order)
    lines_to_remove = []
    
    for dup in duplicates:
        original = dup['original']
        duplicate = dup['duplicate']
        
        msgid_preview = dup['msgid'][:50] + ('...' if len(dup['msgid']) > 50 else '')
        
        print(f"\nDuplicate msgid: '{msgid_preview}'")
        print(f"  Original: line {original.line_start + 1} (obsolete: {original.is_obsolete})")
        print(f"  Duplicate: line {duplicate.line_start + 1} (obsolete: {duplicate.is_obsolete})")
        
        # Prefer to keep active entries over obsolete ones
        if original.is_obsolete and not duplicate.is_obsolete:
            # Remove original, keep duplicate
            lines_to_remove.append((original.line_start, original.line_end + 1))
            print(f"  -> Removing original obsolete entry at lines {original.line_start + 1}-{original.line_end + 1}")
        else:
            # Remove duplicate, keep original
            lines_to_remove.append((duplicate.line_start, duplicate.line_end + 1))
            print(f"  -> Removing duplicate entry at lines {duplicate.line_start + 1}-{duplicate.line_end + 1}")
    
    # Sort by start line in reverse order to maintain line numbers while removing
    lines_to_remove.sort(key=lambda x: x[0], reverse=True)
    
    # Remove duplicate entries
    removed_lines = 0
    for start, end in lines_to_remove:
        del lines[start:end]
        removed_lines += end - start
    
    # Write fixed file
    with open(filename, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    
    print(f"\nFixed! Removed {removed_lines} lines containing duplicates.")
    print(f"File has been updated: {filename}")

def main():
    if len(sys.argv) != 2:
        print("Usage: python3 fix_po_duplicates.py <file.po>")
        print("\nThis script fixes all types of duplicate msgid entries in .po files:")
        print("- Regular duplicate msgid entries")
        print("- Duplicates between active and obsolete (#~) entries")
        print("- Multiline msgid duplicates")
        sys.exit(1)
    
    filename = sys.argv[1]
    if not filename.endswith('.po'):
        print("Warning: File doesn't have .po extension")
    
    try:
        fix_po_file(filename)
    except FileNotFoundError:
        print(f"Error: File '{filename}' not found")
        sys.exit(1)
    except Exception as e:
        print(f"Error processing file: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
