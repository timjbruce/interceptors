"""Wyld Stallyns workflow — orchestrates one time-travel booking.

The steps:
  1. The caller was already validated client-side; the workflow does no auth. It
     just reads the traveler's identity (decoded from the propagated token) for
     display.
  2. paradox_scan may flag the trip for review.
  3. A flagged trip waits, with no time limit, for Rufus's decision.
  4. execute_jump completes the booking.

The scan and jump activities call the JWT-authorized backend over HTTP.
"""

from datetime import timedelta
from typing import Optional

from temporalio import workflow
from temporalio.common import RetryPolicy

# Bound activity retries so a persistent backend problem fails the trip instead of
# looping forever; genuine client-side errors (4xx) are already non-retryable in
# the activity itself.
_ACTIVITY_RETRY = RetryPolicy(maximum_attempts=5)

with workflow.unsafe.imports_passed_through():
    from workflows.activities import execute_jump, paradox_scan
    from workflows.auth import current_grant, decode_identity
    from workflows.models import TripRequest


@workflow.defn
class ChronoTripWorkflow:
    def __init__(self) -> None:
        self._status = "starting"
        self._traveler_id = "unknown"
        self._traveler_name = "unknown"
        self._destination = ""
        self._mission = ""
        self._flagged = False
        self._reason = ""
        self._arrival = ""
        self._review_decision: Optional[str] = None
        self._reviewer = ""

    @workflow.run
    async def run(self, request: TripRequest) -> str:
        # No auth here (that happened client-side). We just decode who's
        # travelling from the propagated token for display in the review queue.
        traveler = decode_identity(current_grant.get())
        if traveler:
            self._traveler_id = traveler["id"]
            self._traveler_name = traveler["name"]
        self._destination = request.destination
        self._mission = request.mission

        # 1. Scan for paradox risk (calls the JWT-authorized backend).
        self._status = "scanning"
        scan = await workflow.execute_activity(
            paradox_scan,
            args=[request, self._traveler_id],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_ACTIVITY_RETRY,
        )
        self._flagged = scan.flagged
        self._reason = scan.reason

        # Demo pacing: a short durable timer between steps so a trip lingers long
        # enough to be observed instead of racing to completion.
        await workflow.sleep(timedelta(seconds=5))

        # 2. If flagged, hold for Rufus — no time limit.
        if scan.flagged:
            self._status = "awaiting_review"
            workflow.logger.info("[workflow] trip flagged for Rufus's review: %s", scan.reason)
            await workflow.wait_condition(lambda: self._review_decision is not None)
            if self._review_decision == "rejected":
                self._status = "rejected"
                self._arrival = (
                    f"Bogus! The journey to {request.destination} was denied "
                    f"(reviewer: {self._reviewer})."
                )
                workflow.logger.info("[workflow] journey denied by %s", self._reviewer)
                return self._arrival
            workflow.logger.info("[workflow] journey approved by %s", self._reviewer)

        # 3. Execute the jump (calls the JWT-authorized backend).
        await workflow.sleep(timedelta(seconds=5))
        self._status = "jumping"
        self._arrival = await workflow.execute_activity(
            execute_jump,
            args=[request, self._traveler_id],
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_ACTIVITY_RETRY,
        )
        self._status = "completed"
        return self._arrival

    @workflow.signal
    def submit_review(self, decision: str, reviewer: str) -> None:
        """Rufus's decision: "approved" or "rejected"."""
        self._reviewer = reviewer
        self._review_decision = "approved" if decision == "approved" else "rejected"

    @workflow.query
    def get_status(self) -> str:
        return self._status

    @workflow.query
    def get_state(self) -> dict:
        return {
            "status": self._status,
            "traveler_id": self._traveler_id,
            "traveler_name": self._traveler_name,
            "destination": self._destination,
            "mission": self._mission,
            "flagged": self._flagged,
            "reason": self._reason,
            "arrival": self._arrival,
            "reviewer": self._reviewer,
        }
