
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8080

WORKDIR /app

# System deps for numpy/torch/etc.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential git curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first (better layer caching)
COPY backend/requirements.txt ./requirements.txt
RUN pip install --upgrade pip && pip install -r requirements.txt
RUN pip install gunicorn

# Copy app code
COPY backend/ ./

EXPOSE 8080

# Adjust "app:app" if your Flask entrypoint differs
# Example: if backend/app.py has `app = Flask(__name__)` → "app:app"
#          if backend/wsgi.py has `application = ...` → "wsgi:application"
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "4", "--timeout", "300", "run:app"]

