"""Grant propagation — carry the delegation grant to the activities.

Temporal delivers the start header to the workflow but does not forward it to
activities. This interceptor bridges that gap. It moves *context*, never a usable
credential — the grant it carries authorizes nothing on its own:

  * Workflow INBOUND (sandbox): read the `delegation-grant` header into
    `current_grant`.
  * Workflow OUTBOUND (sandbox): copy the header onto each scheduled activity.
  * Activity INBOUND (worker): read the header into `current_grant`, which the
    token-exchange interceptor then redeems for a real access token.

Both inbound hooks set `current_grant` *unconditionally* (to the grant or None) so
each execution resets it — a header-less run must not read a value left behind by a
previous workflow/activity on the same worker.
"""

from typing import Any, Optional, Type

import temporalio.converter
from temporalio import workflow
from temporalio.worker import (
    ActivityInboundInterceptor,
    ExecuteActivityInput,
    ExecuteWorkflowInput,
    Interceptor,
    StartActivityInput,
    WorkflowInboundInterceptor,
    WorkflowInterceptorClassInput,
    WorkflowOutboundInterceptor,
)

from workflows.interceptors.client_auth import GRANT_HEADER_KEY

with workflow.unsafe.imports_passed_through():
    from workflows.auth import current_grant


class GrantPropagationInterceptor(Interceptor):
    """Worker interceptor: forward the delegation grant workflow -> activity."""

    def workflow_interceptor_class(
        self, input: WorkflowInterceptorClassInput
    ) -> Optional[Type[WorkflowInboundInterceptor]]:
        return _PropagatingWorkflowInbound

    def intercept_activity(self, next: ActivityInboundInterceptor) -> ActivityInboundInterceptor:
        return _PropagatingActivityInbound(next)


class _PropagatingWorkflowInbound(WorkflowInboundInterceptor):
    def init(self, outbound: WorkflowOutboundInterceptor) -> None:
        super().init(_PropagatingWorkflowOutbound(outbound))

    async def execute_workflow(self, input: ExecuteWorkflowInput) -> Any:
        payload = (input.headers or {}).get(GRANT_HEADER_KEY)
        token = workflow.payload_converter().from_payload(payload, str) if payload is not None else None
        current_grant.set(token)  # always set (reset), even to None
        return await super().execute_workflow(input)


class _PropagatingWorkflowOutbound(WorkflowOutboundInterceptor):
    def start_activity(self, input: StartActivityInput):
        token = current_grant.get()
        if token is not None:
            input.headers = {
                **(input.headers or {}),
                GRANT_HEADER_KEY: workflow.payload_converter().to_payload(token),
            }
        return super().start_activity(input)


class _PropagatingActivityInbound(ActivityInboundInterceptor):
    async def execute_activity(self, input: ExecuteActivityInput) -> Any:
        payload = (input.headers or {}).get(GRANT_HEADER_KEY)
        token = temporalio.converter.default().payload_converter.from_payload(payload, str) if payload is not None else None
        current_grant.set(token)  # always set (reset), even to None
        return await super().execute_activity(input)
