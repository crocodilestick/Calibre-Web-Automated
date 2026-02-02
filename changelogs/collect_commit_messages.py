#!/usr/bin/env python3
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2024-2025 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.

"""Collect commit messages across multiple git projects since a given commit.

Usage examples:
    python changelogs/collect_commit_messages.py <since_commit>
    python changelogs/collect_commit_messages.py <since_commit> --aggregate --body
    python changelogs/collect_commit_messages.py <since_commit> --root /other/path --output commits.txt

Contract / behavior:
  Inputs:
    - since_commit (positional): Commit hash, tag, or ref to start AFTER (exclusive).
    - --root: Root directory to recursively search for git repositories. Default = git repo root (auto-detected) or CWD fallback.
    - --max-depth: Maximum directory depth to search (default=6) to avoid huge traversals.
    - --output: Optional output file (UTF-8). If omitted, prints to stdout.
    - --aggregate: If set, all commits across repos are merged chronologically instead of grouped by repo.
    - --include-merges: Include merge commits (default: True).
    - --body: Include body lines (default: True).
    - --subjects-only: Output ONLY the commit subject lines (suppresses repo/hash/date/body formatting). Overrides --body.
    - --markdown-list: Render output as a Markdown bullet list (commit lines become "- <text>"). Headings (### repo) preserved. (Default: True)
    - --no-strip-newlines: Preserve blank lines inside commit bodies (default: bodies are compacted to single line).
    - --since-date / --until-date: Additional date filters applied per repo (optional, ISO format or anything git understands).
    - --reverse: Output from oldest to newest (default newest to oldest within each grouping / aggregated list).
  Output:
    - Text list of commits either grouped by repo or globally aggregated.
    - Each commit line starts with: <repo_name> | <commit_hash> | <author_date_iso> | <subject>[ | <body>]
  Exit codes:
    0 success (even if no commits found)
    1 usage / argument error
    2 git command failure (unexpected)

Edge cases handled:
  - Repositories where the since_commit doesn't exist: they are skipped with a warning.
  - Shallow clones: still works; only commits present are considered.
  - Identical repo directories (duplicates by path) avoided.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, List, Optional


@dataclass
class Commit:
    repo: str
    hash: str
    date: datetime
    subject: str
    body: str

    def format(self, include_body: bool, preserve_newlines: bool) -> str:
        body_part = ""
        if include_body and self.body:
            body = self.body.rstrip("\n")
            if not preserve_newlines:
                body = " ".join(line.strip() for line in body.splitlines() if line.strip())
            body_part = f" | {body}"
        return f"{self.repo} | {self.hash} | {self.date.isoformat()} | {self.subject}{body_part}"


def discover_repos(root: str, max_depth: int) -> List[str]:
    repos: List[str] = []
    root = os.path.abspath(root)
    root_depth = root.count(os.sep)
    for dirpath, dirnames, filenames in os.walk(root):
        depth = dirpath.count(os.sep) - root_depth
        if depth > max_depth:
            # Prune deeper traversal
            dirnames[:] = []
            continue
        if ".git" in dirnames:
            repos.append(dirpath)
            # Don't recurse into subdirectories of a repo root (avoid nested repos / submodules traversal)
            dirnames[:] = [d for d in dirnames if d == ".git"]
    return sorted(repos)


def git_exists_commit(repo_path: str, commit: str) -> bool:
    try:
        subprocess.run(
            ["git", "-C", repo_path, "rev-parse", "--verify", f"{commit}^{{commit}}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def collect_commits(
    repo_path: str,
    since_commit: str,
    include_merges: bool,
    include_body: bool,
    since_date: Optional[str],
    until_date: Optional[str],
) -> Iterable[Commit]:
    # Build git log command
    format_tokens = ["%H", "%ad", "%s"]
    if include_body:
        format_tokens.append("%b")
    pretty = "%x1f".join(format_tokens) + "%x1e"  # unit separator fields, record sep at end

    cmd = [
        "git",
        "-C",
        repo_path,
        "log",
        f"{since_commit}..HEAD",
        f"--pretty=format:{pretty}",
        "--date=iso-strict",
    ]
    if not include_merges:
        cmd.append("--no-merges")
    if since_date:
        cmd.append(f"--since={since_date}")
    if until_date:
        cmd.append(f"--until={until_date}")

    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
    except subprocess.CalledProcessError as e:
        print(f"[collect-commits] ERROR running git log in {repo_path}: {e.stderr.strip()}", file=sys.stderr)
        raise SystemExit(2)

    repo_name = os.path.basename(repo_path.rstrip(os.sep))
    raw = proc.stdout
    if not raw:
        return []
    records = raw.strip("\n\x1e").split("\x1e") if raw else []
    commits: List[Commit] = []
    for rec in records:
        if not rec.strip():
            continue
        parts = rec.split("\x1f")
        if len(parts) < 3:
            continue
        h, date_str, subject = parts[:3]
        body = parts[3] if include_body and len(parts) > 3 else ""
        try:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        except ValueError:
            # Fallback parse
            dt = datetime.strptime(date_str.split(" ")[0], "%Y-%m-%d")
        commits.append(Commit(repo=repo_name, hash=h, date=dt, subject=subject, body=body))
    return commits


def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Collect commit messages across git repositories since a given commit.")
    p.add_argument("since_commit", help="Commit hash / tag / ref to start AFTER (exclusive). Use e.g. last release tag.")
    p.add_argument("--root", default=None, help="Root directory to search recursively (default: auto git root)")
    p.add_argument("--max-depth", type=int, default=6, help="Maximum directory depth for repo discovery (default: 6)")
    p.add_argument("--output", help="Optional output file (UTF-8). If omitted, prints to stdout")
    p.add_argument("--aggregate", action="store_true", help="Aggregate commits from all repos into a single chronological list")
    p.add_argument("--include-merges", action="store_true", help="Include merge commits (default: exclude)")
    p.add_argument("--body", action="store_true", help="Include commit body text")
    p.add_argument("--subjects-only", action="store_true", help="Output only commit subjects (one per line); overrides other formatting flags")
    p.add_argument("--markdown-list", action="store_true", help="Render output as a Markdown bullet list")
    p.add_argument("--no-strip-newlines", action="store_true", help="Preserve newlines inside commit body (default flattens)")
    p.add_argument("--since-date", help="Optional additional since date filter (git understands many formats)")
    p.add_argument("--until-date", help="Optional until date filter")
    p.add_argument("--reverse", action="store_true", help="Oldest first (default newest first)")
    return p.parse_args(argv)


def detect_git_root(start: str) -> str:
    """Return git repository root for start path (file or directory) or fallback to CWD."""
    path = os.path.abspath(start)
    if os.path.isfile(path):
        path = os.path.dirname(path)
    try:
        proc = subprocess.run(
            ["git", "-C", path, "rev-parse", "--show-toplevel"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return proc.stdout.strip()
    except subprocess.CalledProcessError:
        return os.getcwd()


def main(argv: List[str]) -> int:
    args = parse_args(argv)
    # Determine search root: explicit --root overrides auto-detection
    search_root = args.root or detect_git_root(os.path.abspath(__file__))
    repos = discover_repos(search_root, args.max_depth)
    if not repos:
        print(f"[collect-commits] No git repositories discovered under {search_root}", file=sys.stderr)
        return 0

    all_commits: List[Commit] = []
    for repo in repos:
        if not git_exists_commit(repo, args.since_commit):
            print(f"[collect-commits] Skipping {repo}: since_commit not found", file=sys.stderr)
            continue
        commits = collect_commits(
            repo,
            args.since_commit,
            include_merges=args.include_merges,
            include_body=args.body,
            since_date=args.since_date,
            until_date=args.until_date,
        )
        all_commits.extend(commits)

    if not all_commits:
        print("[collect-commits] No commits found after since_commit in discovered repos.", file=sys.stderr)
        return 0

    if args.subjects_only:
        # Simplified output: just subjects.
        if args.aggregate:
            all_commits.sort(key=lambda c: c.date, reverse=not args.reverse)
            lines = [c.subject for c in all_commits]
        else:
            by_repo = {}
            for c in all_commits:
                by_repo.setdefault(c.repo, []).append(c)
            lines = []
            for repo in sorted(by_repo):
                repo_commits = by_repo[repo]
                if args.reverse:
                    repo_commits = list(reversed(repo_commits))
                lines.extend(c.subject for c in repo_commits)
    else:
        if args.aggregate:
            all_commits.sort(key=lambda c: c.date, reverse=not args.reverse)
            lines = [c.format(include_body=args.body, preserve_newlines=args.no_strip_newlines) for c in all_commits]
        else:
            # Group by repo preserving internal ordering (git log returns newest->oldest); optionally reverse within group
            by_repo = {}
            for c in all_commits:
                by_repo.setdefault(c.repo, []).append(c)
            lines: List[str] = []
            for repo in sorted(by_repo):
                repo_commits = by_repo[repo]
                if args.reverse:
                    repo_commits = list(reversed(repo_commits))
                lines.append(f"### {repo}")
                lines.extend(
                    c.format(include_body=args.body, preserve_newlines=args.no_strip_newlines) for c in repo_commits
                )
                lines.append("")

    # Apply markdown list formatting if requested (skip headings and empty lines)
    if args.markdown_list:
        md_lines: List[str] = []
        for ln in lines:
            if not ln.strip():
                md_lines.append(ln)
            elif ln.startswith("### "):
                md_lines.append(ln)  # keep heading as-is
            elif ln.startswith("- ") or ln.startswith("* "):
                md_lines.append(ln)  # already a list item
            else:
                md_lines.append(f"- {ln}")
        lines = md_lines

    output_text = "\n".join(lines).rstrip() + "\n"

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output_text)
        print(f"[collect-commits] Wrote {len(lines)} lines to {args.output}")
    else:
        sys.stdout.write(output_text)
    return 0


if __name__ == "__main__":  # pragma: no cover
    try:
        sys.exit(main(sys.argv[1:]))
    except KeyboardInterrupt:
        print("[collect-commits] Interrupted", file=sys.stderr)
        sys.exit(130)
