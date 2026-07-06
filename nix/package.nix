{ lib
, python3
, calibre
, version ? "4.0.6"
}:

python3.pkgs.buildPythonApplication rec {
  pname = "calibre-web-automated";
  inherit version;
  pyproject = true;

  src = ../.;

  prePatch = ''
    # Fix broken entry point (calibreweb package does not exist in the tree).
    substituteInPlace pyproject.toml \
      --replace-fail 'cps = "calibreweb:main"' 'cps = "cps.main:main"'

    # Replace 'dynamic = ["version"]' in [project] with a static version,
    # then remove the now-invalid dynamic version line from [tool.setuptools.dynamic].
    substituteInPlace pyproject.toml \
      --replace-fail 'dynamic = ["version"]' 'version = "${version}"'
    sed -i '/^version = {attr/d' pyproject.toml

    # Restrict package discovery to the 'cps' package.
    # The source tree contains non-Python directories (nix/, root/, koreader/,
    # kubernetes/, …) that confuse setuptools' flat-layout auto-discovery.
    printf '\n[tool.setuptools.packages.find]\ninclude = ["cps*"]\n' >> pyproject.toml

    # Rename netifaces-plus → netifaces in the declared deps; the app imports
    # the module as 'netifaces' and nixpkgs ships netifaces under that name.
    sed -i 's/netifaces-plus/netifaces/g' pyproject.toml

    # flask-limiter 4.x removed the auto_check parameter (swallow_errors is still valid).
    sed -i 's/, auto_check=False//' cps/__init__.py

    # flask-limiter 4.x removed limiter.check(); the try block catches
    # AttributeError as a generic Exception and shows users a misleading
    # "Connection error" that blocks login entirely.  Stub it out so the
    # except branches are dead code and login proceeds normally.
    sed -i 's/        limiter\.check()/        pass  # limiter.check() removed in flask-limiter 4.x/' cps/web.py

    # Explicit package-data: 'include-package-data = true' only works with a
    # VCS checkout; the Nix sandbox has no .git, so non-.py files (templates,
    # static assets, translations) are silently omitted without this section.
    printf '\n[tool.setuptools.package-data]\ncps = ["templates/**", "static/**", "translations/**", "cache/**", "*.sql"]\n' >> pyproject.toml

    # ── Hardcoded Docker paths ────────────────────────────────────────────
    # All of these assume the Docker volume layout (/config, /app, /calibre-library).
    # Replace with constants.CONFIG_DIR (set to ~/.calibre-web-automated or
    # CALIBRE_DBPATH) so the app works on a normal Linux/NixOS system.

    # config_sql.py: replace the hardcoded /calibre-library fallback with an
    # env var so the NixOS module (and users) can point at any library dir.
    sed -i \
      "s|fallback_db = '/calibre-library/metadata.db'|fallback_db = os.path.join(os.environ.get('CWA_LIBRARY_DIR', '/calibre-library'), 'metadata.db')|" \
      cps/config_sql.py

    # cwa_db.py: database path
    substituteInPlace scripts/cwa_db.py \
      --replace-fail \
        'self.db_path = "/config/"' \
        'self.db_path = os.environ.get("CALIBRE_DBPATH", os.path.join(os.path.expanduser("~"), ".calibre-web-automated")) + "/"'

    # render_template.py: notice/sentinel files written on every page render
    sed -i \
      -e "s|'/app/cwa_update_notice'|os.path.join(constants.CONFIG_DIR, 'cwa_update_notice')|g" \
      -e "s|'/app/theme_migration_notice'|os.path.join(constants.CONFIG_DIR, 'theme_migration_notice')|g" \
      -e 's|f"/app/cwa_translation_notice_{lang}"|os.path.join(constants.CONFIG_DIR, f"cwa_translation_notice_{lang}")|g' \
      -e 's|po_path = f"cps/translations/{lang}/LC_MESSAGES/messages.po"|po_path = os.path.join(constants.TRANSLATIONS_DIR, lang, "LC_MESSAGES", "messages.po")|g' \
      cps/render_template.py

    # cwa_functions.py: log/archive paths and dirs.json
    sed -i \
      -e 's|LOG_ARCHIVE = "/config/log_archive"|LOG_ARCHIVE = os.path.join(constants.CONFIG_DIR, "log_archive")|g' \
      -e 's|DIRS_JSON = "/app/calibre-web-automated/dirs.json"|DIRS_JSON = os.path.join(constants.BASE_DIR, "dirs.json")|g' \
      -e 's|log_path = "/config/convert-library.log"|log_path = os.path.join(constants.CONFIG_DIR, "convert-library.log")|g' \
      -e 's|LOG_DIR = "/config"|LOG_DIR = constants.CONFIG_DIR|g' \
      -e "s|with open(\"/config/convert-library.log\", 'r')|with open(os.path.join(constants.CONFIG_DIR, \"convert-library.log\"), 'r')|g" \
      -e 's|log_path = "/config/epub-fixer.log"|log_path = os.path.join(constants.CONFIG_DIR, "epub-fixer.log")|g' \
      -e "s|with open(\"/config/epub-fixer.log\", 'r')|with open(os.path.join(constants.CONFIG_DIR, \"epub-fixer.log\"), 'r')|g" \
      -e 's|json_path = "/config/user_profiles.json"|json_path = os.path.join(constants.CONFIG_DIR, "user_profiles.json")|g' \
      cps/cwa_functions.py

    # admin.py: backup dir and calibredb fallback path
    sed -i \
      -e 's|app_db_path = ub.app_DB_path or cli_param.settings_path or "/config/app.db"|app_db_path = ub.app_DB_path or cli_param.settings_path or os.path.join(constants.CONFIG_DIR, "app.db")|g' \
      -e 's|calibredb_binary = get_calibre_binarypath("calibredb") or "/app/calibre/calibredb"|calibredb_binary = get_calibre_binarypath("calibredb") or "calibredb"|g' \
      cps/admin.py
    # backup_dir contains single quotes inside the f-string so sed can't quote
    # it cleanly; use Python for the replacement instead.
    python3 -c "
import re, pathlib
p = pathlib.Path('cps/admin.py')
src = p.read_text()
src = src.replace(
    \"backup_dir = f\\\"/config/backup/restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}\\\"\",
    \"backup_dir = os.path.join(constants.CONFIG_DIR, \\\"backup\\\", f\\\"restore_{datetime.now().strftime('%Y%m%d_%H%M%S')}\\\")\",
)
p.write_text(src)
"

    # duplicates.py: resolution backup path (Python for single-quote safety)
    python3 -c "
import pathlib
p = pathlib.Path('cps/duplicates.py')
src = p.read_text()
src = src.replace(
    \"backup_dir = f\\\"/config/processed_books/duplicate_resolutions/{datetime.now().strftime('%Y%m%d_%H%M%S')}_group_{group['group_hash'][:8]}\\\"\",
    \"backup_dir = os.path.join(constants.CONFIG_DIR, \\\"processed_books\\\", \\\"duplicate_resolutions\\\", f\\\"{datetime.now().strftime('%Y%m%d_%H%M%S')}_group_{group['group_hash'][:8]}\\\")\",
)
p.write_text(src)
"

    # Comprehensive Docker-path sweep: replaces all remaining /config/, /app/,
    # and /calibre-library/ references across cps/ and scripts/.
    # See nix/patch_paths.py for full documentation of what is replaced and why.
    python3 ${./patch_paths.py}
  '';

  nativeBuildInputs = with python3.pkgs; [
    setuptools
    # Strips upper-bound version pins that are tighter than what nixpkgs ships.
    # The app's constraints (e.g. flask-babel<4.1, lxml<5.4, cryptography<45)
    # predate current nixpkgs versions; the packages themselves are compatible.
    pythonRelaxDepsHook
  ];

  pythonRelaxDeps = true;

  propagatedBuildInputs = with python3.pkgs; [
    # ── Core ──────────────────────────────────────────────────────────────
    apscheduler
    babel
    flask
    flask-babel
    flask-httpauth
    flask-limiter
    flask-principal
    flask-wtf
    lxml
    pycountry
    pypdf
    pytz
    regex
    requests
    sqlalchemy
    tornado
    unidecode
    urllib3
    wand

    # Security / crypto
    bleach
    certifi
    charset-normalizer
    cryptography
    idna
    python-magic

    # Utilities
    chardet
    polib
    qrcode
    tabulate

    # ── Optional extras (included by default — widely needed) ─────────────

    # Async WSGI server (preferred over Tornado)
    gevent
    greenlet

    # Metadata extraction
    beautifulsoup4
    html2text
    markdown2
    mutagen
    py7zr
    python-dateutil
    rarfile

    # Comics
    natsort

    # OAuth / Google Drive / Gmail
    flask-dance
    google-api-python-client
    google-auth-oauthlib
    httplib2
    oauth2client
    pyasn1
    pyasn1-modules
    pyyaml
    rsa
    sqlalchemy-utils
    uritemplate

    # LDAP authentication
    python-ldap

    # Fuzzy matching (Goodreads, metadata)
    levenshtein

    # Kobo integration
    jsonschema

    # pyproject.toml lists netifaces-plus, but the app imports the module as
    # 'netifaces' and handles its absence.  nixpkgs ships the original
    # netifaces package under the same module name, so it works as a drop-in.
    netifaces

    # TODO: packages not yet in nixpkgs — add custom derivations as needed:
    #   curl-cffi       (Kobo HTTP client)
    #   comicapi        (comic metadata)
    #   faust-cchardet  (charset detection for metadata extraction)
    #   goodreads       (Goodreads API client)
    #   pydrive2        (Google Drive v2 client)
    #   flask-simpleldap
    #   scholarly       (academic metadata)
  ];

  postInstall = ''
    # Install all scripts to site-packages so that:
    #   a) `import cwa_db` works without sys.path manipulation
    #   b) subprocess calls via sys.executable + constants.BASE_DIR resolve
    #   c) __file__-relative lookups for dirs.json / schema land correctly
    cp scripts/*.py  "$out/${python3.sitePackages}/"
    cp scripts/*.sql "$out/${python3.sitePackages}/"

    # Stamp version files so about.py / admin.py can read them.
    # constants.py prefers the CWA_INSTALLED_VERSION env var (set in the
    # wrapper below) but the direct file-open paths in about.py / admin.py
    # look at BASE_DIR (= site-packages).
    echo "v${version}" > "$out/${python3.sitePackages}/CWA_RELEASE"
    echo "v${version}" > "$out/${python3.sitePackages}/CWA_STABLE_RELEASE"
    echo "v0.0.0"      > "$out/${python3.sitePackages}/KEPUBIFY_RELEASE"

    # cps/constants.py looks for a .HOMEDIR sentinel in the cps package
    # directory.  When present it uses ~/.calibre-web-automated as the config
    # root; when absent it falls back to BASE_DIR (the Nix store — read-only).
    touch "$out/${python3.sitePackages}/cps/.HOMEDIR"
  '';

  makeWrapperArgs = [
    "--prefix PATH : ${lib.makeBinPath [ calibre ]}"
    # constants.py reads CWA_INSTALLED_VERSION before falling back to the file
    "--set CWA_INSTALLED_VERSION v${version}"
    "--set CWA_STABLE_VERSION    v${version}"
  ];

  # Tests require a running Calibre library; skip during the Nix build.
  doCheck = false;

  # Importing cps triggers os.makedirs("~/.calibre-web-automated") at module
  # level (cps/constants.py), which fails in the sandbox where HOME is not
  # writable.  The package installs correctly; skip this check.
  pythonImportsCheck = [ ];

  meta = {
    description = "Calibre-Web with automated library management and many new features";
    longDescription = ''
      Calibre-Web Automated is a fork of Calibre-Web that adds automated book
      ingest, format conversion, metadata enforcement, duplicate detection,
      Kobo/KOReader sync, and Hardcover metadata integration.
    '';
    homepage = "https://github.com/crocodilestick/Calibre-Web-Automated";
    changelog = "https://github.com/crocodilestick/Calibre-Web-Automated/releases";
    license = lib.licenses.gpl3Plus;
    maintainers = [ ];
    platforms = lib.platforms.linux;
    mainProgram = "cps";
  };
}
