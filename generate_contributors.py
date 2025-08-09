#!/usr/bin/env python3
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2025 Calibre-Web contributors
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""
Generate (or refresh) a CONTRIBUTORS file by querying the GitHub API for:
  * Upstream Calibre-Web repo (janeczku/calibre-web)
  * Fork Calibre-Web Automated repo (crocodilestick/calibre-web-automated)

Features:
  * Handles pagination (per_page=100) until all contributors are fetched.
  * Includes anonymous contributors (?anon=1).
  * Aggregates contribution counts per displayed name.
  * Separates upstream and fork sections for clarity & license attribution.
  * Uses GITHUB_TOKEN if present (recommended to avoid low unauthenticated rate limits).
  * Idempotent: rewrites CONTRIBUTORS file in project root.

Usage:
  export GITHUB_TOKEN=ghp_xxx   # optional but recommended
  python generate_contributors.py

Optional arguments:
  --upstream owner/repo   (default janeczku/calibre-web)
  --fork owner/repo       (default crocodilestick/calibre-web-automated)
  --output FILENAME       (default CONTRIBUTORS)
  --include-avatars       (adds avatar URLs as HTML comments)

The script purposely avoids adding emails (privacy) and does not try to
resolve real names beyond what the contributors endpoint provides.

Requires: requests (falls back to stdlib urllib if unavailable, with reduced functionality)
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time
from typing import Dict, List, Tuple

try:
    import requests  # type: ignore
except ImportError:  # Lightweight fallback (no pagination link parsing beyond basic)
    requests = None  # type: ignore
    import urllib.request
    import urllib.error

DEFAULT_UPSTREAM = "janeczku/calibre-web"
DEFAULT_FORK = "crocodilestick/calibre-web-automated"
START_YEAR_FORK = 2024

API_BASE = "https://api.github.com"
PER_PAGE = 100


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate CONTRIBUTORS file from GitHub API")
    p.add_argument("--upstream", default=DEFAULT_UPSTREAM, help="Upstream owner/repo")
    p.add_argument("--fork", default=DEFAULT_FORK, help="Fork owner/repo")
    p.add_argument("--output", default="CONTRIBUTORS", help="Output filename")
    p.add_argument("--include-avatars", action="store_true", help="Include avatar URLs as comments")
    p.add_argument("--timeout", type=float, default=15.0, help="HTTP timeout seconds")
    p.add_argument("--retries", type=int, default=3, help="Retry attempts on transient errors")
    return p.parse_args()


