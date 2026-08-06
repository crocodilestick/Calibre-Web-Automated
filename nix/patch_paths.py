#!/usr/bin/env python3
"""
Patch hardcoded Docker paths in Calibre-Web-Automated for Nix packaging.
Must be run from the repo root directory (where cps/ and scripts/ live).

Docker layout assumed by the source:
  /config/             – runtime config / data (app.db, logs, processed_books, …)
  /app/calibre-web-automated/ – app install dir (scripts, dirs.json, version files)
  /calibre-library/    – Calibre library (metadata.db)

Nix replacements:
  /config/             → constants.CONFIG_DIR  (cps/ files)
                         os.environ["CALIBRE_DBPATH"] / ~/.calibre-web-automated  (scripts/)
  /app/…/scripts/      → site-packages  (sys.path lines removed; scripts installed there)
  /app/…/dirs.json     → constants.CONFIG_DIR/dirs.json  (written by module preStart)
  /app/…/metadata_*    → CONFIG_DIR/…
  /app/CWA_RELEASE     → constants.BASE_DIR/CWA_RELEASE  (file installed in postInstall)
  /calibre-library/    → os.environ["CWA_LIBRARY_DIR"]  (set by module / user)
"""
import pathlib
import sys

ROOT = pathlib.Path(".")


def apply(path, *replacements, warn_missing=True):
    """Apply text replacements to a source file in-place."""
    p = ROOT / path
    if not p.exists():
        print(f"SKIP  {path}: not found", file=sys.stderr)
        return
    text = p.read_text()
    for old, new in replacements:
        if old in text:
            text = text.replace(old, new)
        elif warn_missing:
            print(f"WARN  {path}: pattern not found: {old!r}", file=sys.stderr)
    p.write_text(text)


# ── 1. Remove all sys.path.insert('/app/calibre-web-automated/scripts/') ─────
# Every script is installed to site-packages; path manipulation is unnecessary.
# Only remove lines that are sys.path operations — NOT subprocess calls that
# happen to reference the same scripts/ directory.
for py in ROOT.glob("cps/**/*.py"):
    text = py.read_text()
    filtered = "".join(
        line for line in text.splitlines(keepends=True)
        if not (
            "/app/calibre-web-automated/scripts/" in line
            and "sys.path" in line  # matches both sys.path and _sys.path
        )
    )
    if filtered != text:
        py.write_text(filtered)

# ── 2. Fix DIRS_JSON location ─────────────────────────────────────────────────
# The existing prePatch sed already replaced the Docker path with BASE_DIR, but
# BASE_DIR is the read-only Nix store.  dirs.json is a runtime file → CONFIG_DIR.
apply("cps/cwa_functions.py",
    ('DIRS_JSON = os.path.join(constants.BASE_DIR, "dirs.json")',
     'DIRS_JSON = os.path.join(constants.CONFIG_DIR, "dirs.json")'))

# ── 3. /calibre-library/metadata.db → CWA_LIBRARY_DIR env var ───────────────
_lib_sq = "os.path.join(os.environ.get('CWA_LIBRARY_DIR', '/calibre-library'), 'metadata.db')"
_lib_dq = 'os.path.join(os.environ.get("CWA_LIBRARY_DIR", "/calibre-library"), "metadata.db")'
_lib_dir_sq = "os.environ.get('CWA_LIBRARY_DIR', '/calibre-library')"

for f in ["cps/admin.py", "scripts/cwa_db.py", "scripts/kindle_epub_fixer.py"]:
    apply(f,
        ("'/calibre-library/metadata.db'", _lib_sq),
        ('"/calibre-library/metadata.db"', _lib_dq),
        warn_missing=False)

# admin.py has two fallback assignments that set `incoming` to the Docker path
# after the isfile check (which we've already patched above to use CWA_LIBRARY_DIR).
# The assignment itself must also use the env var, otherwise `incoming` ends up
# pointing at /calibre-library (which doesn't exist) and check_valid_db fails.
apply("cps/admin.py",
    ("        incoming = '/calibre-library'", f"        incoming = {_lib_dir_sq}"),
    warn_missing=False)

