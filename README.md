# Wyld Stallyns Time Travel: Temporal interceptors, end to end

A small but complete, runnable demo of Temporal's interceptors, wrapped in a most non-heinous business context: a phone-booth time-travel booking service.

## Contents

- [About the project](#about-the-project)
- [Purpose](#purpose)
- [Installation](#installation)
- [Running the demo](#running-the-demo)
- [Using the demo](#using-the-demo)
- [Prove it worked](#prove-it-worked)
- [Project layout](#project-layout)
- [Interceptor types and usage](interceptors.md) (companion doc)

## About the project

**Wyld Stallyns Time Travel** is the phone-booth time-travel system that runs on a Temporal Workflow to control the Circuits of History. Rufus needed a way to create a better set of controls, focused on Security, Cost Management, Observability, and Auditability without duplicating code and adding noise to his business logic. He also needed a durable execution environment, he is one person after all!

With Temporal, Rufus built the logic he needed to scan for paradox risk before allowing Bill and Ted to travel through time. With Interceptors, he was able to create the necessary security, audit logging, and information to help him manage costs for the project without duplicating code in his client, workflow, and activities. Even though he **is** saving his current time, he wants to do so securely and responsibly.

Now all Bill and Ted need to do is to authenticate to the phone-booth, select a trip, and get on their way! Rufus can rest assured no evil twins of the pair will use the Circuits of History and screw things up!

A web client drives the phone booth for Bill, Ted, and Rufus. With this demo, you can open up a session in each tab to simulate all the parties involved. Excellent!

## Purpose

This project exists to provide an overview of Temporal's interceptors and demonstrate how they can be used. The time-travel booking app is just a sample: each interceptor solves a real, self-contained problem (authentication, auditability, observability, context propagation) as cross-cutting middleware, kept out of the workflow and activity code where the business logic lives.

For the interceptor-by-interceptor walkthrough (with pointers to the source), the authentication/authorization model, and the SA field notes on the sandbox boundary, billable Actions, and observability, see **[interceptors.md](interceptors.md)**.

## Installation

1. Requires Python 3.10+ 
2. [`temporal` CLI](https://docs.temporal.io/cli).
3. [jq](https://jqlang.org/download/)

```bash
git clone <this-repo> && cd Interceptors
.venv/bin/python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

The run scripts also create the `.venv` and install dependencies on first use, so this step is optional if you just want to run the demo.

Run the tests with `.venv/bin/python -m pytest`: unit tests for auth (`test_auth.py`), plus end-to-end tests (`test_e2e.py`), plus token exchange (`test_token_exchange.py`) that drive the real system over HTTP (client auth + entitlement, the review flow, ownership and admin gating, and the backend's JWT gate). The e2e tests start the whole stack themselves (they need the `temporal` CLI ports 7233 and free ports 8000/9000), or reuse services that are already running. If any port is not available for a service, the tests are skipped.

This project uses shared requirements for the web site, workflow, and JWT-protected backend.

## Running the demo

In four terminals, with the terminal in the comment:

```bash
temporal server start-dev     # 1. local Temporal server
./addsearchattributes.sh      # Run it once in Terminal 2 before running backend
./runbackend.sh               # 2. the JWT-authorized backend, and the token endpoint (:9000)
./runworkflow.sh              # 3. the worker, where five of the six interceptors in this demo run
./runweb.sh                   # 4. the web client (:8000)
```

Then open <http://localhost:8000>.

### Encrypting Payloads
Encrypting payloads encrypts the JWT and other sensitive data in this sample in the Temporal console. Both the worker and the web client must be run with the following steps:
  - Re-run the commands commands below in Terminals 3 and 4.
```bash
ENCRYPT_PAYLOADS=true ./runworkflow.sh      # 3. the worker, where five of the six interceptors in this demo run
ENCRYPT_PAYLOADS=true ./runweb.sh           # 4. the web client (:8000)
```

### Running against Temporal Cloud
This sample can be run against Temporal Cloud by pointing the worker, and web at Temporal Cloud via a script `setcloudenv.sh`. To set this up, complete the following steps:
  
```bash
cp setcloudenv.example setcloudenv.sh
```
  
Edit `setcloudenv.sh`: set `TEMPORAL_ADDRESS` and `TEMPORAL_NAMESPACE`, plus **one** auth option — either `TEMPORAL_API_KEY`, or both `TEMPORAL_CERT_PATH` and `TEMPORAL_KEY_PATH`. Then run the following in Terminals 2, 3, and 4.

```bash
./addsearchattributes.sh      # Run it once in Terminal 2 before running backend
./runbackend.sh               # 2. the JWT-authorized backend, and the token endpoint (:9000)
./runworkflow.sh              # 3. the worker, where five of the six interceptors in this demo run
./runweb.sh                   # 4. the web client (:8000)
```

### No browser configuration with local Temporal dev server
  - Run the commands for Terminals 1, 2, and 3 listed above, then run:

```bash
python -m workflows.cli
```

### Containers deployment

The three services ship as a single container image, with each service differing only in its launch command (backend, worker, web). The image and its deploy spec can be found in [`deploy/`](deploy/). `k8s.yaml` deploys the three services with plain `kubectl`; the spec for the shared-chart route lives in the Temporal-on-kind project instead — see [deploy/README.md](./deploy/README.md) for the full sequence to you can run the services in containers or deploy them onto a local [kind](https://kind.sigs.k8s.io/) cluster.

Once deployed, the services use the ClusterIP and two services need to be port-forwarded to be accessible using the following commands or port forwarding in your tool.

```bash
kubectl -n interceptors port-forward svc/interceptors-web 8000:8000
kubectl -n interceptors port-forward svc/interceptors-backend 9000:9000
```

Technically, only the web service requires port-forwarding. The port-forwarding on the backend is in case you would like to validate the service only accepts requests with valid tokens.

- Open <http://localhost:8000>

Full build, deploy, port-forward, and teardown flow (plus the k9s tip):
[`deploy/README.md`](deploy/README.md).

## Using the demo

### Authenticate

The first step you need to do is to authenticate as a user. In the web UI (<http://localhost:8000>), select one of the users.

- Bill S. Preston, Esq. (Bill) and Ted "Theodore" Logan (Ted) can travel and will receive a JWT ([JSON Web Token](https://www.jwt.io/introduction#what-is-json-web-token)) that can be validated and will allow them to travel in the Circuits of History. The token carries their identity as claims: a `role` (`traveler`) and a `group` (`premium` or `standard`). Bill is in the `premium` group and Ted is in the `standard` group. Group details will be discussed below.

- Rufus can authenticate as the administrator and receives a JWT that enables this. He can approve or deny questionable trips by Bill or Ted via his `role` (`admin`).

- Evil Bill and Evil Ted will receive forged JWTs, which the client interceptor rejects them before any workflow starts. Any trips they attempt to take will be denied.

### Book and take a journey

Selecting Bill or Ted will allow you to book trips. As mentioned above, Bill is in the `premium` group while Ted is in the `standard` group. Bill, being premium, can book trips with the mission `Save the future`. Ted cannot. This is enforced by the client interceptor [read more about interceptors](./interceptors.md), which reads the `group` claim off the verified token and checks the user is entitled to the mission. The backend service also checks the `group` claim, so a request that skips the client interceptor still cannot run a premium-only mission. By checking the value earlier, we can avoid billable Actions for a workflow that cannot complete.

Some journeys will be flagged for review by Rufus. This is done by the backend service that performs a paradox scan (the first non-interceptor scheduled activity in the workflow) or by checking the `Force a bogus timeline` checkbox when booking the journey. These trips will wait for Rufus to approve or deny them via his admin interface (authentice as Rufus to see this). Approval will complete the trip, denial will complete the workflow with a 'rejected' status.

### How the worker acts on your behalf

The token you see in the web UI never leaves the client tier. When you book a trip, the client interceptor verifies your session license and then mints a separate **delegation grant**, which is what travels to the workflow. The token exchange interceptor, attached to each activity, trades that grant, plus the worker's own identity, for a short-lived access token whose subject is you and whose actor is the worker — so the backend logs read `worker=worker-wyld-stallyns acting on behalf of traveler=bill`.

Two reasons it works this way, both worth knowing:

- **What goes on a Temporal header is stored in Event History for the namespace's retention period and cannot be redacted**. A session token there would be a live and could be used by any Temporal administrator to act as the user of the credential. The grant is not able to be used like the session token. Its audience is the token endpoint, only the named worker may redeem it, and it authorizes nothing by itself.
- **A trip can wait days for Rufus to review it.** Session tokens typically expire in minutes to hours. If the workflow carried a session token, trips would fail if Rufus didn't approve them for days and the activities could no longer use the session token or get a credential to call the backend system.

Session licenses in the demo are short-lived (15 minutes), but you will rarely notice: the client interceptor's `get_token` callback (a callback you pass `JWTClientInterceptor`; see (interceptors.md)[./interceptors.md]) renews it over HTTP when it is about to expire, and hands the new one back to the browser. A license more than an hour past expiry cannot be renewed, and you log in again.

Bad JWTs are caught in three independent spots:

1. **The client interceptor, before the workflow starts.** A missing, forged, or unentitled request is rejected at the client and never reaches the sever. Because of this, there is no `start_workflow` received by the server and it never becomes a billable Workflow Execution. This is the gate at the client edge.
2. **The workflow startup interceptor, at the workflow edge.** This interceptor schedules an activity, `verify_grant`, to verify the token's signature and fails the run immediately if the license is missing, malformed, forged, expired, wrong audience, or wrong type, before activities in the main part of the workflow run. This is what catches a workflow started out-of-band, such as a raw `temporal workflow start` from the command line, which stamps no token at all.
3. **The backend services, from every activity call.** The backend services verify the token and check entitlements. A failed call to the backend returns a 401 or 403 and the activity turns these errors into a non-retryable error, so the workflow fails fast instead of retry-looping.

Two of the three do not depend on a worker-side interceptor being registered, so the credential is still checked twice even if the workflow-edge guardrail is removed.

## Prove it worked

Steps to confirm each part is real:

1. **Client auth + entitlement.**
   - Ted picking "Save the future" is rejected instantly, with no workflow started.
   - Bill proceeds.
   - "No license", "Evil Bill", and "Evil Ted" are rejected, with no workflow started.
2. **A delegation grant — not the user's token — reached Temporal.**
   - Book a valid journey with either Bill or Ted.
   - Find the workflow in the Temporal UI and click on it for details.
   - Click on the Event `Workflow Execution Started` and review the `Header` field.
   - You will see a `delegation-grant` value. It deliberately does *not* match the JWT shown in the web UI. The browser holds a short-lived session license; the client interceptor mints a separate grant for the workflow. Decode the grant (paste it into <https://jwt.io>) and note `token_use: grant`, an `aud` of `circuits-of-time-token-endpoint`, and `may_act` naming the worker.
   - That is the security property: this value cannot call the backend and cannot be used to request a trip via the web application. Only the named worker, the Temporal worker, can redeem it.
   - Restart the app using the [Encrypting Payloads](#encrypting-payloads) instructions and watch the header in the Temporal UI become ciphertext.
3. **The worker acted on the user's behalf.**
   - Watch the backend terminal for the delegation pair:
     `[backend] issued delegated token — worker=worker-wyld-stallyns on behalf of traveler=bill`
     then
     `[backend] authorized paradox-scan — worker=worker-wyld-stallyns acting on behalf of traveler=bill (Bill S. Preston, Esq.)`.
   - Both identities on every line is the point: this is delegation and not impersonation.
4. **The backend is genuinely gated (curl).**

   ```bash
   # no token -> 401
   curl -s -o /dev/null -w '%{http_code}\n' -X POST localhost:9000/paradox-scan \
     -H 'Content-Type: application/json' -d '{"destination":"1885"}'

   # a valid USER license -> 401. It identifies a person; it does not authorize a
   # service call, and it is not audience-scoped for the backend.
   TOKEN=$(curl -s -X POST localhost:8000/api/login \
     -H 'Content-Type: application/json' -d '{"identity":"bill"}' | jq -r .token)
   curl -s -o /dev/null -w '%{http_code}\n' -X POST localhost:9000/engage-booth \
     -H "Authorization: Bearer $TOKEN" \
     -H 'Content-Type: application/json' -d '{"destination":"1885"}'

   # exchange it the way the worker does -> then it works (200).
   # Form-encoded, not JSON: RFC 8693 §2.1 requires
   # application/x-www-form-urlencoded, and each token must be accompanied by its
   # *_token_type. Drop subject_token_type and the endpoint answers
   # 400 invalid_request.
   GRANT=$(.venv/bin/python -c "from workflows.auth import *; print(mint_delegation_grant(verify_token('$TOKEN')))")
   ACTOR=$(.venv/bin/python -c "from workflows.auth import mint_actor_token; print(mint_actor_token())")
   JWT=urn:ietf:params:oauth:token-type:jwt
   ACCESS=$(curl -s -X POST localhost:9000/oauth2/token \
     --data-urlencode 'grant_type=urn:ietf:params:oauth:grant-type:token-exchange' \
     --data-urlencode "subject_token=$GRANT"      --data-urlencode "subject_token_type=$JWT" \
     --data-urlencode "actor_token=$ACTOR"        --data-urlencode "actor_token_type=$JWT" \
     --data-urlencode 'audience=circuits-of-time-backend' \
     --data-urlencode 'requested_token_type=urn:ietf:params:oauth:token-type:access_token' \
     | jq -r .access_token)
   curl -s -X POST localhost:9000/engage-booth \
     -H "Authorization: Bearer $ACCESS" \
     -H 'Content-Type: application/json' -d '{"destination":"1885"}'
   ```

   - A forged token (`{"identity":"evil-bill"}`) returns 401 at `/engage-booth`, and cannot be exchanged. Building a grant from the token fails because `verify_token` returns `None`.
   - Note the two different status codes. The **token endpoint** answers `400` with an OAuth error body (`{"error": "invalid_grant"}`) because a refused grant is a bad request. The **resource server** answers `401`, because that is a challenge for credentials. Any 4xx fails the activity non-retryably and only 5xx reponses are retried.
   - Ask for an audience the endpoint won't mint for (`--data-urlencode 'audience=some-other-service'`) and you get `400 invalid_target` rather than a token quietly issued for the wrong service.
   - The `$GRANT` also returns 401 if presented to `/engage-booth` directly — try it.
   - In the container / kind deployment, port-forward the backend before curling using `kubectl --context kind-temporal -n interceptors port-forward svc/interceptors-backend 9000:9000`. See the containers note under [Running the demo](#running-the-demo).
5. **Bypass fails safely.**
   - A `temporal workflow execute` CLI call (no client interceptor, so no grant on the header) is failed at the workflow edge by the workflow startup interceptor's guardrail: a non-retryable `InvalidDelegationGrant` error at the `verify_grant` activity. The interceptor will raise a `InvalidDelegationGrant` error.

   ```bash
   temporal workflow execute \
     --type ChronoTripWorkflow \
     --task-queue interceptor-samples \
     --workflow-id bypass-demo \
     --input '{"destination":"1885","mission":"","force_review":false}'
   ```
6. **Trips are tagged + filterable.**
   - The startup interceptor stamps each run with `Traveler` and `Mission` search attributes (added by a script and populated by the workflow startup interceptor), so you can filter in the Temporal UI or CLI:

   ```bash
   temporal workflow list --query "Traveler = 'Bill S. Preston, Esq.'"
   ```
7. **See the interceptors firing (logs).** The worker-side interceptors log as they run. Watch the **worker terminal** (terminal 3); the backend's auth line
   is in the **backend terminal** (terminal 2). One booking produces lines like:

Abridged: the real lines carry a full date and an `INFO` column.
   ```text
   12:52:44 | activity_logging.py:38   | [interceptor:activity] started: verify_grant (workflow_id=chrono-trip-bill, attempt=1, correlation_id=cot-019fd722)
   12:52:44 | activities.py:159        | [activity:verify-grant] grant verified for bill (Bill S. Preston, Esq.) (...)
   12:52:44 | activity_logging.py:58   | [interceptor:activity] completed: verify_grant in 0.000s [correlation_id=cot-019fd722]
   12:52:44 | workflow_startup.py:171  | [interceptor:startup] trip start: traveler=Bill S. Preston, Esq. mission=Ace our history report correlation_id=cot-019fd722 (...)
   12:52:44 | activity_logging.py:38   | [interceptor:activity] started: paradox_scan (workflow_id=chrono-trip-bill, attempt=1, correlation_id=cot-019fd722)
   12:52:44 | token_exchange.py:250    | [interceptor:exchange] worker-wyld-stallyns acting on behalf of bill (expires in 120s) (...)
   12:52:44 | activities.py:172        | [activity] calling paradox-scan backend for traveler bill -> Ancient Greece, 410 B.C. (...)
   12:52:47 | activity_logging.py:58   | [interceptor:activity] completed: paradox_scan in 3.384s [correlation_id=cot-019fd722]
   ...
   12:53:04 | activity_logging.py:38   | [interceptor:activity] started: execute_jump (workflow_id=chrono-trip-bill, attempt=1, correlation_id=cot-019fd722)
   12:53:10 | activity_logging.py:58   | [interceptor:activity] completed: execute_jump in 5.908s [correlation_id=cot-019fd722]
   ```

This shows the interceptors handing off to each other. `verify_grant` runs **first**, as it is the credential check the startup interceptor schedules, before any business activity. Then the startup interceptor tags the run, then the exchange interceptor mints a delegated token, or reuses a cached one that is still valid, for each activity attempt. The interceptor log lines all carry the same `correlation_id`, seeded by the startup interceptor. The full sequence, including the review pause, is annotated in [interceptors.md](interceptors.md#watching-it-happen).

   - Grant propagation has log lines of its own, so you see its effect in logs and with the backend accepting the call (`[backend] authorized paradox-scan — worker=worker-wyld-stallyns acting on behalf of traveler=bill (Bill S. Preston, Esq.)` in terminal 2) instead of a 401. Additionally, the client interceptor logs rejections in the **web** terminal.
   - In the container / kind deployment, the same lines are in the pod logs: `kubectl --context kind-temporal -n interceptors logs -l app.kubernetes.io/component=worker` (use `component=backend` for the backend line).

See **[interceptors.md](interceptors.md)** for a deeper discussion on Interceptors and what each interceptor is doing behind these steps.

## Project layout

```text
workflows/                     all the Temporal code
├── workflow.py                ChronoTripWorkflow (+ review signal, status queries)
├── activities.py              verify_grant (the credential check) + the two backend calls
├── models.py                  shared dataclasses (TripRequest, ScanResult, GrantCheck)
├── auth.py                    JWTs: subject/grant/actor/access tokens, RFC 8693 exchange, entitlement
├── client.py                  connect(): local or Cloud; wires the encryption codec
├── codec.py                   optional payload encryption (ENCRYPT_PAYLOADS)
├── config.py                  task queue, address/namespace, backend URL, from env
├── worker.py                  registers workflow, activities, worker-side interceptors
├── cli.py                     CLI demo (auth + entitlement scenarios)
└── interceptors/
    ├── client_auth.py         Client: validate (+expiry) + entitlement + mint the delegation grant
    ├── workflow_startup.py    Workflow start: correlation id + guardrail + search-attr tagging
    ├── grant_propagation.py   Workflow + activity: carry the grant to the activities
    ├── token_exchange.py      Activity: redeem the grant for a delegated access token (on-behalf-of)
    ├── activity_logging.py    Activity: log every activity's start, duration, and outcome
    └── workflow_audit.py      Workflow inbound: signal/query audit (no auth)
backend/
└── service.py                 JWT-authorized backend (:9000) + token exchange & refresh endpoints
web/
├── app.py                     FastAPI web client (login, booking, review)
└── static/                    index.html, app.js, style.css, favicon.ico, phonebooth.svg, temporal.svg
tests/
├── conftest.py                starts (or reuses) the live stack for the e2e tests
├── test_auth.py               auth unit tests: tokens, expiry, type confusion, entitlement
├── test_token_exchange.py     RFC 8693 exchange unit tests
└── test_e2e.py                end-to-end over real HTTP against the running stack
deploy/                        container image + kind/Kubernetes deploy (see deploy/README.md)
├── Dockerfile                 one shared image for backend, worker, and web
├── k8s.yaml                   namespace, Deployments, Services — no external chart
└── build.sh                   build the image + kind load
runbackend.sh, runworkflow.sh, runweb.sh   start each service (share _bootstrap.sh)
addsearchattributes.sh         register the Traveler + Mission search attributes
setcloudenv.example            copy to setcloudenv.sh to target Temporal Cloud
requirements.txt, pytest.ini   shared dependencies for all three services; test config
interceptors.md                interceptor types + how this project uses them
presentation.md                slide deck: what interceptors are + how the demo shows them off
```
