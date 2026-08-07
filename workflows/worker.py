"""Runs the Worker with its worker-side interceptors (start-of-workflow tagging +
guardrail + correlation, activity logging, workflow audit, and grant
propagation) registered.

Connects locally by default; set the TEMPORAL_* env vars (see setcloudenv.example)
to run against Temporal Cloud. Start it with `./runworkflow.sh`.
"""

import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from workflows.activities import execute_jump, paradox_scan, verify_grant
from workflows.client import connect
from workflows.config import TASK_QUEUE, TEMPORAL_ADDRESS, TEMPORAL_NAMESPACE
from workflows.interceptors.activity_logging import ActivityLoggingInterceptor
from workflows.interceptors.grant_propagation import GrantPropagationInterceptor
from workflows.interceptors.token_exchange import TokenExchangeInterceptor
from workflows.interceptors.workflow_audit import WorkflowAuditInterceptor
from workflows.interceptors.workflow_startup import WorkflowStartupInterceptor
from workflows.workflow import ChronoTripWorkflow

logger = logging.getLogger("temporal.worker")

async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(filename)s:%(lineno)s | %(message)s",
    )
    client = await connect()
    print(f"Connecting to Temporal at {TEMPORAL_ADDRESS} (namespace: {TEMPORAL_NAMESPACE})")
    print(f"Worker starting on task queue '{TASK_QUEUE}'...")
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[ChronoTripWorkflow],
        # `verify_grant` is not business logic: it is the credential check the
        # startup interceptor schedules, registered here because an interceptor can
        # only execute activities this worker knows about.
        activities=[paradox_scan, execute_jump, verify_grant],
        interceptors=[
            # First in the list is outermost. The startup interceptor runs first so
            # its guardrail fires before anything else and its correlation id is set
            # before the activity logger reads it.
            WorkflowStartupInterceptor(),
            ActivityLoggingInterceptor(),
            WorkflowAuditInterceptor(),
            GrantPropagationInterceptor(),
            # Innermost on the activity-inbound chain, so the exchanged credential is
            # in place immediately before the activity body runs — and so the timing
            # logged by ActivityLoggingInterceptor (further out) includes the
            # exchange.
            TokenExchangeInterceptor(),
        ],
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
