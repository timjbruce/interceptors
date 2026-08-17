"""Wyld Stallyns Time Travel — web client for the interceptor demo.

Start the Temporal dev server and the worker first, then:

    ./runweb.sh               # or: python -m uvicorn web.app:app --port 8000

and open http://localhost:8000.

Auth model — the token is NOT hard-coded here. The browser logs in as a dude,
receives its own license (JWT), stashes it for the session, and sends it in the
`Authorization: Bearer …` header on every request. This service just forwards
whatever token the request carries onto the Temporal start header (via the
client interceptor). Nothing on the booking path chooses a token for you.

That's what lets you open several sessions at once: Bill in one tab, Ted in
another (both booking journeys), and Rufus — the admin — in a third, reviewing
the timelines that got flagged.
"""

import asyncio
import contextlib
import contextvars
import logging
import pathlib
import time
from typing import AsyncIterator, Optional

import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from temporalio.client import Client, WorkflowFailureError
from temporalio.exceptions import WorkflowAlreadyStartedError

from workflows.auth import (
    FORGED_TOKENS,
    IMPOSTOR_CLAIMS,
    ISSUER_USERS,
    REFRESH_SKEW,
    REJECT_EXPIRED,
    SUBJECT_TTL,
    USE_SUBJECT,
    bearer_token,
    mint_token,
    rejection_reason,
    verify_token,
)
from workflows.client import connect
from workflows.config import BACKEND_URL, TASK_QUEUE
from workflows.workflow import ChronoTripWorkflow
from workflows.interceptors.client_auth import JWTClientInterceptor, LicenseError
from workflows.models import TripRequest

STATIC_DIR = pathlib.Path(__file__).parent / "static"

# Per-request token holder. The client interceptor's get_token() reads this, so
# each incoming HTTP request forwards its own caller's token (or none) without
# us rebuilding the Temporal client each time.
_request_token: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "request_token", default=None
)

# Set by the get_token callback when it refreshed the caller's license, so the
# booking response can hand the new one back to the browser.
_refreshed_token: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "refreshed_token", default=None
)

logger = logging.getLogger(__name__)

# Uvicorn configures handlers for its own loggers and leaves the root alone, so anything
# we log below WARNING is discarded by default. That is why a forged licence used to show
# up in this terminal (client_auth logs it at warning) and an entitlement refusal did not
# (it logs at info). Attach one handler to our two package loggers, and let propagation
# carry every child.
#
# Deliberately not `logging.basicConfig()`: that lands on the root logger and would also
# surface httpx's per-request INFO line, which floods this terminal during a demo.
_LOG_FORMAT = "%(asctime)s | %(levelname)s | %(filename)s:%(lineno)s | %(message)s"
for _pkg in ("workflows", "web"):
    _pkg_logger = logging.getLogger(_pkg)
    if not _pkg_logger.handlers:
        _handler = logging.StreamHandler()
        _handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        _pkg_logger.addHandler(_handler)
        _pkg_logger.setLevel(logging.INFO)

_client: Optional[Client] = None


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    global _client
    _client = await connect(
        interceptors=[JWTClientInterceptor(get_token=_token_for_start)],
    )
    yield


