"""Activity interceptor: log start/complete with duration.

This is the "create side effects" category: pure observability, no change to
arguments or control flow. It runs on the Worker, outside the Workflow
sandbox, so real I/O (writing to a real logger/metrics backend) is fine here.

Because this hook wraps EVERY Activity execution on the Worker, you get
consistent start/complete/failure logging for free across every Activity
type, without touching a single Activity implementation.
"""

import logging
import time
from typing import Any

from temporalio import activity
from temporalio.worker import ActivityInboundInterceptor, ExecuteActivityInput, Interceptor

from workflows.interceptors.workflow_startup import correlation_id

logger = logging.getLogger("temporal.activity")


class ActivityLoggingInterceptor(Interceptor):
    """Worker interceptor that logs every Activity's start, duration, and outcome."""

    def intercept_activity(self, next: ActivityInboundInterceptor) -> ActivityInboundInterceptor:
        return _LoggingActivityInboundInterceptor(next)


class _LoggingActivityInboundInterceptor(ActivityInboundInterceptor):
    async def execute_activity(self, input: ExecuteActivityInput) -> Any:
        info = activity.info()
        started = time.monotonic()
        # correlation id is seeded by the startup interceptor and propagated onto
        # the activity header, so every activity log line ties back to its trip.
        cid = correlation_id.get()
        logger.info(
            "[interceptor:activity] started: %s (workflow_id=%s, attempt=%d, correlation_id=%s)",
            info.activity_type,
            info.workflow_id,
            info.attempt,
            cid,
        )
        try:
            result = await super().execute_activity(input)
        except BaseException as exc:
            logger.warning(
                "[interceptor:activity] failed: %s after %.3fs (%s: %s) [correlation_id=%s]",
                info.activity_type,
                time.monotonic() - started,
                type(exc).__name__,
                exc,
                cid,
            )
            raise
        else:
            logger.info(
                "[interceptor:activity] completed: %s in %.3fs [correlation_id=%s]",
                info.activity_type,
                time.monotonic() - started,
                cid,
            )
            return result
