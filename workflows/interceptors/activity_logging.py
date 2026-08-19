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


logger = logging.getLogger("temporal.activity")


class ActivityLoggingInterceptor(Interceptor):
    """Worker interceptor that logs every Activity's start, duration, and outcome."""

    def intercept_activity(self, next: ActivityInboundInterceptor) -> ActivityInboundInterceptor:
        return _LoggingActivityInboundInterceptor(next)


class _LoggingActivityInboundInterceptor(ActivityInboundInterceptor):
    async def execute_activity(self, input: ExecuteActivityInput) -> Any:
        info = activity.info()
        started = time.monotonic()
        # No correlation id in these messages. The startup interceptor seeds it, the
        # header carries it here, and `CorrelationLogFilter` puts it in the prefix of
        # every line this process writes — including lines from activities and SDK code
        # that have never heard of it. Formatting it again here would only print it
        # twice, and would suggest a call site has to know about it.
        logger.info(
            "[interceptor:activity] started: %s (workflow_id=%s, attempt=%d)",
            info.activity_type,
            info.workflow_id,
            info.attempt,
        )
        try:
            result = await super().execute_activity(input)
        except BaseException as exc:
            logger.warning(
                "[interceptor:activity] failed: %s after %.3fs (%s: %s)",
                info.activity_type,
                time.monotonic() - started,
                type(exc).__name__,
                exc,
            )
            raise
        else:
            logger.info(
                "[interceptor:activity] completed: %s in %.3fs",
                info.activity_type,
                time.monotonic() - started,
            )
            return result
