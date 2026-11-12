# syntax=docker/dockerfile:1
# The browser revision must match package-lock.json. This official image already
# contains Chromium and its system libraries; apt runs only while building it.
FROM mcr.microsoft.com/playwright:v1.56.1-noble@sha256:f1e7e01021efd65dd1a2c56064be399f3e4de00fd021ac561325f2bfbb2b837a

LABEL org.opencontainers.image.source="https://github.com/the-omega-institute/trureturing-books-template" \
      org.opencontainers.image.description="Complete build toolchain for trureturing books" \
      org.opencontainers.image.licenses="Apache-2.0"

ENV DEBIAN_FRONTEND=noninteractive \
    PATH="/opt/tbook/venv/bin:${PATH}" \
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 \
    PYTHONUNBUFFERED=1 \
    FILM_CACHE=/opt/tbook/film \
    TBOOK_TOOLCHAIN=/opt/tbook

ENV TECTONIC_CACHE_DIR=/opt/tbook/tectonic-cache

RUN apt-get -o Acquire::Retries=3 update \
    && apt-get -o Acquire::Retries=3 install -y --no-install-recommends \
       python3 python3-venv default-jre-headless ffmpeg fontconfig libsndfile1 \
       espeak-ng gh sudo \
       fonts-noto-cjk fonts-noto-core fonts-jetbrains-mono fonts-dejavu-core \
       fonts-noto-color-emoji fonts-unifont xfonts-cyrillic xfonts-scalable \
       fonts-liberation fonts-ipafont-gothic fonts-wqy-zenhei fonts-tlwg-loma-otf fonts-freefont-ttf \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m venv /opt/tbook/venv

WORKDIR /opt/tbook
COPY requirements.txt package.json package-lock.json ./
COPY theme/film/requirements.txt theme/film/setup.sh ./theme/film/
RUN python -m pip install --no-cache-dir -r requirements.txt -r theme/film/requirements.txt \
    && npm ci --no-audit --no-fund \
    && npm cache clean --force \
    && PYTHON=/opt/tbook/venv/bin/python bash theme/film/setup.sh

# Verified release binaries: no Rust compiler is needed in the final image.
ARG TARGETARCH
COPY tools/install-tectonic.sh ./tools/
RUN bash tools/install-tectonic.sh /usr/local/bin
# Warm the versioned bundle for the academic source contract; runtime smoke uses --only-cached.
RUN printf '%s\n' '\documentclass{beamer}\usepackage{amssymb,xurl,appendixnumberbeamer}\begin{document}\begin{frame}{Toolchain}Academic slides\note{Speaker notes}\end{frame}\end{document}' > beamer-smoke.tex \
    && SOURCE_DATE_EPOCH=946684800 tectonic -X compile --bundle https://relay.fullyjustified.net/default_bundle_v33.tar beamer-smoke.tex \
    && rm beamer-smoke.tex beamer-smoke.pdf
RUN case "$TARGETARCH" in \
      amd64) archive=x86_64-unknown-linux-musl; sum=5222beabd3e37dc5be0d18ff99b79058469354db5c220153a1b92db5ba12be89 ;; \
      arm64) archive=aarch64-unknown-linux-musl; sum=753e5c5c363ee8a56972344dcf91466f005a51db84a7aeffe427ae3ef83d6d44 ;; \
      *) echo "Unsupported architecture: $TARGETARCH" >&2; exit 1 ;; \
    esac \
    && curl -fsSL --retry 3 "https://github.com/rust-lang/mdBook/releases/download/v0.5.4/mdbook-v0.5.4-${archive}.tar.gz" -o /tmp/mdbook.tar.gz \
    && echo "$sum  /tmp/mdbook.tar.gz" | sha256sum --check \
    && tar -xzf /tmp/mdbook.tar.gz -C /usr/local/bin mdbook \
    && rm /tmp/mdbook.tar.gz

COPY tools/fetch-fonts.sh ./tools/
COPY theme/typst/fonts.sha256 ./theme/typst/
RUN bash tools/fetch-fonts.sh \
    && mkdir -p /usr/local/share/fonts/tbook \
    && cp .cache/fonts/*tf /usr/local/share/fonts/tbook/ \
    && fc-cache -f

COPY tools/container/ ./container/
RUN python container/prepare.py --record \
    && python container/smoke.py

WORKDIR /work
CMD ["bash"]
