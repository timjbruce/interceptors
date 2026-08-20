"""Workflow startup interceptor — cross-cutting work done once at workflow start.

Runs at the `execute_workflow` seam: it fires when the run begins (and again on
replay), needs NO user intervention — no signals, updates, or queries — and stays
fully deterministic / replay-safe. It bundles three start-of-workflow concerns
that would otherwise be sprinkled through the workflow body:

  1. **Correlation id**: seed one from the start header, or derive it
     deterministically from the run id, into `correlation_id`, and propagate it to
     activities so their log lines correlate to the trip. Done first so even the
     verification below is logged under it.
  2. **Boundary guardrail**: have the grant on the start header verified and fail
     fast, non-retryably, if it is missing, malformed, forged, expired, or of the
     wrong type. The client interceptor is still the primary gate (it rejects before
     a workflow is even started, so no Action is billed); this stops a raw `temporal
     workflow start` bypass right at the workflow edge — before any business
     activity or backend call — instead of later at the backend.
  3. **Tag the execution** with Search Attributes (`Traveler`, `Mission`) so trips
     are filterable in the Temporal UI / CLI (e.g. `Traveler = 'bill'`) without
     touching business code. (This interceptor populates their values on every run.)

## The check runs in an activity, and that is the interesting part

This interceptor **schedules** the verification (`interceptors/auth_activities.verify_grant`); it
does not perform it. Doing the check inline here would put it inside the sandbox,
where there is no clock and no network — so it could only ever answer *"was this
signed and well-formed"*, never *"is this credential still valid right now."*
Expiry needs a clock; revocation and a JWKS fetch need I/O. A check that silently
skips all three looks like a security boundary while enforcing far less than one.

Handing it to an activity gets the clock and the network back, and the recorded
activity result is what keeps replay deterministic — the replaying workflow reads
the outcome instead of re-deciding it. `activities.py` has the full reasoning.

The general rule: an interceptor is a good place to *decide that* cross-cutting work
happens, and a bad place to *do* it when the work is non-deterministic.

## Determinism

Everything this interceptor does itself is replay-safe: it reads the start header,
the workflow args, and `workflow.info()` (run id); schedules one activity and emits
`upsert_search_attributes` (both recorded commands); logs via the replay-aware
`workflow.logger`; and raises deterministically off the recorded result. No
wall-clock, randomness, or I/O in here.

The traveler's identity comes back from that activity — verified, and recorded — so
the search attributes below never depend on decoding the grant in the sandbox.
"""

import contextvars
import logging
from datetime import timedelta
from typing import Any, Optional, Type

import temporalio.converter
from temporalio import workflow
from temporalio.common import RetryPolicy, SearchAttributeKey
from temporalio.exceptions import ApplicationError
from temporalio.worker import (
    ActivityInboundInterceptor,
    ExecuteActivityInput,
    ExecuteWorkflowInput,
    HandleQueryInput,
    HandleSignalInput,
    Interceptor,
    StartActivityInput,
    WorkflowInboundInterceptor,
    WorkflowInterceptorClassInput,
    WorkflowOutboundInterceptor,
)

from workflows.interceptors.client_auth import GRANT_HEADER_KEY

with workflow.unsafe.imports_passed_through():
    from workflows.interceptors.auth_activities import verify_grant

# Header carrying the correlation id from the workflow to its activities.
CORRELATION_HEADER_KEY = "correlation-id"

# The verification activity is a local, sub-millisecond check today, but it is the
# seam where a real JWKS fetch or introspection call would go — so it gets a network
# call's timeout and a few retries for a transient issuer failure. A *bad* grant
# comes back as a result, not an error, so it is answered on the first attempt.
_VERIFY_TIMEOUT = timedelta(seconds=10)
_VERIFY_RETRY = RetryPolicy(maximum_attempts=3)

