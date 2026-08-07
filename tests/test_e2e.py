"""End-to-end tests that drive the real system over HTTP.

No mocks: these call the live web client (:8000) and backend (:9000), which run
the real Temporal worker and its interceptors. The `stack` fixture (conftest.py)
starts the whole thing (or reuses a running one) and skips if it can't.

What this proves through real API calls:
- client auth + entitlement rejection (before any workflow starts),
- the paradox-scan review flow,
- ownership enforcement (IDOR) and admin-only endpoints,
- the backend's own JWT + entitlement gate.

Not reachable through real calls (the real backend never emits them), so left to
`test_auth.py` and covered only by the live smoke: the activity's 5xx-retryable
and malformed-body-non-retryable classification.
"""

import asyncio
import time

import httpx
import pytest
import temporalio.converter
from temporalio.client import (
    Client,
    Interceptor,
    OutboundInterceptor,
    StartWorkflowInput,
    WorkflowFailureError,
    WorkflowHandle,
)
from temporalio.common import SearchAttributeKey

from workflows.auth import (
    BACKEND_AUDIENCE,
    EXCHANGE_GRANT_TYPE,
    REFRESH_GRACE,
    TOKEN_TYPE_ACCESS,
    TOKEN_TYPE_JWT,
    USE_ACCESS,
    USE_SUBJECT,
    WORKER_IDENTITY,
    _decode_claims as _claims,
    mint_actor_token,
    mint_delegation_grant,
    mint_token,
    verify_token,
)
from workflows.interceptors.client_auth import GRANT_HEADER_KEY
from workflows.models import TripRequest
from workflows.workflow import ChronoTripWorkflow

WEB = "http://localhost:8000"
BACKEND = "http://localhost:9000"
TEMPORAL = "localhost:7233"
TASK_QUEUE = "interceptor-samples"

_TRAVELER_SA = SearchAttributeKey.for_keyword("Traveler")
_MISSION_SA = SearchAttributeKey.for_keyword("Mission")

pytestmark = pytest.mark.usefixtures("stack")

REGULAR_MISSION = "Ace our history report"
PREMIUM_MISSION = "Save the future"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"} if token else {}


class _HeaderStamper(Interceptor):
    """Put an arbitrary grant on the start header, skipping the real client checks.

    Lets a test hand the worker a grant the client interceptor would have refused, so
    the workflow-edge check can be exercised on its own.
    """

    def __init__(self, grant: str) -> None:
        self._grant = grant

    def intercept_client(self, next: OutboundInterceptor) -> OutboundInterceptor:
        return _StampingOutbound(next, self._grant)


class _StampingOutbound(OutboundInterceptor):
    def __init__(self, next: OutboundInterceptor, grant: str) -> None:
        super().__init__(next)
        self._grant = grant

    async def start_workflow(self, input: StartWorkflowInput) -> WorkflowHandle:
        input.headers = {
            **(input.headers or {}),
            GRANT_HEADER_KEY: temporalio.converter.default().payload_converter.to_payload(
                self._grant
            ),
        }
        return await super().start_workflow(input)


async def _login(c: httpx.AsyncClient, identity: str) -> dict:
    r = await c.post(f"{WEB}/api/login", json={"identity": identity})
    r.raise_for_status()
    return r.json()


async def _book(
    c, token, *, mission=REGULAR_MISSION, destination="1885", force_review=False
) -> dict:
    r = await c.post(
        f"{WEB}/api/book",
        headers=_auth(token),
        json={"destination": destination, "mission": mission, "force_review": force_review},
    )
    r.raise_for_status()
    return r.json()


async def _approve(c, wf: str) -> None:
    rufus = await _login(c, "rufus")
    r = await c.post(
        f"{WEB}/api/review",
        headers=_auth(rufus["token"]),
        json={"workflow_id": wf, "decision": "approved"},
    )
    r.raise_for_status()


# Trips are deliberately slow (per-step timers + simulated backend latency), so
# polls need a generous budget: worst case ~scan(7s) + 5s + 5s + jump(7s).
async def _poll_status(c, token, wf, want, *, tries=120, delay=0.5) -> dict:
    last = None
    for _ in range(tries):
        r = await c.get(f"{WEB}/api/trip/{wf}", headers=_auth(token))
        last = r
        if r.status_code == 200 and r.json().get("status") == want:
            return r.json()
        await asyncio.sleep(delay)
    raise AssertionError(f"{wf} never reached {want!r}; last={last.status_code} {last.text}")


