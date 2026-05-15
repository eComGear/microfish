FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
  && apt-get install -y --no-install-recommends build-essential curl \
  && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt \
 && pip install --no-cache-dir gunicorn

COPY backend ./backend

WORKDIR /app/backend

ENV HOST=0.0.0.0 \
    PORT=8080 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8080

# Production WSGI server. 2 workers x 8 threads, 5-min timeout for long sims.
CMD ["gunicorn", "-w", "2", "-k", "gthread", "--threads", "8", \
     "-t", "300", "--graceful-timeout", "120", \
     "-b", "0.0.0.0:8080", "run:app"]
