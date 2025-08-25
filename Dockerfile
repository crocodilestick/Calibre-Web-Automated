# syntax=docker/dockerfile:1

FROM ghcr.io/linuxserver/unrar:latest AS unrar
FROM ghcr.io/linuxserver/baseimage-ubuntu:jammy

# Set the default shell for the following RUN instructions to bash instead of sh
SHELL ["/bin/bash", "-c"]

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

ARG BUILD_DATE
ARG VERSION
ARG CALIBREWEB_RELEASE=0.6.24
ARG CALIBRE_RELEASE=8.9.0
ARG KEPUBIFY_RELEASE=v4.0.4
LABEL build_version="Version:- ${VERSION}"
LABEL build_date="${BUILD_DATE}"
LABEL CW-base-version="${CALIBREWEB_RELEASE}"
LABEL maintainer="CrocodileStick"

# Copy local files into the container
COPY --chown=abc:abc . /app/calibre-web-automated/
# STEP 1 - Install Required Packages
RUN \
  # STEP 1.1 - Install required apt packages
  echo "**** install build packages ****" && \
  apt-get update && \
  apt-get install -y --no-install-recommends \
    build-essential \
    libldap2-dev \
    libsasl2-dev \
    gettext \
    python3-dev && \
  echo "**** install runtime packages ****" && \
  apt-get install -y --no-install-recommends \
    imagemagick \
    ghostscript \
    libldap-2.5-0 \
    libmagic1 \
    libsasl2-2 \
    libxi6 \
    libxslt1.1 \
    xdg-utils \
    inotify-tools \
    python3 \
    python3-pip \
    nano \
    sqlite3 \
    zip \
    lsof \
    python3-venv && \
  # STEP 1.2 - Set up a python virtual environment and install pip and wheel packages
  cd /app/calibre-web-automated && \
  python3 -m venv /lsiopy && \
  pip install -U --no-cache-dir \
    pip \
    wheel && \
  # STEP 1.3 - Installing the required python packages listed in 'requirements.txt' and 'optional-requirements.txt'
    # HOWEVER, they are not pulled from PyPi directly, they are pulled from linuxserver's Ubuntu Wheel Index
    # This is essentially a repository of precompiled some of the most popular packages with C/C++ source code
    # This provides the install maximum compatibility with multiple different architectures including: x86_64, armv71 and aarch64
    # You can read more about python wheels here: https://realpython.com/python-wheels/
  pip install -U --no-cache-dir --find-links https://wheel-index.linuxserver.io/ubuntu/ -r \
    requirements.txt -r optional-requirements.txt && \
# STEP 2 - Move contents of /app/calibre-web-automated/root to / and delete the /app/calibre-web-automated/root directory
  cp -R /app/calibre-web-automated/root/* / && \
  rm -R /app/calibre-web-automated/root/ && \
# STEP 3 - Run CWA install script to make required dirs, set script permissions and add aliases for CLI commands  ect.
  chmod +x /app/calibre-web-automated/scripts/setup-cwa.sh && \
  /app/calibre-web-automated/scripts/setup-cwa.sh && \
# STEP 4 - Create koplugin.zip from KOReader plugin folder
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
  # STEP 4.1 - Move koplugin.zip to static directory
  if [ -f "/app/calibre-web-automated/koreader/plugins/koplugin.zip" ]; then \
    mkdir -p /app/calibre-web-automated/cps/static && \
    cp /app/calibre-web-automated/koreader/plugins/koplugin.zip /app/calibre-web-automated/cps/static/ && \
    echo "Moved koplugin.zip to static directory"; \
  else \
    echo "Warning: koplugin.zip not found, skipping move to static directory"; \
  fi && \
# STEP 5 - Installs kepubify
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
# STEP 6 - Install Calibre
  # STEP 6.1 - Install additional required packages
  apt-get update && \
  apt-get install -y --no-install-recommends \
    libxtst6 \
    libxrandr2 \
    libxkbfile1 \
    libxcomposite1 \
    libopengl0 \
    libnss3 \
    libxkbcommon0 \
    libegl1 \
    libxdamage1 \
    libgl1 \
    libglx-mesa0 \
    xz-utils \
    binutils && \
  # STEP 6.2 - Make the /app/calibre directory for the installed files
  mkdir -p \
  /app/calibre && \
  # STEP 6.3 - Download the desired version of Calibre, determined by the CALIBRE_RELEASE variable and the architecture of the build environment
  if [ "$(uname -m)" == "x86_64" ]; then \
    curl -o \
      /calibre.txz -L \
      "https://download.calibre-ebook.com/${CALIBRE_RELEASE}/calibre-${CALIBRE_RELEASE}-x86_64.txz"; \
  elif [ "$(uname -m)" == "aarch64" ]; then \
    curl -o \
      /calibre.txz -L \
      "https://download.calibre-ebook.com/${CALIBRE_RELEASE}/calibre-${CALIBRE_RELEASE}-arm64.txz"; \
  fi && \
  # STEP 6.4 - Extract the downloaded file to /app/calibre
  tar xf \
      /calibre.txz -C \
      /app/calibre && \
  # STEP 6.4.1 - Remove the ABI tag from the extracted libQt6* files to allow them to be used on older kernels
    # Removed in V3.1.4 because it was breaking Calibre features that require Qt6. Replaced with a kernel check in the cwa-init service
  # STEP 6.5 - Delete the extracted calibre.txz to save space in final image
  rm /calibre.txz && \
# STEP 7 - ADD files referencing the versions of the installed main packages
  echo "$VERSION" >| /app/CWA_RELEASE && \
  echo "$KEPUBIFY_RELEASE" >| /app/KEPUBIFY_RELEASE && \
  echo "$CALIBRE_RELEASE" > /CALIBRE_RELEASE

# Removes packages that are no longer required, also emptying dirs used to build the image that are no longer needed
RUN \
  echo "**** cleanup ****" && \
  apt-get -y purge \
    build-essential \
    libldap2-dev \
    libsasl2-dev \
    gettext \
    python3-dev && \
  apt-get -y autoremove && \
  rm -rf \
    /tmp/* \
    /var/lib/apt/lists/* \
    /var/tmp/* \
    /root/.cache

# add unrar
COPY --from=unrar /usr/bin/unrar-ubuntu /usr/bin/unrar

# set calibre environment variable
ENV CALIBRE_CONFIG_DIR=/config/.config/calibre

# ports and volumes
WORKDIR /config
# The default port CWA listens on. Can be overridden with the CWA_PORT_OVERRIDE environment variable.
EXPOSE 8083
VOLUME /config
VOLUME /cwa-book-ingest
VOLUME /calibre-library
