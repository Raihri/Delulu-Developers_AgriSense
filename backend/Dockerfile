# AgriSense backend — pinned to Python 3.12 so you don't need it on your Mac.
# Build context is the repository root (see docker-compose.yml) so that the
# repo layout (backend/ next to dataset/) is preserved and config.py path
# resolution keeps working: BACKEND_ROOT=/app/backend, REPOSITORY_ROOT=/app.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app/backend

# Install dependencies first for better layer caching.
COPY backend/requirements.txt backend/requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the backend source (dataset/ is provided as a read-only volume at runtime
# only when you run kb.migrate / kb.build / kb.validate; the API does not need it).
COPY backend/ /app/backend/

EXPOSE 8000

# Runtime: serve the FastAPI app. Migration/seed are separate one-off commands,
# e.g.  docker compose run --rm backend python -m kb.build
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
