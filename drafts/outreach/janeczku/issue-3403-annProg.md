https://github.com/janeczku/calibre-web/issues/3403

<!-- DO-NOT-POST until a release containing fork commit <SHA> is published. Fill <TAG>/<SHA> then post via scripts/post-release-outreach.sh or manually. fork_commit=<SHA> release=<TAG> -->
---
If you have two authors whose names differ only by an accent (like "George Pólya" and "George Polya"), or that romanize the same way, this is fixed in Calibre-Web-NextGen — a community-maintained, CWA-derived build of Calibre-Web. Metadata edits on those books, including cover-only changes, now save instead of erroring on `UNIQUE constraint failed: authors.name`.

```
docker pull ghcr.io/new-usemame/calibre-web-nextgen:<TAG>
```

Heads-up: it's CWA-based, so it also adds auto-ingest, kepubify and KOReader sync on top of plain Calibre-Web. Thanks @annProg for the report and @apetresc / @wnmurphy for the accented-name examples. Issues: https://github.com/new-usemame/Calibre-Web-NextGen/issues
