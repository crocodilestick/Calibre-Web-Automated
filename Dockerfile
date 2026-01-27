# syntax=docker/dockerfile:1

# Simple Example Build Command:
# docker build \
# --tag crocodilestick/calibre-web-automated:dev \
# --build-arg="BUILD_DATE=27-09-2024 12:06" \
# --build-arg="VERSION=2.1.0-test-5" .

# Good guide on how to set up a buildx builder here:
# https://a-berahman.medium.com/simplifying-docker-multiplatform-builds-with-buildx-3d7efd670f58

# Multi-Platform Example Build & Push Command:
# docker buildx build \
# --push \
# --platform linux/amd64,linux/arm64, \
# --build-arg="BUILD_DATE=02-08-2024 20:52" \
# --build-arg="VERSION=2.1.0" \
# --tag crocodilestick/calibre-web-automated:latest .

# ============================================================================
# STAGE 1: Dependencies - Install system packages and Python dependencies
# ============================================================================
FROM ghcr.io/linuxserver/baseimage-ubuntu:noble AS dependencies

ARG CALIBRE_RELEASE=8.9.0
ARG KEPUBIFY_RELEASE=v4.0.4

# Set the default shell for the following RUN instructions to bash instead of sh
SHELL ["/bin/bash", "-c"]

# STEP 1 - Install Required Packages
RUN \
  # STEP 1.1 - Add deadsnakes PPA for Python 3.13 and install required apt packages
  echo "**** add deadsnakes PPA for Python 3.13 ****" && \
  apt-get update && \
  apt-get install -y --no-install-recommends software-properties-common && \
  add-apt-repository ppa:deadsnakes/ppa && \
  apt-get update && \
  echo "**** install build packages ****" && \
  apt-get install -y --no-install-recommends \
  build-essential \
  libldap2-dev \
  libsasl2-dev \
  gettext \
  python3.13-dev \
  python3.13-venv \
  curl && \
  echo "**** install runtime packages ****" && \
  apt-get install -y --no-install-recommends \
  imagemagick \
  ghostscript \
  libldap2 \
  libmagic1 \
  libsasl2-2 \
  libxi6 \
  libxslt1.1 \
  xdg-utils \
  inotify-tools \
  python3.13 \
  nano \
  sqlite3 \
  zip && \
  # STEP 1.2 - Install additional Calibre required packages
  apt-get install -y --no-install-recommends \
  libxtst6 \
  libxrandr2 \
  libxkbfile1 \
  libxcomposite1 \
  libxcursor1 \
  libxfixes3 \
  libxrender1 \
  libopengl0 \
  libnss3 \
  libxkbcommon0 \
  libegl1 \
  libxdamage1 \
  libgl1 \
  libglx-mesa0 \
  xz-utils \
  binutils && \
  # Install lsof 4.99.5 from source to fix hanging issue with 4.95 (issue #654)
  echo "**** install lsof 4.99.5 from source ****" && \
  LSOF_VERSION="4.99.5" && \
  curl -L "https://github.com/lsof-org/lsof/archive/${LSOF_VERSION}.tar.gz" -o /tmp/lsof.tar.gz && \
  cd /tmp && \
  tar -xzf lsof.tar.gz && \
  cd "lsof-${LSOF_VERSION}" && \
  ./Configure -n linux && \
  make && \
  cp lsof /usr/bin/lsof && \
  chmod 755 /usr/bin/lsof && \
  cd / && \
  rm -rf /tmp/lsof* && \
  # Create python3 symlink to point to python3.13
  ln -sf /usr/bin/python3.13 /usr/bin/python3 && \
  # Install pip for Python 3.13
  curl -sS https://bootstrap.pypa.io/get-pip.py | python3.13

# STEP 2 - Set up Python virtual environment
RUN \
  python3.13 -m venv /lsiopy && \
  /lsiopy/bin/pip install -U --no-cache-dir \
  pip \
  wheel

# STEP 3 - Copy requirements files and install Python packages
# Copy only requirements files first to leverage Docker layer caching
COPY --chown=abc:abc requirements.txt optional-requirements.txt /app/calibre-web-automated/

RUN \
  # STEP 3.1 - Installing the required python packages listed in 'requirements.txt' and 'optional-requirements.txt'
  # HOWEVER, they are not pulled from PyPi directly, they are pulled from linuxserver's Ubuntu Wheel Index
  # This is essentially a repository of precompiled some of the most popular packages with C/C++ source code
  # This provides the install maximum compatibility with multiple different architectures including: x86_64, armv71 and aarch64
  # You can read more about python wheels here: https://realpython.com/python-wheels/
  /lsiopy/bin/pip install -U --no-cache-dir --find-links https://wheel-index.linuxserver.io/ubuntu/ -r \
  /app/calibre-web-automated/requirements.txt -r /app/calibre-web-automated/optional-requirements.txt