def gh_headers() -> Dict[str, str]:
    token = os.getenv("GITHUB_TOKEN")
    h = {"Accept": "application/vnd.github+json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def http_get(url: str, timeout: float) -> Tuple[int, Dict[str, str], str]:
    """Returns (status_code, headers, text)."""
    if requests:
        resp = requests.get(url, headers=gh_headers(), timeout=timeout)
        return resp.status_code, dict(resp.headers), resp.text
    else:
        req = urllib.request.Request(url, headers=gh_headers())
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:  # type: ignore
                return r.status, dict(r.headers), r.read().decode()
        except urllib.error.HTTPError as e:  # type: ignore
            return e.code, dict(e.headers), e.read().decode(errors="ignore")


def parse_link_header(headers: Dict[str, str]) -> Dict[str, str]:
    link = headers.get("Link") or headers.get("link")
    res: Dict[str, str] = {}
    if not link:
        return res
    parts = link.split(",")
    for part in parts:
        segs = part.split(";")
        if len(segs) < 2:
            continue
        url_part = segs[0].strip().lstrip("<").rstrip(">")
        rel = None
        for s in segs[1:]:
            if "rel=" in s:
                rel = s.split("=", 1)[1].strip().strip('"')
        if rel:
            res[rel] = url_part
    return res


def fetch_all_contributors(repo: str, timeout: float, retries: int) -> List[Dict]:
    owner_repo = repo
    url = f"{API_BASE}/repos/{owner_repo}/contributors?per_page={PER_PAGE}&anon=1"
    all_items: List[Dict] = []
    while url:
        attempt = 0
        while attempt <= retries:
            status, headers, text = http_get(url, timeout)
            if status == 200:
                break
            attempt += 1
            if status in (403, 429) and attempt <= retries:
                # simple backoff on rate limiting
                time.sleep(2 * attempt)
            else:
                sys.stderr.write(f"Warning: failed to fetch {url} (status {status})\n")
                return all_items
        try:
            data = json.loads(text)
            if not isinstance(data, list):  # Unexpected structure
                sys.stderr.write(f"Warning: unexpected JSON structure for {repo}\n")
                return all_items
            all_items.extend(data)
        except json.JSONDecodeError:
            sys.stderr.write(f"Warning: JSON decode error for {repo}\n")
            return all_items
        links = parse_link_header(headers)
        url = links.get("next")
    return all_items


def aggregate(items: List[Dict]) -> Dict[str, Dict[str, int]]:
    """Return mapping display_name -> {'contributions': int, 'anonymous': 0/1}."""
    agg: Dict[str, Dict[str, int]] = {}
    for c in items:
        login = c.get("login")
        is_anon = 1 if (c.get("type") == "Anonymous" or login is None) else 0
        name = login or c.get("name") or "anonymous"
        entry = agg.setdefault(name, {"contributions": 0, "anonymous": is_anon})
        entry["contributions"] += int(c.get("contributions", 0))
        # If any occurrence is anonymous, keep flag
        entry["anonymous"] = max(entry["anonymous"], is_anon)
    return agg


def format_section(title: str, repo: str, agg: Dict[str, Dict[str, int]], include_avatars: bool, raw_items: List[Dict]) -> str:
    lines = [f"# {title} ({repo})", ""]
    # Map name -> avatar (first occurrence)
    avatar_map: Dict[str, str] = {}
    if include_avatars:
        for c in raw_items:
            key = c.get("login") or c.get("name") or "anonymous"
            if key not in avatar_map and c.get("avatar_url"):
                avatar_map[key] = c["avatar_url"]
    for name, data in sorted(agg.items(), key=lambda x: (-x[1]["contributions"], x[0].lower())):
        anon_mark = " (anon)" if data["anonymous"] else ""
        line = f"- {name}{anon_mark} ({data['contributions']} commits)"
        if include_avatars and name in avatar_map:
            line += f"  <!-- avatar: {avatar_map[name]} -->"
        lines.append(line)
    lines.append("")
    return "\n".join(lines)


def build_contributors(upstream: str, fork: str, include_avatars: bool, timeout: float, retries: int) -> str:
    upstream_items = fetch_all_contributors(upstream, timeout, retries)
    fork_items = fetch_all_contributors(fork, timeout, retries)

    upstream_agg = aggregate(upstream_items)
    fork_agg = aggregate(fork_items)

    year_now = datetime.date.today().year

    header = [
        "CONTRIBUTORS",
        "",  # blank line
        "This file is automatically generated. DO NOT EDIT MANUALLY.",
        f"Generated on: {datetime.datetime.utcnow().isoformat()}Z",
        "",  # blank line
        f"Upstream project: https://github.com/{upstream}",
        f"Fork project (Calibre-Web Automated, since {START_YEAR_FORK}): https://github.com/{fork}",
        "",  # blank
        "License notice: This fork retains attribution to original Calibre-Web contributors in accordance with GPL-3.0-or-later.",
        "",  # blank
        f"Copyright (C) 2018-{year_now} Calibre-Web contributors",
        f"Copyright (C) {START_YEAR_FORK}-{year_now} Calibre-Web Automated contributors",
        "",
    ]

    upstream_section = format_section("Upstream Contributors", upstream, upstream_agg, include_avatars, upstream_items)
    fork_section = format_section("Fork Contributors", fork, fork_agg, include_avatars, fork_items)

    return "\n".join(header) + upstream_section + fork_section


def main() -> int:
    args = parse_args()
    content = build_contributors(args.upstream, args.fork, args.include_avatars, args.timeout, args.retries)
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Wrote {args.output} (contributors from {args.upstream} and {args.fork})")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
