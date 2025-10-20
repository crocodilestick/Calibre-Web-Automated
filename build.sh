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

set -u

usage() {
  printf 'Usage: %s [-l]\n' "${0}"
  printf '\t-l\t\tLocal build mode (skip git clone)\n'
  printf '\t-u DH_USER\tDocker Hub username\n'
  printf '\t-v VERSION\tVersion number (e.g., v2.0.1)\n'
  printf '\t-r TESTNUM\tTest version number (numeric only, for dev builds)\n'
  printf '\t-d REPO_DIR\tDirectory to clone repo into if not doing a local build\n'
  printf '\t-c CLONE_URL\tGit URL to clone from if not doing a local build\n'
  printf '\t-h\t\tShow this help message and exit\n'
}

while getopts "lu:v:r:d:c:h" opt; do
  case $opt in
  l)
    LOCAL_BUILD=1
    build_type="dev"
    ;;
  u)
    DH_USER="$OPTARG"
    DH_USER_FROM_ARG=1
    ;;
  v)
    version="$OPTARG"
    ;;
  r)
    testnum="$OPTARG"
    ;;
  d)
    REPO_DIR="$OPTARG"
    ;;
  c)
    REPO_URL="$OPTARG"
    ;;
  h)
    usage
    exit 0
    ;;
  *)
    usage
    exit 1
    ;;
  esac
done

: "${LOCAL_BUILD:=0}" # Set to 1 to skip git clone (for local dev/testing)
: "${DH_USER:=}"
: "${DH_USER_FROM_ARG:=0}"
: "${REPO_DIR:=}"
: "${REPO_URL:=https://github.com/crocodilestick/calibre-web-automated.git}"
: "${build_type:=}"
: "${version:=}"
: "${testnum:=}"

# ---- Pre-flight checks ----
die() {
  echo "❌ $*" >&2
  exit 1
}

for dep in git docker; do
  command -v "$dep" >/dev/null 2>&1 || die "Missing dependency: $dep (install it and re-run)."
done

if ! docker info >/dev/null 2>&1; then
  echo "⚠️  Docker daemon not reachable."
  echo "    Try: sudo systemctl start docker   (or ensure your user is in the 'docker' group')"
  exit 1
fi

# ---- REPO_DIR selection ----
if [ ${LOCAL_BUILD} -eq 1 ]; then
  REPO_DIR="$(dirname "${0}")"
  printf 'Doing local build from repo directory: %s\n' "${REPO_DIR}"
else
  if [ -n "${REPO_DIR}" ]; then
    echo "The CWA repo will be cloned into: ${REPO_DIR} (configured via \$REPO_DIR)"
    read -r -p "Confirm location? [y/N]: " confirm
    case "$confirm" in
    [Yy]*) ;;
    *)
      read -r -p "Enter new directory [ENTER for default: ${REPO_DIR}]: " input_dir
      REPO_DIR="${input_dir:-${REPO_DIR}}"
      ;;
    esac
  else
    DEFAULT_HOME="${HOME:-}"
    [ -z "${DEFAULT_HOME}" ] && die "Cannot find your home directory, set \$REPO_DIR manually."
    DEFAULT_REPO_DIR="${DEFAULT_HOME}/cwa-repo-download"

    read -r -p "Enter directory for repo files [ENTER for default: ${DEFAULT_REPO_DIR}]: " input_dir
    REPO_DIR="${input_dir:-${DEFAULT_REPO_DIR}}"
  fi

  REPO_DIR="$(realpath -m "${REPO_DIR}")"
fi

# ---- Docker Hub username ----
if [ -n "${DH_USER}" ]; then
  echo "Docker images will be tagged under: ${DH_USER} (configured via \$DH_USER)"
  if [ "${DH_USER_FROM_ARG}" -eq 0 ]; then
    read -r -p "Confirm Docker Hub username? [y/N]: " confirm
    case "$confirm" in
    [Yy]*) ;;
    *)
      read -r -p "Enter Docker Hub username [ENTER for default: ${DH_USER}]: " input_user
      DH_USER="${input_user:-${DH_USER}}"
      ;;
    esac
  fi
