# Operator console for the OT pilot. Deliberately a separate, tiny image:
# it never imports remora, so nothing about the demonstration surface can
# change the behaviour of the system being demonstrated.
#
# Stage 1 builds the console UI from frontend/src/pilot with the same Vite
# setup, design tokens and component library as the main frontend — the pilot
# is not a hand-rolled page, it is the frontend's design system pointed at the
# pilot's console API.
FROM node:24-slim AS ui
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npx vite build --config vite.pilot.config.ts

FROM python:3.12-slim

LABEL org.opencontainers.image.title="REMORA OT Pilot Console" \
      org.opencontainers.image.description="Operator console for the REMORA OT pilot: live governance metrics, scenario calls, OT battery runs and immutable evidence archive. Demonstration surface only — holds no policy and makes no decisions." \
      org.opencontainers.image.source="https://github.com/darklordVirtual/REMORA-research" \
      org.opencontainers.image.licenses="BUSL-1.1" \
      org.opencontainers.image.vendor="Stian Skogbrott"

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /console

RUN pip install --no-cache-dir "fastapi>=0.115" "uvicorn[standard]>=0.30" "httpx>=0.27"

COPY deploy/ot-pilot/console/app.py /console/
# The battery is the same script an operator runs from the shell; the console
# shells out to it rather than reimplementing the cases.
COPY deploy/ot-pilot/run_ot_battery.py /run_ot_battery.py
COPY --from=ui /build/dist-pilot /console/dist

# Non-root, same uid convention as the API image. The evidence directory is
# created here so a fresh named volume inherits this ownership; a volume
# populated by an older root-running console must be recreated (down -v).
RUN useradd --create-home --uid 10001 console \
 && mkdir -p /var/lib/remora/evidence /console/artifacts \
 && chown -R console:console /var/lib/remora /console
USER console

EXPOSE 8090

# The check stays local on purpose: it proves the console process serves its
# UI, not that the governed API behind it is up — that is the API's own check.
HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/', timeout=4)" || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8090"]
