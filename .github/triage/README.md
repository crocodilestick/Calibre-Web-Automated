# Issue & PR triage export

`export.py` pulls every open issue and PR into local, compacted markdown so the
backlog can be reviewed offline instead of one item at a time through the
GitHub UI/API.

```bash
pip install requests                      # only dependency
export GITHUB_TOKEN=ghp_...               # optional, but 5000 req/h instead of 60
python3 .github/triage/export.py --quiet-commenter <login-of-boilerplate-bot>
```

Output goes to `.triage/` (gitignored):

| File | What it is | Size (Sep 2026, 460 items) |
|---|---|---|
| `index.md` | one row per item: CI state, mergeability, age, last activity, whether a maintainer replied | ~45 KB |
| `index.tsv` | same data for `sort`/`awk`/`grep` | ~60 KB |
| `digest.md` | one paragraph per item: body gist + latest human comment | ~320 KB |
| `items/<n>.md` | full compacted item: body, comments, reviews, inline review comments (long logs trimmed) | ~2.2 MB total |
| `diffs/<n>.diff` | full PR patch | ~5 MB total |
| `raw/<n>.json` | API cache; re-runs only refetch items whose `updated_at` changed | ~12 MB |

A first run takes about a minute and roughly 800 API calls. Later runs only fetch
what changed.

## Token-efficient review order

Work from cheap to expensive, and only go deeper when an item needs it:

1. **`index.md`**: the whole backlog on one screen. Sort out what needs no reading at
   all: translation PRs, PRs whose CI is waiting on approval (`approve`), merge conflicts
   (`dirty`), and issues nobody has answered (`m` column empty).
2. **`digest.md`**: enough to cluster issues by theme, spot duplicates and support
   questions, and match issues to the PRs that fix them.
3. **`items/<n>.md`**: only for items you are actually deciding on.
4. **`diffs/<n>.diff`**: only for PRs you are about to review or merge.

Useful one-liners:

```bash
# PRs waiting for you to approve a CI run (first-time contributors)
awk -F'\t' '$2=="PR" && $13=="approve"' .triage/index.tsv | cut -f1,18
# issues a maintainer has never replied to, oldest first
awk -F'\t' '$2=="IS" && $6=="False"' .triage/index.tsv | sort -t$'\t' -k3 -n -r | cut -f1,3,18
# everything that mentions kobo
grep -il kobo .triage/items/*.md
```

## Notes

- `CI` column: `approve` means the workflow is waiting for a maintainer to click
  *Approve and run* (fork PRs from first-time contributors), `none` means no runs were
  found for the head commit.
- `MAINTAINERS` at the top of `export.py` controls whose comments are highlighted and
  what counts as "maintainer replied".
- Delete `.triage/raw/` (or bump `CACHE_VERSION`) to force a full refetch.