else
  DEFAULT_DH_USER="${USER:-}"
  if [ -z "$DEFAULT_DH_USER" ]; then
    GH_USER="$(git config --global user.name 2>/dev/null || true)"
    DEFAULT_DH_USER="${GH_USER:-}"
  fi
  [ -z "$DEFAULT_DH_USER" ] && die "Cannot find your username, set \$DH_USER manually."

  read -r -p "Enter Docker Hub username [ENTER for default: ${DEFAULT_DH_USER}]: " input_user
  DH_USER="${input_user:-${DEFAULT_DH_USER}}"
fi

# ---- Build mode & version prompts ----
if [ "${LOCAL_BUILD}" -eq 1 ]; then
  printf 'Local build mode, building development image\n'
else
  while true; do
    echo "Select build type:"
    echo "  [1] Development image"
    echo "  [2] Production image"
    read -r -p "Enter 1 or 2: " build_choice
    case "${build_choice}" in
    1)
      build_type="dev"
      break
      ;;
    2)
      build_type="prod"
      break
      ;;
    *)
      echo "Invalid choice. Please enter 1 or 2."
      echo
      ;;
    esac
  done
fi

while [ -z "${version}" ]; do
  read -r -p 'Enter Version Number (e.g., "V2.0.1"): ' version
  [ -z "${version}" ] && echo "Version cannot be empty."
done

if [ "$build_type" = "dev" ]; then
  while [[ ! "${testnum}" =~ ^[0-9]+$ ]]; do
    read -r -p "Enter test version number (numeric only): " testnum
    [[ ! "${testnum}" =~ ^[0-9]+$ ]] && echo "Test number must be numeric (e.g., 1, 2, 10)."
  done
fi

# ---- Summary & confirmation ----
NOW="$(date +"%Y-%m-%d %H:%M:%S")"

if [ "${build_type}" = "dev" ]; then
  image_preview="${DH_USER}/calibre-web-automated:dev-$testnum"
  version_str="${version}-TEST-${testnum}"
else
  image_preview="${DH_USER}/calibre-web-automated:$version"
  version_str="${version}"
fi

build_cmd="docker build --tag \"${image_preview}\" --build-arg \"BUILD_DATE=${NOW}\" --build-arg \"VERSION=${version_str}\" ."

echo
echo "============================================================"
[ "${LOCAL_BUILD}" -eq 0 ] && echo "The script is ready to clone into: ${REPO_DIR}"
echo "A Docker image will be built as:  ${image_preview}"
echo
if [ "${LOCAL_BUILD}" -eq 0 ]; then
  echo "⚠️  WARNING: Any existing files/code at:"
  echo "   ${REPO_DIR}"
  echo "   will be WIPED CLEAN in favor of a fresh clone."
  echo
fi
echo "Planned build command:"
echo "  ${build_cmd}"
echo "============================================================"
echo

# ---- Execute (destructive clone, then build) ----
read -r -p "Proceed? [Y/n]: " confirm
case "${confirm}" in
[Yy]* | "")
  if [ "${LOCAL_BUILD}" -eq 0 ]; then
    echo "Proceeding with clone and build..."

    rm -rf -- "${REPO_DIR}" # destructive: matches warning above
    git clone --depth=1 "${REPO_URL}" "${REPO_DIR}"
  else
    printf 'Proceeding with local build from: %s\n' "${REPO_DIR}"
  fi
  cd "${REPO_DIR}"

  echo
  echo "Running build command:"
  echo "  ${build_cmd}"
  echo

  eval "${build_cmd}" # single source of truth

  if [ "${build_type}" = "dev" ]; then
    TYPE_LABEL="Dev image Version ${version} - Test ${testnum}"
  else
    TYPE_LABEL="Prod image Version ${version}"
  fi

  echo
  echo "✅ ${TYPE_LABEL} created! Exiting now..."
  ;;
*)
  echo "Cancelling build."
  exit 1
  ;;
esac
