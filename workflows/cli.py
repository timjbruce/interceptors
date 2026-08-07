"""CLI demo of the Wyld Stallyns booking flow (the web UI's non-browser twin).

Runs a few bookings so you can watch the interceptors work. Auth + entitlement
are enforced client-side, so bad requests are rejected before a workflow starts:
  1. Bill's valid license          -> completes (excellent!)
  2. no license                    -> rejected by the client interceptor (bogus!)
  3. forged license                -> rejected by the client interceptor (bogus!)
  4. Ted (standard) saves the future  -> rejected: premium-only mission (bogus!)
  5. Bill (premium) saves the future -> allowed (excellent!)

Start the worker (./runworkflow.sh) and the backend first, then:
  .venv/bin/python -m workflows.cli
"""

import asyncio

from temporalio.client import Client, WorkflowFailureError

from workflows.auth import FORGED_TOKENS, GOOD_TOKENS
from workflows.client import connect
from workflows.config import TASK_QUEUE
from workflows.interceptors.client_auth import JWTClientInterceptor, LicenseError
from workflows.models import TripRequest
from workflows.workflow import ChronoTripWorkflow

# The token used for the *next* start_workflow call. The client interceptor's
# get_token callback reads this, mirroring how the web app forwards each
# request's token. None means "send no token", exercising the no-license path.
_next_token: list[str | None] = [None]


async def book(client: Client, label: str, token: str | None, mission: str = "") -> None:
    _next_token[0] = token
    print(f"\n=== {label} ===")
    try:
        handle = await client.start_workflow(
            ChronoTripWorkflow.run,
            TripRequest(destination="San Dimas, 1988", mission=mission),
            id=f"chrono-{label.replace(' ', '-').replace(',', '').lower()}",
            task_queue=TASK_QUEUE,
        )
        result = await asyncio.wait_for(handle.result(), timeout=8)
        print(f"  result: {result}")
    except LicenseError as exc:
        print(f"  rejected before start (client interceptor): {exc}")
    except WorkflowFailureError as exc:
        print(f"  workflow failed: {getattr(exc.cause, 'message', exc.cause)}")
    except asyncio.TimeoutError:
        state = await handle.query(ChronoTripWorkflow.get_state)
        print(f"  still running ({state['status']}): {state['reason']}")


async def main() -> None:
    client = await connect(
        interceptors=[JWTClientInterceptor(get_token=lambda: _next_token[0])],
    )
    await book(client, "Bill's valid license", GOOD_TOKENS["bill"])
    await book(client, "no license", None)
    await book(client, "forged license", FORGED_TOKENS["evil-bill"])
    await book(client, "Ted (standard) saves the future", GOOD_TOKENS["ted"], "Save the future")
    await book(client, "Bill (premium) saves the future", GOOD_TOKENS["bill"], "Save the future")


if __name__ == "__main__":
    asyncio.run(main())
