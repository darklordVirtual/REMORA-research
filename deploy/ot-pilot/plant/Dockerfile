# The OT pilot's plant (plant_service.py): its own image and trust domain.
#
# Standard library only. The image holds the plant model, the service and
# a dump helper for the assessor, and nothing of REMORA: no package, no keys,
# no tool registry. Its two credentials arrive as environment variables from
# docker-compose.yml (OT_PLANT_WRITE_TOKEN, OT_PLANT_READ_TOKEN).
FROM python:3.12-slim

LABEL org.opencontainers.image.title="REMORA OT Pilot plant" \
      org.opencontainers.image.description="Simulated OT plant with its own write and read credentials and a complete request journal." \
      org.opencontainers.image.licenses="BUSL-1.1"

RUN useradd --create-home --uid 10002 plant
COPY deploy/ot-pilot/plant_model.py deploy/ot-pilot/plant_service.py deploy/ot-pilot/plant_dump.py /plant/
USER plant
EXPOSE 9100
CMD ["python", "/plant/plant_service.py"]