# STEP 4 - Install kepubify
RUN \
  echo "**** install kepubify ****" && \
  if [[ $KEPUBIFY_RELEASE == 'newest' ]]; then \
  KEPUBIFY_RELEASE=$(curl -sX GET "https://api.github.com/repos/pgaskin/kepubify/releases/latest" \
  | awk '/tag_name/{print $4;exit}' FS='[""]'); \
  fi && \
  if [ "$(uname -m)" == "x86_64" ]; then \
  curl -o \
  /usr/bin/kepubify -L \
  https://github.com/pgaskin/kepubify/releases/download/${KEPUBIFY_RELEASE}/kepubify-linux-64bit; \
  elif [ "$(uname -m)" == "aarch64" ]; then \
  curl -o \
  /usr/bin/kepubify -L \
  https://github.com/pgaskin/kepubify/releases/download/${KEPUBIFY_RELEASE}/kepubify-linux-arm64; \
  fi && \
  chmod +x /usr/bin/kepubify

# STEP 5 - Install Calibre
RUN \
  # STEP 5.1 - Make the /app/calibre directory for the installed files
  mkdir -p /app/calibre && \
  # STEP 5.2 - Download the desired version of Calibre, determined by the CALIBRE_RELEASE variable and the architecture of the build environment
  if [ "$(uname -m)" == "x86_64" ]; then \
  curl -o \
  /calibre.txz -L \
  "https://download.calibre-ebook.com/${CALIBRE_RELEASE}/calibre-${CALIBRE_RELEASE}-x86_64.txz"; \
  elif [ "$(uname -m)" == "aarch64" ]; then \
  curl -o \
  /calibre.txz -L \
  "https://download.calibre-ebook.com/${CALIBRE_RELEASE}/calibre-${CALIBRE_RELEASE}-arm64.txz"; \
  fi && \
  # STEP 5.3 - Extract the downloaded file to /app/calibre
  tar xf \
  /calibre.txz -C \
  /app/calibre && \
  # STEP 5.3.1 - Remove the ABI tag from the extracted libQt6* files to allow them to be used on older kernels
  # Removed in V3.1.4 because it was breaking Calibre features that require Qt6. Replaced with a kernel check in the cwa-init service
  # STEP 5.4 - Delete the extracted calibre.txz to save space in final image
  rm /calibre.txz

# ============================================================================
# STAGE 2: Final - Build the final runtime image
# ============================================================================
FROM ghcr.io/linuxserver/baseimage-ubuntu:noble AS unrar-stage
FROM ghcr.io/linuxserver/unrar:latest AS unrar

FROM ghcr.io/linuxserver/baseimage-ubuntu:noble

ARG BUILD_DATE
ARG VERSION
ARG CALIBREWEB_RELEASE=0.6.24
ARG CALIBRE_RELEASE=8.9.0
ARG KEPUBIFY_RELEASE=v4.0.4

LABEL build_version="Version:- ${VERSION}"
LABEL build_date="${BUILD_DATE}"
LABEL CW-base-version="${CALIBREWEB_RELEASE}"
LABEL maintainer="CrocodileStick"

# Set the default shell for the following RUN instructions to bash instead of sh
SHELL ["/bin/bash", "-c"]

# Copy installed dependencies from the dependencies stage
COPY --from=dependencies /lsiopy /lsiopy
COPY --from=dependencies /usr/bin/kepubify /usr/bin/kepubify
COPY --from=dependencies /app/calibre /app/calibre
COPY --from=dependencies /usr/bin/lsof /usr/bin/lsof
COPY --from=dependencies /usr/bin/python3.13 /usr/bin/python3.13
COPY --from=dependencies /usr/lib/python3.13 /usr/lib/python3.13

