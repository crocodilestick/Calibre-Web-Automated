# =====================================================================
# This script builds a custom Docker image of Calibre-Web-Automated.
# It clones the upstream repository into a specified local directory,
# then builds either a development or production image tagged under
# your Docker Hub username, with versioning and build date metadata.
#
# Optional Environment Variables:
#
#   REPO_DIR – Local directory where the Calibre-Web-Automated repo
#              will be cloned for building.
#              Example: export REPO_DIR="$HOME/cwa-repo-download"
#
#   DH_USER  – Docker Hub username used to tag the built image.
#              Example: export DH_USER="mydockerusername"
#
# If set, these values are used with confirmation prompts.
# If unset, the script will prompt for them with defaults.
#
# ⚠️ WARNING: Any existing files in REPO_DIR will be deleted
#              before cloning the repository.
# =====================================================================

#!/bin/bash
# Ensure we are running under bash even if invoked via `sh build.sh`
if [ -z "${BASH_VERSION:-}" ]; then
  if command -v bash >/dev/null 2>&1; then
    exec bash "$0" "$@"
  else
    echo "This script requires bash. Try: bash $0" >&2
    exit 1
  fi
fi

# ---- Pre-flight checks ----
die() { echo "❌ $*" >&2; exit 1; }

for dep in git docker; do
  command -v "$dep" >/dev/null 2>&1 || die "Missing dependency: $dep (install it and re-run)."
done

if ! docker info >/dev/null 2>&1; then
  echo "⚠️  Docker daemon not reachable."
  echo "    Try: sudo systemctl start docker   (or ensure your user is in the 'docker' group')"
  exit 1
fi

# ---- REPO_DIR selection ----
DEFAULT_HOME="${HOME:-}"
[ -z "$DEFAULT_HOME" ] && DEFAULT_HOME="changeme"
DEFAULT_REPO_DIR="$DEFAULT_HOME/cwa-repo-download"

if [ -n "${REPO_DIR:-}" ]; then
  echo "The CWA repo will be cloned into: $REPO_DIR (configured via \$REPO_DIR)"
  read -r -p "Confirm location? [y/N]: " confirm
  case "$confirm" in
    [Yy]*) ;;
    *) read -r -p "Enter new directory [ENTER for default: $DEFAULT_REPO_DIR]: " input_dir
       REPO_DIR="${input_dir:-$DEFAULT_REPO_DIR}"
       ;;
  esac
else
  read -r -p "Enter directory for repo files [ENTER for default: $DEFAULT_REPO_DIR]: " input_dir
  REPO_DIR="${input_dir:-$DEFAULT_REPO_DIR}"
fi

REPO_DIR="$(realpath -m "$REPO_DIR")"

# ---- Docker Hub username ----
DEFAULT_DH_USER="${USER:-}"
if [ -z "$DEFAULT_DH_USER" ]; then
  GH_USER="$(git config --global user.name 2>/dev/null || true)"
  DEFAULT_DH_USER="${GH_USER:-}"
fi
[ -z "$DEFAULT_DH_USER" ] && DEFAULT_DH_USER="changeme"

if [ -n "${DH_USER:-}" ]; then
  echo "Docker images will be tagged under: $DH_USER (configured via \$DH_USER)"
  read -r -p "Confirm Docker Hub username? [y/N]: " confirm
  case "$confirm" in
    [Yy]*) ;;
    *) read -r -p "Enter Docker Hub username [ENTER for default: $DEFAULT_DH_USER]: " input_user
       DH_USER="${input_user:-$DEFAULT_DH_USER}"
       ;;
  esac
else
  read -r -p "Enter Docker Hub username [ENTER for default: $DEFAULT_DH_USER]: " input_user
  DH_USER="${input_user:-$DEFAULT_DH_USER}"
fi

# ---- Build mode & version prompts ----
while true; do
  echo "Select build type:"
  echo "  [1] Development image"
  echo "  [2] Production image"
  read -r -p "Enter 1 or 2: " build_choice
  case "$build_choice" in
    1) build_type="dev"; break ;;
    2) build_type="prod"; break ;;
    *) echo "Invalid choice. Please enter 1 or 2."; echo ;;
  esac
done

while true; do
  read -r -p 'Enter Version Number (e.g., "V2.0.1"): ' version
  [ -n "$version" ] && break
  echo "Version cannot be empty."
done

testnum=""
if [ "$build_type" = "dev" ]; then
  while true; do
    read -r -p "Enter test version number (numeric only): " testnum
    [[ "$testnum" =~ ^[0-9]+$ ]] && break
    echo "Test number must be numeric (e.g., 1, 2, 10)."
  done
fi

# ---- Summary & confirmation ----
NOW="$(date +"%Y-%m-%d %H:%M:%S")"

if [ "$build_type" = "dev" ]; then
  image_preview="$DH_USER/calibre-web-automated:dev-$testnum"
  build_cmd="docker build --tag \"$image_preview\" --build-arg \"BUILD_DATE=$NOW\" --build-arg \"VERSION=${version}-TEST-${testnum}\" ."
else
  image_preview="$DH_USER/calibre-web-automated:$version"
  build_cmd="docker build --tag \"$image_preview\" --build-arg \"BUILD_DATE=$NOW\" --build-arg \"VERSION=$version\" ."
fi

echo
echo "============================================================"
echo "The script is ready to clone into: $REPO_DIR"
echo "A Docker image will be built as:  $image_preview"
echo
echo "⚠️  WARNING: Any existing files/code at:"
echo "   $REPO_DIR"
echo "   will be WIPED CLEAN in favor of a fresh clone."
echo
echo "Planned build command:"
echo "  $build_cmd"
echo "============================================================"
echo

# ---- Execute (destructive clone, then build) ----
read -r -p "Proceed? [Y/n]: " confirm
case "$confirm" in
  [Yy]* | "" )
    echo "Proceeding with clone and build..."

    REPO_URL="${REPO_URL:-https://github.com/crocodilestick/calibre-web-automated.git}"

    rm -rf -- "$REPO_DIR"            # destructive: matches warning above
    git clone --depth=1 "$REPO_URL" "$REPO_DIR"
    cd "$REPO_DIR"

    echo
    echo "Running build command:"
    echo "  $build_cmd"
    echo

    eval "$build_cmd"                # single source of truth

    if [ "$build_type" = "dev" ]; then
      TYPE_LABEL="Dev image Version ${version} - Test ${testnum}"
    else
      TYPE_LABEL="Prod image Version ${version}"
    fi

    echo
    echo "✅ $TYPE_LABEL created! Exiting now..."
    ;;
  * )
    echo "Cancelling build."
    exit 1
    ;;
esac
