#!/usr/bin/env bash
# Launch the AgriSense backend (FastAPI) and frontend (Next.js) in one container.
# Either process exiting brings the container down so orchestrators can restart it.
set -euo pipefail

# Backend API on :8000
( cd /app/backend && exec uvicorn app:app --host 0.0.0.0 --port 8000 ) &
backend_pid=$!

# Frontend on :3000. Its server-side proxy targets the backend in THIS container.
( cd /app/frontend && exec env AGRISENSE_API_BASE_URL="http://127.0.0.1:8000" npm run dev ) &
frontend_pid=$!

terminate() {
  kill "$backend_pid" "$frontend_pid" 2>/dev/null || true
}
trap terminate SIGTERM SIGINT

echo "AgriSense running — frontend http://localhost:3000  backend http://localhost:8000"

# Exit as soon as either process stops, then stop the other.
wait -n "$backend_pid" "$frontend_pid"
terminate
