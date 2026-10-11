#!/usr/bin/env bash
# Starts both halves of the app:
#   backend   uvicorn on 127.0.0.1:8000   (FastAPI, docs at /docs)
#   frontend  python -m http.server 5500  (static files, no build step)
#
# 5500 is the port the backend's default CORS_ORIGINS allows, and 8000 is
# what nsya-frontend/index.html points window.NSYA_API_URL at - change one
# and you have to change the other.
#
# Ctrl+C stops both. Run install.sh first.
set -u
cd "$(dirname "$0")"

BACKEND="$(pwd)/backend"
FRONTEND="$(pwd)/nsya-frontend"
PY="$BACKEND/.venv/bin/python3"

if [ ! -x "$PY" ]; then
  echo "ERROR: backend/.venv not found. Run 'bash install.sh' first."
  exit 1
fi

# One Ctrl+C should take both servers down, not orphan the backend in the
# background with port 8000 still held.
cleanup() {
  echo ""
  echo "Stopping..."
  [ -n "${BACK_PID:-}" ] && kill "$BACK_PID" 2>/dev/null
  [ -n "${FRONT_PID:-}" ] && kill "$FRONT_PID" 2>/dev/null
  wait 2>/dev/null
  exit 0
}
trap cleanup INT TERM

echo "Starting backend on http://127.0.0.1:8000 ..."
(cd "$BACKEND" && "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port 8000) &
BACK_PID=$!

echo "Starting frontend on http://127.0.0.1:5500 ..."
(cd "$FRONTEND" && "$PY" -m http.server 5500) &
FRONT_PID=$!

sleep 2
cat <<'BANNER'

==================================================================
 NSYA is running:
   app       http://127.0.0.1:5500
   API docs  http://127.0.0.1:8000/docs

 Upload sample-syllabus.txt (one subject) or
 multi-subject-sample.txt (two subjects) to try it.

 Press Ctrl+C to stop both.
==================================================================
BANNER

wait
