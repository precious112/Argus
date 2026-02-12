FROM python:3.12-slim
WORKDIR /app

# Install the local Argus Python SDK first
COPY packages/sdk-python/ /tmp/sdk-python/
RUN pip install --no-cache-dir /tmp/sdk-python/ && rm -rf /tmp/sdk-python/

# Install remaining dependencies (skip argus-python since it's already installed)
COPY examples/python-fastapi/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY examples/python-fastapi/app.py .
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
