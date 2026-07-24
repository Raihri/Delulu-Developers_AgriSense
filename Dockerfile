# All-in-one AgriSense image: runs BOTH the FastAPI backend and the Next.js
# frontend in a single container. Python is pinned to 3.12 (the repo needs
# 3.11+), and Node 20 is installed for the frontend.
#
#   docker build -t agrisense .
#   docker run --rm -p 3000:3000 -p 8000:8000 --env-file backend/.env agrisense
#
# Then open http://localhost:3000 (frontend) — it proxies to the backend at
# http://localhost:8000 inside the same container.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    NODE_ENV=development

# Node 20 (for Next.js) + bash (start.sh uses `wait -n`).
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates bash \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && apt-get purge -y curl \
    && apt-get autoremove -y \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Backend deps first (layer caching). Keeps repo path resolution intact:
# BACKEND_ROOT=/app/backend, REPOSITORY_ROOT=/app, DATASET_ROOT=/app/dataset.
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

# Frontend deps next.
COPY frontend/package.json frontend/package-lock.json frontend/
RUN cd frontend && npm ci

# Application source.
COPY backend/ backend/
COPY frontend/ frontend/
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

EXPOSE 3000 8000

CMD ["/app/start.sh"]
