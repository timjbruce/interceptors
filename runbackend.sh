#!/usr/bin/env bash
# Start the JWT-authorized backend service the activities call (:9000).
set -euo pipefail
source "$(dirname "$0")/_bootstrap.sh"

exec .venv/bin/python -m uvicorn backend.service:app --port 9000
