# =============================================================================
# STAGE 1: Dependencies - Install system packages and Python dependencies
# =============================================================================
ARG CALIBRE_RELEASE=9.1.0
ARG KEPUBIFY_RELEASE=v4.0.4

FROM debian:trixie-slim AS dependencies

ARG CALIBRE_RELEASE
ARG KEPUBIFY_RELEASE

# Use bash for RUN instructions
SHELL ["/bin/bash", "-c"]

# Install build-only packages (runtime packages go in the final stage)
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates \
      build-essential \
      libldap2-dev \
      libsasl2-dev \
      python3 \
      python3-venv \
      python3-dev \
      curl \
      xz-utils \
 && update-ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# Python virtual environment
RUN python3 -m venv /venv \
 && /venv/bin/pip install -U --no-cache-dir pip wheel

# Install python dependencies
WORKDIR /app/calibre-web-automated
COPY requirements.txt optional-requirements.txt ./
RUN /venv/bin/pip install -U --no-cache-dir -r requirements.txt -r optional-requirements.txt

# Install kepubify
RUN echo "**** install kepubify ****" \
 && if [[ $KEPUBIFY_RELEASE == 'newest' ]]; then \
      KEPUBIFY_RELEASE=$(curl -sX GET "https://api.github.com/repos/pgaskin/kepubify/releases/latest" | awk '/tag_name/{print $4;exit}' FS='["\"]'); \
    fi \
 && if [ "$(uname -m)" == "x86_64" ]; then \
      curl -o /usr/bin/kepubify -L "https://github.com/pgaskin/kepubify/releases/download/${KEPUBIFY_RELEASE}/kepubify-linux-64bit"; \
    elif [ "$(uname -m)" == "aarch64" ]; then \
      curl -o /usr/bin/kepubify -L "https://github.com/pgaskin/kepubify/releases/download/${KEPUBIFY_RELEASE}/kepubify-linux-arm64"; \
    fi \
 && chmod +x /usr/bin/kepubify

# Install Calibre
RUN mkdir -p /app/calibre \
 && if [ "$(uname -m)" == "x86_64" ]; then \
      curl -o /calibre.txz -L "https://download.calibre-ebook.com/${CALIBRE_RELEASE}/calibre-${CALIBRE_RELEASE}-x86_64.txz"; \
    elif [ "$(uname -m)" == "aarch64" ]; then \
      curl -o /calibre.txz -L "https://download.calibre-ebook.com/${CALIBRE_RELEASE}/calibre-${CALIBRE_RELEASE}-arm64.txz"; \
    fi \
 && tar xf /calibre.txz -C /app/calibre \
 && rm /calibre.txz

# =============================================================================
# STAGE 2: Final - Runtime image
# =============================================================================
FROM debian:trixie-slim

ARG BUILD_DATE
ARG VERSION
ARG CALIBRE_RELEASE
ARG KEPUBIFY_RELEASE

LABEL build_version="Version:- ${VERSION}"
LABEL build_date="${BUILD_DATE}"
LABEL maintainer="CrocodileStick"

SHELL ["/bin/bash", "-c"]

# Create runtime user
RUN groupadd -g 1000 calibre \
 && useradd -u 1000 -g 1000 -m -s /bin/bash calibre

# Copy built artifacts
COPY --from=dependencies /venv /venv
COPY --from=dependencies /usr/bin/kepubify /usr/bin/kepubify
COPY --chown=calibre:calibre --from=dependencies /app/calibre /app/calibre

# Prepend venv to PATH so 'python'/'python3' resolve to the venv binaries
ENV PATH=/venv/bin:$PATH

# Runtime packages (single layer: certs + app deps + Calibre GUI deps)
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates \
      imagemagick \
      ghostscript \
      libldap2 \
      libmagic1 \
      libsasl2-2 \
      python3 \
      libxi6 \
      libxslt1.1 \
      xdg-utils \
      inotify-tools \
      nano \
      sqlite3 \
      zip \
      gettext \
      libasound2 \
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
      lsof \
      unar \
      xz-utils \
      curl \
 && update-ca-certificates \
 && rm -rf /var/lib/apt/lists/*

# App code
WORKDIR /app/calibre-web-automated
COPY --chown=calibre:calibre . ./

# Configure application (build-time)
RUN   chmod +x /app/calibre-web-automated/scripts/setup-cwa.sh && \
 chmod +x /app/calibre-web-automated/scripts/services/*.sh && \
 /app/calibre/calibre_postinstall && \
 /app/calibre-web-automated/scripts/setup-cwa.sh && \
 echo "~~~~ Creating koplugin.zip from KOReader plugin folder... ~~~~" \
 && if [ -d "/app/calibre-web-automated/koreader/plugins/cwasync.koplugin" ]; then \
      cd /app/calibre-web-automated/koreader/plugins; \
      echo "Calculating digest of plugin files..."; \
      PLUGIN_DIGEST=$(find cwasync.koplugin -type f -name "*.lua" -o -name "*.json" | sort | xargs sha256sum | sha256sum | cut -d' ' -f1); \
      echo "Plugin digest: $PLUGIN_DIGEST"; \
      echo "Plugin files digest: $PLUGIN_DIGEST" > cwasync.koplugin/${PLUGIN_DIGEST}.digest; \
      echo "Build date: $(date)" >> cwasync.koplugin/${PLUGIN_DIGEST}.digest; \
      echo "Files included:" >> cwasync.koplugin/${PLUGIN_DIGEST}.digest; \
      find cwasync.koplugin -type f -name "*.lua" -o -name "*.json" | sort >> cwasync.koplugin/${PLUGIN_DIGEST}.digest; \
      zip -r koplugin.zip cwasync.koplugin/; \
      echo "Created koplugin.zip from cwasync.koplugin folder with digest file: ${PLUGIN_DIGEST}.digest"; \
    else \
      echo "Warning: cwasync.koplugin folder not found, skipping zip creation"; \
    fi \
 && if [ -f "/app/calibre-web-automated/koreader/plugins/koplugin.zip" ]; then \
      mkdir -p /app/calibre-web-automated/cps/static; \
      cp /app/calibre-web-automated/koreader/plugins/koplugin.zip /app/calibre-web-automated/cps/static/; \
      echo "Moved koplugin.zip to static directory"; \
    else \
      echo "Warning: koplugin.zip not found, skipping move to static directory"; \
    fi \
 && echo "$VERSION" >| /app/CWA_RELEASE \
 && echo "$KEPUBIFY_RELEASE" >| /app/KEPUBIFY_RELEASE \
 && echo "$CALIBRE_RELEASE" > /CALIBRE_RELEASE

ENV CALIBRE_DBPATH=/config \
    CALIBRE_CONFIG_DIR=/config/.config/calibre
    
WORKDIR /config

EXPOSE 8083
VOLUME /config
VOLUME /cwa-book-ingest
VOLUME /calibre-library

USER calibre

CMD ["python", "/app/calibre-web-automated/cps.py"]

HEALTHCHECK --interval=30s --timeout=3s --start-period=120s --retries=3 \
  CMD curl -f http://localhost:${CWA_PORT_OVERRIDE:-8083}/ || curl -f -k https://localhost:${CWA_PORT_OVERRIDE:-8083}/ || exit 1
