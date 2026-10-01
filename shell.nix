# Development shell.
# Usage:
#   nix develop          (with flakes enabled)
#   nix-shell            (legacy / without flakes)
{ pkgs ? import <nixpkgs> { } }:

let
  # Reuse the same Python package set as the main derivation so that
  # the in-tree source and the installed package see identical deps.
  devPython = pkgs.python3.withPackages (ps: with ps; [
    # ── Runtime deps (mirrors nix/package.nix) ───────────────────────────
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

    bleach
    certifi
    charset-normalizer
    cryptography
    idna
    python-magic

    chardet
    polib
    qrcode
    tabulate

    gevent
    greenlet

    beautifulsoup4
    html2text
    markdown2
    mutagen
    py7zr
    python-dateutil
    rarfile

    natsort

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

    python-ldap
    levenshtein
    jsonschema
    netifaces

    # ── Dev / test extras ─────────────────────────────────────────────────
    pytest
    pytest-flask
    pytest-cov
    pytest-mock
    pytest-timeout
    pytest-xdist
    freezegun
    requests-mock
    faker
    factory_boy
    isort
    ipython
  ]);
in
pkgs.mkShell {
  name = "calibre-web-automated-dev";

  packages = [
    devPython

    # Runtime system tools
    pkgs.calibre
    pkgs.imagemagick
    pkgs.ghostscript
    pkgs.file

    # Code quality
    pkgs.ruff
    pkgs.black

    # Database inspection
    pkgs.sqlite

    # Misc
    pkgs.git
    pkgs.curl
  ];

  shellHook = ''
    export PYTHONPATH="$(pwd):''${PYTHONPATH:-}"
    export CWA_PORT_OVERRIDE="''${CWA_PORT_OVERRIDE:-8083}"
    export CWA_LIBRARY_DIR="''${CWA_LIBRARY_DIR:-$HOME/calibre-library}"

    echo ""
    echo "  Calibre-Web Automated — development shell"
    echo ""
    echo "  Run:   python cps.py"
    echo "  Test:  pytest tests/"
    echo "  Lint:  ruff check cps/ && black --check cps/"
    echo "  Library: \$CWA_LIBRARY_DIR (override with CWA_LIBRARY_DIR=...)"
    echo ""
  '';
}
