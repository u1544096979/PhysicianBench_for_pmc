FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY agent agent
COPY tools tools
COPY utils utils
COPY scripts scripts
COPY pipeline pipeline

RUN pip install --no-cache-dir .

ENTRYPOINT ["python", "scripts/run_task.py"]
