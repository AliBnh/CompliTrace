FROM python:3.10-slim

WORKDIR /app

COPY apps/orchestration-service/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY apps/orchestration-service /app

ENV PYTHONUNBUFFERED=1
EXPOSE 8003

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8003"]
