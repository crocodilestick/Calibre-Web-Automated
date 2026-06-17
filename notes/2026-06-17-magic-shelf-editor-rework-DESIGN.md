# Magic Shelf editor rework (task #22) — research + plan

Status: **research complete, implementation not started.** Written after the
reader program (#29/#30/#31) shipped; parked at a clean point so the rework
starts fresh rather than on depleted context. This note is the entry point.

## What a Magic Shelf is

A dynamic/smart shelf defined by a rule tree (like a smart playlist). Books are
matched by query, not added by hand.

- **Model:** `MagicShelf` — `cps/ub.py:462-483`. `rules` is a JSON column in
  jQuery-QueryBuilder shape: `{condition: "AND"|"OR", rules: [{id, field, type,
  operator, value}, ...]}`, nestable (a rule entry that itself has `condition`
  is a group). `HiddenMagicShelfTemplate` (`ub.py:526-544`) lets a user hide a
  system/public shelf without deleting it. `MagicShelfCache` (`ub.py:485-499`)
  caches matched book ids for 30 min.
- **Rule engine:** `cps/magic_shelf.py` — `FIELD_MAP` (281-296: title, author,
  tag, series, publisher, rating, language, pubdate, timestamp, has_cover,
  series_index, comments, read_status, hardcover_id, custom_column_*),
  `OPERATOR_MAP` (299-327: equal/contains/begins_with/between/is_empty/… +
  negations), `build_query_from_rules()` (601-632, recursive AND/OR).
- **System templates:** `magic_shelf.py:154-260` (recently_added, highly_rated,
  currently_reading, yet_to_read, recent_publications, …).
- **Routes** (`cps/web.py`): `GET/POST /magicshelf` create (1335-1450),
  `GET/POST /magicshelf/<id>/edit` (1453-1588), `POST /magicshelf/preview`
  (1268-1309 → count + sample), `POST /magicshelf/<id>/delete` (1641-1684),
  `POST /magicshelf/<id>/duplicate` (1589-1639), `GET /magicshelf/<id>` list.
  Save payload: `{name, icon, rules, kobo_sync, is_public, opds_expose}`.

## The editor today

`cps/templates/magic_shelf_edit.html` — **937 lines**, all-in-one: inline
`<style>` (7-279), the form (name + char counter, emoji icon picker, kobo/opds/
public checkboxes, the `#builder` QueryBuilder mount, preview box, action
buttons), and inline JS (488-935: fields array 536-634, operators 666-687,
`queryBuilder()` init 689, preview 771-819, save 822-879, delete/duplicate
882-933). The rule UI is **jQuery QueryBuilder 3.0.0** (vendored minified +
`cps/static/css/query_builder.css` overrides). Editor is a full page, not a modal.

## Concrete mobile/desktop pain points (from the audit)

P1 — small, high-value, low-risk (CSS, fixes real breakage):
1. `query_builder.css:57` `width: --webkit-fill-available` is a webkit-only
   typo → should be `width: 100%` (field/operator/value selects don't fill).
2. `.form-group` uses `padding-inline: 4rem` (template ~386/410) with **no
   mobile override** → inputs/text clip below ~375px. Add `@media (max-width:
   480px)` reducing to ~1rem.
3. Preview results list has no `word-wrap` → long titles overflow horizontally.
4. Action buttons (`.btn-group` wrap) stack into 3–4 rows on mobile; give
   Save/Cancel/Preview a sensible `min-width` / 2-up layout.
5. Help panel (`.help-content { padding: 4rem }`, ~203) has no mobile styles.

P2 — moderate UX:
6. Icon picker grid is tight on small phones; collapse to an accordion/“pick
   icon” disclosure under ~600px.
7. QueryBuilder rule rows are inherently row-based (`inline-block`); the
   `@media` flex-column override (query_builder.css:121-172) helps but rows
   still cluster. Tighten the mobile stacking (one control per line, full-width,
   clear rule-card boundaries + delete affordance).
8. Native `<select>` for field/operator is acceptable on mobile (iOS full-screen
   picker) — leave unless P3 replaces the lib.

P3 — large (separate, deliberate decision):
9. Replace jQuery QueryBuilder with a mobile-first rule builder (custom, or a
   maintained lib). Biggest UX win on mobile but high blast radius (touches the
   rules round-trip + every system template's JSON must still load/save). Only
   if P1+P2 prove insufficient.
10. Optional: a step flow on mobile (name → icon → rules → preview/save).

## Recommended first PR (when picked up)

Ship **P1 (1–5)** as one CSS-focused PR — it removes the actual mobile breakage
(clipping, overflow, the width typo) and brings the editor to a usable mobile
standard without touching the rules round-trip. Then evaluate P2 as a second
pass. Hold P3 (library replacement) for an explicit operator decision — it's a
rework of the rule UI's core, not a polish.

**Verification plan:** rebuild cwn-local; create/edit a Magic Shelf with several
rules + a nested group; Playwright at 390×844 and 1280 — assert no horizontal
overflow, selects fill width, buttons reachable, preview wraps, save round-trips
the rules JSON unchanged (load an existing shelf, save, diff the `rules`). Source-
pin the `width:100%` fix + the mobile `@media` in a JS/CSS test.

## Open decision for the operator
- **Fix-in-place (P1+P2) or replace QueryBuilder (P3)?** P1+P2 is the low-risk,
  high-value path and what this note recommends first. P3 is a larger commitment.