# kindle_epub_fixer.py has a bare `return` statement form too
apply("scripts/kindle_epub_fixer.py",
    ('return "/calibre-library/metadata.db"',
     'return os.path.join(os.environ.get("CWA_LIBRARY_DIR", "/calibre-library"), "metadata.db")'),
    warn_missing=False)

# ── 4. /app/ version files → constants.BASE_DIR (installed by postInstall) ───
# admin.py imports `from . import constants` so BASE_DIR is available.
# about.py already wraps the open() in try/except → shows "Unknown" gracefully.
apply("cps/admin.py",
    ('"/app/CWA_RELEASE"',        'os.path.join(constants.BASE_DIR, "CWA_RELEASE")'),
    ('"/app/KEPUBIFY_RELEASE"',   'os.path.join(constants.BASE_DIR, "KEPUBIFY_RELEASE")'),
    ('"/app/CWA_STABLE_RELEASE"', 'os.path.join(constants.BASE_DIR, "CWA_STABLE_RELEASE")'),
    warn_missing=False)

# ── 5. cwa_functions.py: remaining /config/ paths not in the first pass ──────
# (LOG_ARCHIVE, log_path, LOG_DIR, user_profiles.json already done via sed)
apply("cps/cwa_functions.py",
    ("with open('/config/cwa_ingest_status', 'r')",
     "with open(os.path.join(constants.CONFIG_DIR, 'cwa_ingest_status'), 'r')"),
    ("with open('/config/cwa_ingest_retry_queue', 'r')",
     "with open(os.path.join(constants.CONFIG_DIR, 'cwa_ingest_retry_queue'), 'r')"),
    # write-mode opens (read-mode already patched by earlier sed)
    ("open('/config/convert-library.log', 'w')",
     "open(os.path.join(constants.CONFIG_DIR, 'convert-library.log'), 'w')"),
    ("open('/config/epub-fixer.log', 'w')",
     "open(os.path.join(constants.CONFIG_DIR, 'epub-fixer.log'), 'w')"))

# ── 6. cwa_functions.py: subprocess calls → site-packages scripts ────────────
# sys is already imported in cwa_functions.py.
# constants.BASE_DIR is site-packages, where all scripts/ are installed.
apply("cps/cwa_functions.py",
    ("'python3', '/app/calibre-web-automated/scripts/ingest_processor.py'",
     "sys.executable, os.path.join(constants.BASE_DIR, 'ingest_processor.py')"),
    ("'python3', '/app/calibre-web-automated/scripts/convert_library.py'",
     "sys.executable, os.path.join(constants.BASE_DIR, 'convert_library.py')"),
    ("'python3', '/app/calibre-web-automated/scripts/kindle_epub_fixer.py'",
     "sys.executable, os.path.join(constants.BASE_DIR, 'kindle_epub_fixer.py')"),
    # Docker-only service health check — no-op on NixOS
    ("'/app/calibre-web-automated/scripts/check-cwa-services.sh'",
     "'true'"),
    ('"/app/calibre-web-automated/scripts/kindle_epub_fixer.py"',
     'os.path.join(constants.BASE_DIR, "kindle_epub_fixer.py")'))

# ── 7. web.py: dirs.json path ─────────────────────────────────────────────────
apply("cps/web.py",
    ("with open('/app/calibre-web-automated/dirs.json', 'r') as f:",
     "with open(os.path.join(constants.CONFIG_DIR, 'dirs.json'), 'r') as f:"))

# ── 8. tasks/ops.py: log paths ───────────────────────────────────────────────
# ops.py imports `os` but not `constants`; use env var directly.
_dbpath = ("os.path.join(os.environ.get('CALIBRE_DBPATH',"
           " os.path.expanduser('~/.calibre-web-automated'))")
apply("cps/tasks/ops.py",
    ('self.log_path = "/config/convert-library.log"',
     f"self.log_path = {_dbpath}, 'convert-library.log')"),
    ('self.log_path = "/config/epub-fixer.log"',
     f"self.log_path = {_dbpath}, 'epub-fixer.log')"))

