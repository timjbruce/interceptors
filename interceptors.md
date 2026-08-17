# Interceptors, Types, and how this project uses them

In this discussion, you're going to learn about Temporal Interceptors. This guide is written for someone with a base knowledge of Temporal Clients, Workflows, and Activities.

## Contents
- [Project Scope](#project-scope)
    - [What this demo is about](#what-this-demo-is-about)
    - [Running the demo](#running-the-demo)
- [Pre-requisite Information](#pre-requisite-information)
    - [Temporal terms used in this guide](#temporal-terms-used-in-this-guide)
    - [Headers, arguments, and payloads](#headers-arguments-and-payloads)
    - [How state crosses the inbound/outbound seam](#how-state-crosses-the-inboundoutbound-seam)
    - [JWTs](#jwts)
- [Interceptors Overview](#interceptors-overview)
    - [Interceptors defined](#interceptors-defined)
    - [Why and when should someone use Interceptors?](#why-and-when-should-someone-use-interceptors)
    - [Awesome! So, what can I wrap with Interceptors?](#awesome-so-what-can-i-wrap-with-interceptors)
    - [Building Interceptors](#building-interceptors)
    - [Classes can contain multiple interceptors, or just a single one](#classes-can-contain-multiple-interceptors-or-just-a-single-one)
    - [Registering Interceptors with your Worker and Client](#registering-interceptors-with-your-worker-and-client)
    - [Registering multiple Interceptors](#registering-multiple-interceptors)
    - [Where are Interceptors run and what about Nondeterminism?](#where-are-interceptors-run-and-what-about-nondeterminism)
- [That's all great, but let's see them in action!](#thats-all-great-but-lets-see-them-in-action)
- [The interceptor classes and their categories](#the-interceptor-classes-and-their-categories)
- [Changing an interceptor while workflows are in flight](#changing-an-interceptor-while-workflows-are-in-flight)
- [The six interceptors](#the-six-interceptors)
    - [1. Client interceptor](#1-client-interceptor)
        - [The `get_token` callback: where real I/O earns its place](#the-get_token-callback-where-real-io-earns-its-place)
        - [Do not copy this interceptor's error messages](#do-not-copy-this-interceptors-error-messages)
    - [2. Workflow startup interceptor](#2-workflow-startup-interceptor)
    - [3. Header-propagation interceptor](#3-header-propagation-interceptor)
    - [4. Token-exchange interceptor](#4-token-exchange-interceptor)
    - [5. Activity logging interceptor](#5-activity-logging-interceptor)
    - [6. Workflow inbound interceptor](#6-workflow-inbound-interceptor)
    - [Watching it happen](#watching-it-happen)
- [What happens when an interceptor throws](#what-happens-when-an-interceptor-throws)
- [Auth model: defence in depth with delegation](#auth-model-defence-in-depth-with-delegation)
    - [Four tokens, four jobs](#four-tokens-four-jobs)
    - [Why a grant, and not the user's token, on the header](#why-a-grant-and-not-the-users-token-on-the-header)
    - [What is visible in the Temporal console](#what-is-visible-in-the-temporal-console)
    - [A caveat on the workflow-edge check](#a-caveat-on-the-workflow-edge-check)
    - [Could an activity do the real check instead?](#could-an-activity-do-the-real-check-instead)
    - [Continue-As-New and child workflows](#continue-as-new-and-child-workflows)
- [Business policy vs. business logic](#business-policy-vs-business-logic)
- [Field notes for solutions architects](#field-notes-for-solutions-architects)
    - [Insight 1: inside vs. outside the Workflow sandbox](#insight-1-inside-vs-outside-the-workflow-sandbox)
    - [Insight 2: billable Actions and where you place the check](#insight-2-billable-actions-and-where-you-place-the-check)
    - [What each interceptor can and cannot adjust](#what-each-interceptor-can-and-cannot-adjust)
    - [Insight 3: logging interceptor vs. OTel vs. the Temporal UI](#insight-3-logging-interceptor-vs-otel-vs-the-temporal-ui)
    - [Broader patterns](#broader-patterns)
    - [What are Interceptors not?](#what-are-interceptors-not)
- [References](#references)

---
## Project Scope

### What this demo is about

**Wyld Stallyns Time Travel** is a phone-booth time-travel booking service. A traveller books a trip; a backend service scans it for paradox risk; risky trips wait for an administrator to approve or reject them; approved trips complete. The business logic is deliberately small, because the point is everything wrapped around it, the Interceptors.

The cast, which the rest of this document refers to freely:

| Name | Who they are |
| --- | --- |
| **Bill** and **Ted** | travellers who book trips. Bill is `premium`, Ted is `standard` |
| **Rufus** | the administrator, who approves or rejects flagged trips |
| **Evil Bill** and **Evil Ted** | robot doubles carrying forged licences, so you can watch a forgery get caught |
| **Circuits of History** | the in-world name for the system, so a "Circuits of History license" is just this demo's JWT |
| **a trip** | one workflow execution |

The time travel phone booth is built on a Temporal Workflow that uses Interceptors. Interceptors are middleware that can be registered with Temporal Clients and Workers to cover use-cases  such as common utilities or business policies that cross the Client, Workflow, Activities, and other Temporal primitives. Interceptors allow you to take your business' "glue code" and encapsulate it outside of your workflow and activities. Your "glue code" may be related to auditing, logging, security, or business policy. Interceptors enable reuse within and across workflows by being separate from your main workflow and activity code. Interceptors also allows your workflows and activities to remain focused on the business problem that they are trying to solve.

### Running the demo

Run each of the below processes in its own terminal to start the demo. The client can then be opened at <http://localhost:8000>. More information can be found in the project [README](README.md). In four terminals, with the terminal in the comment:

```bash
temporal server start-dev     # 1. local Temporal server
./addsearchattributes.sh      # Run it once in Terminal 2 before running backend
./runbackend.sh               # 2. the JWT-authorized backend, and the token endpoint (:9000)
./runworkflow.sh              # 3. the worker, where five of the six interceptors in this demo run
./runweb.sh                   # 4. the web client (:8000)
```

### What this demo is NOT about

This Interceptor guide and the demo are not meant to be a discourse in security or Python. Some data about both are covered, and each of these can topics can extend well beyond the scope of this document and repository.

Additionally, code snippets are provided as a way of displaying the concepts and are not meant to be complete, runnable code. Code in the repository is runnable and the snippets are taken from them.

## Pre-requisite Information

### Temporal terms used in this guide

Assumed Temporal knowledge, not covered in this document includes Workflows, Activities, Workers, Task Queues, Priority and Fairness, and Signals, Queries, and Updates (the three kinds of message you can send a running workflow). See the [Temporal 101 course](https://learn.temporal.io/courses/temporal_101/python/) to start building knowledge about Temporal.

**Replay.** When a workflow needs to resume, it re-runs your workflow code from the beginning, feeding it the recorded results of everything that already happened instead of redoing that work. This process is referred to as replay. Your workflow code must be deterministic: that is, given the same history it has to make the same decisions/have the same outcomes. If it does not, the code cannot replay due to what is termed a "non-deterministic error" or NDE. See <https://docs.temporal.io/workflows#how-workflow-replay-works>.

**Event History.** The ordered log of everything that has happened in a workflow, and the source of truth replay reads from. It is durable, replicated, readable by anyone with namespace read access, and **not redactable**. Anything you put on a workflow header ends up here permanently, which turns out to drive several design decisions in this project.

**The Workflow Sandbox.** In Python, workflow code runs in an isolated environment that re-imports your workflow file per run and blocks many known-nondeterministic calls. The sandbox is a safety net, not a guarantee. Temporal describes it as "not completely isoldated". See <https://docs.temporal.io/develop/python/best-practices/python-sdk-sandbox>.

### Headers and arguments

A Temporal header is a map of key/value metadata attached to the workflow, just like web-based headers. Just like web-based requests, this is to separate information about the requestor (using headers) versus information for the request itself (arguments). Just like your workflow arguments, header data is persisted in Event History. This separation of responsiblity helps to keep your code cleaner, specifically your function signatures can focus on the business elements of your work.

As a note, headers are also attached to activities, child workflows, signals, queries, and updates. However, headers are not automatically passed on from a workflow to these primitives.

<TODO: Review>
### How state crosses the inbound/outbound seam

Headers move data *between* processes. Something else is needed to move it between two hooks in the same process — because an interceptor's inbound half and its outbound half are separate methods, called at different moments, with no shared arguments. An inbound hook reads the header once; the outbound hook has to stamp that value onto every activity the workflow schedules, possibly minutes later.

In Python that carrier is a **contextvar**: a variable whose value is scoped to the current execution rather than shared globally, from the standard library's [`contextvars`](https://docs.python.org/3/library/contextvars.html). Inbound calls `.set()`, outbound calls `.get()`. This demo has two, `current_grant` and `correlation_id`.

The question that decides whether this is safe: **one worker runs many workflows and activities at once — can they see each other's values?** In Python the answer differs for the two, and it is worth knowing which is which:

- **Activities are isolated.** Each activity task is started with `asyncio.create_task`, and asyncio gives every task its own copy of the context, so a `.set()` inside one attempt is invisible to every other attempt running beside it. Sync activities that run in a thread pool are covered too — the SDK explicitly copies the context across into the executor thread.
- **Workflows are not, and you must not assume they are.** Workflow activations are dispatched to a shared thread pool, and the SDK does not give each workflow instance its own context. A value left behind by one workflow's activation can still be present when a *different* workflow activates on that same thread.

Hence the rule every hook in this demo follows, and the reason for the repeated `# always set (reset), even to None` comments: **set the contextvar unconditionally on every inbound call, even when there is nothing to set.** A header-less run must overwrite the previous value rather than inherit it. Reading a stale grant from a previous execution would be an identity leak, not a cosmetic bug.

Other SDKs solve the same problem with their own primitive, so this is the piece to translate first when porting:

| SDK | Carrier |
| --- | --- |
| Go | values on the `workflow.Context` every workflow function already receives — `func WithValue(parent Context, key interface{}, val interface{}) Context`, read back with `ctx.Value(key)` |
| Java | `WorkflowLocal<T>` — "a value that is local to a single workflow execution", so the isolation Python leaves to you is built in |
| TypeScript | workflow interceptors "run in the Workflow isolate", which is where their shared state lives — see the [TypeScript interceptor guide](https://docs.temporal.io/develop/typescript/interceptors) |

### JWTs

This demo uses JWTs, or JSON Web Tokens. JWTs are a compact, URL-safe way to securely transmit information between a client and a server as a JSON object. Token information can be trusted because the JWT is digitally signed using a secret key or a public/private key pair. JWTs are typically issued by trusted authentication servers when users authenticate. The user's browser, or other client, stores this token and uses it to prove their identity to services that trust it. When making requests, JWTs are typically sent as a header using `Authorization: Bearer <your_jwt_token_here>` or as a cookie from the client to any backend services. JWTs also carry an expiration and must be renewed periodically, as credentials could be revoked and you would want to validate the person should have a token.

A key note about this demo is that it uses simulated JWTs by generating them directly for users and the backend services. In a real production system, you would have something like Active Directory, Microsoft Entra ID, or Okta act as the authentication endpoint and JWT dispenser. The simulation dispenses tokens via the web backend, which allows clients to get and refresh tokens. This approach would not be used or recommended as a secure solution.

Many enterprises use JWTs to support single-signon to services for users. Looking deeper at enterprise services that use JWTs, many do so for auditing capability, specifically to note which users used the system and took what actions. To accomplish this, Temporal workers in this demo act as or on behalf of users, which will require the ability to pass the user's permissions from their client to the Temporal workflow. The Temporal worker in this demo exchanges the user JWT for it's own token to pass to downstream systems to show `<worker> taking action on behalf of <user>`, where user is the person making the request and worker is the activity. To do this, the client interceptor creates a delegation grant and passes that as the header. This is part of [RFC 8693](https://datatracker.ietf.org/doc/html/rfc8693) and is discussed more in the [Client Interceptor](#1-client-interceptor) section below.

JWTs have a number of fields, called claims, that carry state about the token and the user. The tokens this demo uses include:

| Claim | Meaning here |
| --- | --- |
| `sub` | the subject: which user the token is about |
| `role` | `traveler` or `admin` |
| `group` | `standard` or `premium`, which drives mission entitlement |
| `exp` | expiry |
| `aud` | audience: which service is allowed to accept this token |
| `token_use` | which of this demo's four token types it is, so one cannot be mistaken for another |
| `act` | the actor who is acting on behalf of `sub`. This is what makes delegation visible |
| `may_act` | which workload is permitted to act for `sub` |

Note that checking the expiration of the token is not done in this demo in the workflow. Expired tokens must be refreshed at the client side before being sent to the workflow. If an expired token does reach the backend, it will error out with an expired token.

## Interceptors Overview

This section covers Interceptors in general, helping to describe what they are, when and how they are used.

## Interceptors defined

Interceptors are Temporal's middleware that wrap inbound and outbound Temporal calls. They allow cross-cutting concerns to live in one place in your code instead of you copying code into and across your clients, workflows, and activities.

Temporal, in general, allows developers to focus on business logic instead of having to worry about things like retry/backoff logic, persistence, queues, timers, etc. This doesn't mean that all the code you need to write is related to your workflow and activities. Sometimes, you need to store and pass user tokens, provide an audit trail in your workflow, or maybe keep a history of all the retries across all of your activities. How do you handle these requirements without duplicating code all over the place, causing yourself a maintenance nightmare while making your business process / workflow harder to read, review, and update?

The answer is Interceptors. Interceptors allow developers to take their business' glue code for requirements like auditing, security, and idempotency key / context passing, and wrap it around Client, Workflow, Activity, and Nexus calls so they can further focus on business logic instead of having to copy and paste code for all of these concerns throughout their project.

## What are Interceptors not?

There are a few good notes to remmeber about Interceptors while reviewing this. First, an interceptor is not a billable Action by itself. It can trigger billable actions, such as scheduling a workflow or activity or upserting search attributes. Second, Interceptors do not reduce actions by themselves, but they can help customers with meantime to recovery (MTTR) and help optimize surfaces by tracking what actions have the most retries.

Do not use interceptors if it is for only one workflow or activity. Also, activity interceptors are meant to perform the same logic for every activity. If that changes, the call then belongs in the activity.

## Why and when should someone use Interceptors?

Interceptors should be used when you have cross-cutting requirements, that is, requirements that need to be handled in many places in your workflow or by a number of activities. Without Interceptors, cross-cutting requirements would require you to copy and paste code (or re-type it, if you must!) in many parts of their workflow or in multiple activities. This causes maintenance issues. If you see the same code across your activities and/or workflow, there's a good chance that you should look into Interceptors.

An example of a cross-cutting requirement is passing a correlation id to your workflow and all of its activities. Correlation ids can help you correlate specific workflow and activity log entries in your log files and tie all of the logs back to a single run of your workflow. Without Interceptors, this correlation id would need to be added to each activity, signal, query, update, and other types of Temporal calls. Basically, anywhere you might log data, you would need this trade id available. Yes, you could pass this as a part of data to each call, but this can cause code maintenance issues and may be missed by another developer adding a new activity or signal handler.

With interceptors, you don't need to worry about the correlation id at all in your workflow or activities. The interceptors for the workflow and its activities, once registered, can handle the passing of data. You can then focus on your workflow and activity logic and utilize the correlation id as you need it.

## Awesome! So, what can I wrap with Interceptors?

There are 2 types of Temporal Interceptors, Inbound and Outbound. These break into 7 categories of Interceptors, which are all listed in the table below:

| Type | Category | Partial list of SDK calls wrapped |
| --- | --- | --- |
| Inbound | Workflow | `execute_workflow`, `handle_signal`, `handle_query`, and two update hooks: `handle_update_validator` (sync, must not block) and `handle_update_handler` |
| Inbound | Activity | `execute_activity` |
| Outbound | Client | `start_workflow`, `signal_workflow`, `query_workflow`, `cancel_workflow`, and the rest of the client surface |
| Outbound | Workflow | `start_activity`, `start_local_activity`, `start_child_workflow`, `signal_child_workflow`, `signal_external_workflow`, `continue_as_new`, `info` |
| Outbound | Activity | `heartbeat` and `info` only |
| Inbound | Nexus | `StartOperation`, `CancelOperation` |
| Outbound | Nexus | `GetOperationInfo`, `GetClient`, `GetLogger` |

Inbound and Outbound are directions from your Workflow and Activity code. Inbound will run before your Workflow and Activity code and Outbound will run when your Workflow or Activity make an SDK call.

When you code your interceptors, you define the category of the interceptor and the Temporal events you want to intercept and run your own code. Details of this will follow in [Building Interceptors](#building-interceptors) below. The type is based on the implementation, as you will see later in this guide.

*A small note:* Not all the SDKs have equal implementations of Interceptors. This is especially true for the Nexus Outbound Interceptors, which are currently experimental and in the Go, and Typescript SDKs.

## Building Interceptors

Interceptors are code and are built by extending classes that are exposed in the Temporal SDK. The table below is for Python, which is what the demo project is written in. Go, Java, TypeScript and .NET all expose the same five categories used in this demo and the same wrap-the-next-call shape, but the class names and the registration API differ, so check your own SDK's interceptor guide before porting anything here. What does *not* transfer unexamined: the outbound-installed-from-inbound trick, and the class-not-instance constraint below, are Python specifics. The classes and types are listed in the table below.

| Category | Type | Base class you extend | How it gets installed |
| --- | --- | --- | --- |
| Client | Outbound | `client.OutboundInterceptor` | returned from `client.Interceptor.intercept_client(next)` |
| Workflow | Inbound | `worker.WorkflowInboundInterceptor` | the class is returned from `worker.Interceptor.workflow_interceptor_class(input)` |
| Workflow | Outbound | `worker.WorkflowOutboundInterceptor` | installed from the workflow inbound's `init(outbound)` |
| Activity | Inbound | `worker.ActivityInboundInterceptor` | returned from `worker.Interceptor.intercept_activity(next)` |
| Activity | Outbound | `worker.ActivityOutboundInterceptor` | installed from the activity inbound's `init(outbound)` |
| Nexus | Inbound | `worker.NexusOperationInboundInterceptor` | returned from `worker.Interceptor.intercept_nexus_operation(next)` |
| Nexus | Outbound| n/a | n/a |

Temporal's Interceptor API is a small factory pattern:
- A workflow interceptor subclasses `worker.Interceptor` and returns the `WorkflowInboundInterceptor` class from `workflow_interceptor_class(...)`. The WorkflowOutboundInterceptor is installed from the InboundInterceptor's `init()`.
- An activity interceptor subclasses `worker.Interceptor` and returns an `ActivityInboundInterceptor` from `intercept_activity(next)`. The ActivityOutboundInterceptor is installed from the InboundInterceptor's `init()`.
- The client interceptor subclasses `client.Interceptor` and returns an `OutboundInterceptor` from `intercept_client(next)`. There is no client inbound interceptor.

The return type is a class that has methods that can be called to "intercept" the Temporal call. For example, if you want to intercept the Start Workflow method in python, you would define a method of `start_workflow` in your implementation class with code to execute upon starting the workflow. At the end of the method, your code should call `super()` or `self.next` to pass control to the chain of code execution back to Temporal. If you don't call either, the call will not reach Temporal and your workflow will be stuck. The table below can be used as a guide.

| Type of Interceptor | Call to delegate** |
| --- | --- |
| `WorkflowInboundInterceptor` / `WorkflowOutboundInterceptor` | `super().same_method(input)` or `self.next.same_method(input)` |
| `ActivityInboundInterceptor` / `ActivityOutboundInterceptor` | `super().same_method(input)` or `self.next.same_method(input)` |
| `client.OutboundInterceptor` | `super().same_method(input)`  or `self.next.same_method(input)` |

**A note about outbound calls**: Calls to info() for outbound interceptors take no arguments. Calls to heartbeat() take varargs.

*Note:* `super()` works everywhere in this demo project and will probably work for most use cases.

If you do not define a method to intercept, the default behaviour is a pass-through.

If you don't call `super()`, the subsequent operations do not get called including your workflow or activity. This is one way to short-circuit a call.

<TODO: Review>
An partial example Interceptor might look like this in Python. The `correlation_id.set(...)` and `.get()` calls in it are the contextvar handoff described in [How state crosses the inbound/outbound seam](#how-state-crosses-the-inboundoutbound-seam) — the inbound hook stores the value, the outbound hook reads it back to stamp onto each activity, and it is set unconditionally so a run never inherits the previous workflow's id:

```python
class WorkflowStartupInterceptor(Interceptor):
    """Worker interceptor: start-of-workflow tagging, guardrail, correlation."""

    def workflow_interceptor_class(
        self, input: WorkflowInterceptorClassInput
    ) -> Optional[Type[WorkflowInboundInterceptor]]:
        return _StartupWorkflowInbound

    def intercept_activity(self, next: ActivityInboundInterceptor) -> ActivityInboundInterceptor:
        return _StartupActivityInbound(next)


class _StartupWorkflowInbound(WorkflowInboundInterceptor):
    def init(self, outbound: WorkflowOutboundInterceptor) -> None:
        super().init(_StartupWorkflowOutbound(outbound))

    async def execute_workflow(self, input: ExecuteWorkflowInput) -> Any:
        # (1) Correlation id: from the header if present, else deterministic from
        # the run id (stable across replays). Set first so the verification activity
        # scheduled below already logs under it. Propagated to activities by the
        # outbound hook.
        cpayload = (input.headers or {}).get(CORRELATION_HEADER_KEY)
        cid = workflow.payload_converter().from_payload(cpayload, str) if cpayload is not None else None
        cid = cid or f"cot-{workflow.info().run_id[:8]}"
        correlation_id.set(cid)

        # (2) Guardrail. Read the grant off the start header and hand it to an
        # ACTIVITY to be verified — see this module's docstring and
        # `activities.py` for why the check cannot honestly happen in here.
        #
        # The grant reaches the activity on its HEADER, like every other activity in
        # this demo, so `verify_grant` reads it the same way the rest of the worker
        # does. We stamp it ourselves, for this one call only: the grant-propagation
        # interceptor is registered *after* this one, so its inbound half has not run
        # yet and `current_grant` is still empty at this point in the chain.
        self._outbound.grant_for_next_activity = grant
        try:
            check = await workflow.execute_activity(
                verify_grant,
                start_to_close_timeout=_VERIFY_TIMEOUT,
                retry_policy=_VERIFY_RETRY,
            )

        # A missing, malformed, forged, EXPIRED, or wrong-type grant -> fail fast,
        # before any business activity. Catches a raw `temporal workflow start`
        # bypass at the workflow edge, and anything tampered with after the client.
        # Raising here (rather than in the activity) keeps the failure the workflow
        # closes with a single non-retryable ApplicationError instead of an activity
        # failure wrapping one. The message stays generic; `check.reason` is logged.
        if not check.valid:
            workflow.logger.warning(
                "[interceptor:startup] rejected trip start: %s [correlation_id=%s]",
                check.reason,
                cid,
            )
            raise ApplicationError(
                "Bogus! This trip has no valid Circuits of History delegation grant on its header.",
                type="InvalidDelegationGrant",
                non_retryable=True,
            )

        # (3) Tag the execution so trips are filterable by traveler and mission.
        # Use the traveler's display name (proper caps, as shown in the UI), not
        # the short lowercase id, so the search attribute reads the same everywhere.
        mission = getattr(input.args[0], "mission", "") if input.args else ""
        workflow.upsert_search_attributes(
            [
                TRAVELER_SA.value_set(check.traveler_name),
                MISSION_SA.value_set(mission or "(none)"),
            ]
        )

        workflow.logger.info(
            "[interceptor:startup] trip start: traveler=%s mission=%s correlation_id=%s",
            check.traveler_name,
            mission or "(none)",
            cid,
        )
        return await super().execute_workflow(input)
```

This Interceptor is defined for a Workflow and would intercept calls for `execute_workflow`. This interceptor wraps `execute_workflow`, so it runs once at the start of every trip and again on every replay. The interceptor reads the delegation grant off the start header and hands it to the `verify_grant` activity, which checks signature, token type, audience and expiry out on the worker where wall clocks are available. The interceptor acts on the activity results and raises a non-retryable `InvalidDelegationGrant` if the grant is bad. Else, it calls`super().execute_workflow(input)` to pass control on to the workflow itself.

In this case, if there is no token or the shape of the token is not correct, this interceptor throws a non-retryable error. This is good, as without the token, downstream activities might fail and be retried. By taking this action early, you would prevent a number of actions from being called.

## Other SDK classes for interceptors

The categories of interceptors in this demo exist in the major SDKs. The names and registration methods also differ. This table is offered as a translation key and was verified against each SDK's own API reference. Additionally, the scope of the Inteceptors is not equal across SDKs.

| Category | Go — `go.temporal.io/sdk/interceptor` | Java — `io.temporal.common.interceptors` | TypeScript | .NET |
| --- | --- | --- | --- | --- |
| Client outbound | `ClientOutboundInterceptor` | `WorkflowClientCallsInterceptor` | `WorkflowClientInterceptor` | `ClientOutboundInterceptor` |
| Workflow inbound | `WorkflowInboundInterceptor` | `WorkflowInboundCallsInterceptor` | `WorkflowInboundCallsInterceptor` | `WorkflowInboundInterceptor` |
| Workflow outbound | `WorkflowOutboundInterceptor` | `WorkflowOutboundCallsInterceptor` | `WorkflowOutboundCallsInterceptor` | `WorkflowOutboundInterceptor` |
| Activity inbound | `ActivityInboundInterceptor` | `ActivityInboundCallsInterceptor` | `ActivityInboundCallsInterceptor` | `ActivityInboundInterceptor` |
| Activity outbound | `ActivityOutboundInterceptor` | via `ActivityExecutionContext` | `ActivityOutboundCallsInterceptor` | `ActivityOutboundInterceptor` |
| Nexus outbound | `NexusOperationOutboundInterceptor`,  `ClientOutboundInterceptor`| - | `NexusOutboundCallsInterceptor` | - | 
| Nexus inbound | `NexusOperationInboundInterceptor` | - | `NexusInboundCallsInterceptor` | - |
| The entry point you register | `WorkerInterceptor`, `ClientInterceptor` | `WorkerInterceptor`, `WorkflowClientInterceptor` | factory functions | `IWorkerInterceptor`, `IClientInterceptor` |


How each one is registered:

| SDK | Worker side | Client side |
| --- | --- | --- |
| Go | `worker.Options{Interceptors: []interceptor.WorkerInterceptor{…}}` | `client.Options` |
| Java | `WorkerFactoryOptions.Builder.setWorkerInterceptors(WorkerInterceptor…)` | `WorkflowClientOptions.Builder.setInterceptors(WorkflowClientInterceptor…)` |
| TypeScript | `WorkerOptions.interceptors.activity`, `WorkerOptions.interceptors.workflowModules` | `ClientOptions.interceptors` |
| .NET | `TemporalWorkerOptions.Interceptors` (`IReadOnlyCollection<IWorkerInterceptor>?`) | `TemporalClientOptions.Interceptors` |

The Interceptor implementations for other SDKs may be different than the ones discussed for Python in this guide. This guide is not meant to call out these differences and you should refer to the documetation for your runtime.

Sources: [Go](https://pkg.go.dev/go.temporal.io/sdk/interceptor) ·
[Java](https://javadoc.io/doc/io.temporal/temporal-sdk/latest/io/temporal/common/interceptors/package-summary.html) ·
[TypeScript](https://docs.temporal.io/develop/typescript/interceptors) ·
[.NET](https://dotnet.temporal.io/api/Temporalio.Worker.Interceptors.html)

## Classes can contain multiple interceptors, or just a single one

There might be cases where you want to have the same class contain multiple interceptors, for instance covering both workflows and activities. An example of this could be the handling of a correlation id. Correlation ids are often used in distributed systems logging so that operators and developers can match log entries for different systems and activities to a specific transaction. Building separate classes for each of the interceptors, in this case, could increase your maintenance if you change how your correlation ids are defined or the format of them. Sharing the logic in a single class helps to reduce maintenance overhead. The below snipped of interceptor is defined for both the workflow (inbound for `execute_workflow` and outbound for `start_activity` actions) and activities (inbound for `execute_activity` action). More details can be found in the actual project.

```python
class WorkflowStartupInterceptor(Interceptor):
    """Worker interceptor: start-of-workflow correlation."""

    def workflow_interceptor_class(
        self, input: WorkflowInterceptorClassInput
    ) -> Optional[Type[WorkflowInboundInterceptor]]:
        return _StartupWorkflowInbound

    def intercept_activity(self, next: ActivityInboundInterceptor) -> ActivityInboundInterceptor:
        return _StartupActivityInbound(next)


class _StartupWorkflowInbound(WorkflowInboundInterceptor):
    def init(self, outbound: WorkflowOutboundInterceptor) -> None:
        super().init(_StartupWorkflowOutbound(outbound))

    async def execute_workflow(self, input: ExecuteWorkflowInput) -> Any:
        # Correlation id: from the header if present, else deterministic from
        # the run id (stable across replays). Propagated to activities below.
        cpayload = (input.headers or {}).get(CORRELATION_HEADER_KEY)
        cid = workflow.payload_converter().from_payload(cpayload, str) if cpayload is not None else None
        cid = cid or f"cot-{workflow.info().run_id[:8]}"
        correlation_id.set(cid)

        workflow.logger.info(
            "[interceptor:startup] trip start: correlation_id=%s",
            cid,
        )
        return await super().execute_workflow(input)


class _StartupWorkflowOutbound(WorkflowOutboundInterceptor):
    def start_activity(self, input: StartActivityInput):
        cid = correlation_id.get()
        if cid is not None:
            input.headers = {
                **(input.headers or {}),
                CORRELATION_HEADER_KEY: workflow.payload_converter().to_payload(cid),
            }
        return super().start_activity(input)


class _StartupActivityInbound(ActivityInboundInterceptor):
    async def execute_activity(self, input: ExecuteActivityInput) -> Any:
        payload = (input.headers or {}).get(CORRELATION_HEADER_KEY)
        cid = (
            temporalio.converter.default().payload_converter.from_payload(payload, str)
            if payload is not None
            else None
        )
        correlation_id.set(cid)  # always set (reset), even to None
        return await super().execute_activity(input)
```

You will want to consider if and when you should combine different requirements and use cases into a single class for an interceptor even when the logic needs to be executed during a single SDK call. The choice is truly a design, performance, and maintenance choice and is left to the developer.

## Registering Interceptors with your Worker and Client

You register Interceptors in two places. The worker list is where the workflow and activity interceptors are registered. The below case shows a single interceptor registered on a worker.

```python
# Worker-side interceptors. First in the list is outermost.
Worker(client, task_queue=..., workflows=[...], activities=[...],
       interceptors=[
           WorkflowStartupInterceptor(),
       ])
```

You register client interceptors in the Client.connect. The below case shows a single interceptor registered on a client.

```python
# Client-side interceptor. First in the list is outermost.
Client.connect(..., interceptors=[JWTClientInterceptor(get_token=get_token)])
```

## Registering multiple Interceptors

You may want to include multiple interceptors for your projects. This is useful in cases where you have multiple requirements and don't want to combine the logic for many interceptors into a single class.

```python
# Worker-side interceptors. First in the list is outermost.
Worker(client, task_queue=..., workflows=[...], activities=[...],
       interceptors=[
           WorkflowStartupInterceptor(),
           ActivityLoggingInterceptor(),
           WorkflowAuditInterceptor(),
           GrantPropagationInterceptor(),
           TokenExchangeInterceptor(),
       ])
```

Order matters when registering interceptors. They form a nested chain and always execute **outermost to innermost**, each one delegating inward until the call reaches the real Temporal implementation. First in the list is outermost. On the **worker** chain the nesting then inverts for outbound calls, so inbound and outbound traverse the same chain in opposite registration order. The **client** chain has no inbound half, so nothing inverts and the first interceptor registered is outermost.

In the above example, `WorkflowStartupInterceptor`, `WorkflowAuditInterceptor`, and `GrantPropagationInterceptor` are all Workflow Interceptors. On **inbound** events they fire as `WorkflowStartupInterceptor` -> `WorkflowAuditInterceptor` -> `GrantPropagationInterceptor`. On **outbound** events the order reverses. Note that only classes that actually install an outbound half appear in the outbound chain: `WorkflowAuditInterceptor` has no outbound interceptor, so the outbound order is is `GrantPropagationInterceptor` -> `WorkflowStartupInterceptor`.

The inversion of interceptors is not a rule you have to remember, it simply falls out of how an outbound interceptor gets installed. An outbound interceptor can only be created by an inbound one, in its `init()`, wrapping the outbound object it was handed. The SDK walks the inbound chain from outermost inward, so each interceptor wraps the outbound object after the one outside it. Whoever is innermost on the way in therefore wraps last and wrapping last means being outermost on the way out.

There are cases where the inbound or outbound chain can be altered. In the example above for the WorkflowStartupInterceptor, it schedules an activity and throws an error if the token is missing. If there are additional inbound interceptors, they would be skipped due to the error. Remember, the interceptor and activity first checks for a key piece of data and can throw a non-retryable error before proceeding with any other code. This ordering is on purpose so that the first interceptor can stop addditional code from running and saves resources (compute/worker time).

## Where are Interceptors run and what about Nondeterminism?

Knowing where Interceptors run will help you with what they can do safely. The answer to the question depends on the category of the Interceptors. It's important to note each Interceptor inherits its constraints from where it sits. Two of the five categories in this demo run inside the sandbox and will re-run on replay.

| Category | Runs on | Sandbox? | Re-runs on replay? |
| --- | --- | --- | --- |
| Client (outbound) | your app process | outside - the starting client | no |
| Activity inbound / outbound | worker (activity context) | outside | no |
| Workflow inbound / outbound | worker (workflow sandbox) | inside | yes |

The same rules for determinism apply for Interceptors running within the workflow sandbox: no I/O, no wall clock, no unguarded randomness. Because the workflow interceptors fire on replay, you may run into nondeterministic errors (NDEs) on replay if you have any randomness in your process.

### Continue-As-New and child workflows

Continue-As-New starts a new Workflow Execution with a new Event History. Likewise, anything you want to include to the continued workflow needs to be added to the `continue_as_new` call, which is a workflow-outbound wrapper. Otherwise, your new execution will not have access to whatever headers your initial workflow had access to.

Child workflows get whatever headers are included from the `start_child_workflow` outbound wrapper. If you want to propogate headers to children, you will need to implement this, as it is not automatically done.

## Versioning and changes to Interceptors

Interceptors run with your workflow and activities. As such, you should think about a versioning strategy. This is especially true for workflow interceptors, since they can run on replay of long-running workflows. It is recommended to adopt the same approach you use for workflow patching (versioning or patching) with your workflow interceptors.

For activity interceptors, be aware of what you are changing and consider worker versioning if you are are updating anything that may introduce errors or require new data from the workflow.

## Interceptors and Errors

Interceptor errors behave exactly like the category errors (Client, Workflow, and Activity). Client interceptor errors mean that workflow start is never sent to Temporal, as it happens in the client. Workflow interceptor errors can be non-retryable or just fail the task and leave the workflow open (error). Activity interceptor errors can be retryable, based on the retry policy of the activity or are non-retryable if marked so.

### Data visibility in the Temporal UI

Because the grant rides as a header, its value is recorded in Event History and visible to any admin in the Temporal Web UI. That is useful proof the chain reached Temporal in this demo, but it can be a risk for customers who might share secrets or other data they would like to keep private via the headers.

You can encode the headers, but it does require an extra step from just using the standard CODEC in connection. To encode all headers, the code would look similar to the following:

```python
client = await Client.connect(
    "localhost:7233",
    data_converter=dataclasses.replace(
        temporalio.converter.default(),
        payload_codec=EncryptionCodec()
    ),
    header_codec_behavior=HeaderCodecBehavior.CODEC
)
```

You can read more about the header codec behavior in the [Temporal Python SDK Documentation](https://python.temporal.io/temporalio.client.HeaderCodecBehavior.html).

## That's all great, but let's see them in action!

Let's get on with it!

## The interceptor classes and their categories

This section introduces the interceptors that are built for this project, the reason the interceptor was built, and the structure that was used to build them. You could rebuild this demo with a different number of classes, as was called out in the section on [combining interceptors in one class](#classes-can-contain-multiple-interceptors-or-just-a-single-one). This demo fills four of the seven (again, this project does not cover Nexus Interceptors at this time) categories with six classes.

| Reason the interceptor exists | Class | Categories it occupies |
| --- | --- | --- |
| Authenticate the traveler, authorize the mission, and mint the delegation grant before a workflow is ever started | `JWTClientInterceptor` | Client outbound |
| Seed a correlation id, guard the workflow edge, and tag the run for search | `WorkflowStartupInterceptor` | Workflow inbound + outbound, Activity inbound |
| Carry the delegation grant from the workflow down to each of its activities | `GrantPropagationInterceptor` | Workflow inbound + outbound, Activity inbound |
| Redeem that grant for a short-lived credential, once per activity attempt | `TokenExchangeInterceptor` | Activity inbound |
| Log a uniform start, duration, and outcome around every activity | `ActivityLoggingInterceptor` | Activity inbound |
| Audit every signal and query that arrives at a running workflow | `WorkflowAuditInterceptor` | Workflow inbound |
| *(nothing in this demo heartbeats, so no class is needed)* | *none* | Activity outbound |

A single class often occupies several categories, and that is not the same as being several interceptors. `GrantPropagationInterceptor` spans three categories: a workflow inbound to read the grant off the start header, a workflow outbound to write it onto each scheduled activity, and an activity-inbound that publishes the same grant into `current_grant` which becomes available for any activity or downstream interceptor to use.

Activity inbound is the busiest category here, with four classes in it. That is because it runs on the worker and outside the sandbox. Anything needing a clock or a network call ends up on activity inbound, which is why both the timing and the credential-exchange concerns landed there.

Activity outbound is the one category left empty. It wraps only an activity's `heartbeat` and `info` calls. Nothing in this demo uses heartbeats and the info() use case is not implemented in this demo.

## The six interceptors

This section introduces the six classes used in this demo, in the order they run as you book a time-travel trip. Each one is presented the same way: why a customer would care, what fires it, what it does, what you will see when it runs, code location, and any way to trigger it from outside the demo app.

Each overview also includes other use cases for the type of interceptor. This is meant to provide ideas for projects.

### 1. Client interceptor

*Category: Client (outbound). Runs in your process, outside the sandbox, before the request leaves. This is the demo's first authorization point.*

- **Why a customer would care:** downstream systems sometimes need a verifiable credential to authorize an action and to record which user or service took it. A signed token is proof of identity those systems can validate themselves, whereas a name or id sitting in an ordinary business field is an unverified, mutable claim. If the user does not have proper permissions, rejecting the workflow here will prevent a number of billable actions from occurring and saves the customer money. More info can be found in [Insight 2](#insight-2-billable-actions-and-where-you-place-the-check) below.
- **What fires it:** clicking "Fire up the booth" in the web client, which posts to `/api/book` and calls `start_workflow`.
- **What it does:** In order, it performs 3 steps. First, it **authenticates** the token, including expiry, because out here a clock is legal. Second, it **authorizes** the request against business entitlements, since some missions are premium-only. Third, it **mints a delegation grant** and stamps that onto the Temporal header. A missing, forged, unrefreshable, or unentitled request is rejected before the workflow starts.
- **What you will see when it runs:** valid and entitled requests proceed, and bad ones return a `BOGUS!` result immediately with no workflow started. This demo shares the specific fault as a way of showing the failure from the client interceptor ("that license is forged", "expired", "log in first") and is not a best practice to follow. Production systems should only state that the authentication/authorization has failed and not why.
- **Code location:** [`workflows/interceptors/client_auth.py`](workflows/interceptors/client_auth.py).
- **Triggering it outside the demo app:** `.venv/bin/python -m workflows.cli` runs the same client interceptor. It builds its Temporal client the same way. The Temporal CLI has no way to load your client interceptor directly.
- **Other use cases:** per-tenant routing, context and correlation-id propagation, and request de-duplication. Anything that has to happen once per request, before the server is involved.

#### Do not copy this interceptor's error messages

The error messsages in this demo tell the caller which check failed, including that a license was forged. Authentication/authorization systems should never respond in such a way. This messaging is only for the demo to show that it caught the forgery is the entire point of the Evil Bill and Evil Ted personas, and a generic "invalid license" would hide the thing you came to see.

### 2. Workflow startup interceptor

*Category: Workflow inbound + outbound (sandbox) and Activity inbound (worker). Runs at workflow start and is replay-safe. "At start" means once per run and again at replay. Because of this, it must stay deterministic.*

- **Why a customer would care:** this is operational hygiene that belongs off to the side of business logic. A customer can get searchable executions, evaluate boundary preconditions, and generate correlated logs are applied to every workflow without a line of code for these itesm appearing in the workflow itself. It is also an inexpensive place for a customer to stop a workflow that should never have started.
- **What fires it:** booking a trip from the web client starts `ChronoTripWorkflow`, and the interceptor runs at `execute_workflow` before any workflow code. Its outbound and activity wrapper fires as the workflow schedules each activity.
- **What it does:** it seeds a **correlation id** from the header, or deterministically from the run id, then propagates it to activities so their log lines tie back to the trip. Next, it applies a **guardrail** via an activity, verifying the grant on the start header and failing fast with a non-retryable `InvalidDelegationGrant` error if it is missing, malformed, forged, or the wrong type. Finally, it **adds search attributes** for Traveler and Mission, making trips filterable in the UI and CLI without touching the workflow body.
- **What you will see:** a `[interceptor:startup] trip start: traveler=... mission=... correlation_id=...` line at the start of each trip, the same `correlation_id` on the activity log lines, and `Traveler` and `Mission` visible on the workflow in the Temporal UI. A start with no grant, or with a forged one, fails immediately with `InvalidDelegationGrant`.
- **Code location:** [`workflows/interceptors/workflow_startup.py`](workflows/interceptors/workflow_startup.py).
- **Triggering it outside the demo app:** run `.venv/bin/python -m workflows.cli` to trigger the workflow. running `temporal workflow start...` skips the client interceptor entirely and grant data will be missing from the request. This will cause the guardrail check on the token to fail the run with `InvalidDelegationGrant` after this first interceptor and activity is run.
- **Other use cases:** stamping memo or search attributes for ops dashboards, per-run feature-flag and config resolution, and one-time validation or setup at the start of every workflow. The outbound interceptor can also set priority and fairness on the activities and child workflows it schedules, which is a good fit for per-tenant or per-tier scheduling policy applied in one place. Note that the interceptor cannot change the running workflow's own priority, because that is fixed when the workflow starts.

### 3. Grant-propagation interceptor

*Category: Workflow inbound + outbound (sandbox) and Activity inbound (worker). No auth, it only moves context.*

- **Why a customer would care:** the caller's identity can follow the work to every downstream call without copying code to every activity. In some cases, iidentity may be enforced by backend systems workflows might have to interact with, and the identity, via the grant, will enable the workflow to complete successfully without creating a new security framework for the downstream applications or cluttering activities. This also shows a separation of concerns that some customers may be interested. It separates out the handling of security concerns from traceability and operational needs, covered by the Workflow startup interceptor.
- **What fires it:** the workflow starting (inbound, to read the header) and each activity being scheduled (outbound, to copy the header on), both during a normal booking.
- **What it does:** Temporal delivers the start header to the workflow but does not forward it to activities, and this interceptor bridges that gap. It reads the `delegation-grant` header into a contextvar and copies it onto each scheduled activity, so the token-exchange interceptor has something to redeem when the activity runs.
- **What you will see:** its effect is to transfer the grant to the activities so there is a grant to redeem. Without a redeemed grant, the backend service would return a 401 instead of a 200.
**Code Location:** [`workflows/interceptors/grant_propagation.py`](workflows/interceptors/grant_propagation.py).
- **Triggering it outside the demo app:** run `.venv/bin/python -m workflows.cli` to trigger the workflow. running `temporal workflow start...` skips the client interceptor entirely and grant data will be missing from the request. This will cause the guardrail check on the token to fail the run with `InvalidDelegationGrant` before this interceptor is executed.
- **Other use cases:** distributed-tracing context (OpenTelemetry), tenant ids, and locale or feature flags. Anything request-scoped that has to ride along without living in business arguments.

### 4. Token-exchange interceptor

*Category: Worker / Activity (inbound). Runs on the worker, outside the sandbox, once per activity attempt. This is the on-behalf-of use case.*

- **Why a customer would care:**  customers need the ability to show how certain calls were done via log files for auditing practices. Best practices in this area are to show systems acting on behalf of a user. This interceptor does just that by exchanging a grant for a short-lived token that gives the service permission to act on behalf of the user.

If the user token was propogated, customers would lose the visibility into *how exactly* some transaction occurred, which would require systematic remediation to pass audit steps.
- **What fires it:** every activity execution during a booking, just before the activity body runs. This ensures the short-lived token that is received will be good for the upcoming transaction.
- **What it does:** it redeems the propagated grant, together with the worker's own workload credential, for a short-lived access token whose `sub` is the traveler and whose `act` is the worker. That is [RFC 8693](https://datatracker.ietf.org/doc/html/rfc8693) delegation. The result goes into a contextvar, and the activity simply reads it as its Bearer token while knowing nothing about any of this.

This interceptor allows us to use a network call, obtain new tokens, when necessary, for each retry of an activity, and ensure that short-lived tokens are not written to durable storage for the workload. Additionally, we do not need to share the user's token throughout this process, which can result in failed workflows due to expired tokens.
- **What you will see:** `[interceptor:exchange] worker-wyld-stallyns acting on behalf of bill (expires in 120s)` before each activity, and the matching `[backend] issued delegated token` and `authorized ... acting on behalf of ...` pair in the backend terminal.
- **Code location:** [`workflows/interceptors/token_exchange.py`](workflows/interceptors/token_exchange.py).
- **Triggering it outside the demo app:** cannot be done directly, since it only runs as part of an activity attempt. You can exercise the endpoint it calls, though. It takes `application/x-www-form-urlencoded`, which RFC 8693 §2.1 requires, and each token must be accompanied by its `*_token_type`:

  ```bash
  curl -X POST localhost:9000/oauth2/token \
    --data-urlencode 'grant_type=urn:ietf:params:oauth:grant-type:token-exchange' \
    --data-urlencode "subject_token=$GRANT" \
    --data-urlencode 'subject_token_type=urn:ietf:params:oauth:token-type:jwt' \
    --data-urlencode "actor_token=$ACTOR" \
    --data-urlencode 'actor_token_type=urn:ietf:params:oauth:token-type:jwt' \
    --data-urlencode 'audience=circuits-of-time-backend' \
    --data-urlencode 'requested_token_type=urn:ietf:params:oauth:token-type:access_token'
  ```

  Minting the two tokens by hand is a bit complex; the [README](README.md) "Prove it worked" section has a copy-pasteable version.
- **Other use cases:** any per-call credential that has to be fresh, such as a database password from a secret manager, a cloud STS session, an mTLS client cert, or a DPoP proof. Also per-activity connection pools and tenant-scoped clients.

### 5. Activity logging interceptor

*Category: Worker / Activity (inbound). Runs on the worker, outside the sandbox.*

- **Why a customer would care:** not all observability can be done within the console or within observability tools. Some customers will need data across every activity type in one place, such as audit data, security events, or cost drivers like activity retries.
- **What fires it:** every activity execution during a booking (`verify_grant`, `paradox_scan`, and `execute_jump`), where the last two make real HTTP calls to the backend.
- **What it does:** logs a uniform start, duration, and outcome line around every activity, with no per-activity code.
- **What you will see:** paired `[interceptor:activity] started/completed` lines, interleaved with the activity's own `[activity] calling ... backend` line.
- **Code location:** [`workflows/interceptors/activity_logging.py`](workflows/interceptors/activity_logging.py).
- **Triggering it outside the demo app:** cannot be done directly, since it only runs as part of an activity attempt.
- **Other use cases:** metrics and tracing spans per activity, injecting per-activity context such as loggers and database sessions, and enforcing redaction or timeouts uniformly.

### 6. Workflow inbound interceptor

*Category: Worker / Workflow (inbound). Runs inside the sandbox, so `workflow.logger` only. It does no auth.*

- **Why a customer would care:** a uniform, hard-to-bypass audit trail for compliance that individual handlers cannot skip, and that never copies sensitive payloads into a second store.
- **What fires it:** every signal and query into a running workflow. In the web client that means Rufus approving or rejecting a flagged trip (`submit_review`) and the traveler's status polls (`get_state`).
- **What it does:** one cross-cutting, non-auth job. It audits, logging every inbound signal and query with argument types rather than values.
- **What you will see:** `[interceptor:workflow]` audit lines for every message from `query` or `signal`, which are the only two message types this demo uses.
- **Code location:** [`workflows/interceptors/workflow_audit.py`](workflows/interceptors/workflow_audit.py).
- **Triggering it outside the demo app:** yes. Signals and queries executed via the CLI go straight to the worker rather than through your client code.
  ```bash
  temporal workflow signal --workflow-id ID --name submit_review --input '"approved"' --input '"Rufus"'
  temporal workflow query  --workflow-id ID --type get_state
  ```
- **Other use cases:** message and argument validation, signal idempotency (dropping duplicates), and retry-on-signal operational control.

### Watching it happen

Identity travels client to service to workflow to activity to backend, changing form as it goes: a session token becomes a grant at the client, and the grant becomes a delegated access token at each activity. The log tags tell the sources apart, with `[interceptor:*]` for the interceptors, `[activity]` for activity code, `[workflow]` for workflow logic, and `[backend]` lines appearing in the backend's terminal. A flagged trip that Bill books and Rufus approves reads like this:

Trimmed for reading: `(...)` replaces the context dictionary Temporal's workflow and
activity loggers append to every line (`run_id`, `task_queue`, `workflow_id`, and the
rest), the date prefix is dropped from the timestamp, and the repeated status polls are
collapsed to a `...` marker. Everything else is a real capture — and the correlation id
is left on every line it appears on, because following it down the page *is* the
demonstration.
```text
# worker terminal
Worker starting on task queue 'interceptor-samples'...
12:52:44 | INFO | activity_logging.py:38  | [interceptor:activity] started: verify_grant (workflow_id=chrono-trip-bill, attempt=1, correlation_id=cot-019fd722)
12:52:44 | INFO | activities.py:159       | [activity:verify-grant] grant verified for bill (Bill S. Preston, Esq.) (...)
12:52:44 | INFO | activity_logging.py:58  | [interceptor:activity] completed: verify_grant in 0.000s [correlation_id=cot-019fd722]
12:52:44 | INFO | workflow_startup.py:171 | [interceptor:startup] trip start: traveler=Bill S. Preston, Esq. mission=Ace our history report correlation_id=cot-019fd722 (...)
12:52:44 | INFO | activity_logging.py:38  | [interceptor:activity] started: paradox_scan (workflow_id=chrono-trip-bill, attempt=1, correlation_id=cot-019fd722)
12:52:44 | INFO | _client.py:1740         | HTTP Request: POST http://localhost:9000/oauth2/token "HTTP/1.1 200 OK"
12:52:44 | INFO | token_exchange.py:250   | [interceptor:exchange] worker-wyld-stallyns acting on behalf of bill (expires in 120s) (...)
12:52:44 | INFO | activities.py:172       | [activity] calling paradox-scan backend for traveler bill -> Ancient Greece, 410 B.C. (...)
12:52:47 | INFO | _client.py:1740         | HTTP Request: POST http://localhost:9000/paradox-scan "HTTP/1.1 200 OK"
12:52:47 | INFO | activity_logging.py:58  | [interceptor:activity] completed: paradox_scan in 3.384s [correlation_id=cot-019fd722]
12:52:52 | INFO | workflow.py:74          | [workflow] trip flagged for Rufus's review: Whoa — the Circuits of History detected a most bogus paradox risk! (...)
12:52:54 | INFO | workflow_audit.py:42    | [interceptor:workflow] query received: get_state args=() (...)
   ...  the traveler's browser polls get_state every ~2s while the trip waits for Rufus  ...
12:52:59 | INFO | workflow_audit.py:34    | [interceptor:workflow] signal received: submit_review args=(str, str) (...)
12:52:59 | INFO | workflow.py:84          | [workflow] journey approved by Rufus (...)
   ...  polling continues until the trip closes  ...
12:53:04 | INFO | activity_logging.py:38  | [interceptor:activity] started: execute_jump (workflow_id=chrono-trip-bill, attempt=1, correlation_id=cot-019fd722)
12:53:04 | INFO | activities.py:191       | [activity] calling engage-booth backend for traveler bill -> Ancient Greece, 410 B.C. (...)
12:53:10 | INFO | _client.py:1740         | HTTP Request: POST http://localhost:9000/engage-booth "HTTP/1.1 200 OK"
12:53:10 | INFO | activity_logging.py:58  | [interceptor:activity] completed: execute_jump in 5.908s [correlation_id=cot-019fd722]

# backend terminal
12:52:44 | INFO | [backend] issued delegated token — worker=worker-wyld-stallyns on behalf of traveler=bill
INFO:     10.244.1.4:37598 - "POST /oauth2/token HTTP/1.1" 200 OK
12:52:44 | INFO | [backend] authorized paradox-scan — worker=worker-wyld-stallyns acting on behalf of traveler=bill (Bill S. Preston, Esq.)
INFO:     10.244.1.4:37604 - "POST /paradox-scan HTTP/1.1" 200 OK
12:53:04 | INFO | [backend] authorized engage-booth — worker=worker-wyld-stallyns acting on behalf of traveler=bill (Bill S. Preston, Esq.)
INFO:     10.244.1.4:32958 - "POST /engage-booth HTTP/1.1" 200 OK
```

Two things in there are easy to miss. **`verify_grant` runs first** - before the startup interceptor's own log line, because that interceptor schedules the check and waits for the recorded result before doing anything else. You'll also see that `execute_jump` doesn't have a `[interceptor:exchange]` log entry. The activity-inbound token-exchange interceptor caches the access token minted for previous activities and reuse it if it is still valid, within 90 seconds, when the jump ran 20 seconds later, so the token-exchange interceptor served it from its per-grant cache instead of minting a second one. If Rufus didn't approve a trip in a timely fashion, you would see a second call in the logs for `[interceptor:exchange]`.

Note that both identities appear on every authorized call for the backend, which is what makes this delegation rather than impersonation. This gives auditors what they typically want: who acted and for whom. The alternative is a log that makes it look as though Bill called an internal service himself.

---

## Field notes for solutions architects

Below are the insights that I felt were the biggest areas to watch with Interceptors.

### Insight 1: Inside vs. outside the Workflow sandbox

Interceptors follow the same sandbox and replay rules as the concern they wrap. Workflow Interceptors need to be deterministic. They run in the same sandbox as the workflow and need to be deterministic. Workflow Interceptors run on replay, as well.

Activity Interceptors run outside of the sandbox and can be nondeterministic. Activity Interceptors are able to take all the actions an Activity can and will not run on replay.

Following this insight will help you determine where to attach an Interceptor in your project.

### Insight 2: Ordering your interceptors properly can save time and cost

Think about the ordering of your Interceptors when registering them. If you have Interceptors that can throw errors and stop the workflow due to missing data or incomplete permissions, it is best to have these registered to fire first in your list, as these will prevent extra billable Actions for the workflow.

### Insight 3: Know what can and cannot be adjusted by the different Interceptors

Interceptors cannot do *everything*, but they can be very helpful.

| Interceptor | Can set/adjust | Cannot set/adjust (example listing)|
| --- | --- | --- |
| Client (`start_workflow`) | the workflow's own priority or fairness, retry policy, memo, search attributes, task queue, headers, args | injecting headers in unit tests |
| Workflow outbound (`start_activity` / child) | priority or fairness, retry policy, task queue, headers on the activities and children it schedules | no known list |
| Workflow inbound | gate, observe, or audit `execute_workflow`, signals, queries, and both update hooks; set contextvars | change the running workflow's own priority from workflow code |
| Activity inbound | read and rewrite this attempt's input and headers; do real I/O; set contextvars for the activity body | workflow-level scheduling attributes; what was already recorded in `ActivityTaskScheduled` |

Note the distinction in that last row. An Activity inbound interceptor *can* rewrite the headers it hands to this attempt; what it cannot do is change what was recorded when the activity was scheduled. An activity's headers are written into `ActivityTaskScheduled` when the workflow schedules it, and retries reuse that same event. An activity-inbound interceptor can only read those headers and retries will use the same ones. So anything time-sensitive, a credential above all, has to be derived at execution time rather than stamped at scheduling time. This is why this demo puts a long-lived inert grant on the header and mints the short-lived credential in the interceptor.

### Insight 4: Logging interceptor vs. OTel vs. the Temporal UI

A logging interceptor is not "OTel but cheaper". The difference is where the data lands.

| Option | What you get | Cost model | Best for |
| --- | --- | --- | --- |
| Custom logging interceptor | Plain (JSON) log lines you write | Reuses the log pipeline you already own; no new tool | Reusing infra; domain-enriched or redacted lines; Security Information and Event Management (SIEM) feeds |
| OTel interceptor + backend | Distributed traces + metrics | A backend to operate (Jaeger/Tempo/Prometheus, or a paid Application Performance Monitor (APM)) | Fleet-wide traces, dashboards, alerting |
| Temporal Web UI / Event History | Per-execution timeline | Free, already there | Debugging one workflow |

**Note:** Temporal's OTel integration is itself an interceptor (`temporalio.contrib.opentelemetry.TracingInterceptor`)

### Insight 5: Interceptors can be plumbing and governance

The interceptors in this demo are "plumbing by design", focusing on cross-cutting concerns in a single workflow. Interceptors are also the right home for business policy and governance that crosses workflows, which is a different thing from plumbing.

"Save the future" is a premium-only mission and is a good example of a business policy. Users not in the group for premium features do not get access to this mission. The same architectural shape covers per-tenant routing, quotas, per-tier priority and fairness, and PII redaction.

#### Additional patterns

- **Central retry and error classification:** an outbound workflow interceptor can cap `MaximumAttempts` and mark known-permanent failures as `NonRetryableErrorTypes` in one place. Each avoided retry is one avoided Action.
- **Signal coalescing and idempotency:** capture and drop redundant signals in the client (outbound) interceptor before the RPC leaves the client, so you pay for one Signal Action instead of many. Dropping them workflow-inbound prevents redundant work but not the Action, because the signal already arrived.
- **Workflow-ID dedup:** the server already skips billing a de-duplicated start, so the client interceptor's role is simply to ensure a stable ID.

---

## References

- Temporal Cloud Actions (what's billable): <https://docs.temporal.io/cloud/actions>
- Cloud pricing and plans: <https://docs.temporal.io/cloud/pricing>
- Workflow cost optimization: <https://docs.temporal.io/best-practices/cost-optimization>
- Task Queue Priority and Fairness: <https://docs.temporal.io/develop/task-queue-priority-fairness>
- Interceptors (encyclopedia): <https://docs.temporal.io/encyclopedia/interceptors>
- Interceptors, incl. the "Runs on" / replay table (Python SDK): <https://docs.temporal.io/develop/python/workers/interceptors>
- OAuth 2.0 Token Exchange (RFC 8693), the delegation model used here: <https://datatracker.ietf.org/doc/html/rfc8693>
- Workflow determinism constraints: <https://docs.temporal.io/workflow-definition>
 