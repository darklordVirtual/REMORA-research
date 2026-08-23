# REMORA OT pilot — production-mode API in a container.
#
# Runs servers.api with REMORA_ENV=production, which means the fail-closed
# prerequisites are real: without durable execution state, a durable envelope
# store, a token table and a non-mock oracle backend the process refuses to
# start. docker-compose.yml supplies all four.
FROM python:3.12-slim

LABEL org.opencontainers.image.title="REMORA OT Pilot API" \
      org.opencontainers.image.description="REMORA governance API in production mode, execution surface only: fail-closed prerequisites (durable execution state, durable envelope store, token table) are binding at startup. No oracle, no retrieval store, no network egress." \
      org.opencontainers.image.source="https://github.com/darklordVirtual/REMORA-research" \
      org.opencontainers.image.licenses="BUSL-1.1" \
      org.opencontainers.image.vendor="Stian Skogbrott"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# No apt layer. The postgres extra pins psycopg[binary] and psycopg2-binary,
# which ship their own libpq, so gcc and libpq-dev are never used; they only
# survived into the runtime image, where they cost 206 MB. The healthcheck
# below uses the interpreter that is already present instead of adding curl.

# pyproject force-includes servers/ and schemas/ in the wheel (REM-045), so
# they must be present before the editable install resolves metadata.
COPY pyproject.toml README.md /app/
COPY remora /app/remora
COPY servers /app/servers
COPY schemas /app/schemas
RUN pip install --upgrade pip \
 && pip install -e ".[api,postgres]"

COPY scripts /app/scripts

# Deployment-owned configuration: the tool registry and the semantic bundle.
# These are the two modules a deployment writes itself; everything else is
# the shipped package.
COPY deploy/ot-pilot/ot_registry.py /app/ot_registry.py
COPY deploy/ot-pilot/ot_bundle.py /app/ot_bundle.py
COPY deploy/ot-pilot/work_orders.json /app/work_orders.json

# The governed GitHub tool set for the MCP gateway. Same principle as the OT
# files above: deployment-owned modules, not shipped package code. Which of
# them a process uses is chosen by REMORA_TOOL_REGISTRY_MODULE and
# REMORA_SEMANTIC_BUNDLE_MODULE, so one image serves both deployments.
COPY deploy/gateway /app/deploy/gateway

RUN useradd --create-home --uid 10001 remora \
 && mkdir -p /var/lib/remora/artifacts \
 && chown -R remora:remora /var/lib/remora /app
USER remora

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/v1/health', timeout=4).status == 200 else 1)"

CMD ["uvicorn", "servers.api:app", "--host", "0.0.0.0", "--port", "8000"]