# ── 9. editbooks.py: metadata_change_logs → constants.CONFIG_DIR ─────────────
# editbooks.py imports `from . import constants`.
# Replace the base path prefix inside f-strings; the {expr} tails are preserved.
# The f-string uses single quotes so we use double quotes inside the replacement
# expression to avoid a syntax conflict.
apply("cps/editbooks.py",
    ("/app/calibre-web-automated/metadata_change_logs/",
     '{os.path.join(constants.CONFIG_DIR, "metadata_change_logs")}/'),
    warn_missing=False)

# ── 10. scripts/ directory: /config/ and /app/ paths ─────────────────────────
# These scripts don't import from cps; use os.environ directly.
_cfg = ('os.environ.get("CALIBRE_DBPATH",'
        ' os.path.join(os.path.expanduser("~"), ".calibre-web-automated"))')

_scripts = [
    "scripts/convert_library.py",
    "scripts/cover_enforcer.py",
    "scripts/ingest_processor.py",
    "scripts/kindle_epub_fixer.py",
    "scripts/auto_zip.py",
    "scripts/generate_book_checksums.py",
    "scripts/cwa_db.py",
]

for script in _scripts:
    apply(script,
        # /config/app.db
        ('"/config/app.db"',
         f'os.path.join({_cfg}, "app.db")'),
        # /config/processed_books  (exact string, no trailing slash)
        ('"/config/processed_books"',
         f'os.path.join({_cfg}, "processed_books")'),
        # /config/processed_books/ (trailing slash variant)
        ('"/config/processed_books/"',
         f'os.path.join({_cfg}, "processed_books") + "/"'),
        # dirs.json → alongside the installed script (site-packages after install)
        ('"/app/calibre-web-automated/dirs.json"',
         'os.path.join(os.path.dirname(os.path.abspath(__file__)), "dirs.json")'),
        ("'/app/calibre-web-automated/dirs.json'",
         "os.path.join(os.path.dirname(os.path.abspath(__file__)), 'dirs.json')"),
        # metadata_change_logs / metadata_temp → config dir
        ('"/app/calibre-web-automated/metadata_change_logs"',
         f'os.path.join({_cfg}, "metadata_change_logs")'),
        ('"/app/calibre-web-automated/metadata_temp"',
         f'os.path.join({_cfg}, "metadata_temp")'),
        warn_missing=False)

# Per-script extras not covered by the generic loop:

apply("scripts/cwa_db.py",
    # single-quoted debug log path
    ("with open('/config/.cwa_db_debug', 'a') as f:",
     f"with open(os.path.join({_cfg}, '.cwa_db_debug'), 'a') as f:"),
    warn_missing=False)

apply("scripts/convert_library.py",
    ('convert_library_log_file = "/config/convert-library.log"',
     f'convert_library_log_file = os.path.join({_cfg}, "convert-library.log")'),
    # f-string path not caught by the generic "/config/processed_books" replacement
    ('output_path = f"/config/processed_books/failed/{os.path.basename(target_filepath)}"',
     f'output_path = os.path.join({_cfg}, "processed_books", "failed",'
     ' os.path.basename(target_filepath))'),
    warn_missing=False)

apply("scripts/kindle_epub_fixer.py",
    ('epub_fixer_log_file = "/config/epub-fixer.log"',
     f'epub_fixer_log_file = os.path.join({_cfg}, "epub-fixer.log")'),
    # f-string path with trailing slash
    ('output_path = f"/config/processed_books/fixed_originals/"',
     f'output_path = os.path.join({_cfg}, "processed_books", "fixed_originals") + "/"'),
    warn_missing=False)

apply("scripts/auto_zip.py",
    ('self.archive_dirs_stem = "/config/processed_books/"',
     f'self.archive_dirs_stem = os.path.join({_cfg}, "processed_books") + "/"'),
    warn_missing=False)

print("All Docker path patches applied successfully.")
