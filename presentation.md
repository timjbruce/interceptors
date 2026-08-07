---
marp: true
title: Temporal Interceptors, a problem-first guide
paginate: true
---

<!--
Marp-compatible deck (https://marp.app). `---` separates slides; HTML comments
are speaker notes. Grounded in Temporal's own docs; see the Sources slide.
Format: each capability is taught as Problem -> Temporal's answer -> Realize it
(real demo code, where it is wired, what triggers it) -> What you'll see.
-->

# Temporal Interceptors

## A problem-first guide

Start with the pain a team feels, then the interceptor that solves it, then the
exact code that realizes it.

---

## How this guide is built

Every capability slide follows one shape:

1. **Problem** the team actually has
2. **Temporal's answer** (which use case, which category)
3. **Realize it** (real demo code, where it is registered, what triggers it)
4. **What you'll see**

The running demo is **Wyld Stallyns Time Travel** (Python): a phone-booth booking
service whose business logic stays clean because every cross-cutting concern is an
interceptor.

<!--
Set expectations: this is not "here is a feature," it is "here is a problem you
have and how to solve it." The demo is Python, but the pattern is portable
(covered near the end).
-->

---

# Part 1: The idea, grounded in Temporal

---

## The problem interceptors exist to solve

You have behavior that **every** workflow and activity needs, but none of them
should own: authentication, logging, tracing, carrying a request id.

Put it in the business code and it gets **copy-pasted, drifts, and is forgotten**
on the next new workflow.

Temporal's framing (Python SDK docs): interceptors let you

> "add common behavior across many calls, such as tracing and context
> propagation."

One place, applied to every call, instead of scattered through the code.

<!--
Anchor everything on "common behavior across many calls." That single phrase is
the reason interceptors exist. Source: docs.temporal.io/develop/python/workers/interceptors
-->

---

## What Temporal says an interceptor is

Straight from the Temporal Encyclopedia:

> "Interceptors let you add cross-cutting behavior **before and after** SDK
> operations such as starting a Workflow, executing an Activity, or handling a
> Signal. They work like **middleware**: each interceptor **wraps the next**,
> forming a chain that executes around the underlying operation."

So an interceptor is middleware for the Temporal SDK. Next: what "middleware"
means, exactly.

<!-- Source: docs.temporal.io/encyclopedia/interceptors -->

---

## "Middleware", expanded

Middleware is the **wrap-the-call** pattern: your code holds the "next" step and
decides whether to call it.

```python
async def start_workflow(self, input):
    # before: inspect / modify / decide
    result = await super().start_workflow(input)   # call the rest of the chain
    # after: inspect / react
    return result
```

- You write **one method**; "before" and "after" are the code around `super()`.
- Refuse to call `super()` and you **short-circuit** the operation.
- It is a chain: **first registered is outermost**, and the innermost call is
  Temporal's real work. You already know this shape from Django, Starlette, and
  Flask middleware.

<!--
Temporal's docs explicitly compare interceptors to Django/Starlette/Flask
middleware. The "holds next, chooses to call it" point is what separates
middleware from a lifecycle hook (a hook only notifies; it cannot short-circuit
or reshape the result).
-->

---

## Where you can hook in: the five categories

| Category | Wraps | Runs |
|---|---|---|
| Client (outbound) | your calls out (start, signal, query) | your app process |
| Workflow inbound | calls into a workflow (execute, signal, query, update) | worker, in the sandbox |
| Workflow outbound | calls a workflow makes (activity, child, timer) | worker, in the sandbox |
| Activity inbound | one activity execution | worker |
| Activity outbound | calls an activity makes (heartbeat, info) | worker |

Pick the category by **where the call is**. Two of them (the workflow ones) run
inside the sandbox, which sets one hard rule we return to in Part 3.

<!-- Source: docs.temporal.io/develop/python/workers/interceptors (the five categories). -->

---

## The use cases Temporal names

The Encyclopedia lists exactly what interceptors are for:

- **Observability** (logging, metrics, tracing)
- **Authorization and authentication** checks
- **Header manipulation** (propagating metadata)
- **Input and output validation**

Part 2 takes these one at a time, as problems, and solves each in the demo.

<!-- Source: docs.temporal.io/encyclopedia/interceptors. This is the menu Part 2 works through. -->

---

# Part 2: Problem, answer, realize it

---

## Problem: authentication copy-pasted everywhere

> "Every booking has to validate the caller's license and entitlement group. We
> keep pasting that check into each path, and a new one can forget it, or worse,
> run and get billed before failing."

**Temporal's answer:** an **authentication and authorization check** at the
**client** category, so a bad request is rejected before the workflow ever starts.

```python
async def start_workflow(self, input):
    traveler = verify_token(token, now=time.time(), expect_use=USE_SUBJECT)  # authenticate (+expiry)
    if traveler is None:
        raise LicenseError("A valid, unexpired license is required.")
    if err := mission_entitlement_error(traveler, mission):
        raise LicenseError(err)                          # authorize
    grant = mint_delegation_grant(traveler)              # delegate, don't forward
    input.headers = {**(input.headers or {}), GRANT_HEADER_KEY: to_payload(grant)}
    return await super().start_workflow(input)           # stamp, then continue
```

- **Where:** `workflows/interceptors/client_auth.py`, registered in
  `Client.connect(interceptors=[…])` (`web/app.py`, `workflows/cli.py`)
- **Fires when:** every `start_workflow`; in the demo, `POST /api/book`
- **You'll see:** a bad license rejected instantly. No workflow, no billed Action.

---

## The `get_token` callback: real I/O, legally

The token comes from a **callback**, not a fixed string — and the callback may be
**async**. That is where the sandbox rule pays off in the *other* direction: a client
interceptor may block on the network, so credential acquisition belongs here.

```python
async def _token_for_start():                     # web/app.py
    token = _request_token.get()
    # Skewed clock: a license expiring within a minute counts as expired already.
    if rejection_reason(token, now=time.time() + REFRESH_SKEW,
                        expect_use=USE_SUBJECT) != REJECT_EXPIRED:
        return token                              # good, or unfixable by refresh
    async with httpx.AsyncClient() as http:                    # <- real network I/O
        resp = await http.post(f"{BACKEND_URL}/oauth2/refresh",
                               json={"session_token": token})
    ...
```

- **Refresh proactively.** The skew means a slow request cannot outlive its credential.
- **Only refresh what refresh fixes.** Acts on `expired`; a forged token falls through
  to rejection.
- **Return the new token to the caller**, or the browser keeps sending the stale one.

The identical call inside a workflow interceptor would be a determinism violation.
Same code, different seam, opposite verdict.

<!--
Contrast with the token-exchange slide later: this refreshes the USER'S SESSION once
per start; that one mints a PER-ATTEMPT credential on the worker. A workflow
interceptor sits between them and may do no I/O at all.
Demo shortcut to admit if asked: /oauth2/refresh accepts the expiring token itself as
proof. A real IdP wants a refresh token or session cookie.
-->

---

## Problem: carry identity to a downstream service

> "The activity calls a real backend that needs the caller's identity. I do not want
> that in the workflow input or threaded through every function signature."

**Temporal's answer:** **header manipulation / context propagation**. Headers
carry user metadata "from one execution context to another." They are read by
inbound interceptors and written by outbound ones, and are **not** auto-forwarded,
so you re-stamp them going out. Spans three categories.

```python
# Workflow OUTBOUND: stamp the grant onto each activity the workflow schedules
def start_activity(self, input):
    grant = current_grant.get()
    if grant is not None:
        input.headers = {**(input.headers or {}), GRANT_HEADER_KEY: to_payload(grant)}
    return super().start_activity(input)
```

- **Where:** `workflows/interceptors/header_propagation.py`, registered in
  `workflows/worker.py`
- **Fires when:** workflow start (reads the header), then each
  `workflow.execute_activity(...)` in `workflows/workflow.py` (stamps it onward)
- **You'll see:** the next interceptor has something to redeem, so the backend
  accepts the call — and nothing appears in business arguments.

**What rides here is a delegation grant, not the user's token.** Headers land in
Event History permanently, so the value must be one that cannot be replayed. The
credential itself is minted later, per activity attempt — next slide.

<!--
Grounding: Temporal staff describe headers as metadata "made specifically to
propagate user-defined information from one execution context to another,"
readable by inbound interceptors and writable by outbound ones, and "not
auto-forwarded from inbound to outbound." Note Temporal also has a dedicated
Context Propagation concept (propagators); in Python you implement it with
interceptors plus headers. Covered on the Context Propagation slide in Part 3.
-->

---

## Problem: uniform activity logs without touching each activity

> "We want start, complete, failure, and duration for every activity, in one
> format, without editing every activity function."

**Temporal's answer:** **observability** at the **activity inbound** category. One
wrapper covers every activity type.

```python
async def execute_activity(self, input):
    info, started = activity.info(), time.monotonic()
    logger.info("started: %s (correlation_id=%s)", info.activity_type, correlation_id.get())
    try:
        return await super().execute_activity(input)
    finally:
        logger.info("done: %s in %.3fs", info.activity_type, time.monotonic() - started)
```

- **Where:** `workflows/interceptors/activity_logging.py`, registered in
  `workflows/worker.py`
- **Fires when:** every activity run; in the demo, `paradox_scan` and
  `execute_jump` (`workflows/activities.py`)
- **You'll see:** one consistent line per activity, carrying the correlation id.

---

## Problem: tag, guard, and correlate every trip at its start

> "Every trip should be searchable, should fail fast if its license is bad, and
> should be correlated in logs. That logic should not be sprinkled through the
> workflow, and it must survive replay."

**Temporal's answer:** do it once at **workflow inbound** (`execute_workflow`).
Temporal staff call this the **"inject context once per execution"** pattern, and
it uses replay-safe operations only.

```python
async def execute_workflow(self, input):
    traveler = verify_token(token_from(input.headers))      # pure HMAC -> replay-safe
    if traveler is None:                                   # input validation / guardrail
        raise ApplicationError("no valid license on header", type="MissingLicense", non_retryable=True)
    correlation_id.set(cid_from(input.headers) or f"cot-{workflow.info().run_id[:8]}")
    workflow.upsert_search_attributes(                     # tag: recorded, replay-safe
        [TRAVELER_SA.value_set(traveler["name"]), MISSION_SA.value_set(mission)])
    return await super().execute_workflow(input)
```

- **Where:** `workflows/interceptors/workflow_startup.py`, registered in
  `workflows/worker.py`
- **Fires when:** the start of every `ChronoTripWorkflow` run
- **You'll see:** `Traveler` and `Mission` searchable in the UI; a start with a
  missing or forged license fails fast; the correlation id on every log line.

**Why a signature check is legal here** — and this is the slide's real teaching
point. The sandbox rule is *no clock, no randomness, no I/O*; it is **not** "no
cryptography." `verify_token` is an HMAC over bytes already on the header, so it is
pure and replays identically. Two deliberate choices keep it that way: the licenses
carry **no `exp` claim** (an expiry check reads the wall clock, so a token valid on
the first run could be expired on replay), and identity comes from the token's
**claims** rather than a user-directory lookup (which is I/O, and would also mean
routine user churn changes how an in-flight run replays). Swap in a real JWKS fetch
and this stops being safe — the check moves back to the client.

<!--
Grounding: the "inject context once per execution" phrasing is Temporal staff
guidance (bind in execute_workflow / execute_activity, clear in finally).
upsert_search_attributes is a recorded command, so it is replay-safe.
-->

---

## Problem: audit every message into a running workflow without editing it

> "Compliance needs a uniform record of every signal and query a workflow
> receives — argument types, not values — that individual handlers can't skip and
> that never copies sensitive payloads into a second store."

**Temporal's answer:** wrap messages at the **workflow inbound** category. This is
the same shape as Temporal's own retry-on-signal interceptor sample.

```python
async def handle_signal(self, input):
    workflow.logger.info(                                 # audit (replay-safe logger)
        "signal: %s args=%s",
        input.signal, _safe_summary(input.args),          # log types, not values
    )
    await super().handle_signal(input)
```

- **Where:** `workflows/interceptors/workflow_audit.py`, registered in
  `workflows/worker.py`
- **Fires when:** signals and queries; in the demo, `/api/review` and the
  `get_state` status polls
- **You'll see:** a replay-safe audit line per signal and query, logging argument
  types rather than values.

---

## Problem: the worker must act *as* the user, for hours

> "Our audit log has to say which user an action was taken for. But the workflow
> waits on a human reviewer, and by then the user's session token is long expired."

**Temporal's answer:** do the credential exchange on **activity inbound** — the only
seam that runs per attempt, on the worker, outside the sandbox. This is RFC 8693
**delegation**: the resulting token's `sub` is the user and its `act` is the worker.

```python
async def execute_activity(self, input):
    grant = _grant_from(input.headers)                      # long-lived, inert
    access = await _access_token_for(grant) if grant else None   # network call: legal here
    current_access_token.set(access)                        # 2-minute credential
    try:
        return await super().execute_activity(input)
    finally:
        current_access_token.set(None)
```

- **Where:** `workflows/interceptors/token_exchange.py`
- **Fires when:** every activity **attempt**, before the activity body
- **You'll see:** `[backend] authorized paradox-scan — worker=worker-wyld-stallyns
  acting on behalf of traveler=bill (Bill S. Preston, Esq.)`

Three constraints force it here, and each one is a lesson:

| Constraint | Consequence |
| --- | --- |
| The exchange is **I/O** | cannot live in a workflow interceptor |
| Activity headers freeze at **scheduling**, and retries reuse them | must run per *attempt*, not per schedule |
| Everything a workflow receives is in **Event History forever** | credentials must never travel back through it |

<!--
Grounding: RFC 8693 delegation (act claim) vs impersonation; activity headers are
recorded in ActivityTaskScheduled and reused across attempts.
-->

---

## One booking exercises all six

```text
Bill books ─▶ Client: authenticate (+expiry), authorize, mint a GRANT (reject unbilled)
           ─▶ Startup: guard, tag Traveler/Mission, seed correlation id
           ─▶ Header propagation: carry the grant onto the activity
           ─▶ Token exchange: grant + worker identity → 2-min delegated token
           ─▶ Activity logging: one line per activity, with the correlation id
           ─▶ Backend: requires the delegated token → flagged? hold for Rufus
           ─▶ Audit: log every inbound signal/query (types, not values)
```

Six problems, six interceptors, one traceable request. The workflow and activities
still read like the business — no auth code in either.

---

# Part 3: Doing it right (the guidance)

---

## Rule 1: workflow interceptors run on replay

Temporal is explicit:

> "Workflow inbound and outbound interceptor methods **also execute during
> replay**. Use replay-safe APIs for logging, randomness, and time."

So, inside the workflow categories:

- Use `workflow.logger` and `workflow.metric_meter()` (both replay-aware), and
  recorded commands like `upsert_search_attributes`.
- Do **not** read the **clock**, use unguarded **randomness**, or make **network
  calls**. Push those to an **activity** or the **client** category.
- If you must, guard with `workflow.unsafe.is_replaying()`.
- The rule constrains **how** you compute, not **which** concern you own. Pure
  computation on data already in hand is fine — the demo verifies a JWT signature
  here (HMAC, no clock, no I/O). Checking that same token's *expiry* would not be,
  because that reads the wall clock. Watch the mechanism, not the topic.

Client and activity interceptors are **not** affected by replay.

<!--
Grounding: docs state workflow interceptor methods execute during replay; staff
confirm workflow interceptors are inside the sandbox and subject to determinism,
and that Temporal's own metric emission is only safe because it is replay-aware
and guarded with is_replaying().
-->

---

## Rule 2: headers are the propagation pipe

- Headers carry metadata "from one execution context to another."
- They are **not visible** to workflow or activity code directly. Only
  interceptors read and write them.
- They are **not auto-forwarded** from inbound to outbound. To reach activities
  and child workflows, an outbound interceptor must re-stamp them.

This is exactly why header propagation in the demo spans three categories: read
inbound, stamp outbound, read again in the activity.

<!--
Grounding: Temporal staff describe headers precisely this way, including "not
auto-forwarded from inbound to outbound." This is the number-one gotcha.
-->

---

## Placement helps you manage cost and safety

Where you put a check is a lever:

| Reject at… | Start Action | Downstream |
|---|---|---|
| Client interceptor | not billed, never sent | not billed, workflow never runs |
| Workflow inbound interceptor | billed once (start already succeeded) | not billed, stops before scheduling |
| In business logic | billed | billed for whatever ran first |

Reject at the **client** for the cheapest gate. Keep an **edge guardrail** at the
workflow start for anything that bypassed the client (a raw `temporal workflow
start`).

---

## Register once, in the right place

- **Client interceptors:** pass to `Client.connect(interceptors=[…])`.
- **Worker interceptors:** pass to `Worker(interceptors=[…])`.
- One class can be **both** a client and a worker interceptor (their method sets
  do not overlap).
- Best practice from Temporal: register on the **client** for things that must
  propagate, and **do not** register the same interceptor on both client and
  worker.

```python
# workflows/worker.py
worker = Worker(client, task_queue=TASK_QUEUE,
    workflows=[ChronoTripWorkflow], activities=[paradox_scan, execute_jump],
    interceptors=[                       # first = outermost
        WorkflowStartupInterceptor(), ActivityLoggingInterceptor(),
        TokenExchangeInterceptor(),
        WorkflowAuditInterceptor(), HeaderPropagationInterceptor()])
```

<!-- Grounding: Temporal OpenTelemetry best practices: register on client, avoid duplicating on both. -->

---

## What interceptors cannot do

They are middleware, not magic. An interceptor cannot:

- **Break determinism in the sandbox.** Clock reads, randomness, and I/O are out;
  push those to the client or an activity. Pure computation is fine.
- **Change a workflow's fixed-at-start attributes** (priority, retry policy, task
  queue) mid-run.
- **Un-bill a Start once it succeeded.** Reject earlier if you want to avoid it.
- **Be your only authorization boundary.** A bypass (a raw start, a direct backend
  call) must still be stopped elsewhere. In the demo the credential is checked at
  three points: the client interceptor rejects before a workflow exists, the startup
  guardrail verifies the signature at the workflow edge, and the backend re-verifies
  on every call. Two of the three need no worker-side interceptor at all.
- **Implement idempotency.** It can propagate an idempotency key, but the
  deduplication lives in the target system. Start deduplication is Temporal's
  workflow-id reuse policy.
- **Invent new categories.** You get the five the SDK exposes.

---

## Demo caveat: the signing secret is in the repo

Worth saying out loud before someone asks, because it is the honest limit of the
demo rather than a flaw in the pattern.

Identity rides in the token's claims — `role` and `group` — and every hop trusts
those claims *because the signature vouches for them*. That is the correct
real-world model: the identity provider holds the signing key, so only the IdP can
mint a license, and any service can authorize locally with no callback.

**Here, the HS256 secret lives in `workflows/auth.py`.** So anyone can sign their
own token claiming `group: premium` or `role: admin`, and every gate will accept it.
"Ted cannot save the future" holds only for the token `/api/login` issued him.

What the demo does get right, and is worth keeping: the thing on the Temporal header
is a **delegation grant**, not the user's session token. Lift it out of Event History
and it is inert — wrong audience for the backend, wrong type for the web app, and
redeemable only by the one named worker.

---

## Demo caveat: the error messages leak on purpose

Book as Evil Bill and the UI says **"that license is forged."** Useful on stage.
Wrong in production.

A precise failure reason is an **oracle** — it turns an attacker's guesswork into a
checklist, telling them which part of a token to fix next. Real systems return one
generic rejection and log the cause.

The right pattern is one file away in the same repo. Both call the same
`rejection_reason()` helper; they differ only in what they disclose:

| | Diagnoses | Tells the caller |
| --- | --- | --- |
| `interceptors/client_auth.py` (demo) | precise reason | **the precise reason** |
| `backend/service.py` (production-shaped) | precise reason | a flat 401 |

The one reason worth surfacing for real is **expiry**: actionable ("log in again"),
and it reveals nothing the token's holder does not already know.

<!--
If asked "why not just always be specific": the oracle argument. If asked "so is the
demo insecure": no, the enforcement is identical; only the message differs.
-->

- This is deliberate: it keeps the demo runnable with no IdP to stand up.
- It is the tradeoff of claim-based identity, not a bug in it. An earlier version
  looked entitlement up in a server-side registry, which blocked self-escalation
  even with the secret — but a registry lookup is **I/O**, so it could never run
  inside the workflow sandbox, and routine user churn would change how in-flight
  runs replay.
- In production: secret in the IdP, verify with a public key or JWKS, and add `exp`
  and `aud`. Note that all three of those are **clock or network** dependent, which
  is exactly why real verification belongs in the client interceptor and the
  backend, not in the sandbox.

---

## Context propagation is its own concept

Temporal lists **Context Propagation** as a distinct extensibility mechanism,
alongside interceptors:

> "pass custom key-value data from a Client to Workflows, and from Workflows to
> Activities and Child Workflows, without threading values through every function
> signature."

- Go and Java expose a dedicated **`ContextPropagator`** interface.
- Python, .NET, and TypeScript implement the same idea **with interceptors plus
  headers** (what the demo does).

So "carry a tenant id or trace id everywhere" is a first-class Temporal use case;
interceptors are how you realize it in several SDKs.

<!-- Source: docs.temporal.io/encyclopedia/context-propagation and the Go/Java propagator guides. -->

---

# Part 4: Reference

---

## Interceptor support across the SDKs

Interceptors are a first-class feature in **every** Temporal SDK, on the same
five-category model.

| SDKs | Coverage |
|---|---|
| Go, Python, .NET, TypeScript | All five categories |
| Java, PHP | All except activity-outbound |
| Ruby | Full; reached general availability recently |
| Rust | In progress; activity-execution interceptors landing in the core |

Extras: TypeScript adds Nexus interceptors; Java adds a Schedule-client
interceptor; PHP adds gRPC and RoadRunner-request interceptors. Naming differs
(`...Interceptor` versus `...CallsInterceptor`), the concept is identical.

**The demo is Python, but the pattern is portable.**

---

## Trace it in the repo

In the order a booking hits them:

| Interceptor (concern) | File (under `workflows/interceptors/`) | Registered in | Triggered by |
|---|---|---|---|
| Client auth | `client_auth.py` | `web/app.py`, `workflows/cli.py` | `POST /api/book` |
| Workflow startup | `workflow_startup.py` | `workflows/worker.py` | start of each `ChronoTripWorkflow` |
| Header propagation | `header_propagation.py` | `workflows/worker.py` | workflow start, then each `execute_activity` |
| Activity logging | `activity_logging.py` | `workflows/worker.py` | `paradox_scan`, `execute_jump` |
| Workflow audit | `workflow_audit.py` | `workflows/worker.py` | `/api/review`, `get_state` polls |

Worker interceptors register together in `Worker(interceptors=[…])`; the client
one in `Client.connect(interceptors=[…])`.

---

## Sources (grounded in Temporal docs)

- Encyclopedia: Interceptors, docs.temporal.io/encyclopedia/interceptors
- Encyclopedia: Context Propagation, docs.temporal.io/encyclopedia/context-propagation
- Encyclopedia: Extensibility, docs.temporal.io/encyclopedia/extensibility
- Python SDK interceptors, docs.temporal.io/develop/python/workers/interceptors
- .NET and TypeScript interceptor guides, docs.temporal.io/develop/{dotnet,typescript}/workers/interceptors
- Tracing and context-propagation guides (Go, Java) and the OpenTelemetry contrib modules

---

## Questions and answers

- Exercise: add an **OpenTelemetry** tracing interceptor and compare it with the
  custom logging one.
- Exercise: extend the startup guardrail to require a **tenant** claim alongside
  `role` and `group`. Keep it replay-safe: read the claim, do not look the tenant up.
- Live demo: book as Bill, force review, **approve** as Rufus (the trip completes),
  and filter the Temporal UI by `Traveler`.
