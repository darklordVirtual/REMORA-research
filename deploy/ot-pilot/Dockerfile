# REMORA OT pilot — production-mode API in a container.
#
# Runs servers.api with REMORA_ENV=production, which means the fail-closed
# prerequisites are real: without durable execution state, a durable envelope
# store, a token table and a non-mock oracle backend the process refuses to
# start. docker-compose.yml supplies all four.
FROM python:3.12-slim

LABEL org.opencontainers.image.title="REMORA OT Pilot API" \
      org.opencontainers.image.description="REMORA governance API in production mode: fail-closed prerequisites (durable execution state, durable envelope store, token table, non-mock oracle backend) are binding at startup." \
      org.opencontainers.image.source="https://github.com/darklordVirtual/REMORA-research" \
      org.opencontainers.image.licenses="BUSL-1.1" \
      org.opencontainers.image.vendor="Stian Skogbrott"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps for psycopg (durable Postgres execution state).
RUN apt-get update \
 && apt-get install -y --no-install-recommends gcc libpq-dev curl \
 && rm -rf /var/lib/apt/lists/*

# pyproject force-includes servers/ and schemas/ in the wheel (REM-045), so
# they must be present before the editable install resolves metadata.
COPY pyproject.toml README.md /app/
COPY remora /app/remora
COPY servers /app/servers
COPY schemas /app/schemas
RUN pip install --upgrade pip \
 && pip install -e ".[api,postgres]"

COPY scripts /app/scripts

# Production mode refuses to start on an empty retrieval evidence store
# (servers/api.py::_make_retrieval_provider). The shipped knowledge pack is
# what /v1/assess retrieves against; the execution path does not use it, but
# the fail-closed check runs at import time regardless.
COPY datasets/remora_knowledge_v1/evidence_packs /app/datasets/remora_knowledge_v1/evidence_packs

# Deployment-owned configuration: the tool registry and the semantic bundle.
# These are the two modules a deployment writes itself; everything else is
# the shipped package.
COPY deploy/ot-pilot/ot_registry.py /app/ot_registry.py
COPY deploy/ot-pilot/ot_bundle.py /app/ot_bundle.py
COPY deploy/ot-pilot/work_orders.json /app/work_orders.json

RUN useradd --create-home --uid 10001 remora \
 && mkdir -p /var/lib/remora/artifacts \
 && chown -R remora:remora /var/lib/remora /app
USER remora

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=5 \
  CMD curl -fsS http://127.0.0.1:8000/v1/health || exit 1

CMD ["uvicorn", "servers.api:app", "--host", "0.0.0.0", "--port", "8000"]
