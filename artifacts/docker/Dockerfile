FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md /app/
COPY remora /app/remora
COPY servers /app/servers
COPY schemas /app/schemas
COPY experiments /app/experiments
COPY scripts /app/scripts
COPY tests /app/tests

RUN mkdir -p /app/results /app/datasets

RUN pip install --upgrade pip \
    && pip install -e '.[api,dev,analysis]'

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=5 \
  CMD curl -fsS http://127.0.0.1:8000/v1/health || exit 1

CMD ["uvicorn", "servers.api:app", "--host", "0.0.0.0", "--port", "8000"]