app = FastAPI(title="Wyld Stallyns Time Travel", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def client() -> Client:
    assert _client is not None, "Temporal client not connected"
    return _client


# ---------------------------------------------------------------------------
# Auth helpers — read the bearer token the browser sent.
# ---------------------------------------------------------------------------


def _session_identity(authorization: Optional[str]) -> Optional[dict]:
    """Verify the browser's session license. Runs in the web tier, which has a
    clock, so it enforces expiry and pins the token type to `subject`."""
    return verify_token(bearer_token(authorization), now=time.time(), expect_use=USE_SUBJECT)


async def _token_for_start() -> Optional[str]:
    """`get_token` callback for the client interceptor — refreshing on the way through.

    This is the callback the interceptor was designed around, doing the thing it
    exists for: if the caller's session license is expiring (or recently expired), it
    calls the IdP's refresh endpoint over HTTP and returns the fresh one.

    **That network call is the point.** Client interceptors run outside the Workflow
    sandbox, so I/O here is legal — the identical call inside a workflow interceptor
    would be a determinism violation. It is also why the interceptor accepts an async
    token source.

    The refreshed license is stashed in `_refreshed_token` so the booking response can
    hand it back to the browser; otherwise the browser keeps sending the stale one and
    we would refresh on every request.
    """
    token = _request_token.get()
    if token is None:
        return None

    # Refresh proactively: treat a token expiring within REFRESH_SKEW as expired, so a
    # booking never starts with a license that dies mid-request.
    reason = rejection_reason(token, now=time.time() + REFRESH_SKEW, expect_use=USE_SUBJECT)
    if reason != REJECT_EXPIRED:
        return token  # good, or broken in a way refresh cannot fix (forged, wrong type)

    try:
        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.post(
                f"{BACKEND_URL}/oauth2/refresh", json={"session_token": token}
            )
    except Exception as exc:
        logger.warning("[interceptor:client] refresh endpoint unreachable: %s", exc)
        return token  # let the interceptor reject it, with "expired"

    if resp.status_code != 200:
        logger.info("[interceptor:client] refresh refused: %s", resp.text[:120])
        return token

    fresh = resp.json().get("session_token")
    if not fresh:
        return token
    _refreshed_token.set(fresh)
    logger.info("[interceptor:client] refreshed an expiring session license")
    return fresh


def _with_refreshed(payload: dict) -> dict:
    """Attach a refreshed session license to a response, if the callback minted one.

    Without this the browser would keep sending the stale token and we would refresh
    on every single request. A real SPA does the same thing (or sets a cookie).
    """
    fresh = _refreshed_token.get()
    return {**payload, "token": fresh} if fresh else payload


def _require_admin(authorization: Optional[str]) -> dict:
    identity = _session_identity(authorization)
    if not identity or identity.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Bogus! Only Rufus can review the Circuits of History.")
    return identity


# ---------------------------------------------------------------------------
# Request models.
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    identity: str  # a key in ISSUER_USERS or IMPOSTOR_CLAIMS, or "none"


class BookRequest(BaseModel):
    destination: str
    mission: str = ""
    force_review: bool = False


class ReviewRequest(BaseModel):
    workflow_id: str
    decision: str  # "approved" | "rejected"


# ---------------------------------------------------------------------------
# Routes.
# ---------------------------------------------------------------------------


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/identities")
async def identities() -> dict:
    """Who you can log in as (drives the login dropdown)."""
    dudes = [{"value": k, "label": v["name"], "role": v["role"]} for k, v in ISSUER_USERS.items()]
    impostors = [
        {"value": k, "label": f"{v['name']} — forged", "role": v["role"]}
        for k, v in IMPOSTOR_CLAIMS.items()
    ]
    demo = [{"value": "none", "label": "No license (unlicensed dude)", "role": "traveler"}]
    return {"identities": dudes + impostors + demo}


@app.post("/api/login")
async def login(body: LoginRequest) -> dict:
    """Issue the caller their own license. This is the ONLY place a token is
    minted; from here on the browser holds it and sends it with each request."""
    if body.identity in IMPOSTOR_CLAIMS:
        # Evil robot double: well-formed claims, but signed with the wrong secret,
        # so every verifying hop bounces it.
        claims = IMPOSTOR_CLAIMS[body.identity]
        return {
            "token": FORGED_TOKENS[body.identity],
            "name": claims["name"],
            "role": claims["role"],
            "group": claims["group"],
        }
    if body.identity == "none":
        return {"token": "", "name": "Unlicensed Dude", "role": "traveler", "group": "—"}
    record = ISSUER_USERS.get(body.identity)
    if record is None:
        raise HTTPException(status_code=400, detail="Unknown dude.")
    return {
        "token": mint_token(body.identity, ttl=SUBJECT_TTL),
        "name": record["name"],
        "role": record["role"],
        "group": record["group"],
    }


@app.post("/api/book")
async def book(body: BookRequest, authorization: Optional[str] = Header(default=None)) -> dict:
    # Forward whatever token the caller sent — we don't pick one.
    token = bearer_token(authorization)
    _request_token.set(token)
    _refreshed_token.set(None)

    # One trip per traveler at a time. A stable per-traveler workflow ID lets
    # Temporal enforce this for us: starting a second trip while the current one
    # is still running raises WorkflowAlreadyStartedError (a completed/failed
    # trip's ID is free to reuse). Falls back to "anonymous" for an unlicensed
    # caller, whose start the client interceptor rejects before it reaches here.
    caller = verify_token(token, now=time.time(), expect_use=USE_SUBJECT)
    traveler_id = caller["id"] if caller else "anonymous"
    wf_id = f"chrono-trip-{traveler_id}"

    # The client interceptor validates + authorizes before the workflow starts;
    # a bad license or a premium-only mission is rejected here (no workflow, no
    # billed Action).
    try:
        handle = await client().start_workflow(
            ChronoTripWorkflow.run,
            TripRequest(
                destination=body.destination or "somewhere in time",
                mission=body.mission,
                force_review=body.force_review,
            ),
            id=wf_id,
            task_queue=TASK_QUEUE,
        )
    except LicenseError as exc:
        return _with_refreshed({"status": "failed", "message": str(exc)})
    except WorkflowAlreadyStartedError:
        return _with_refreshed({
            "status": "failed",
            "message": "Whoa! You've still got a trip on the Circuits of History. Let it finish before booking another.",
        })

    # An un-flagged trip resolves fast; a flagged trip is still waiting for Rufus
    # when we time out.
    try:
        message = await asyncio.wait_for(handle.result(), timeout=10)
        return _with_refreshed({"status": "completed", "workflow_id": wf_id, "message": message})
    except asyncio.TimeoutError:
        state = await handle.query(ChronoTripWorkflow.get_state)
        return _with_refreshed({"status": state["status"], "workflow_id": wf_id, "detail": state})
    except WorkflowFailureError as exc:
        cause = exc.cause
        message = getattr(cause, "message", str(cause))
        return _with_refreshed({"status": "failed", "workflow_id": wf_id, "message": message})


@app.get("/api/trip/{workflow_id}")
async def trip(workflow_id: str, authorization: Optional[str] = Header(default=None)) -> dict:
    """Live status poll for a traveler's own trip: its current step and — once
    done — the outcome.

    We query the workflow state (running or closed) so the traveler sees progress
    in real time, and the read enforces ownership (a traveler sees only their own
    trip; admins may see any). At scale you'd expose progress via Search
    Attributes rather than a Query Action per poll; fine at demo scale.
    """
    caller = _session_identity(authorization)
    if caller is None:
        raise HTTPException(status_code=401, detail="Bogus! Log in first.")

    handle = client().get_workflow_handle(workflow_id)
    try:
        state = await handle.query(ChronoTripWorkflow.get_state)
    except Exception:
        # A failed workflow (e.g. the raw-start bypass) can't be queried; surface
        # the failure reason, which carries no cross-traveler data.
        try:
            await handle.result()
        except WorkflowFailureError as exc:
            return {"status": "failed", "workflow_id": workflow_id, "message": getattr(exc.cause, "message", str(exc.cause))}
        return {"status": "unknown", "workflow_id": workflow_id}

    if caller.get("role") != "admin" and state.get("traveler_id") != caller["id"]:
        raise HTTPException(status_code=403, detail="Bogus! That's not your trip.")

    return {
        "status": state["status"],
        "workflow_id": workflow_id,
        "message": state["arrival"],
    }


@app.get("/api/trips")
async def trips_list(authorization: Optional[str] = Header(default=None)) -> dict:
    """All running trips, for Rufus's control panel. Flagged trips wait here for
    an approve/reject. Admin only.

    Note: this queries each running workflow (a billable Query Action per poll).
    Fine at demo scale; at scale you'd track status with a Search Attribute and
    filter on it instead. The UI polls this on an interval and pauses when hidden.
    """
    _require_admin(authorization)
    trips = []
    async for wf in client().list_workflows(
        "WorkflowType = 'ChronoTripWorkflow' AND ExecutionStatus = 'Running'"
    ):
        handle = client().get_workflow_handle(wf.id)
        try:
            state = await handle.query(ChronoTripWorkflow.get_state)
        except Exception:
            continue
        trips.append({"workflow_id": wf.id, **state})
    return {"trips": trips}


@app.post("/api/review")
async def review(body: ReviewRequest, authorization: Optional[str] = Header(default=None)) -> dict:
    admin = _require_admin(authorization)
    handle = client().get_workflow_handle(body.workflow_id)
    await handle.signal(ChronoTripWorkflow.submit_review, args=[body.decision, admin["name"]])
    return {"ok": True}
