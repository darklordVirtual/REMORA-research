FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md /app/
COPY remora /app/remora
COPY experiments /app/experiments
COPY scripts /app/scripts
COPY results /app/results
COPY tests /app/tests

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -e .[dev,analysis]

CMD ["bash"]
