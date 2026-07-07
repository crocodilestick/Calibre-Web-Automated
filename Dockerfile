ARG BASE_IMAGE=ghcr.io/linuxserver/baseimage-debian:trixie
ARG BUILD_DATE
ARG CALIBRE_RELEASE=9.1.0
ARG DEBIAN_FRONTEND=noninteractive
ARG KEPUBIFY_RELEASE=v4.0.4
# Install lsof 4.99.5 from source to fix hanging issue with 4.95 (issue #654)
ARG LSOF_VERSION=4.99.5
ARG TARGETARCH
ARG VERSION

# ==============================================================================
# STAGE 1: Common runtime base. Installs runtime packages only, the final image
# is built FROM this stage so the runtime package layer can be cached.
# ==============================================================================
FROM ${BASE_IMAGE} AS runtime-base

# Set the default shell for the following RUN instructions to bash instead of sh
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

ARG DEBIAN_FRONTEND=noninteractive

RUN \
  apt-get update && \
  apt-get install -y --no-install-recommends \
  binutils \
  build-essential \
  curl \
  libldap2-dev \
  libsasl2-dev \
  gettext \
  ghostscript \
  imagemagick \
  inotify-tools \
  # libasound2t64 \
  libxdamage1 \
  libegl1 \
  libgl1 \
  libglx-mesa0 \
  libldap2 \
  libmagic1 \
  libnss3 \
  libopengl0 \
  libsasl2-2 \
  # libxkbcommon0 \
  libxcomposite1 \
  libxcursor1 \
  libxfixes3 \
  libxi6 \
  libxkbfile1 \
  libxrandr2 \
  libxrender1 \
  libxslt1.1 \
  libxtst6 \
  nano \
  python3.13 \
  sqlite3 \
  xdg-utils \
  xz-utils \
  zip && \
  rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/* /root/.cache

# ==============================================================================
# STAGE 2: Build base for compilers and headers needed for Python dependencies.
# ==============================================================================
FROM runtime-base AS build-base

ARG DEBIAN_FRONTEND=noninteractive

RUN \
  apt-get update && \
  apt-get install -y --no-install-recommends \
  build-essential \
  libldap2-dev \
  libsasl2-dev \
  python3.13-dev \
  python3.13-venv && \
  python3.13 -m venv /lsiopy && \
  /lsiopy/bin/python -m pip install --upgrade --no-cache-dir pip wheel setuptools && \
  rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/* /root/.cache

# ==============================================================================
# STAGE 3: Python dependencies
# ==============================================================================
FROM build-base AS python-deps

COPY --chown=abc:abc requirements.txt optional-requirements.txt /tmp/

RUN \
  /lsiopy/bin/pip3 install --upgrade --no-cache-dir \
  --find-links https://wheel-index.linuxserver.io/ubuntu/ \
  -r /tmp/requirements.txt -r /tmp/optional-requirements.txt

# ==============================================================================
# STAGE 4: Build lsof
# ==============================================================================
FROM build-base AS lsof-builder

ARG LSOF_VERSION

WORKDIR /tmp

RUN \
  curl -fsSL "https://github.com/lsof-org/lsof/archive/${LSOF_VERSION}.tar.gz" -o lsof.tar.gz && \
  tar -xzf lsof.tar.gz

WORKDIR /tmp/lsof-${LSOF_VERSION}

RUN \
  ./Configure -n linux && \
  make -j"$(getconf _NPROCESSORS_ONLN || printf '1')" && \
  install -m 0755 lsof /usr/local/bin/lsof && \
  rm -rf /tmp/lsof*

# ==============================================================================
# STAGE 5: kepubify
# ==============================================================================
FROM runtime-base AS kepubify

ARG KEPUBIFY_RELEASE
ARG TARGETARCH

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN \
  set -eux; \
  release="${KEPUBIFY_RELEASE}"; \
  if [[ "${release}" == "newest" ]]; then \
  release="$(curl -fsSL https://api.github.com/repos/pgaskin/kepubify/releases/latest | awk -F'"' '/tag_name/ { print $4; exit }')"; \
  fi; \
  case "${TARGETARCH:-}" in \
  amd64) asset="kepubify-linux-64bit" ;; \
  arm64) asset="kepubify-linux-arm64" ;; \
  "") \
  case "$(uname -m)" in \
  x86_64) asset="kepubify-linux-64bit" ;; \
  aarch64) asset="kepubify-linux-arm64" ;; \
  *) printf 'Unsupported architecture: %s\n' "$(uname -m)" >&2; exit 1 ;; \
  esac \
  ;; \
  *) printf 'Unsupported TARGETARCH: %s\n' "${TARGETARCH}}" >&2; exit 1 ;; \
  esac; \
  curl -fsSL "https://github.com/pgaskin/kepubify/releases/download/${release}/${asset}" -o /usr/local/bin/kepubify && \
  chmod 0755 /usr/local/bin/kepubify

# ==============================================================================
# STAGE 6: Install calibre
# ==============================================================================
FROM runtime-base AS calibre

ARG CALIBRE_RELEASE
ARG TARGETARCH

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN \
  set -eux; \
  mkdir -p /app/calibre && \
  case "${TARGETARCH}" in \
  amd64) calibre_arch="x86_64" ;; \
  arm64) calibre_arch="arm64" ;; \
  "") \
  case "$(uname -m)" in \
  x86_64) calibre_arch="x86_64" ;; \
  aarch64) calibre_arch="arm64" ;; \
  *) printf 'Unsupported architecture: %s\n' "$(uname -m)" >&2; exit 1 ;; \
  esac \
  ;; \
  *) printf 'Unsupported TARGETARCH: %s\n' "${TARGETARCH}}" >&2; exit 1 ;; \
  esac; \
  curl -fsSL "https://download.calibre-ebook.com/${CALIBRE_RELEASE}/calibre-${CALIBRE_RELEASE}-${calibre_arch}.txz" -o /tmp/calibre.txz && \
  tar -xf /tmp/calibre.txz -C /app/calibre && \
  rm -f /tmp/calibre.txz

# ==============================================================================
# STAGE 7: unrar
# ==============================================================================
FROM ghcr.io/linuxserver/unrar:latest AS unrar

# ==============================================================================
# STAGE 8: Final image
# ==============================================================================
FROM runtime-base

ARG BUILD_DATE
ARG VERSION
ARG CALIBRE_RELEASE
ARG KEPUBIFY_RELEASE

LABEL build_version="Version:- ${VERSION}" \
  build_date="${BUILD_DATE}" \
  maintainer="CrocodileStick"

# Set the default shell for the following RUN instructions to bash instead of sh
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Copy installed dependencies from the dependencies stage
COPY --from=python-deps /lsiopy /lsiopy
COPY --from=lsof-builder /usr/local/bin/lsof /usr/bin/lsof
COPY --from=kepubify /usr/local/bin/kepubify /usr/bin/kepubify
COPY --from=calibre /app/calibre /app/calibre
COPY --from=unrar /usr/bin/unrar-ubuntu /usr/bin/unrar

# Copy only the application after dependency layers so source changes do not
# invalidate dependency caches
COPY --chown=abc:abc . /app/calibre-web-automated

RUN \
  cp -a /app/calibre-web-automated/root/. / && \
  rm -rf /app/calibre-web-automated/root && \
  chmod +x /app/calibre-web-automated/scripts/setup-cwa.sh && \
  /app/calibre-web-automated/scripts/setup-cwa.sh && \
  if [ -d /app/calibre-web-automated/koreader/plugins/cwasync.koplugin ]; then \
  cd /app/calibre-web-automated/koreader/plugins && \
  PLUGIN_DIGEST="$(find cwasync.koplugin -type f \( -name '*.lua' -o -name '*.json' \) | sort | xargs sha256sum | sha256sum | cut -d' ' -f1)" && \
  { \
  printf 'Plugin files digest: %s\n' "${PLUGIN_DIGEST}"; \
  printf 'Build date: %s\n' "$(date)"; \
  printf 'Files included:\n'; \
  find cwasync.koplugin -type f \( -name '*.lua' -o -name '*.json' \) | sort; \
  } >"cwasync.koplugin/${PLUGIN_DIGEST}.digest" && \
  zip -r koplugin.zip cwasync.koplugin/ && \
  mkdir -p /app/calibre-web-automated/cps/static && \
  mv koplugin.zip /app/calibre-web-automated/cps/static/; \
  else \
  printf 'Warning: cwasync.koplugin folder not found, skipping plugin zip creation\n'; \
  fi && \
  printf '%s\n' "${VERSION}" > /app/CWA_RELEASE && \
  printf '%s\n' "${KEPUBIFY_RELEASE}" > /app/KEPUBIFY_RELEASE && \
  printf '%s\n' "${CALIBRE_RELEASE}" > /CALIBRE_RELEASE

ENV CALIBRE_CONFIG_DIR=/config/.config/calibre

WORKDIR /config

# The default port CWA listens on. Can be overridden with the CWA_PORT_OVERRIDE
# environment variable.
EXPOSE 8083
VOLUME /config
VOLUME /cwa-book-ingest
VOLUME /calibre-library

# Health check for container orchestration
# Uses shell form to support environment variable substitution for CWA_PORT_OVERRIDE
HEALTHCHECK --interval=30s --timeout=3s --start-period=120s --retries=3 \
  CMD curl -f http://localhost:${CWA_PORT_OVERRIDE:-8083}/ || curl -f -k https://localhost:${CWA_PORT_OVERRIDE:-8083}/ || exit 1
