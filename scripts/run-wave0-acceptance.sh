#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
: "${THESIS_TRACE_TEST_DATABASE_URL:?THESIS_TRACE_TEST_DATABASE_URL is required}"
task_python="$project_root/backend/.venv/bin/python"
PYTHONPATH="$project_root/backend:$project_root/backend/src" "$task_python" -m uvicorn tests.fixtures.acceptance_api:app --host 127.0.0.1 --port 8000 &
api_pid=$!
for _ in $(seq 1 100); do
  if "$task_python" -c 'import urllib.request; urllib.request.urlopen("http://127.0.0.1:8000/health/ready", timeout=1)' 2>/dev/null; then break; fi
  sleep 0.1
done
PYTHONPATH="$project_root/backend:$project_root/backend/src" "$task_python" -m tests.fixtures.acceptance_worker &
worker_pid=$!
npm --prefix frontend run build
"$task_python" scripts/acceptance_gateway.py &
gateway_pid=$!
trap 'kill "$gateway_pid" "$worker_pid" "$api_pid" 2>/dev/null || true' EXIT
wait "$gateway_pid"
