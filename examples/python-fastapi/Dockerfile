FROM python:3.12-slim
WORKDIR /app

COPY examples/python-fastapi/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY examples/python-fastapi/app.py .
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
