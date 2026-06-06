#!/usr/bin/env python3
"""Kobo device sync simulator — drives /kobo/<token>/v1/library/sync the way a
real device does (round-tripping x-kobo-synctoken, honoring the continuation
header) and reports exactly what a device would receive.

Built for fork #359 live verification: distinguishes book entitlements
(new/changed/removed), reading states, and collection Tags (new/changed/
deleted) per round, and decodes the synctoken cursor so cursor advancement
is observable.

Usage:
  python3 scripts/manual/kobo_sync_simulator.py --token <kobo_auth_token> \
      [--base http://localhost:8086] [--max-rounds 30] [--synctoken '']

Prints one line per round plus a final JSON summary to stdout.
"""
import argparse
import base64
import json
import urllib.request
import zlib


def decode_token(tok):
    if not tok:
        return {}
    try:
        if tok.startswith("z1:"):
            # Transport-compressed format (fork #331).
            payload = tok[3:]
            return json.loads(zlib.decompress(
                base64.b64decode(payload + "=" * (-len(payload) % 4))))
        return json.loads(base64.b64decode(tok + "=" * (-len(tok) % 4)))
    except Exception:
        return {"undecodable": tok[:40]}


def sync_round(base, token, synctoken):
    url = "{}/kobo/{}/v1/library/sync".format(base, token)
    req = urllib.request.Request(url)
    if synctoken:
        req.add_header("x-kobo-synctoken", synctoken)
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = json.loads(resp.read())
        headers = {k.lower(): v for k, v in resp.headers.items()}
    return body, headers


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8086")
    ap.add_argument("--token", required=True)
    ap.add_argument("--max-rounds", type=int, default=30)
    ap.add_argument("--synctoken", default="")
    ap.add_argument("--quiet", action="store_true", help="suppress per-round lines")
    args = ap.parse_args()

    synctoken = args.synctoken
    books = {}   # title -> [(round, kind)]
    tags = []    # (round, kind, name_or_id, item_count)
    rounds = 0
    while rounds < args.max_rounds:
        rounds += 1
        body, headers = sync_round(args.base, args.token, synctoken)
        counts = {"new": 0, "changed": 0, "removed": 0, "rstate": 0,
                  "ntag": 0, "ctag": 0, "dtag": 0}
        for item in body:
            if "NewEntitlement" in item:
                counts["new"] += 1
                md = item["NewEntitlement"].get("BookMetadata", {})
                books.setdefault(md.get("Title", "?"), []).append((rounds, "new"))
            elif "ChangedEntitlement" in item:
                ent = item["ChangedEntitlement"].get("BookEntitlement", {})
                md = item["ChangedEntitlement"].get("BookMetadata", {})
                kind = "removed" if ent.get("IsRemoved") else "changed"
                counts[kind] += 1
                books.setdefault(md.get("Title", "?"), []).append((rounds, kind))
            elif "ChangedReadingState" in item:
                counts["rstate"] += 1
            elif "NewTag" in item:
                counts["ntag"] += 1
                t = item["NewTag"].get("Tag", {})
                tags.append((rounds, "new", t.get("Name", t.get("Id")),
                             len(t.get("Items", []))))
            elif "ChangedTag" in item:
                counts["ctag"] += 1
                t = item["ChangedTag"].get("Tag", {})
                tags.append((rounds, "changed", t.get("Name", t.get("Id")),
                             len(t.get("Items", []))))
            elif "DeletedTag" in item:
                counts["dtag"] += 1
                t = item["DeletedTag"].get("Tag", {})
                tags.append((rounds, "deleted", t.get("Id"), 0))
        cont = headers.get("x-kobo-sync", "")
        synctoken = headers.get("x-kobo-synctoken", synctoken)
        tok = decode_token(synctoken).get("data", {})
        if not args.quiet:
            print("round {}: items={} new={} chg={} rm={} rstate={} "
                  "tags(n/c/d)={}/{}/{} cont={!r} cursor(lm={}, id={}, "
                  "msli={}, msat={})".format(
                      rounds, len(body), counts["new"], counts["changed"],
                      counts["removed"], counts["rstate"], counts["ntag"],
                      counts["ctag"], counts["dtag"], cont,
                      tok.get("books_last_modified"), tok.get("books_last_id"),
                      tok.get("magic_shelf_last_id"),
                      tok.get("magic_shelf_membership_at")))
        if cont != "continue":
            break

    summary = {
        "rounds": rounds,
        "unique_books": len(books),
        "books": {k: v for k, v in sorted(books.items())},
        "tags": tags,
        "final_synctoken_data": decode_token(synctoken).get("data", {}),
    }
    print(json.dumps(summary, indent=1, default=str))


if __name__ == "__main__":
    main()
