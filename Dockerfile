# Cloudflare Containers build for MiroFish backend (Flask + camel-ai/oasis)
# Exposes port 5001 internally; the Worker forwards to it.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=5001 \
    HOST=0.0.0.0

RUN apt-get update && apt-get install -y --no-install-recommends \
      git build-essential curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first for better layer caching
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source
COPY backend/ ./backend/
WORKDIR /app/backend

EXPOSE 5001

# Optional but useful: container healthcheck
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD curl -fsS http://127.0.0.1:5001/health || exit 1

CMD ["python", "-u", "run.py"]
