#!/usr/bin/env bash
# Start the FastAPI web client (:8000). Extra args pass through to uvicorn
# (e.g. --reload).
set -euo pipefail
source "$(dirname "$0")/_bootstrap.sh"
[ -f setcloudenv.sh ] && source setcloudenv.sh   # optional Temporal Cloud config

exec .venv/bin/python -m uvicorn web.app:app --port 8000 "$@"