async def _drive_to_completion(c, token, wf, *, tries=160, delay=0.5) -> dict:
    """Poll a trip until it closes, approving it if it lands in review. Handles
    the ~50% of unforced trips the paradox scan randomly flags."""
    approved = False
    last = None
    for _ in range(tries):
        r = await c.get(f"{WEB}/api/trip/{wf}", headers=_auth(token))
        last = r
        if r.status_code == 200:
            data = r.json()
            if data.get("status") in ("completed", "failed", "rejected"):
                return data
            if data.get("status") == "awaiting_review" and not approved:
                await _approve(c, wf)
                approved = True
        await asyncio.sleep(delay)
    raise AssertionError(f"{wf} never closed; last={last.status_code} {last.text}")


async def test_valid_booking_completes():
    async with httpx.AsyncClient(timeout=60) as c:
        bill = await _login(c, "bill")
        res = await _book(c, bill["token"])
        assert res["status"] != "failed"
        # With the step timers, `book` usually returns mid-flight; drive it to a
        # close (approving if the scan flagged it).
        if res["status"] != "completed":
            res = await _drive_to_completion(c, bill["token"], res["workflow_id"])
        assert res["status"] == "completed"
        assert res["message"]


async def test_premium_mission_rejected_for_basic_plan():
    async with httpx.AsyncClient(timeout=20) as c:
        ted = await _login(c, "ted")
        res = await _book(c, ted["token"], mission=PREMIUM_MISSION)
        assert res["status"] == "failed"
        assert "premium" in res["message"].lower()


async def test_premium_mission_allowed_for_premium_plan():
    async with httpx.AsyncClient(timeout=60) as c:
        bill = await _login(c, "bill")
        res = await _book(c, bill["token"], mission=PREMIUM_MISSION)
        assert res["status"] != "failed"
        # One trip per traveler: drive it to a close so later bill bookings are free.
        if res["status"] != "completed":
            await _drive_to_completion(c, bill["token"], res["workflow_id"])


async def test_no_license_rejected():
    async with httpx.AsyncClient(timeout=20) as c:
        res = await _book(c, "")  # "none" login issues an empty token
        assert res["status"] == "failed"


async def test_forged_token_rejected():
    async with httpx.AsyncClient(timeout=20) as c:
        evil = await _login(c, "evil-bill")
        res = await _book(c, evil["token"])
        assert res["status"] == "failed"
        # The demo names the specific fault so a caught forgery is visible. That is
        # deliberately NOT production behaviour — see client_auth.py's docstring.
        assert "forged" in res["message"].lower()
        # And it must not mislead: Evil Bill's license is well-formed and unexpired.
        assert "expired" not in res["message"].lower()


async def test_missing_license_message_is_distinct():
    async with httpx.AsyncClient(timeout=20) as c:
        res = await _book(c, "")
        assert res["status"] == "failed"
        assert "log in" in res["message"].lower()
        assert "forged" not in res["message"].lower()


async def test_flagged_trip_waits_then_approves():
    async with httpx.AsyncClient(timeout=60) as c:
        bill = await _login(c, "bill")
        res = await _book(c, bill["token"], force_review=True)
        wf = res["workflow_id"]
        # The scan + step timer run first, so poll until it parks for review.
        await _poll_status(c, bill["token"], wf, "awaiting_review")

        rufus = await _login(c, "rufus")
        r = await c.get(f"{WEB}/api/trips", headers=_auth(rufus["token"]))
        assert r.status_code == 200
        assert any(t["workflow_id"] == wf for t in r.json()["trips"])

        await _approve(c, wf)
        await _poll_status(c, bill["token"], wf, "completed")


async def test_second_trip_blocked_while_in_flight():
    async with httpx.AsyncClient(timeout=60) as c:
        bill = await _login(c, "bill")
        res = await _book(c, bill["token"], force_review=True)  # parks -> stays running
        wf = res["workflow_id"]
        await _poll_status(c, bill["token"], wf, "awaiting_review")

        # A second booking while the first is still in flight is refused.
        blocked = await _book(c, bill["token"])
        assert blocked["status"] == "failed"
        assert "trip" in blocked["message"].lower()

        # Once it finishes, booking is allowed again.
        await _approve(c, wf)
        await _poll_status(c, bill["token"], wf, "completed")
        again = await _book(c, bill["token"])
        assert again["status"] != "failed"
        await _drive_to_completion(c, bill["token"], again["workflow_id"])


