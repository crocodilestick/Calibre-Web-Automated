# Phase 1 (web-reader create/edit/delete) — verification record

Date: 2026-05-25. Branch: `feat/annotation-two-way-phase1-phase2`.
Design: `notes/2026-05-25-annotation-two-way-phase1-phase2-DESIGN.md` §3.

Verified across three layers (per CLAUDE.md enterprise standard — not stopping
at the unit boundary).

## 1. Unit (20 tests, `./.venv/bin/pytest`, all green)
- `test_annotations_create_endpoint.py` (7): source='webreader', `cwn-web-` id,
  `span#kobo.x.y` selector round-trips through `_extract_kobospan_id`, `-99`
  sentinel, cfi computed against a synthetic kepub, cfi=None tolerated when no
  kepub, `content_id` built from `book.uuid`+chapter, bad payload → ValueError.
- `test_annotations_edit_delete_endpoint.py` (11): color/note mutate, position
  immutable, invalid color rejected, soft-delete drops from `_load`, idempotent
  re-delete, IDOR (foreign user → None → route 404).
- `test_annotations_webreader_hardcover_fanout.py` (3): enabled handler →
  sync_target synced; disabled → none; tombstone never re-pushed.

## 2. Over-the-wire HTTP on the live container (`cwn-local`, book 20 kepub)
Authenticated session (cwng84test) + CSRF, real `curl` against the deployed
instance — full flow against a real KoboSpan (`kobo.0.1`) from the on-disk kepub:

```
login: 302   data.json authed: 200   baseline count: 4
CREATE -> 201  source=webreader  cfi_range=epubcfi(/6/4!/4/2[book-columns]/2[book-inner]/2/2[kobo.0.1],/1:0,/1:10)
  count after create: 5   readback: source=webreader color=green note='probe note' span=kobo.0.1
EDIT  -> 200  color=blue note='edited note'
DELETE-> 200  count after delete: 4  (soft-deleted, excluded from data.json)
```

Routes confirmed CSRF-protected: POST/PATCH/DELETE without a token → 400.

## 3. Live browser (Playwright via MCP) — the user-visible flow
Logged in, opened `/read/20/kepub`, navigated to `OEBPS/part0001.xhtml`:
- Selecting text fired epub.js `selected` → my handler built the create popup
  (4 swatches + note + Save). `selectionToAnchor` resolved `kobo.0.1` / "Nineteen ".
  → `feat-annotation-phase1-create-popup.png`
- Save → POST → row created (sidebar 4→5), overlay painted as a 124×37px
  `cwa-annotation-overlay` rect in the marks-pane layer; console clean (0 err).
  Green highlight visible over "Nineteen ". → `feat-annotation-phase1-overlay-painted.png`
- Clicking the highlight opened the edit popup with the note pre-filled.
- Delete → overlay 1→0, sidebar 5→4, `data.json` count back to 4.

## Notes / scope
- **i18n:** new strings live in `annotations.js` (reader popup labels). The
  reader's JS strings are not wired into the gettext catalog today (the existing
  reader JS, e.g. "No annotations on this book.", is hardcoded English). Adding
  JS i18n would require threading translated strings through the template — out
  of scope here and consistent with the current reader. No `.po` changes.
- **Committed Playwright harness:** the repo has no pytest-playwright CI infra;
  verification was done by live MCP-driven Playwright (evidence above). A
  committed harness is a separate infra task if desired.
- Test data created during verification was deleted (book 20 back to baseline 4).
