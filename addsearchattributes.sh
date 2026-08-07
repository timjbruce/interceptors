#!/usr/bin/env bash
# Add the custom Search Attributes this demo writes: Traveler and Mission.
# The worker also does this at startup, so this is only needed when it can't --
# e.g. credentials without operator permission on the namespace.
# Local by default; copy setcloudenv.example -> setcloudenv.sh to target Cloud.
set -euo pipefail
cd "$(dirname "$0")"
[ -f setcloudenv.sh ] && source setcloudenv.sh   # optional Temporal Cloud config

temporal operator search-attribute create \
  --namespace "${TEMPORAL_NAMESPACE:-default}" \
  --name Traveler --type Keyword \
  --name Mission --type Keyword