async def test_trip_ownership_enforced_on_closed_trip():
    async with httpx.AsyncClient(timeout=60) as c:
        ted = await _login(c, "ted")
        res = await _book(c, ted["token"], force_review=True)
        wf = res["workflow_id"]
        await _poll_status(c, ted["token"], wf, "awaiting_review")
        await _approve(c, wf)
        await _poll_status(c, ted["token"], wf, "completed")  # owner can read it

        bill = await _login(c, "bill")
        r = await c.get(f"{WEB}/api/trip/{wf}", headers=_auth(bill["token"]))
        assert r.status_code == 403  # not Bill's trip


async def test_admin_endpoints_reject_travelers():
    async with httpx.AsyncClient(timeout=20) as c:
        ted = await _login(c, "ted")
        r = await c.get(f"{WEB}/api/trips", headers=_auth(ted["token"]))
        assert r.status_code == 403

        rufus = await _login(c, "rufus")
        r = await c.get(f"{WEB}/api/trips", headers=_auth(rufus["token"]))
        assert r.status_code == 200


async def test_startup_interceptor_tags_search_attributes():
    # The startup interceptor tags each run with Traveler + Mission search
    # attributes (auto-registered by the worker); they persist after close.
    async with httpx.AsyncClient(timeout=60) as c:
        bill = await _login(c, "bill")
        res = await _book(c, bill["token"], mission=REGULAR_MISSION)
        wf = res["workflow_id"]
        await _drive_to_completion(c, bill["token"], wf)  # also frees the traveler

    tclient = await Client.connect(TEMPORAL)
    desc = await tclient.get_workflow_handle(wf).describe()
    sa = desc.typed_search_attributes
    assert sa.get(_TRAVELER_SA) == "Bill S. Preston, Esq."  # display name, not the id
    assert sa.get(_MISSION_SA) == REGULAR_MISSION


async def test_workflow_guardrail_rejects_headerless_start():
    # Start WITHOUT the client interceptor -> no grant on the header. The startup
    # interceptor schedules its verify_grant activity, gets back "missing", and must
    # fail the trip fast (before any business activity) and non-retryably, rather
    # than letting it reach the backend.
    tclient = await Client.connect(TEMPORAL)
    handle = await tclient.start_workflow(
        ChronoTripWorkflow.run,
        TripRequest(destination="1885", mission=""),
        id="chrono-trip-bypass-test",
        task_queue=TASK_QUEUE,
    )
    with pytest.raises(WorkflowFailureError) as excinfo:
        await handle.result()
    cause = excinfo.value.cause
    # The failure is the interceptor's own ApplicationError, not an activity failure
    # wrapping one, and it names no specific reason (that is logged, not returned).
    assert "delegation grant" in str(cause).lower()
    assert getattr(cause, "type", None) == "InvalidDelegationGrant"


async def test_workflow_guardrail_rejects_an_expired_grant():
    """The check the in-sandbox version could not do: expiry.

    An expired delegation grant is well-formed and correctly signed, so a
    signature-only check inside the workflow would wave it through. Verification runs
    in an activity, where the clock is legal, so it is caught at the workflow edge.
    """
    async with httpx.AsyncClient(timeout=20) as c:
        bill = await _login(c, "bill")
    expired = mint_delegation_grant(
        verify_token(bill["token"]), ttl=60, now=time.time() - 10_000
    )
    assert _claims(expired)["token_use"] == "grant"  # well-formed and signed...
    assert verify_token(expired, expect_use="grant") is not None  # ...and signature-valid

    # Stamp that grant on the header, as the real client interceptor would.
    tclient = await Client.connect(TEMPORAL, interceptors=[_HeaderStamper(expired)])
    handle = await tclient.start_workflow(
        ChronoTripWorkflow.run,
        TripRequest(destination="1885", mission=""),
        id="chrono-trip-expired-grant-test",
        task_queue=TASK_QUEUE,
    )
    with pytest.raises(WorkflowFailureError) as excinfo:
        await handle.result()
    assert getattr(excinfo.value.cause, "type", None) == "InvalidDelegationGrant"


def _grant_for(session_token: str, **kw) -> str:
    """Mint the delegation grant the client interceptor would put on the header."""
    return mint_delegation_grant(verify_token(session_token), **kw)