# Custom Search Attributes (Keyword) this interceptor populates on every run.
TRAVELER_SA = SearchAttributeKey.for_keyword("Traveler")
MISSION_SA = SearchAttributeKey.for_keyword("Mission")

# The trip's correlation id, exposed to activities for correlated logging. Set
# unconditionally on every execution so a run never reads a stale value left by a
# previous workflow/activity on the same worker.
correlation_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "correlation_id", default=None
)

# What a log line shows when there is no trip in context: worker startup, poller
# chatter, the SDK's own messages. Without a default the format string raises on every
# one of them.
NO_CORRELATION = "-"


class CorrelationLogFilter(logging.Filter):
    """Put the current trip's correlation id on every log record in the process.

    The point of this over each call site formatting its own id: no business code, and
    no activity, has to know the id exists. Set it once on the way in, add one field to
    the log format, and every line written while a trip is in context carries it -
    including lines from code that has never heard of this interceptor.

    A `Filter` on a *handler* rather than a logger, because handler filters see records
    that propagated up from every logger in the process; a logger filter would only see
    records logged directly to that logger.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "correlation_id"):
            record.correlation_id = correlation_id.get() or NO_CORRELATION
        return True


def install_correlation_logging() -> None:
    """Attach `CorrelationLogFilter` to every root handler. Call after `basicConfig`.

    Idempotent: calling it twice does not double-filter, so it is safe from a module
    that may be imported more than once.
    """
    for handler in logging.getLogger().handlers:
        if not any(isinstance(f, CorrelationLogFilter) for f in handler.filters):
            handler.addFilter(CorrelationLogFilter())


class WorkflowStartupInterceptor(Interceptor):
    """Worker interceptor: start-of-workflow tagging, guardrail, correlation."""

    def workflow_interceptor_class(
        self, input: WorkflowInterceptorClassInput
    ) -> Optional[Type[WorkflowInboundInterceptor]]:
        return _StartupWorkflowInbound

    def intercept_activity(self, next: ActivityInboundInterceptor) -> ActivityInboundInterceptor:
        return _StartupActivityInbound(next)


class _StartupWorkflowInbound(WorkflowInboundInterceptor):
    # The trip's id, remembered on the instance so the signal and query handlers can put
    # it back on their own context. See `_seed_correlation_id`. Declared at CLASS level
    # so a handler can never meet a missing attribute: the SDK always calls `init()`
    # before dispatching anything, but a handler that reads this must not depend on that.
    _cid: Optional[str] = None

    def init(self, outbound: WorkflowOutboundInterceptor) -> None:
        # Keep the reference: `execute_workflow` needs to hand the grant to the
        # outbound half so it can stamp the verification activity's header.
        self._outbound = _StartupWorkflowOutbound(outbound)
        super().init(self._outbound)

    def _seed_correlation_id(self) -> str:
        """Set `correlation_id` on the CURRENT task's context, and return it.

        Why every handler has to call this, and why setting it once in
        `execute_workflow` was not enough:

        The SDK runs the workflow body, each signal and each query as SEPARATE asyncio
        tasks (`_workflow_instance.py:1096`, `:2503`, `:791`), and `create_task` is called
        with `context=None`, so each task gets its own COPY of the context taken when the
        task was created. A `ContextVar.set()` inside the workflow-body task is therefore
        invisible to a signal or query task: they were not created from it. The result was
        that every `handle_signal` and `handle_query` line logged the filter's placeholder
        instead of the trip's id, which is the audit trail for requirement 3.

        Deterministic and replay-safe: the id comes from the start header or from the run
        id, both of which are fixed for the life of the run.
        """
        cid = self._cid or f"cot-{workflow.info().run_id}"
        self._cid = cid
        correlation_id.set(cid)
        return cid

    async def handle_signal(self, input: HandleSignalInput) -> None:
        # Runs before the audit interceptor's own `handle_signal`, because this
        # interceptor is registered first and inbound chains run in registration order.
        # So the id is in place by the time the audit line is written.
        self._seed_correlation_id()
        return await super().handle_signal(input)

    async def handle_query(self, input: HandleQueryInput) -> Any:
        self._seed_correlation_id()
        return await super().handle_query(input)

    async def execute_workflow(self, input: ExecuteWorkflowInput) -> Any:
        # (1) Correlation id: from the header if present, else deterministic from
        # the run id (stable across replays). Set first so the verification activity
        # scheduled below already logs under it. Propagated to activities by the
        # outbound hook.
        #
        # The WHOLE run id, not a slice of it. Run ids are UUIDv7, so their leading hex
        # digits are a millisecond timestamp: `run_id[:8]` only changes about every 65
        # seconds, which made every trip started in the same minute share one id and made
        # `grep <cid>` return somebody else's trip. Longer log lines are the whole cost.
        cpayload = (input.headers or {}).get(CORRELATION_HEADER_KEY)
        cid = workflow.payload_converter().from_payload(cpayload, str) if cpayload is not None else None
        self._cid = cid or f"cot-{workflow.info().run_id}"
        correlation_id.set(self._cid)

        # (2) Guardrail. Read the grant off the start header and hand it to an
        # ACTIVITY to be verified — see this module's docstring and
        # `activities.py` for why the check cannot honestly happen in here.
        #
        # The grant reaches the activity on its HEADER, like every other activity in
        # this demo, so `verify_grant` reads it the same way the rest of the worker
        # does. We stamp it ourselves, for this one call only: the grant-propagation
        # interceptor is registered *after* this one, so its inbound half has not run
        # yet and `current_grant` is still empty at this point in the chain.
        payload = (input.headers or {}).get(GRANT_HEADER_KEY)
        grant = workflow.payload_converter().from_payload(payload, str) if payload is not None else None
        self._outbound.grant_for_next_activity = grant
        try:
            check = await workflow.execute_activity(
                verify_grant,
                start_to_close_timeout=_VERIFY_TIMEOUT,
                retry_policy=_VERIFY_RETRY,
            )
        finally:
            # One-off: clear it so the business activities this workflow schedules
            # later get their grant header from the propagation interceptor, which is
            # the interceptor that owns that job.
            self._outbound.grant_for_next_activity = None

        # A missing, malformed, forged, EXPIRED, or wrong-type grant -> fail fast,
        # before any business activity. Catches a raw `temporal workflow start`
        # bypass at the workflow edge, and anything tampered with after the client.
        # Raising here (rather than in the activity) keeps the failure the workflow
        # closes with a single non-retryable ApplicationError instead of an activity
        # failure wrapping one. The message stays generic; `check.reason` is logged.
        if not check.valid:
            workflow.logger.warning(
                "[interceptor:startup] rejected trip start: %s",
                check.reason,
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
            # The id is not in this message: `CorrelationLogFilter` already puts it in
            # the prefix of every line, this one included.
            "[interceptor:startup] trip start: traveler=%s mission=%s",
            check.traveler_name,
            mission or "(none)",
        )
        return await super().execute_workflow(input)


class _StartupWorkflowOutbound(WorkflowOutboundInterceptor):
    def __init__(self, next: WorkflowOutboundInterceptor) -> None:
        super().__init__(next)
        # Set by the inbound half around the verification activity only, and cleared
        # immediately after. Per workflow instance (this object is constructed in the
        # inbound's `init()`), so concurrent workflows on one worker cannot see each
        # other's value.
        self.grant_for_next_activity: Optional[str] = None

    def start_activity(self, input: StartActivityInput):
        headers = dict(input.headers or {})
        cid = correlation_id.get()
        if cid is not None:
            headers[CORRELATION_HEADER_KEY] = workflow.payload_converter().to_payload(cid)
        if self.grant_for_next_activity is not None:
            headers[GRANT_HEADER_KEY] = workflow.payload_converter().to_payload(
                self.grant_for_next_activity
            )
        input.headers = headers
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
