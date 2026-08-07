#!/usr/bin/env bash
# Start the Temporal worker (workflow + activity + propagation interceptors).
# Local by default; copy setcloudenv.example -> setcloudenv.sh to target Cloud.
set -euo pipefail
source "$(dirname "$0")/_bootstrap.sh"
[ -f setcloudenv.sh ] && source setcloudenv.sh   # optional Temporal Cloud config

exec .venv/bin/python -m workflows.worker
