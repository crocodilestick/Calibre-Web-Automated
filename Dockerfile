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
ARG LSCW_RELEASE=0.6.24-ls304
ARG UNIVERSAL_CALIBRE_RELEASE=7.16.0
ARG KEPUBIFY_RELEASE=v4.0.4
LABEL build_version="Version:- ${VERSION}"
LABEL build_date="${BUILD_DATE}" 
LABEL CW-Stock-version="${CALIBREWEB_RELEASE}"
LABEL LSCW_Image_Release="${LSCW_RELEASE}"
LABEL maintainer="CrocodileStick"

# Copy local files into the container
COPY --chown=abc:abc . /app/calibre-web-automated/

# STEP 1 - Install stock Calibre-Web
RUN \
  # STEP 1.1 - Installs required build & runtime packages
  echo "**** install build packages ****" && \
  apt-get update && \
  apt-get install -y --no-install-recommends \
    build-essential \
    libldap2-dev \
    libsasl2-dev \
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
    python3-venv && \
  echo "**** install calibre-web ****" && \
  # STEP 1.2 - Check that $CALIBREWEB_RELEASE ARG is not none and if it is, sets the variables value to the most recent tag name
  if [ -z ${CALIBREWEB_RELEASE+x} ]; then \
    CALIBREWEB_RELEASE=$(curl -sX GET "https://api.github.com/repos/janeczku/calibre-web/releases/latest" \
    | awk '/tag_name/{print $4;exit}' FS='[""]'); \
  fi && \
  # STEP 1.3 - Downloads the tarball of the release stored in $CALIBREWEB_RELEASE from CW's GitHub Repo, saving it into /tmp
  curl -o \
    /tmp/calibre-web.tar.gz -L \
    https://github.com/janeczku/calibre-web/archive/${CALIBREWEB_RELEASE}.tar.gz && \
  # STEP 1.4 - Makes /app/calibre-web to extract the downloaded files from the repo to, -p to ignore potential errors that could arise if the folder already existed
  mkdir -p \
    /app/calibre-web && \
  # STEP 1.5 - Extracts the contents of the tar.gz file downloaded from the repo to the /app/calibre-web dir previously created
  tar xf \
    /tmp/calibre-web.tar.gz -C \
    /app/calibre-web --strip-components=1 && \
  # STEP 1.6 - Sets up a python virtual environment and installs pip and wheel packages
  cd /app/calibre-web && \
  python3 -m venv /lsiopy && \
  pip install -U --no-cache-dir \
    pip \
    wheel && \
  # STEP 1.7 - Installing the required python packages listed in 'requirements.txt' and 'optional-requirements.txt'
    # HOWEVER, they are not pulled from PyPi directly, they are pulled from linuxserver's Ubuntu Wheel Index
    # This is essentially a repository of precompiled some of the most popular packages with C/C++ source code
    # This provides the install maximum compatibility with multiple different architectures including: x86_64, armv71 and aarch64
    # You can read more about python wheels here: https://realpython.com/python-wheels/
  pip install -U --no-cache-dir --find-links https://wheel-index.linuxserver.io/ubuntu/ -r \
    requirements.txt -r \
    optional-requirements.txt && \
  # STEP 1.8 - Installs the latest release of kepubify
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
# STEP 2 - Install Calibre-Web Automated
  echo "~~~~ CWA Install - installing additional required packages ~~~~" && \
  # STEP 2.1 - Install additional required packages
  apt-get update && \
  apt-get install -y --no-install-recommends \
    xdg-utils \
    inotify-tools \
    python3 \
    python3-pip \
    nano \
    sqlite3 && \
  # STEP 2.2 - Install additional required python packages
  pip install -r /app/calibre-web-automated/requirements.txt && \
  # STEP 2.3 - Get required 'root' dir from the linuxserver/docker-calibre-web repo
  echo "~~~~ Getting required files from linuxserver/docker-calibre-web... ~~~~" && \
    # STEP 2.4.1 - Check the most recent release of linuxserver/docker-calibre-web and store it's tag in LSCW_RELEASE if one was not specified as an ARG
  if [[ $LSCW_RELEASE == 'newest' ]]; then \
      LSCW_RELEASE=$(curl -sX GET "https://api.github.com/repos/linuxserver/docker-calibre-web/releases/latest" \
      | awk '/tag_name/{print $4;exit}' FS='[""]'); \
  fi && \
    # STEP 2.4.2 - Download the most recent LSCW release to /tmp
  curl -o \
      /tmp/lscw.tar.gz -L \
      https://github.com/linuxserver/docker-calibre-web/archive/refs/tags/${LSCW_RELEASE}.tar.gz && \
    # STEP 2.4.3 - Makes /app/calibre-web to extract the downloaded files from the repo to, -p to ignore potential errors that could arise if the folder already existed
  mkdir -p \
    /tmp/lscw && \
    # STEP 2.4.4 - Extract contents of lscw.tat.gz to /tmp/lscw
  tar xf \
      /tmp/lscw.tar.gz -C \
      /tmp/lscw --strip-components=1 && \
    # STEP 2.4.5 - Move contents of 'root' dirs to root dir
  cp -R /tmp/lscw/root/* / && \
  cp -R /app/calibre-web-automated/root/* / && \
    # STEP 2.4.6 - Remove the temp files
  rm -R /app/calibre-web-automated/root/ && \
  rm -R /tmp/lscw/root/ && \
  # STEP 2.5 - ADD files referencing the versions of the installed main packages
    # CALIBRE_RELEASE is placed in root by universal calibre below and containers the calibre version being used
  echo "$VERSION" >| /app/CWA_RELEASE && \
  echo "$LSCW_RELEASE" >| /app/LSCW_RELEASE && \
  echo "$KEPUBIFY_RELEASE" >| /app/KEPUBIFY_RELEASE && \
  # STEP 2.6 - Run CWA install script to make required dirs, set script permissions and add aliases for CLI commands  ect.
  chmod +x /app/calibre-web-automated/scripts/setup-cwa.sh && \
  /app/calibre-web-automated/scripts/setup-cwa.sh && \
# STEP 3 - Install Universal Calibre
  # STEP 3.1 - Install additional required packages
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
    xz-utils && \
  # STEP 3.2 - Make the /app/calibre directory for the installed files
  mkdir -p \
  /app/calibre && \
  # STEP 3.3 - Download the desired version of Calibre, determined by the UNIVERSAL_CALIBRE_RELEASE variable and the architecture of the build environment
  if [ "$(uname -m)" == "x86_64" ]; then \
    curl -o \
      /calibre.txz -L \
      "https://download.calibre-ebook.com/${UNIVERSAL_CALIBRE_RELEASE}/calibre-${UNIVERSAL_CALIBRE_RELEASE}-x86_64.txz"; \
  elif [ "$(uname -m)" == "aarch64" ]; then \
    curl -o \
      /calibre.txz -L \
      "https://download.calibre-ebook.com/${UNIVERSAL_CALIBRE_RELEASE}/calibre-${UNIVERSAL_CALIBRE_RELEASE}-arm64.txz"; \
  fi && \
  # STEP 3.4 - Extract the downloaded file to /app/calibre
  tar xf \
      /calibre.txz -C \
      /app/calibre && \
  # STEP 3.5 - Delete the extracted calibre.txz to save space in final image
  rm /calibre.txz && \
  # STEP 3.6 - Store the UNIVERSAL_CALIBRE_RELEASE in the root of the image in CALIBRE_RELEASE
  echo $UNIVERSAL_CALIBRE_RELEASE > /CALIBRE_RELEASE

# Removes packages that are no longer required, also emptying dirs used to build the image that are no longer needed
RUN \
  echo "**** cleanup ****" && \
  apt-get -y purge \
    build-essential \
    libldap2-dev \
    libsasl2-dev \
    python3-dev && \
  apt-get -y autoremove && \
  rm -rf \
    /tmp/* \
    /var/lib/apt/lists/* \
    /var/tmp/* \
    /root/.cache

# add unrar
COPY --from=unrar /usr/bin/unrar-ubuntu /usr/bin/unrar

# ports and volumes
EXPOSE 8083
VOLUME /config
VOLUME /cwa-book-ingest
VOLUME /calibre-library