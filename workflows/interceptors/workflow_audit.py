"""Workflow inbound interceptor — audit. No auth.

This runs INSIDE the Workflow sandbox, so it obeys determinism rules and logs via
`workflow.logger` (replay-aware). It does one cross-cutting thing, which is not
authentication (auth happens client-side; see `client_auth.py`):

  * **Audit** every inbound signal and query, logging argument *types* not values
    so the audit trail never becomes a second place sensitive data leaks.
"""

from typing import Any, Optional, Type

from temporalio import workflow
from temporalio.worker import (
    HandleQueryInput,
    HandleSignalInput,
    Interceptor,
    WorkflowInboundInterceptor,
    WorkflowInterceptorClassInput,
)


class WorkflowAuditInterceptor(Interceptor):
    """Worker interceptor installing inbound signal/query audit."""

    def workflow_interceptor_class(
        self, input: WorkflowInterceptorClassInput
    ) -> Optional[Type[WorkflowInboundInterceptor]]:
        return _AuditWorkflowInbound


class _AuditWorkflowInbound(WorkflowInboundInterceptor):
    async def handle_signal(self, input: HandleSignalInput) -> None:
        workflow.logger.info(
            "[interceptor:workflow] signal received: %s args=%s",
            input.signal,
            _safe_summary(input.args),
        )
        await super().handle_signal(input)

    async def handle_query(self, input: HandleQueryInput) -> Any:
        workflow.logger.info(
            "[interceptor:workflow] query received: %s args=%s",
            input.query,
            _safe_summary(input.args),
        )
        return await super().handle_query(input)


def _safe_summary(args) -> str:
    # Log argument TYPES, not values, so the audit trail doesn't become a second,
    # uncontrolled place where sensitive payload contents leak out.
    return "(" + ", ".join(type(a).__name__ for a in args) + ")"
