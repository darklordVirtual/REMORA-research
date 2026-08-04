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

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /console

RUN pip install --no-cache-dir "fastapi>=0.115" "uvicorn[standard]>=0.30" "httpx>=0.27"

COPY deploy/ot-pilot/console/app.py /console/
# The battery is the same script an operator runs from the shell; the console
# shells out to it rather than reimplementing the cases.
COPY deploy/ot-pilot/run_ot_battery.py /run_ot_battery.py
COPY --from=ui /build/dist-pilot /console/dist

EXPOSE 8090
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8090"]
