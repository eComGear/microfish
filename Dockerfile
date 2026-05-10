# Cloudflare Containers build for MiroFish backend (Flask + camel-ai/oasis)
# Exposes port 5001 internally; the Worker forwards to it.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    git build-essential curl ca-certificates && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

COPY backend/ ./backend/
WORKDIR /app/backend

ENV PORT=5001 HOST=0.0.0.0
EXPOSE 5001
CMD ["python", "run.py"]
