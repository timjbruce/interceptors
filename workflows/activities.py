"""ChronoLabs activities: the trip's business steps.

`paradox_scan` and `execute_jump`, both real HTTP calls to the JWT-authorized backend
(see `backend/service.py`). They run on the Worker, outside the Workflow sandbox, so real
network I/O and a real clock are fine here.

The credential check that the workflow-startup interceptor schedules lives in
`interceptors/auth_activities.py`, not here. It is registered on the same Worker and it is an activity
for the same reason these are, but it is not part of the trip, and keeping it out of this
module is the point: nothing in `workflow.py` asks for it.

## These activities do no token handling at all

Each presents a **delegated access token** as its `Bearer` credential, and never touches
the user's credentials. The token-exchange interceptor
(`interceptors/token_exchange.py`) has already redeemed the propagated delegation grant
for a short-lived token that says "this worker, acting on behalf of this traveler," and
left it in `current_access_token`. That is the whole point of putting it in an
interceptor — the credential lifecycle stays out of business code.

The client already validated the caller, so in the normal path the backend accepts the
redeemed token. If a request bypassed the client (e.g. a raw `temporal workflow start`)
there is no grant to redeem, so the backend returns 401 — and we turn that into a
**non-retryable** error so the activity fails fast instead of hammering the backend
forever.
"""

import httpx
from temporalio import activity
from temporalio.exceptions import ApplicationError

from workflows.auth import current_access_token
from workflows.config import BACKEND_URL
from workflows.models import ScanResult, TripRequest


def _auth_headers() -> dict:
    token = current_access_token.get()
    return {"Authorization": f"Bearer {token}"} if token else {}


async def _call_backend(path: str, body: dict) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(f"{BACKEND_URL}{path}", json=body, headers=_auth_headers())

    # 4xx is a client-side error (bad/absent license, bad request): it won't fix
    # itself on retry, so fail permanently instead of looping.
    if 400 <= resp.status_code < 500:
        detail = "rejected"
        try:
            detail = resp.json().get("detail", detail)
        except Exception:
            pass
        raise ApplicationError(
            f"Backend rejected the request ({resp.status_code}): {detail}",
            type="BackendClientError",
            non_retryable=True,
        )
    resp.raise_for_status()  # 5xx stays retryable (transient)

    try:
        return resp.json()
    except Exception as exc:
        # A 200 with an unparseable body is a contract mismatch, not transient.
        raise ApplicationError(
            "Backend returned an unparseable response.",
            type="BackendContractError",
            non_retryable=True,
        ) from exc


@activity.defn
async def paradox_scan(request: TripRequest, traveler_id: str) -> ScanResult:
    """Call the Paradox Risk Service (JWT-authorized) for this trip."""
    activity.logger.info(
        "[activity] calling paradox-scan backend for traveler %s -> %s",
        traveler_id,
        request.destination,
    )
    data = await _call_backend(
        "/paradox-scan",
        {
            "destination": request.destination,
            "mission": request.mission,
            "force_review": request.force_review,
        },
    )
    return ScanResult(data["flagged"], data["reason"])


@activity.defn
async def execute_jump(request: TripRequest, traveler_id: str) -> str:
    """Call the flux-capacitor service (JWT-authorized) to complete the journey."""
    activity.logger.info(
        "[activity] calling engage-booth backend for traveler %s -> %s",
        traveler_id,
        request.destination,
    )
    data = await _call_backend("/engage-booth", {"destination": request.destination})
    return data["arrival"]
