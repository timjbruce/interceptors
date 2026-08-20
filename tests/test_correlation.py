"""Regression tests for the correlation id on signal and query handlers.

The bug these lock down: `correlation_id` is a `ContextVar`, and the SDK runs the
workflow body, each signal and each query as SEPARATE asyncio tasks
(`_workflow_instance.py:1096`, `:2503`, `:791`), each created with `context=None` so each
gets its own COPY of the context taken at creation time. Setting the var inside the
workflow body's task is therefore invisible to a signal or query task: they were never
created from it. Every `[interceptor:workflow] signal received` and `query received` line
came out with `CorrelationLogFilter`'s `"-"` placeholder instead of the trip's id, which
is the audit trail requirement 3 depends on.

`_StartupWorkflowInbound` now re-seeds the var at the top of both handlers. It is
registered before the audit interceptor (worker.py:53-66) and inbound chains run in
registration order, so the id is in place by the time the audit line is written.

These assert on the LOG RECORD, not just the context variable, because the log line is
the thing that was actually broken.
"""

import asyncio
import contextvars
import logging

import pytest
import temporalio.workflow
from temporalio.worker import (
    HandleQueryInput,
    HandleSignalInput,
    WorkflowInboundInterceptor,
)

from workflows.interceptors.workflow_audit import _AuditWorkflowInbound
from workflows.interceptors.workflow_startup import (
    NO_CORRELATION,
    CorrelationLogFilter,
    _StartupWorkflowInbound,
    correlation_id,
)

CID = "cot-01234567-89ab-7def-8000-000000000001"


class _Recorder(WorkflowInboundInterceptor):
    """Innermost link. Records the correlation id as seen when control reaches it."""

    def __init__(self) -> None:  # deliberately no `next`: nothing follows it
        self.seen: list[str | None] = []

    def init(self, outbound) -> None:
        pass

    async def handle_signal(self, input: HandleSignalInput) -> None:
        self.seen.append(correlation_id.get())

    async def handle_query(self, input: HandleQueryInput):
        self.seen.append(correlation_id.get())
        return "queried"


@pytest.fixture
def captured(monkeypatch):
    """Stand in for `workflow.logger`, filtered exactly like the worker's root handler.

    The worker attaches `CorrelationLogFilter` to its root handlers
    (`install_correlation_logging`). Doing the same here means a captured record carries
    whatever the real worker would have printed in the `%(correlation_id)s` slot.
    """
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Capture()
    handler.addFilter(CorrelationLogFilter())
    logger = logging.getLogger("test.workflow.audit")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    monkeypatch.setattr(temporalio.workflow, "logger", logger)
    return records


def _chain():
    """startup -> audit -> recorder, the real registration order from worker.py:53-66."""
    recorder = _Recorder()
    startup = _StartupWorkflowInbound(_AuditWorkflowInbound(recorder))
    startup._cid = CID
    return startup, recorder


async def _in_fresh_task(coro_factory):
    """Run in a task whose context has NEVER seen the var set.

    This is the whole point: it reproduces how the SDK dispatches a signal or query,
    instead of letting the test inherit a value the workflow body happened to set.
    """
    ctx = contextvars.copy_context()
    assert ctx.run(correlation_id.get) is None
    return await asyncio.create_task(coro_factory(), context=ctx)


async def test_signal_audit_line_carries_the_correlation_id(captured):
    startup, recorder = _chain()
    sig = HandleSignalInput(signal="submit_review", args=("approved", "Rufus"), headers={})

    await _in_fresh_task(lambda: startup.handle_signal(sig))

    assert recorder.seen == [CID], "signal handler ran without the trip's correlation id"
    assert [r.correlation_id for r in captured] == [CID]
    assert "signal received" in captured[0].getMessage()


async def test_query_audit_line_carries_the_correlation_id(captured):
    startup, recorder = _chain()
    qry = HandleQueryInput(id="q1", query="status", args=(), headers={})

    result = await _in_fresh_task(lambda: startup.handle_query(qry))

    assert result == "queried", "handle_query must return the inner result unchanged"
    assert recorder.seen == [CID], "query handler ran without the trip's correlation id"
    assert [r.correlation_id for r in captured] == [CID]
    assert "query received" in captured[0].getMessage()


async def test_without_the_fix_the_line_would_have_shown_the_placeholder(captured):
    """Pin the old behaviour, so the test proves the fix rather than the plumbing.

    The audit interceptor on its own, with nothing seeding the var, is what the chain
    used to do once the workflow body's context was out of the picture.
    """
    audit = _AuditWorkflowInbound(_Recorder())
    sig = HandleSignalInput(signal="submit_review", args=(), headers={})

    await _in_fresh_task(lambda: audit.handle_signal(sig))

    assert [r.correlation_id for r in captured] == [NO_CORRELATION]


async def test_handlers_do_not_leak_the_id_into_the_dispatching_context(captured):
    """Each handler seeds its OWN task context; the context that dispatched stays clean."""
    startup, _ = _chain()
    sig = HandleSignalInput(signal="submit_review", args=(), headers={})

    await _in_fresh_task(lambda: startup.handle_signal(sig))

    assert correlation_id.get() is None


async def test_a_handler_never_dies_on_a_missing_attribute():
    """`_cid` is a class attribute, so a handler reaching it before `init()` still works.

    Outside a workflow the run-id fallback cannot resolve, and that is fine: what must not
    happen is an AttributeError, which would fail the signal instead of the log line.
    """
    startup = _StartupWorkflowInbound(_Recorder())
    assert startup._cid is None

    with pytest.raises(temporalio.workflow._NotInWorkflowEventLoopError):
        startup._seed_correlation_id()


def test_log_filter_placeholder_only_when_there_is_no_id():
    f = CorrelationLogFilter()
    rec = logging.LogRecord("t", logging.INFO, __file__, 1, "m", None, None)
    f.filter(rec)
    assert rec.correlation_id == NO_CORRELATION

    token = correlation_id.set(CID)
    try:
        rec2 = logging.LogRecord("t", logging.INFO, __file__, 1, "m", None, None)
        f.filter(rec2)
        assert rec2.correlation_id == CID
    finally:
        correlation_id.reset(token)
