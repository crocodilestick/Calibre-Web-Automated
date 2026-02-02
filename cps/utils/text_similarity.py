# -*- coding: utf-8 -*-
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""
Text similarity utilities for metadata matching
"""
from typing import List, Set
import re


def levenshtein_distance(s1: str, s2: str) -> int:
    """
    Calculate Levenshtein distance between two strings.
    Returns the minimum number of single-character edits required to change one word into the other.
    """
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    
    if len(s2) == 0:
        return len(s1)
    
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            # Cost of insertions, deletions, or substitutions
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    
    return previous_row[-1]


def normalized_levenshtein_similarity(s1: str, s2: str) -> float:
    """
    Calculate normalized Levenshtein similarity (0.0 to 1.0).
    1.0 means exact match, 0.0 means completely different.
    """
    s1_norm = normalize_string(s1)
    s2_norm = normalize_string(s2)
    
    if not s1_norm or not s2_norm:
        return 0.0
    
    max_len = max(len(s1_norm), len(s2_norm))
    if max_len == 0:
        return 1.0
    
    distance = levenshtein_distance(s1_norm, s2_norm)
    return 1.0 - (distance / max_len)


def normalize_string(s: str) -> str:
    """
    Normalize a string for comparison:
    - Convert to lowercase
    - Remove special characters and extra whitespace
    - Remove common articles and conjunctions
    """
    if not s:
        return ""
    
    # Convert to lowercase
    s = s.lower()
    
    # Remove common articles and conjunctions
    articles = ['the', 'a', 'an', 'and', '&']
    words = s.split()
    words = [w for w in words if w not in articles]
    s = ' '.join(words)
    
    # Remove special characters except spaces and alphanumeric
    s = re.sub(r'[^\w\s]', '', s)
    
    # Collapse multiple spaces
    s = re.sub(r'\s+', ' ', s)
    
    return s.strip()


def tokenize(s: str) -> Set[str]:
    """
    Tokenize a string into a set of normalized words.
    """
    normalized = normalize_string(s)
    return set(normalized.split())


def jaccard_similarity(s1: str, s2: str) -> float:
    """
    Calculate Jaccard similarity coefficient between two strings (0.0 to 1.0).
    Based on word-level token overlap.
    """
    tokens1 = tokenize(s1)
    tokens2 = tokenize(s2)
    
    if not tokens1 and not tokens2:
        return 1.0
    if not tokens1 or not tokens2:
        return 0.0
    
    intersection = tokens1.intersection(tokens2)
    union = tokens1.union(tokens2)
    
    return len(intersection) / len(union)


def author_list_similarity(authors1: List[str], authors2: List[str]) -> tuple[float, bool]:
    """
    Calculate similarity between two author lists.
    
    Returns:
        tuple: (similarity_score, is_and_match)
            - similarity_score: 0.0 to 1.0
            - is_and_match: True if all authors from the smaller list match (AND logic)
    """
    if not authors1 or not authors2:
        return 0.0, False
    
    # Normalize author names
    norm_authors1 = [normalize_string(a) for a in authors1]
    norm_authors2 = [normalize_string(a) for a in authors2]
    
    # Calculate per-author similarities
    max_scores = []
    for auth1 in norm_authors1:
        # Find best match for this author in the other list
        best_score = max([
            normalized_levenshtein_similarity(auth1, auth2)
            for auth2 in norm_authors2
        ])
        max_scores.append(best_score)
    
    # Check if all authors from smaller list have good matches (>0.8)
    threshold = 0.8
    is_and_match = all(score >= threshold for score in max_scores)
    
    # Overall similarity is average of best matches
    avg_similarity = sum(max_scores) / len(max_scores) if max_scores else 0.0
    
    return avg_similarity, is_and_match


def calculate_year_similarity(year1: str, year2: str) -> float:
    """
    Calculate similarity between publication years.
    Returns 1.0 for exact match, 0.5 for ±1 year, 0.0 otherwise.
    """
    if not year1 or not year2:
        return 0.0
    
    try:
        # Extract 4-digit year from date string
        y1_match = re.search(r'\b(\d{4})\b', str(year1))
        y2_match = re.search(r'\b(\d{4})\b', str(year2))
        
        if not y1_match or not y2_match:
            return 0.0
        
        y1 = int(y1_match.group(1))
        y2 = int(y2_match.group(1))
        
        diff = abs(y1 - y2)
        if diff == 0:
            return 1.0
        elif diff == 1:
            return 0.5
        else:
            return 0.0
    except (ValueError, AttributeError):
        return 0.0