# Install only runtime packages (no build tools)
RUN \
  echo "**** add deadsnakes PPA for Python 3.13 runtime ****" && \
  apt-get update && \
  apt-get install -y --no-install-recommends software-properties-common && \
  add-apt-repository ppa:deadsnakes/ppa && \
  apt-get update && \
  echo "**** install runtime packages ****" && \
  apt-get install -y --no-install-recommends \
  imagemagick \
  ghostscript \
  libldap2 \
  libmagic1 \
  libsasl2-2 \
  libxi6 \
  libxslt1.1 \
  xdg-utils \
  inotify-tools \
  python3.13 \
  nano \
  sqlite3 \
  zip \
  gettext \
  libasound2t64 \
  libxtst6 \
  libxrandr2 \
  libxkbfile1 \
  libxcomposite1 \
  libxcursor1 \
  libxfixes3 \
  libxrender1 \
  libopengl0 \
  libnss3 \
  libxkbcommon0 \
  libegl1 \
  libxdamage1 \
  libgl1 \
  libglx-mesa0 \
  xz-utils \
  curl && \
  # Create python3 symlink to point to python3.13
  ln -sf /usr/bin/python3.13 /usr/bin/python3 && \
  # Cleanup
  apt-get -y purge software-properties-common && \
  apt-get -y autoremove && \
  rm -rf \
  /tmp/* \
  /var/lib/apt/lists/* \
  /var/tmp/* \
  /root/.cache

# STEP 6 - Copy application files
# Copy the rest of the application code (changes most frequently)
COPY --chown=abc:abc . /app/calibre-web-automated/

# STEP 7 - Configure application
RUN \
  # STEP 7.1 - Move contents of /app/calibre-web-automated/root to / and delete the /app/calibre-web-automated/root directory
  cp -R /app/calibre-web-automated/root/* / && \
  rm -R /app/calibre-web-automated/root/ && \
  # STEP 7.2 - Run CWA install script to make required dirs, set script permissions and add aliases for CLI commands  ect.
  chmod +x /app/calibre-web-automated/scripts/setup-cwa.sh && \
  /app/calibre-web-automated/scripts/setup-cwa.sh && \
  # STEP 7.3 - Create koplugin.zip from KOReader plugin folder
  echo "~~~~ Creating koplugin.zip from KOReader plugin folder... ~~~~" && \
  if [ -d "/app/calibre-web-automated/koreader/plugins/cwasync.koplugin" ]; then \
  cd /app/calibre-web-automated/koreader/plugins && \
  # Calculate digest of all files in the plugin for debugging purposes
  echo "Calculating digest of plugin files..." && \
  PLUGIN_DIGEST=$(find cwasync.koplugin -type f -name "*.lua" -o -name "*.json" | sort | xargs sha256sum | sha256sum | cut -d' ' -f1) && \
  echo "Plugin digest: $PLUGIN_DIGEST" && \
  # Create a file named after the digest inside the plugin folder
  echo "Plugin files digest: $PLUGIN_DIGEST" > cwasync.koplugin/${PLUGIN_DIGEST}.digest && \
  echo "Build date: $(date)" >> cwasync.koplugin/${PLUGIN_DIGEST}.digest && \
  echo "Files included:" >> cwasync.koplugin/${PLUGIN_DIGEST}.digest && \
  find cwasync.koplugin -type f -name "*.lua" -o -name "*.json" | sort >> cwasync.koplugin/${PLUGIN_DIGEST}.digest && \
  zip -r koplugin.zip cwasync.koplugin/ && \
  echo "Created koplugin.zip from cwasync.koplugin folder with digest file: ${PLUGIN_DIGEST}.digest"; \
  else \
  echo "Warning: cwasync.koplugin folder not found, skipping zip creation"; \
  fi && \
  # STEP 7.4 - Move koplugin.zip to static directory
  if [ -f "/app/calibre-web-automated/koreader/plugins/koplugin.zip" ]; then \
  mkdir -p /app/calibre-web-automated/cps/static && \
  cp /app/calibre-web-automated/koreader/plugins/koplugin.zip /app/calibre-web-automated/cps/static/ && \
  echo "Moved koplugin.zip to static directory"; \
  else \
  echo "Warning: koplugin.zip not found, skipping move to static directory"; \
  fi && \
  # STEP 7.5 - ADD files referencing the versions of the installed main packages
  echo "$VERSION" >| /app/CWA_RELEASE && \
  echo "$KEPUBIFY_RELEASE" >| /app/KEPUBIFY_RELEASE && \
  echo "$CALIBRE_RELEASE" > /CALIBRE_RELEASE

# Add unrar from unrar stage
COPY --from=unrar /usr/bin/unrar-ubuntu /usr/bin/unrar

# Set calibre environment variables
ENV CALIBRE_CONFIG_DIR=/config/.config/calibre

# Ports and volumes
WORKDIR /config
# The default port CWA listens on. Can be overridden with the CWA_PORT_OVERRIDE environment variable.
EXPOSE 8083
VOLUME /config
VOLUME /cwa-book-ingest
VOLUME /calibre-library

# Health check for container orchestration
# Uses shell form to support environment variable substitution for CWA_PORT_OVERRIDE
HEALTHCHECK --interval=30s --timeout=3s --start-period=120s --retries=3 \
  CMD curl -f http://localhost:${CWA_PORT_OVERRIDE:-8083}/ || curl -f -k https://localhost:${CWA_PORT_OVERRIDE:-8083}/ || exit 1
