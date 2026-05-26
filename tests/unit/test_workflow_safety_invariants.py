"""CI-enforced safety invariants for .github/workflows/*.yml.

These tests pin the load-bearing properties that keep the auto-merge
machinery safe. They run on every PR (marked `unit`, picked up by
Fast Tests) and go red the moment someone removes one of the walls.

The walls — each tested below:

  1. auto-merge.yml refuses to act on PRs from forks. Without this the
     workflow would try to enable auto-merge / merge for arbitrary
     attacker-controlled branches.

  2. Any workflow that consumes .github/policy/tier-policy.config or
     scripts/lib/tier_policy.py reads it from main, not the PR head.
     Otherwise a PR could widen its own merge rules by editing the
     policy file in its own branch.

  3. No `pull_request_target` workflow checks out the PR head ref or
     PR head SHA. pull_request_target runs in the base repo's
     privileged context with secrets; checking out attacker-controlled
     code there is the classic GitHub Actions RCE.

  4. No workflow grants `permissions: actions: write` (or `write-all`
     at the top level). The auto-merge / label-guard surfaces only
     need pull-requests + contents; broadening permissions is an
     unexplained escalation.

  5. No workflow pushes to or otherwise mutates the upstream repos
     (`crocodilestick/Calibre-Web-Automated`, `janeczku/calibre-web`).
     CLAUDE.md hard rule #2 — never push to upstream.

If any of these go red, STOP. Read the failing assertion. The fix is
almost never to weaken the test; it's to restore the property in the
workflow.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

try:
    import yaml
except ImportError:  # pragma: no cover - yaml ships with most distros
    yaml = None  # type: ignore[assignment]

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
WF_DIR = REPO_ROOT / ".github" / "workflows"


def _load(path: Path) -> dict:
    if yaml is None:
        pytest.skip("PyYAML not installed in this environment")
    with path.open() as fh:
        return yaml.safe_load(fh) or {}


def _trigger(wf: dict) -> dict:
    """`on:` parsed as either the literal string 'on' or boolean True
    (YAML 1.1 quirk). Return whichever holds."""
    return wf.get("on") or wf.get(True) or {}


def _every_step(wf: dict):
    """Yield (job_name, step_dict) for every step in every job."""
    for job_name, job in (wf.get("jobs") or {}).items():
        if not isinstance(job, dict):
            continue
        for step in (job.get("steps") or []):
            if isinstance(step, dict):
                yield job_name, step


def all_workflows() -> list[Path]:
    return sorted(WF_DIR.glob("*.yml")) + sorted(WF_DIR.glob("*.yaml"))


# ─── Wall 1: auto-merge.yml refuses fork PRs ───────────────────────────


def test_auto_merge_refuses_fork_prs():
    """The workflow must bail out for PRs whose head repo isn't the base
    repo. This protects against acting on attacker-controlled branches.
    Two acceptable shapes:
      (a) Job-level `if:` predicate comparing head.repo.full_name to
          github.repository (the new shape).
      (b) Inline shell guard that returns early on the same comparison
          (the legacy shape, still valid).
    """
    f = WF_DIR / "auto-merge.yml"
    assert f.exists(), f"missing {f}"
    text = f.read_text()
    # Either form must reference the head-repo / base-repo comparison.
    assert (
        "head.repo.full_name" in text
    ), "auto-merge.yml must compare head.repo.full_name against github.repository to refuse fork PRs"
    # Pin that the result is a refusal (skip / exit / continue / if:).
    assert re.search(
        r"refus|skip|continue|exit\s+0|fork",
        text,
        re.IGNORECASE,
    ), "auto-merge.yml must visibly refuse/skip on the fork branch"


# ─── Wall 2: policy reads from main, not PR head ───────────────────────


def test_policy_consuming_workflows_checkout_main():
    """Any workflow that sources tier-policy.config or imports
    scripts.lib.tier_policy must use actions/checkout with ref: main,
    not the PR's head ref. Otherwise a PR could ship a poisoned
    policy file and have it consulted at merge time.
    """
    offenders = []
    for path in all_workflows():
        text = path.read_text()
        consumes_policy = (
            "tier-policy.config" in text or "scripts.lib.tier_policy" in text
        )
        if not consumes_policy:
            continue
        # Workflow consumes policy. It must explicitly checkout main.
        # Look for `ref: main` somewhere in the file (a step-level arg).
        if not re.search(r"\bref:\s*main\b", text):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert not offenders, (
        "These workflows consume tier-policy.config but do not "
        f"explicitly checkout ref: main: {offenders}"
    )


# ─── Wall 3: no pull_request_target checks out PR head ─────────────────

_PR_HEAD_REF_PATTERN = re.compile(
    r"github\.event\.pull_request\.head\.(ref|sha)", re.IGNORECASE
)


def test_pull_request_target_never_checks_out_pr_head():
    """pull_request_target runs in the base repo's privileged context.
    Checking out the PR head means running attacker-controlled code
    in that context — a classic GitHub Actions footgun. Pin: no
    pull_request_target workflow references github.event.pull_request.
    head.{ref,sha} anywhere in an actions/checkout step.
    """
    for path in all_workflows():
        wf = _load(path)
        trig = _trigger(wf)
        if "pull_request_target" not in (trig if isinstance(trig, dict) else {}):
            continue
        for job_name, step in _every_step(wf):
            uses = step.get("uses", "")
            if not isinstance(uses, str) or not uses.startswith("actions/checkout"):
                continue
            with_args = step.get("with") or {}
            ref = with_args.get("ref")
            if isinstance(ref, str) and _PR_HEAD_REF_PATTERN.search(ref):
                pytest.fail(
                    f"{path.name}/{job_name}: actions/checkout uses PR head "
                    f"ref ({ref!r}) under pull_request_target — RCE risk"
                )


# ─── Wall 4: no workflow grants permissions: actions: write ────────────

_DANGEROUS_TOP_LEVEL_PERMS = {
    # Mutating other workflows or rewriting branch protection from
    # within an action grants implicit privilege escalation. The
    # tier-1/2 surfaces only ever need pull-requests + contents.
    "actions": "write",
    "deployments": "write",
    "id-token": "write",
}

# Documented exemptions: workflow name → (scope, justification). If
# someone needs to add a new exemption, the entry MUST include the
# reason — the test is the audit log. Format keeps the noise low when
# we eyeball this list.
_DANGEROUS_PERMS_EXEMPTIONS = {
    ("docker-image-build-release.yml", "id-token"): (
        "GitHub OIDC for sigstore/cosign attestations on the container image; "
        "required for SLSA provenance. Issued per-job, expires immediately."
    ),
    ("update-translations.yml", "actions"): (
        "Workflow re-dispatches itself / downstream workflows after pushing "
        "translation updates so dependent runs pick up fresh .po files."
    ),
}


def test_no_workflow_grants_dangerous_permissions():
    """No workflow grants write access to surfaces that aren't required
    for tier-merge. Documented exemptions live in
    _DANGEROUS_PERMS_EXEMPTIONS — adding a new one is the audit
    moment: every exemption must explain why the broader scope is
    necessary. Silent widening goes red.
    """
    offenders = []
    for path in all_workflows():
        wf = _load(path)
        perms = wf.get("permissions")
        if isinstance(perms, str):
            if perms in ("write-all",):
                offenders.append(f"{path.name}: top-level permissions: {perms}")
            continue
        if not isinstance(perms, dict):
            continue
        for scope, level in perms.items():
            if scope not in _DANGEROUS_TOP_LEVEL_PERMS:
                continue
            if level != _DANGEROUS_TOP_LEVEL_PERMS[scope]:
                continue
            if (path.name, scope) in _DANGEROUS_PERMS_EXEMPTIONS:
                continue
            offenders.append(f"{path.name}: permissions.{scope}: {level}")
        # Also check job-level perms.
        for job_name, job in (wf.get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            job_perms = job.get("permissions") or {}
            if isinstance(job_perms, str) and job_perms == "write-all":
                offenders.append(f"{path.name}/{job_name}: permissions: {job_perms}")
                continue
            if not isinstance(job_perms, dict):
                continue
            for scope, level in job_perms.items():
                if scope not in _DANGEROUS_TOP_LEVEL_PERMS:
                    continue
                if level != _DANGEROUS_TOP_LEVEL_PERMS[scope]:
                    continue
                if (path.name, scope) in _DANGEROUS_PERMS_EXEMPTIONS:
                    continue
                offenders.append(f"{path.name}/{job_name}: permissions.{scope}: {level}")
    assert not offenders, (
        "Workflows granting dangerous write permissions without explicit exemption "
        f"in _DANGEROUS_PERMS_EXEMPTIONS: {offenders}"
    )


# ─── Wall 5: no workflow pushes / mutates upstream ─────────────────────


def test_no_workflow_pushes_to_upstream():
    """CLAUDE.md hard rule #2: never push to upstream. Workflows
    referencing the upstream repo name are OK only if they're
    read-only (e.g. the integration-test docker image tag uses the
    upstream image name historically). Pin: no `gh ... --repo
    crocodilestick/...` mutating call, no `git push` to upstream.
    """
    upstreams = (
        "crocodilestick/Calibre-Web-Automated",
        "crocodilestick/calibre-web-automated",
        "janeczku/calibre-web",
    )
    offenders = []
    push_re = re.compile(r"\bgit\s+push\b.*({})".format("|".join(upstreams)))
    gh_write_re = re.compile(
        r"\bgh\s+(?:pr|issue|api|release)[^\n]*?\s--repo\s+("
        + "|".join(re.escape(u) for u in upstreams)
        + r")",
        re.IGNORECASE,
    )
    # `gh issue list`, `gh pr list`, `gh api repos/.../issues` (read) are OK.
    # Only flag mutating subcommands.
    gh_mutating_subcommands = re.compile(
        r"\bgh\s+(?:pr\s+(?:create|merge|close|edit|comment|reopen|review|ready)"
        r"|issue\s+(?:create|close|edit|comment|reopen|delete|transfer|lock)"
        r"|release\s+(?:create|edit|delete|upload)"
        r"|api\s+(?:-X\s+(?:POST|PATCH|PUT|DELETE)|--method\s+(?:POST|PATCH|PUT|DELETE))"
        r")",
        re.IGNORECASE,
    )
    for path in all_workflows():
        text = path.read_text()
        if push_re.search(text):
            offenders.append(f"{path.name}: git push targets upstream")
        if gh_write_re.search(text) and gh_mutating_subcommands.search(text):
            for line in text.splitlines():
                if any(u in line for u in upstreams) and gh_mutating_subcommands.search(line):
                    offenders.append(f"{path.name}: gh mutating call against upstream: {line.strip()[:120]}")
    assert not offenders, (
        "Workflow(s) appear to mutate an upstream repo (hard rule #2 violation): "
        f"{offenders}"
    )


# ─── Wall 6: structural sanity ─────────────────────────────────────────


# ─── Wall 7: validate-author skips merge commits ───────────────────────
#
# GitHub's "Update branch" web button (and auto-update of a behind
# branch) produces a merge commit whose committer is
# `GitHub <noreply@github.com>` — the clicker is the author, not the
# committer. validate-author scans committer email (%ce), so without
# `--no-merges` every PR that sits long enough for main to advance and
# need a branch update fails the committer gate. That's a recurring
# catch-22 unrelated to who authored the substantive code. These tests
# pin that merge commits are skipped AND that foreign *non-merge*
# commits are still caught (the gate isn't over-relaxed).

VALIDATE_AUTHOR = WF_DIR / "validate-author.yml"
_GITHUB_WEB_MERGE_COMMITTER = "noreply@github.com"
_NEW_USEMAME_COMMITTER = "248195428+new-usemame@users.noreply.github.com"


def _git(repo: Path, *args: str, committer_email: str = _NEW_USEMAME_COMMITTER):
    """Run a git command in `repo` with deterministic author/committer."""
    env = dict(os.environ)
    env.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "HOME": str(repo),  # isolate from the dev's global git config
            "GIT_AUTHOR_NAME": "tester",
            "GIT_AUTHOR_EMAIL": "tester@example.com",
            "GIT_COMMITTER_NAME": "tester",
            "GIT_COMMITTER_EMAIL": committer_email,
        }
    )
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def _committer_scan(repo: Path, base: str, head: str) -> list[str]:
    """Mirror the workflow's scan command and return the committer
    emails it would inspect for the range base..head."""
    out = _git(repo, "log", "--no-merges", "--format=%H %ce", f"{base}..{head}")
    return [line.split()[1] for line in out.stdout.splitlines() if line.strip()]


def test_validate_author_uses_no_merges_flag():
    """Source-pin: the committer scan must use `--no-merges`. If this
    regresses, web-UI branch updates will block auto-merge again."""
    assert VALIDATE_AUTHOR.exists(), f"missing {VALIDATE_AUTHOR}"
    text = VALIDATE_AUTHOR.read_text()
    scan_line = next(
        (ln for ln in text.splitlines() if "git log" in ln and "%ce" in ln),
        None,
    )
    assert scan_line is not None, "validate-author.yml committer-scan git log line not found"
    assert "--no-merges" in scan_line, (
        "validate-author.yml committer scan must pass --no-merges so the "
        f"GitHub web-UI 'Update branch' merge commit (committer {_GITHUB_WEB_MERGE_COMMITTER}) "
        "doesn't break the gate. Found: " + scan_line.strip()
    )


@pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")
def test_no_merges_skips_web_update_merge_commit_but_keeps_real_commits():
    """Behavioral: a web-UI 'Update branch' merge commit (committer
    noreply@github.com) is excluded from the scan, while the PR's own
    new-usemame commit is still inspected."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        _git(repo, "init", "-b", "main")
        (repo / "a.txt").write_text("base\n")
        _git(repo, "add", "a.txt")
        _git(repo, "commit", "-m", "base")
        base = _git(repo, "rev-parse", "HEAD").stdout.strip()

        # PR branch with one legitimate new-usemame commit.
        _git(repo, "checkout", "-b", "feature")
        (repo / "b.txt").write_text("pr work\n")
        _git(repo, "add", "b.txt")
        _git(repo, "commit", "-m", "pr commit")
        pr_commit = _git(repo, "rev-parse", "HEAD").stdout.strip()

        # main advances.
        _git(repo, "checkout", "main")
        (repo / "c.txt").write_text("main moved\n")
        _git(repo, "add", "c.txt")
        _git(repo, "commit", "-m", "main advances")

        # 'Update branch' merge: committer is GitHub's web identity.
        _git(repo, "checkout", "feature")
        _git(
            repo,
            "merge",
            "main",
            "--no-ff",
            "-m",
            "Merge branch 'main' into feature",
            committer_email=_GITHUB_WEB_MERGE_COMMITTER,
        )
        merge_sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
        head = merge_sha

        committers = _committer_scan(repo, base, head)
        # The merge commit's foreign committer must NOT appear (skipped).
        assert _GITHUB_WEB_MERGE_COMMITTER not in committers, (
            "web-UI merge commit committer leaked into the scan despite --no-merges"
        )
        # The real PR commit must still be inspected.
        scanned_shas = _git(
            repo, "log", "--no-merges", "--format=%H", f"{base}..{head}"
        ).stdout.split()
        assert pr_commit in scanned_shas, "PR commit dropped from scan"
        assert merge_sha not in scanned_shas, "merge commit not skipped by --no-merges"


@pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")
def test_no_merges_still_catches_foreign_non_merge_commit():
    """Guard against over-relaxing: a *non-merge* commit by a foreign
    committer must still be inspected (and would be flagged BAD)."""
    with tempfile.TemporaryDirectory() as td:
        repo = Path(td)
        _git(repo, "init", "-b", "main")
        (repo / "a.txt").write_text("base\n")
        _git(repo, "add", "a.txt")
        _git(repo, "commit", "-m", "base")
        base = _git(repo, "rev-parse", "HEAD").stdout.strip()

        _git(repo, "checkout", "-b", "feature")
        (repo / "b.txt").write_text("sneaky\n")
        _git(repo, "add", "b.txt")
        _git(repo, "commit", "-m", "foreign commit", committer_email="attacker@evil.example")
        head = _git(repo, "rev-parse", "HEAD").stdout.strip()

        committers = _committer_scan(repo, base, head)
        assert "attacker@evil.example" in committers, (
            "--no-merges must not hide foreign non-merge commits from the gate"
        )


def test_all_workflows_have_minimum_permissions_block():
    """Every workflow that does any mutating action (commenting,
    labeling, merging) must have an explicit top-level OR job-level
    permissions block. Implicit GITHUB_TOKEN permissions are too
    broad for CI surfaces this sensitive. Workflows that are pure
    read-only (test runners) can omit the block — we only flag
    workflows whose run blocks reference mutating gh commands.
    """
    offenders = []
    mutating = re.compile(
        r"\bgh\s+(?:pr|issue|release)\s+(?:create|merge|close|edit|comment|reopen|review|ready|delete|upload)\b",
        re.IGNORECASE,
    )
    for path in all_workflows():
        text = path.read_text()
        if not mutating.search(text):
            continue
        wf = _load(path)
        top = wf.get("permissions")
        any_job_perms = any(
            isinstance(job, dict) and "permissions" in job
            for job in (wf.get("jobs") or {}).values()
        )
        if top is None and not any_job_perms:
            offenders.append(path.name)
    assert not offenders, (
        "Workflow(s) with mutating gh calls but no explicit permissions block: "
        f"{offenders}"
    )
