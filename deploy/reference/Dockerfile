# Author: Stian Skogbrott
# SPDX-License-Identifier: BUSL-1.1
#
# Containerised reference deployment (issue #89): a LOCKED runtime for
# external pilots. The image is built FROM THE WHEEL — the same artifact the
# wheel-contract CI job proves fulfils the CLI/API promise — never from an
# editable checkout, so what a pilot runs is what CI verified.
#
#   docker build -f deploy/reference/Dockerfile -t remora-reference .
#
# Base image pinned by digest (python:3.12-slim, linux multi-arch index,
# resolved 2026-08-26): a rebuilt image differs only if this file changes.
# The container-contract CI job builds this image and runs the contract
# smoke INSIDE it (remora doctor --json + /v1/health) on every push.

FROM python:3.12-slim@sha256:7a8b475003c4fe15a2cd4e55e5cfc2f3560bdc9333d624f24cdd6d4340fd7a17 AS build
WORKDIR /src
COPY . .
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip wheel . --no-deps -w /dist

FROM python:3.12-slim@sha256:7a8b475003c4fe15a2cd4e55e5cfc2f3560bdc9333d624f24cdd6d4340fd7a17
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

COPY --from=build /dist /dist
# [api]  — FastAPI + uvicorn for servers.api / servers.execution_api
# [sdk]  — the stable client surface
# [postgres] — psycopg (gate) + psycopg2 (control plane/audit adapter):
#              the documented durable storage for a locked pilot install.
RUN pip install --no-cache-dir "$(ls /dist/remora-*.whl)[api,sdk,postgres]" \
    && rm -rf /dist

# Non-root runtime: the API needs no filesystem privileges.
RUN useradd --create-home --shell /usr/sbin/nologin remora
USER remora
WORKDIR /home/remora

EXPOSE 8000

# curl is not in slim; the interpreter that runs the app probes it.
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=5 \
  CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/v1/health', timeout=4).status == 200 else 1)"]

CMD ["uvicorn", "servers.api:app", "--host", "0.0.0.0", "--port", "8000"]