async def _exchange(c, grant: str, **overrides) -> httpx.Response:
    """Do what the token-exchange interceptor does: redeem a delegation grant plus the
    worker's workload credential for a delegated access token.

    Form-encoded (`data=`, not `json=`) because RFC 8693 §2.1 requires it. Pass an
    override of None to drop a parameter entirely.
    """
    form = {
        "grant_type": EXCHANGE_GRANT_TYPE,
        "subject_token": grant,
        "subject_token_type": TOKEN_TYPE_JWT,
        "actor_token": mint_actor_token(),
        "actor_token_type": TOKEN_TYPE_JWT,
        "audience": BACKEND_AUDIENCE,
        "requested_token_type": TOKEN_TYPE_ACCESS,
        **overrides,
    }
    return await c.post(
        f"{BACKEND}/oauth2/token",
        data={k: v for k, v in form.items() if v is not None},
    )


async def test_backend_gate_directly():
    async with httpx.AsyncClient(timeout=20) as c:
        body = {"destination": "1885", "mission": REGULAR_MISSION}

        # No token -> 401.
        r = await c.post(f"{BACKEND}/paradox-scan", json=body)
        assert r.status_code == 401

        # Forged token -> 401.
        evil = await _login(c, "evil-bill")
        r = await c.post(f"{BACKEND}/paradox-scan", headers=_auth(evil["token"]), json=body)
        assert r.status_code == 401

        # A RAW USER LICENSE is refused, even though it is perfectly valid. It
        # identifies a person; it does not authorize a service call, and it is not
        # audience-scoped for this backend. This is the on-behalf-of model working.
        bill = await _login(c, "bill")
        r = await c.post(f"{BACKEND}/paradox-scan", headers=_auth(bill["token"]), json=body)
        assert r.status_code == 401

        # So is the DELEGATION GRANT that rides on the Temporal header. This is the
        # property that makes it safe to persist in Event History: lifted out of the
        # history it cannot call the backend at all.
        grant = _grant_for(bill["token"])
        r = await c.post(f"{BACKEND}/paradox-scan", headers=_auth(grant), json=body)
        assert r.status_code == 401

        # Redeem the grant for a delegated access token -> accepted.
        r = await _exchange(c, grant)
        assert r.status_code == 200
        access = r.json()["access_token"]
        r = await c.post(f"{BACKEND}/paradox-scan", headers=_auth(access), json=body)
        assert r.status_code == 200

        # Entitlement is re-enforced on the delegated token, so a standard-group
        # traveler still cannot run a premium-only mission -> 403.
        ted = await _login(c, "ted")
        ted_access = (await _exchange(c, _grant_for(ted["token"]))).json()["access_token"]
        r = await c.post(
            f"{BACKEND}/paradox-scan",
            headers=_auth(ted_access),
            json={"destination": "1885", "mission": PREMIUM_MISSION},
        )
        assert r.status_code == 403


async def test_session_refresh_endpoint():
    """The endpoint the client interceptor's get_token callback calls. Its existence is
    the demo's proof that real network I/O is legal in a client interceptor."""
    async with httpx.AsyncClient(timeout=20) as c:
        now = time.time()

        # A recently expired license refreshes into a live one.
        stale = mint_token("bill", ttl=60, now=now - 120)
        r = await c.post(f"{BACKEND}/oauth2/refresh", json={"session_token": stale})
        assert r.status_code == 200
        fresh = r.json()["session_token"]
        claims = _claims(fresh)
        assert claims["sub"] == "bill"
        assert claims["token_use"] == USE_SUBJECT
        assert float(claims["exp"]) > now

        # Too old -> refuse; the traveller logs in again.
        ancient = mint_token("bill", ttl=60, now=now - REFRESH_GRACE - 600)
        assert (await c.post(f"{BACKEND}/oauth2/refresh", json={"session_token": ancient})).status_code == 401

        # A forged license can never be refreshed.
        evil = await _login(c, "evil-bill")
        assert (await c.post(f"{BACKEND}/oauth2/refresh", json={"session_token": evil["token"]})).status_code == 401

        # Neither can a grant stand in for a session token.
        bill = await _login(c, "bill")
        grant = _grant_for(bill["token"])
        assert (await c.post(f"{BACKEND}/oauth2/refresh", json={"session_token": grant})).status_code == 401


