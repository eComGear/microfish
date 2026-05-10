# Cloudflare Containers build for MiroFish backend (Flask + camel-ai/oasis)
# Exposes port 5001 internally; the Worker forwards to it.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=5001 \
    HOST=0.0.0.0

RUN apt-get update && apt-get install -y --no-install-recommends \
      git build-essential curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt

# Install CPU-only PyTorch FIRST (saves ~2 GB vs default CUDA build)
# then the rest, then aggressively strip caches/tests/__pycache__
RUN pip install --no-cache-dir torch==2.4.0 --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir -r requirements.txt \
 && find /usr/local/lib/python3.11 -type d -name '__pycache__' -prune -exec rm -rf {} + \
 && find /usr/local/lib/python3.11 -type d -name 'tests' -prune -exec rm -rf {} + \
 && find /usr/local/lib/python3.11 -type d -name 'test' -prune -exec rm -rf {} + \
 && rm -rf /root/.cache /tmp/* \
 && apt-get purge -y --auto-remove build-essential git \
 && rm -rf /var/lib/apt/lists/*

COPY backend/ ./backend/
WORKDIR /app/backend

EXPOSE 5001

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD curl -fsS http://127.0.0.1:5001/health || exit 1

CMD ["python", "-u", "run.py"]
