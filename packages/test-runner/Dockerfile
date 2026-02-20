FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends procps && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY packages/test-runner/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY packages/test-runner/runner.py .
CMD ["python", "runner.py"]
