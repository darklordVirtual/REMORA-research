# Operator console for the OT pilot. Deliberately a separate, tiny image:
# it never imports remora, so nothing about the demonstration surface can
# change the behaviour of the system being demonstrated.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /console

RUN pip install --no-cache-dir "fastapi>=0.115" "uvicorn[standard]>=0.30" "httpx>=0.27"

COPY deploy/ot-pilot/console/app.py deploy/ot-pilot/console/index.html /console/
# The battery is the same script an operator runs from the shell; the console
# shells out to it rather than reimplementing the cases.
COPY deploy/ot-pilot/run_ot_battery.py /console/../run_ot_battery.py

EXPOSE 8090
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8090"]
