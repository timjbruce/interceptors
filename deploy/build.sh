#!/usr/bin/env bash
#
# Build hook for the Temporal project's `task app-up` (scripts/app.sh).
# Builds the single shared image all three services run from and side-loads it
# into the kind cluster. `app.sh` passes CLUSTER_NAME in the environment.
#
# All three components (backend, worker, web) use this one image; they differ
# only in the container command (see deploy/values.yaml).
set -euo pipefail

CLUSTER_NAME="${CLUSTER_NAME:-temporal}"
IMAGE="interceptors:local"
# Repo root = this script's parent's parent (deploy/ -> root).
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Optional: ENCRYPT_PAYLOADS=true|false flips the payload codec for the deploy that
# follows this build. It is NOT a build-time setting — the image is identical either
# way. The chart sets container env from the values.yaml it deploys, and container env
# beats anything baked into the image, so the only way to change it for `task app-up`
# is to edit that values.yaml before helm reads it. That is what this does. Note the
# chart spec now lives in the Temporal project (apps/interceptors/values.yaml); app.sh
# passes its path in APP_VALUES.
#
#     ENCRYPT_PAYLOADS=true task app-up APP=/path/to/interceptors
#
# The edit is written to values.yaml and persists — it is a real config change, not a
# per-run override. Re-run with ENCRYPT_PAYLOADS=false to turn it back off.
if [ -n "${ENCRYPT_PAYLOADS:-}" ]; then
  case "${ENCRYPT_PAYLOADS}" in
    true|false) ;;
    *) echo "ENCRYPT_PAYLOADS must be 'true' or 'false', got '${ENCRYPT_PAYLOADS}'" >&2; exit 1 ;;
  esac
  # Both deploy paths carry the setting, and both must agree: k8s.yaml (the
  # self-contained manifests) and values.yaml (the shared-chart spec). Within each,
  # worker and web must match — they encrypt and decrypt the same payloads — so this
  # rewrites every occurrence rather than a single component's.
  # Two shapes to handle: k8s.yaml's `- name: ENCRYPT_PAYLOADS` / `value: "x"` pair,
  # and values.yaml's single `ENCRYPT_PAYLOADS: "x"`. Matching only a quoted boolean
  # on a `value:` line would also hit any other boolean env var, so the k8s form is
  # keyed off the preceding `name:` line.
  # The chart spec is not necessarily ours: `task app-up` prefers its own
  # apps/<app>/values.yaml and passes the path it resolved in APP_VALUES. Fall back
  # to deploy/values.yaml for a checkout that still carries its own spec.
  for f in "${ROOT}/deploy/k8s.yaml" "${APP_VALUES:-${ROOT}/deploy/values.yaml}"; do
    [ -f "$f" ] || continue
    awk -v v="${ENCRYPT_PAYLOADS}" '
      {
        if (want && $0 ~ /^[[:space:]]*value:[[:space:]]*"(true|false)"[[:space:]]*$/) {
          sub(/"(true|false)"/, "\"" v "\""); want = 0
        } else if ($0 ~ /^[[:space:]]*ENCRYPT_PAYLOADS:[[:space:]]*"(true|false)"[[:space:]]*$/) {
          sub(/"(true|false)"/, "\"" v "\"")
        }
        if ($0 ~ /^[[:space:]]*-[[:space:]]*name:[[:space:]]*ENCRYPT_PAYLOADS[[:space:]]*$/) want = 1
        print
      }
    ' "$f" > "$f.tmp" && mv "$f.tmp" "$f"
    echo "==> ENCRYPT_PAYLOADS=${ENCRYPT_PAYLOADS} written to $f"
  done
  if [ "${ENCRYPT_PAYLOADS}" = "false" ]; then
    echo "    NOTE: workflows started while encryption was on cannot be decoded once it"
    echo "    is off. Let in-flight trips finish before deploying this."
  fi
fi

echo "==> Building ${IMAGE}"
docker build -f "${ROOT}/deploy/Dockerfile" -t "${IMAGE}" "${ROOT}"

echo "==> Loading ${IMAGE} into kind cluster '${CLUSTER_NAME}'"
kind load docker-image "${IMAGE}" --name "${CLUSTER_NAME}"
