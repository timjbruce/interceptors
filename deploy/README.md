# Running the demo in containers

This demo can also be run in containers. These instructions are for deploying to K8s locally. To run in terminals, see the main [README](../README.md)

| File | Purpose |
|------|---------|
| `deploy/Dockerfile` | The single image all three services run from |
| `deploy/build.sh` | Builds that image and side-loads it into a kind cluster |
| `deploy/k8s.yaml` | Namespace, three Deployments, two Services — no external chart |

There is one image (`interceptors:local`) that is built and run, with 3 separate commands for the different services. The commands are:

| Component | Command | Renders |
|------|---------|---------|
| backend | `uvicorn backend.service:app` | Deployment + ClusterIP Service `interceptors-backend:9000` |
| worker  | `python -m workflows.worker` | Deployment (no HTTP, so no Service) |
| web     | `uvicorn web.app:app` | Deployment + ClusterIP Service `interceptors-web:8000` |

## Prerequisites

- Docker, [kind](https://kind.sigs.k8s.io/), and `kubectl`
- `jq` and the [`temporal` CLI](https://docs.temporal.io/cli) for the setup and
  verification steps below
- A Temporal server running either locally, in the cluster, or in the cloud

## Deploy

To deploy the interceptor demo, use the following commands:

```bash
./deploy/build.sh                          # build the image + kind load
kubectl apply -f deploy/k8s.yaml           # namespace, deployments, services
kubectl -n interceptors rollout status deploy/interceptors-worker
```

### Register the search attributes

The startup interceptor tags each run with `Traveler` and `Mission`, and Temporal rejects those tags unless the attributes exist on the namespace. **This is required
as nothing registers them for you**, and without it every booking fails with `BadSearchAttributes`.

```bash
../addsearchattributes.sh
```

### Reach the services

All the services are `ClusterIP`, so you will need to port-forward them. Use port 8000 for the web UI and port 9000 for the backend services:

```bash
kubectl -n interceptors port-forward svc/interceptors-web 8000:8000 &
kubectl -n interceptors port-forward svc/interceptors-backend 9000:9000 &
# open http://localhost:8000
```

Tip: in [k9s](https://k9scli.io/), select a service and press `shift-f` to port-forward it without typing the command.

## Encrypted payloads

`ENCRYPT_PAYLOADS` turns on the codec that encrypts **every payload and header** in Event History. It is a deploy-time setting, not a build-time one and `build.sh` writes it into the
manifests before you apply them:

```bash
ENCRYPT_PAYLOADS=true ./deploy/build.sh
kubectl apply -f deploy/k8s.yaml
kubectl -n interceptors rollout restart deploy -l app.kubernetes.io/name=interceptors
```

The edit persists in `k8s.yaml`. Re-run with `ENCRYPT_PAYLOADS=false` to turn it back off. Worker and web always need to have the same settings as they encrypt and decrypt the same payloads, and a mismatch fails at decode.

To see it: book a trip, then look at the grant on the start header or the input on the workflow.

```bash
TEMPORAL_ADDRESS=localhost:7233 temporal workflow show --workflow-id chrono-trip-bill -o json \
  | jq -r '.events[0].workflowExecutionStartedEventAttributes.header.fields["delegation-grant"].metadata.encoding | @base64d'

TEMPORAL_ADDRESS=localhost:7233 temporal workflow show --workflow-id chrono-trip-bill -o json \
  | jq -r '.events[0].workflowExecutionStartedEventAttributes.input.payloads[0].data | @base64d'
```

You will see binary/encoded data with encryption on and plaintext with encryption off. Ensure all workflows are completed before reseting or you will have some cleanup to do.

## Iterating on code

`kind load` caches the image under the same `:local` tag, and `imagePullPolicy:IfNotPresent` keeps the old one, so force new pods after a rebuild:

```bash
./deploy/build.sh
kubectl -n interceptors rollout restart deploy -l app.kubernetes.io/name=interceptors
```

## Prove it worked — the backend gate

With both port-forwards running:

```bash
# no token -> 401
curl -s -o /dev/null -w '%{http_code}\n' -X POST localhost:9000/paradox-scan \
  -H 'Content-Type: application/json' -d '{"destination":"1885"}'

# a valid session token -> 401. It identifies a person; it does not authorize a
# service call, and it is not audience-scoped for the backend.
TOKEN=$(curl -s -X POST localhost:8000/api/login \
  -H 'Content-Type: application/json' -d '{"identity":"bill"}' | jq -r .token)
curl -s -w '\n%{http_code}\n' -X POST localhost:9000/engage-booth \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"destination":"1885"}'

# exchange it the way the token-exchange interceptor does -> 200.
# These two mint commands run locally, from the repo root, against the in-repo
# demo secret. See the main README's "Prove it worked" for what each parameter is.
GRANT=$(.venv/bin/python -c "from workflows.auth import *; print(mint_delegation_grant(verify_token('$TOKEN')))")
ACTOR=$(.venv/bin/python -c "from workflows.auth import mint_actor_token; print(mint_actor_token())")
JWT=urn:ietf:params:oauth:token-type:jwt
ACCESS=$(curl -s -X POST localhost:9000/oauth2/token \
  --data-urlencode 'grant_type=urn:ietf:params:oauth:grant-type:token-exchange' \
  --data-urlencode "subject_token=$GRANT" --data-urlencode "subject_token_type=$JWT" \
  --data-urlencode "actor_token=$ACTOR"   --data-urlencode "actor_token_type=$JWT" \
  --data-urlencode 'audience=circuits-of-time-backend' \
  --data-urlencode 'requested_token_type=urn:ietf:params:oauth:token-type:access_token' \
  | jq -r .access_token)
curl -s -w '\n%{http_code}\n' -X POST localhost:9000/engage-booth \
  -H "Authorization: Bearer $ACCESS" \
  -H 'Content-Type: application/json' -d '{"destination":"1885"}'
```

## Prove it worked — the interceptors

Book a trip in the UI, then watch the worker:

```bash
kubectl -n interceptors logs -l app.kubernetes.io/component=worker --tail=40
```

You should see the activity for `verify_grant` run early in the logs. This is the activity scheduled by the workflow startup interceptor. Additionally, every line for the trip should have the same `correlation_id`.

The backend's own view of the delegation:

```bash
kubectl -n interceptors logs -l app.kubernetes.io/component=backend | grep authorized
```

The workflow is also visible in Temporal's Web UI. Port-forward it first:

```bash
kubectl -n temporal port-forward svc/temporal-web 8080:8080 &
```

## Teardown

```bash
kubectl delete -f deploy/k8s.yaml
```

This removes only this demo. the Temporal server and the cluster are untouched.