async def test_booking_refreshes_an_expiring_license():
    """End to end: book with an expiring license and the interceptor's callback swaps
    it for a fresh one, handing the new token back in the response."""
    async with httpx.AsyncClient(timeout=60) as c:
        # A license that is still valid but inside the refresh skew.
        expiring = mint_token("ted", ttl=5)
        r = await c.post(
            f"{WEB}/api/book",
            headers=_auth(expiring),
            json={"destination": "1885", "mission": REGULAR_MISSION, "force_review": False},
        )
        r.raise_for_status()
        res = r.json()
        assert res["status"] != "failed", res
        # The response carries a refreshed license, and it is NOT the one we sent.
        assert res.get("token"), "expected a refreshed session token in the response"
        assert res["token"] != expiring
        assert float(_claims(res["token"])["exp"]) > float(_claims(expiring)["exp"])
        await _drive_to_completion(c, res["token"], res["workflow_id"])


async def test_token_exchange_endpoint():
    async with httpx.AsyncClient(timeout=20) as c:
        bill = await _login(c, "bill")

        # A successful exchange names both parties: sub is the traveler, act is the
        # worker. That is delegation, not impersonation.
        r = await _exchange(c, _grant_for(bill["token"]))
        assert r.status_code == 200
        claims = _claims(r.json()["access_token"])
        assert claims["sub"] == "bill"
        assert claims["act"]["sub"] == WORKER_IDENTITY
        assert claims["aud"] == BACKEND_AUDIENCE
        assert claims["token_use"] == USE_ACCESS

        # RFC 8693 §2.2.1: the client is told what it got, so it never has to guess.
        assert r.json()["issued_token_type"] == TOKEN_TYPE_ACCESS
        assert r.json()["token_type"] == "Bearer"
        # RFC 6749 §5.1: a token response must not be cached.
        assert "no-store" in r.headers.get("cache-control", "")

        # Every refusal below is a 400 with an OAuth error body -- NOT a 401. A token
        # endpoint rejecting a grant is reporting a bad request; 401 belongs to the
        # resource server (see test_backend_gate_directly).
        def refused(resp, code: str) -> bool:
            return resp.status_code == 400 and resp.json()["error"] == code

        # A forged license cannot produce a usable grant.
        evil = await _login(c, "evil-bill")
        assert refused(await _exchange(c, evil["token"]), "invalid_grant")

        # A valid user session token is not a grant, so it cannot be redeemed either.
        assert refused(await _exchange(c, bill["token"]), "invalid_grant")

        # Nor can a grant whose may_act names a different workload.
        assert refused(
            await _exchange(c, _grant_for(bill["token"], may_act="other-worker")),
            "invalid_grant",
        )

        # An unsupported grant type is a bad request, not an auth failure.
        assert refused(
            await _exchange(c, _grant_for(bill["token"]), grant_type="client_credentials"),
            "unsupported_grant_type",
        )


async def test_token_exchange_enforces_rfc8693_request_shape():
    """The parameters RFC 8693 §2.1 marks REQUIRED are actually required."""
    async with httpx.AsyncClient(timeout=20) as c:
        grant = _grant_for((await _login(c, "bill"))["token"])

        def refused(resp, code: str) -> bool:
            return resp.status_code == 400 and resp.json()["error"] == code

        # subject_token_type is REQUIRED -- omitted, and wrong, both rejected.
        assert refused(await _exchange(c, grant, subject_token_type=None), "invalid_request")
        assert refused(
            await _exchange(c, grant, subject_token_type="urn:ietf:params:oauth:token-type:saml2"),
            "invalid_request",
        )

        # actor_token_type is REQUIRED when actor_token is present...
        assert refused(await _exchange(c, grant, actor_token_type=None), "invalid_request")
        # ...and MUST NOT be sent without it.
        assert refused(await _exchange(c, grant, actor_token=None), "invalid_request")

        # An audience this endpoint won't mint for gets invalid_target, not a token
        # silently issued for the wrong service.
        assert refused(await _exchange(c, grant, audience="some-other-service"), "invalid_target")

        # Asking for a token type it cannot issue is refused rather than substituted.
        assert refused(
            await _exchange(c, grant, requested_token_type=TOKEN_TYPE_JWT), "invalid_request"
        )

        # A JSON body is not a form body. §2.1 is a MUST.
        r = await c.post(
            f"{BACKEND}/oauth2/token",
            json={"grant_type": EXCHANGE_GRANT_TYPE, "subject_token": grant},
        )
        assert r.status_code in (400, 415, 422)
