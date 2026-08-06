#!/bin/bash
# combine_translations.sh — Layer multiple translation PRs into one .po file
# Usage: combine_translations.sh <lang_code> <pr1> <pr2> ... <prN>
# Orders PRs smallest→largest (by additions) so larger PRs win on conflicts.
# Uses msgmerge + msgcat + msgattrib from gettext — no Python dependencies.

set -euo pipefail

LANG="${1:?Usage: combine_translations.sh <lang_code> <pr1> [pr2...]}"
shift
PRS=("$@")

if [ ${#PRS[@]} -eq 0 ]; then
    echo "Error: at least one PR number required"
    exit 1
fi

PO_PATH="cps/translations/${LANG}/LC_MESSAGES/messages.po"
POT="messages.pot"
TMPDIR=$(mktemp -d /tmp/combine_${LANG}_XXXXXX)
BASE="${TMPDIR}/base.po"
COMBINED="${TMPDIR}/combined.po"

# Verify the base file exists
if [ ! -f "$PO_PATH" ]; then
    echo "Error: $PO_PATH not found (lang '$LANG' may not exist)"
    exit 1
fi

cp "$PO_PATH" "$BASE"
cp "$PO_PATH" "$COMBINED"

# Sort PRs by additions (smallest first) so larger PRs overwrite on conflict
echo "=== Combining translations for '$LANG': ${#PRS[@]} PRs ==="
echo ""

# Fetch metadata to sort by size
declare -A PR_ADDITIONS
for pr in "${PRS[@]}"; do
    additions=$(gh pr view "$pr" --json additions -q '.additions' 2>/dev/null || echo "0")
    PR_ADDITIONS[$pr]=$additions
done

# Sort by additions ascending
SORTED_PRS=($(for pr in "${PRS[@]}"; do echo "${PR_ADDITIONS[$pr]} $pr"; done | sort -n | awk '{print $2}'))
echo "Processing order (smallest→largest): ${SORTED_PRS[*]}"
echo ""

CONTRIBUTIONS=()
FAILED=()

for pr in "${SORTED_PRS[@]}"; do
    echo "[$(date +%H:%M:%S)] PR #$pr..."

    # Fetch the PR's head ref if we haven't already
    FETCHED_REF="__pr_${pr}"
    if ! git show-ref --verify --quiet "refs/heads/${FETCHED_REF}"; then
        ref=$(gh pr view "$pr" --json headRefName -q '.headRefName' 2>/dev/null || echo "")
        repo=$(gh pr view "$pr" --json headRepositoryOwner -q '.headRepositoryOwner.login' 2>/dev/null || echo "")
        if [ -z "$ref" ] || [ -z "$repo" ]; then
            echo "  [!] Could not get ref/repo for PR #$pr, skipping"
            FAILED+=("$pr")
            continue
        fi
        git fetch "https://github.com/${repo}/Calibre-Web-Automated.git" "${ref}:${FETCHED_REF}" 2>/dev/null || {
            echo "  [!] Failed to fetch PR #$pr from ${repo}/${ref}, skipping"
            FAILED+=("$pr")
            continue
        }
    fi

    # Extract the .po file
    PR_PO="${TMPDIR}/pr_${pr}.po"
    PR_CLEAN="${TMPDIR}/pr_${pr}_clean.po"

    if ! git show "${FETCHED_REF}:${PO_PATH}" > "$PR_PO" 2>/dev/null; then
        echo "  [!] Could not extract ${PO_PATH} from PR #$pr, skipping"
        FAILED+=("$pr")
        continue
    fi

    if [ ! -s "$PR_PO" ]; then
        echo "  [!] Extracted file is empty for PR #$pr, skipping"
        FAILED+=("$pr")
        continue
    fi

    # Step 1: msgmerge against current POT (resolves structural drift)
    MERGED_OK=false
    if msgmerge --update "$PR_PO" "$POT" 2>/dev/null; then
        MERGED_OK=true
    else
        # msgmerge is strict about format — try cleaning with polib first
        echo -n "  msgmerge failed, trying polib clean... "
        if /workspace/cwa/.venv/bin/python3 -c "
import polib, sys
try:
    po = polib.pofile('${PR_PO}')
    po.save('${PR_PO}')
except Exception as e:
    sys.exit(1)
" 2>/dev/null; then
            echo "retrying msgmerge..."
            if msgmerge --update "$PR_PO" "$POT" 2>/dev/null; then
                MERGED_OK=true
            fi
        fi
    fi

    if ! $MERGED_OK; then
        echo "  [!] msgmerge failed for PR #$pr (irrecoverable format errors), skipping"
        FAILED+=("$pr")
        continue
    fi

    # Step 2: Remove fuzzy markers (only confirmed translations survive)
    if ! msgattrib --no-fuzzy "$PR_PO" -o "$PR_CLEAN" 2>/dev/null; then
        echo "  [!] msgattrib failed for PR #$pr, using unfiltered version"
        cp "$PR_PO" "$PR_CLEAN"
    fi

    # Step 3: Layer on top of base (PR's translations win via --use-first)
    if ! msgcat "$PR_CLEAN" "$COMBINED" --use-first -o "${TMPDIR}/temp.po" 2>/dev/null; then
        echo "  [!] msgcat failed for PR #$pr, skipping"
        FAILED+=("$pr")
        continue
    fi

    cp "${TMPDIR}/temp.po" "$COMBINED"

    # Track contributions
    author=$(gh pr view "$pr" --json author -q '.author.login' 2>/dev/null || echo "unknown")
    CONTRIBUTIONS+=("#${pr} (@${author})")

    echo "  ✓ Applied"
done

echo ""

# Final validation
echo "--- Validation ---"
if msgfmt --check "$COMBINED" 2>/dev/null; then
    echo "✓ msgfmt --check PASSED"
else
    echo "✗ msgfmt --check FAILED:"
    msgfmt --check "$COMBINED" 2>&1 || true
    echo ""
    echo "Aborting: combined .po file is invalid"
    echo "Temp files preserved at: $TMPDIR"
    exit 1
fi

# Show statistics
echo ""
echo "--- Statistics ---"
msgfmt --statistics "$COMBINED" 2>&1

# Apply the result
cp "$COMBINED" "$PO_PATH"

# Compile .mo
MO_PATH="${PO_PATH%.po}.mo"
msgfmt "$PO_PATH" -o "$MO_PATH" 2>/dev/null || {
    echo "[!] Warning: msgfmt compilation to .mo failed"
}

# Stage the files (skip .mo — it's gitignored)
git add -f "$PO_PATH"

# Build commit message
echo ""
echo "--- Commit ---"
COMMIT_MSG="i18n(${LANG}): merge translations from ${#CONTRIBUTIONS[@]} PRs

Combines translations from: ${CONTRIBUTIONS[*]}

Co-Authored-By: Claude <noreply@anthropic.com>"

echo "$COMMIT_MSG"

# Cleanup temp branches
for pr in "${SORTED_PRS[@]}"; do
    git branch -D "__pr_${pr}" 2>/dev/null || true
done

# Output the commit message for use by caller
echo "$COMMIT_MSG" > "${TMPDIR}/commit_msg.txt"

echo ""
if [ ${#FAILED[@]} -gt 0 ]; then
    echo "⚠ Skipped ${#FAILED[@]} PR(s): ${FAILED[*]}"
fi
echo "✓ Done: $PO_PATH updated with ${#CONTRIBUTIONS[@]} PR contributions"
echo "  File staged. Ready to commit."
echo "  Commit message saved to ${TMPDIR}/commit_msg.txt"
