#!/usr/bin/env python3
# Calibre-Web Automated – fork of Calibre-Web
# Copyright (C) 2018-2026 Calibre-Web contributors
# Copyright (C) 2024-2026 Calibre-Web Automated contributors
# SPDX-License-Identifier: GPL-3.0-or-later
# See CONTRIBUTORS for full list of authors.
"""Bulk-export open GitHub issues & PRs to compact markdown for offline triage.

Why: reading issues one-by-one through the API/UI is slow and repetitive.
This pulls everything once, caches raw JSON,
and writes:

  .triage/index.md          one line per open item (sortable overview)
  .triage/index.tsv         same data, machine-friendly (grep/awk/sort)
  .triage/digest.md         ~1 paragraph per item: body gist + latest human comment
                            (read this before opening individual items)
  .triage/items/<n>.md      compacted issue/PR: metadata, body, comments, reviews
  .triage/diffs/<n>.diff    full PR patch (PRs only)
  .triage/raw/<n>.json      raw API cache (re-runs skip unchanged items)

Usage:
  GITHUB_TOKEN=... python3 .github/triage/export.py [--repo owner/name] [--out .triage]
                                                     [--state open|all] [--workers 8]
                                                     [--quiet-commenter LOGIN ...]

Stdlib + requests only. A token is optional but strongly recommended (60 req/h
unauthenticated vs 5000 req/h). Re-running is cheap: items whose `updated_at`
has not changed are rebuilt from cache without further API calls.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

API = "https://api.github.com"
MAINTAINERS = {"crocodilestick"}  # highlighted in output; extend as needed
BOT_SUFFIX = "[bot]"

# Compaction knobs: long logs/code blocks are the main token sink in bug reports.
MAX_BLOCK_LINES = 30   # code blocks longer than this get head/tail truncated
KEEP_HEAD, KEEP_TAIL = 12, 10
MAX_COMMENT_CHARS = 2500
CACHE_VERSION = 2  # bump when fetch_item gathers new fields, to invalidate raw/ cache
DIGEST_BODY_CHARS, DIGEST_COMMENT_CHARS = 650, 260
# Bug-report template headings carry no information; strip them from the digest.
TEMPLATE_HEADINGS = re.compile(
    r"\*\*(Describe the bug|To Reproduce|Expected behaviou?r|Screenshots|Desktop[^*]*|Smartphone[^*]*|"
    r"Additional context|Configuration[^*]*|Environment[^*]*)\*\*:?"
    r"|^#+\s*(Describe the bug|To Reproduce|Expected behaviou?r|Screenshots|Additional context)\s*$",
    re.I | re.M)


def session(token: str | None) -> requests.Session:
    s = requests.Session()
    s.headers["Accept"] = "application/vnd.github+json"
    s.headers["X-GitHub-Api-Version"] = "2022-11-28"
    if token:
        s.headers["Authorization"] = f"Bearer {token}"
    return s


def get_all(s: requests.Session, url: str, params: dict | None = None) -> list:
    """GET a paginated list endpoint, following Link: rel=next."""
    out, params = [], dict(params or {}, per_page=100)
    prefix = url.split("/repos/", 1)[1].split("/")[:2] if "/repos/" in url else None
    while url:
        r = s.get(url, params=params, timeout=60)
        r.raise_for_status()
        out.extend(r.json())
        url, params = r.links.get("next", {}).get("url"), None
        # GitHub's next links use /repositories/<id>/...; some proxies only allow
        # /repos/<owner>/<name>/..., so normalise back to the form we started with.
        if url and prefix:
            url = re.sub(r"/repositories/\d+/", f"/repos/{prefix[0]}/{prefix[1]}/", url)
    return out


def get_one(s: requests.Session, url: str) -> dict:
    r = s.get(url, timeout=60)
    r.raise_for_status()
    return r.json()


# --------------------------------------------------------------------------- compaction

def compact(text: str | None, limit: int | None = None) -> str:
    if not text:
        return "_(empty)_"
    t = text.replace("\r\n", "\n")
    t = re.sub(r"<!--.*?-->", "", t, flags=re.S)                  # template comments
    t = re.sub(r"<details>.*?<summary>(.*?)</summary>", r"[details: \1]", t, flags=re.S)
    t = re.sub(r"</?details>", "", t)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "[image]", t)              # markdown images
    t = re.sub(r"<img[^>]*>", "[image]", t)

    def trim_block(m: re.Match) -> str:
        fence, body = m.group(1), m.group(2).split("\n")
        if len(body) <= MAX_BLOCK_LINES:
            return m.group(0)
        cut = len(body) - KEEP_HEAD - KEEP_TAIL
        return "\n".join([fence, *body[:KEEP_HEAD], f"... [{cut} lines trimmed] ...",
                          *body[-KEEP_TAIL:], "```"])

    t = re.sub(r"(```[^\n]*)\n(.*?)\n```", trim_block, t, flags=re.S)
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    if limit and len(t) > limit:
        t = t[:limit] + f"\n... [{len(t) - limit} chars trimmed]"
    return t or "_(empty)_"


def who(user: dict | None) -> str:
    login = (user or {}).get("login", "ghost")
    return f"**{login}** (maintainer)" if login in MAINTAINERS else login


def day(ts: str | None) -> str:
    return ts[:10] if ts else "-"


def age_days(ts: str) -> int:
    t = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return (dt.datetime.now(dt.timezone.utc) - t).days


# --------------------------------------------------------------------------- fetching

def fetch_item(s, repo, issue, cache_dir: Path) -> dict:
    """Fetch comments (+ PR details) for one issue unless cache is current."""
    n = issue["number"]
    cache = cache_dir / f"{n}.json"
    if cache.exists():
        old = json.loads(cache.read_text())
        if old["issue"]["updated_at"] == issue["updated_at"] and old.get("v") == CACHE_VERSION:
            return old

    rec = {"v": CACHE_VERSION, "issue": issue, "comments": []}
    if issue.get("comments"):
        rec["comments"] = get_all(s, f"{API}/repos/{repo}/issues/{n}/comments")
    if "pull_request" in issue:
        base = f"{API}/repos/{repo}/pulls/{n}"
        rec["pr"] = get_one(s, base)
        rec["files"] = get_all(s, f"{base}/files")
        rec["reviews"] = get_all(s, f"{base}/reviews")
        rec["review_comments"] = get_all(s, f"{base}/comments")
        sha = rec["pr"]["head"]["sha"]
        try:
            runs = get_one(s, f"{API}/repos/{repo}/commits/{sha}/check-runs?per_page=100")
            rec["checks"] = [{"name": c["name"], "conclusion": c["conclusion"] or c["status"]}
                             for c in runs.get("check_runs", [])]
        except requests.HTTPError:
            rec["checks"] = []
        # Fork PRs from first-time contributors sit at "action_required" until a
        # maintainer approves the workflow run; check-runs alone won't show that.
        try:
            runs = get_one(s, f"{API}/repos/{repo}/actions/runs?head_sha={sha}&per_page=20")
            rec["runs"] = [{"name": w["name"], "conclusion": w["conclusion"] or w["status"]}
                           for w in runs.get("workflow_runs", [])]
        except requests.HTTPError:
            rec["runs"] = []
    cache.write_text(json.dumps(rec))
    return rec


# --------------------------------------------------------------------------- rendering

def reactions(obj: dict) -> str:
    r = obj.get("reactions") or {}
    bits = [f"{k}:{r[k]}" for k in ("+1", "-1", "heart", "hooray", "rocket", "eyes") if r.get(k)]
    return " ".join(bits)


def ci_state(rec: dict) -> str:
    """Summarise CI as red / green / approve (awaiting maintainer approval) / none."""
    states = [c["conclusion"] for c in (rec.get("checks") or []) + (rec.get("runs") or [])]
    if any(c in ("failure", "timed_out", "cancelled") for c in states):
        return "red"
    if "action_required" in states:
        return "approve"
    if any(c in ("queued", "in_progress", "pending", "waiting") for c in states):
        return "running"
    return "green" if states else "none"


def render(rec: dict) -> str:
    i = rec["issue"]
    pr = rec.get("pr")
    kind = "PR" if pr else "Issue"
    labels = ", ".join(l["name"] for l in i["labels"]) or "-"
    L = [f"# {kind} #{i['number']}: {i['title']}",
         f"- author: {who(i['user'])} ({i.get('author_association', '').lower()}) | "
         f"created {day(i['created_at'])} | updated {day(i['updated_at'])} | "
         f"state {i['state']} | comments {i['comments']}",
         f"- labels: {labels} | reactions: {reactions(i) or '-'}"
         + (f" | assignees: {', '.join(a['login'] for a in i['assignees'])}" if i["assignees"] else "")]
    if pr:
        head = pr["head"]
        L.append(f"- branch: {(head.get('repo') or {}).get('full_name', '?')}:{head['ref']} -> "
                 f"{pr['base']['ref']} | draft: {pr['draft']} | mergeable: {pr.get('mergeable')} "
                 f"({pr.get('mergeable_state')}) | +{pr['additions']}/-{pr['deletions']} "
                 f"in {pr['changed_files']} files | commits {pr['commits']}")
        checks = (rec.get("checks") or []) + (rec.get("runs") or [])
        bad = sorted({f"{c['name']}={c['conclusion']}" for c in checks
                      if c["conclusion"] not in ("success", "skipped", "neutral")})
        L.append(f"- ci: {ci_state(rec)}" + (f" ({', '.join(bad)})" if bad else ""))
        L.append("- files: " + ", ".join(f"{f['filename']} (+{f['additions']}/-{f['deletions']})"
                                         for f in rec.get("files", [])[:40]))
    L += ["", "## Body", compact(i["body"])]

    # Merge comments, reviews and review comments into one chronological thread.
    events = [(c["created_at"], "comment", c) for c in rec["comments"]]
    events += [(r["submitted_at"] or "", "review", r) for r in rec.get("reviews", [])
               if r.get("body") or r["state"] in ("APPROVED", "CHANGES_REQUESTED")]
    events += [(c["created_at"], "inline", c) for c in rec.get("review_comments", [])]
    if events:
        L += ["", "## Thread"]
    for ts, typ, c in sorted(events, key=lambda e: e[0]):
        login = (c.get("user") or {}).get("login", "ghost")
        if login.endswith(BOT_SUFFIX):
            L.append(f"\n### {login} {day(ts)} [bot, {len(c.get('body') or '')} chars omitted]")
            continue
        tag = {"comment": "", "review": f" [review: {c.get('state')}]",
               "inline": f" [inline {c.get('path')}:{c.get('line') or c.get('original_line')}]"}[typ]
        L.append(f"\n### {who(c.get('user'))} {day(ts)}{tag}")
        L.append(compact(c.get("body"), MAX_COMMENT_CHARS))
    return "\n".join(L) + "\n"


def index_row(rec: dict) -> dict:
    i, pr = rec["issue"], rec.get("pr")
    commenters = {(c.get("user") or {}).get("login") for c in rec["comments"]}
    last = max([c["created_at"] for c in rec["comments"]], default=i["created_at"])
    last_by = next((c["user"]["login"] for c in sorted(rec["comments"], key=lambda c: c["created_at"],
                                                        reverse=True) if c.get("user")), "-")
    row = {
        "n": i["number"], "kind": "PR" if pr else "IS", "title": i["title"].replace("|", "/")[:90],
        "author": i["user"]["login"], "assoc": i.get("author_association", ""),
        "created": day(i["created_at"]), "age": age_days(i["created_at"]),
        "last_comment": day(last), "last_by": last_by,
        "comments": i["comments"], "thumbs": (i.get("reactions") or {}).get("+1", 0),
        "labels": ",".join(l["name"] for l in i["labels"]),
        "maint_replied": bool(commenters & MAINTAINERS),
        "chars": len(i.get("body") or ""),
    }
    if pr:
        row.update(draft=pr["draft"], size=f"+{pr['additions']}/-{pr['deletions']}",
                   files=pr["changed_files"], mergeable=pr.get("mergeable_state"), ci=ci_state(rec),
                   approvals=sum(r["state"] == "APPROVED" for r in rec.get("reviews", [])))
    return row


def gist(text: str | None, limit: int) -> str:
    """Single-line gist: drop code blocks, images and template headings, collapse whitespace."""
    t = re.sub(r"<!--.*?-->", "", (text or "").replace("\r", ""), flags=re.S)
    t = re.sub(r"```.*?```", "[code]", t, flags=re.S)
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)|<img[^>]*>", "[img]", t)
    t = re.sub(r"\s+", " ", TEMPLATE_HEADINGS.sub("", t)).strip()
    return t[:limit] + ("…" if len(t) > limit else "")


def write_digest(recs: list[dict], out: Path, quiet: set[str]) -> None:
    """One short paragraph per item, newest first: roughly 4x smaller than items/."""
    L = []
    for rec in sorted(recs, key=lambda r: -r["issue"]["number"]):
        i = rec["issue"]
        humans = [c for c in rec["comments"]
                  if not c["user"]["login"].endswith(BOT_SUFFIX) and c["user"]["login"] not in quiet]
        muted = len(rec["comments"]) - len(humans)
        kind = "PR" if rec.get("pr") else "IS"
        head = (f"#{i['number']} {kind} ({day(i['created_at'])}, c{i['comments']}, "
                f"+1:{(i.get('reactions') or {}).get('+1', 0)}"
                + (f", muted:{muted}" if muted else "") + f") {i['title']}")
        L.append(head + "\n  " + gist(i["body"], DIGEST_BODY_CHARS))
        if humans:
            c = humans[-1]
            L.append(f"  >> last {c['user']['login']}: {gist(c['body'], DIGEST_COMMENT_CHARS)}")
    (out / "digest.md").write_text("\n".join(L) + "\n")


def write_index(rows: list[dict], out: Path, repo: str) -> None:
    prs = [r for r in rows if r["kind"] == "PR"]
    iss = [r for r in rows if r["kind"] == "IS"]
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    L = [f"# {repo} open items — exported {now}",
         f"{len(iss)} issues, {len(prs)} PRs. m=maintainer has replied. Details: items/<n>.md", ""]
    L += ["## PRs", "n|draft|ci|merge|size|files|age|last|m|author|title", "-|-|-|-|-|-|-|-|-|-|-"]
    for r in sorted(prs, key=lambda r: -r["n"]):
        L.append(f"{r['n']}|{'D' if r['draft'] else ''}|{r['ci']}|{r['mergeable']}|{r['size']}|"
                 f"{r['files']}|{r['age']}d|{r['last_comment']}|{'m' if r['maint_replied'] else ''}|"
                 f"{r['author']}|{r['title']}")
    L += ["", "## Issues", "n|age|cmts|+1|last|m|labels|title", "-|-|-|-|-|-|-|-"]
    for r in sorted(iss, key=lambda r: -r["n"]):
        L.append(f"{r['n']}|{r['age']}d|{r['comments']}|{r['thumbs']}|{r['last_comment']}|"
                 f"{'m' if r['maint_replied'] else ''}|{r['labels']}|{r['title']}")
    (out / "index.md").write_text("\n".join(L) + "\n")

    cols = ["n", "kind", "age", "comments", "thumbs", "maint_replied", "last_comment", "last_by",
            "author", "assoc", "labels", "draft", "ci", "mergeable", "size", "files", "approvals", "title"]
    with (out / "index.tsv").open("w") as f:
        f.write("\t".join(cols) + "\n")
        for r in sorted(rows, key=lambda r: -r["n"]):
            f.write("\t".join(str(r.get(c, "")) for c in cols) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default="crocodilestick/Calibre-Web-Automated")
    ap.add_argument("--out", default=".triage")
    ap.add_argument("--state", default="open", choices=["open", "closed", "all"])
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--quiet-commenter", action="append", default=[], metavar="LOGIN",
                    help="leave this account's comments out of digest.md (e.g. boilerplate notices); repeatable")
    a = ap.parse_args()

    out = Path(a.out)
    for d in ("items", "diffs", "raw"):
        (out / d).mkdir(parents=True, exist_ok=True)
    s = session(os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"))

    issues = get_all(s, f"{API}/repos/{a.repo}/issues", {"state": a.state})
    print(f"listed {len(issues)} items; fetching details...", file=sys.stderr)
    with ThreadPoolExecutor(a.workers) as pool:
        recs = list(pool.map(lambda i: fetch_item(s, a.repo, i, out / "raw"), issues))

    live = {str(i["number"]) for i in issues}
    for d, ext in (("items", ".md"), ("diffs", ".diff")):   # drop items closed since last run
        for p in (out / d).glob(f"*{ext}"):
            if p.stem not in live:
                p.unlink()

    for rec in recs:
        n = rec["issue"]["number"]
        (out / "items" / f"{n}.md").write_text(render(rec))
        if rec.get("files"):
            (out / "diffs" / f"{n}.diff").write_text("".join(
                f"diff --git a/{f['filename']} b/{f['filename']}\n--- {f['status']}\n"
                f"{f.get('patch', '(binary or too large)')}\n" for f in rec["files"]))
    write_index([index_row(r) for r in recs], out, a.repo)
    write_digest(recs, out, set(a.quiet_commenter))
    left = s.get(f"{API}/rate_limit", timeout=30).json().get("resources", {}).get("core", {})
    print(f"done -> {out}/index.md  (API remaining: {left.get('remaining')})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
