# Jurix Docker Image
# Multi-stage build for Django application with OCR and NLP dependencies
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    libpq-dev \
    tesseract-ocr \
    tesseract-ocr-por \
    poppler-utils \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=15s \
    CMD curl -fsS http://localhost:8000/api/v1/health/live/ || exit 1

# The chatbot streams answers over SSE, and a generation can take tens of seconds.
# A sync worker is blocked for the whole stream (3 concurrent chats freeze the site),
# so use threaded workers: 3 processes x 8 threads = 24 concurrent streams.
# --timeout is the worker heartbeat (threads keep it alive during a stream), and the
# defaults can be overridden at runtime with the GUNICORN_CMD_ARGS environment variable.
CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--worker-class", "gthread", \
     "--threads", "8", \
     "--timeout", "120", \
     "--graceful-timeout", "30", \
     "--keep-alive", "5"]

