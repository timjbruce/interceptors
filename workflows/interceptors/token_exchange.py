"""Token-exchange interceptor — redeem the delegation grant for a real credential.

*Category: Activity inbound (worker, outside the sandbox).*

This is the interceptor that makes the **on-behalf-of** model work. Before every
activity execution it:

  1. reads the propagated **delegation grant** off the activity header,
  2. presents it, together with the worker's own **actor** (workload) credential,
     to the token endpoint,
  3. receives a short-lived **access** token whose `sub` is the user and whose `act`
     is this worker, and
  4. stashes it in `current_access_token` for the activity to present as its Bearer.

The activity code stays unchanged and knows nothing about any of it. This is the
seam that lets the credential lifecycle live entirely outside business logic.

## Why this belongs on activity inbound and nowhere else

**It needs I/O, so it cannot be in the workflow.** The exchange is a network call.
Workflow interceptors run inside the sandbox; activity interceptors do not.

**It must run per execution, not per scheduling.** An activity's headers are written
into `ActivityTaskScheduled` once, when the workflow schedules it. Retries reuse that
same event, so a token stamped at scheduling time goes stale and every retry would
present the expired credential. Exchanging here — on each `execute_activity`, which
runs once per *attempt* — means attempt 12 an hour later gets a fresh token.

**The result must not travel back through the workflow.** Anything a workflow
receives is persisted in Event History forever, so returning refreshed credentials
to the workflow would write live secrets into durable storage. The workflow keeps
propagating the grant — which authorizes nothing — and credentials are minted here,
at the edge, then discarded.

**A grant, not the user's session token.** The grant is long-lived enough to span a
trip that waits hours on Rufus, whereas the user's session token expires in minutes.
That is why the header carries a grant: without it, every long-running workflow would
strand when its activities could no longer obtain a credential.

## Conformance to RFC 8693

The exchange on the wire is the real thing, not a JSON approximation of it, because
the interoperability is the point — swap this demo's token endpoint for an IdP that
implements the RFC and the interceptor should not need editing:

  * **§2.1** — parameters are form-encoded (`application/x-www-form-urlencoded`),
    which the RFC states as a MUST.
  * **§2.1** — `subject_token_type` is sent (REQUIRED), and `actor_token_type` is sent
    because `actor_token` is present (REQUIRED exactly then, forbidden otherwise).
  * **§2.1** — `audience` and `requested_token_type` are sent though both are OPTIONAL:
    the audience is what narrows the issued token to one service.
  * **§2.2.1** — `issued_token_type` and `token_type` on the response are *checked*
    rather than assumed, so an issuer answering with some other token format cannot
    have it pasted into a Bearer header.
  * **§2.2.2** — refusals are read as OAuth error bodies (`error`,
    `error_description`), not as this project's own shape.
  * **§4.1 / §4.4** — the issued token carries `act` (the acting worker) and the grant
    carries `may_act` (who is permitted to act). Those two claims are what make this
    delegation rather than impersonation (§1.1).

## Failure classification

Two very different things can go wrong here, and they must not be conflated:

  * **The grant is refused** (400 + `invalid_grant` / `invalid_request` /
    `invalid_target`: forged, expired, wrong audience, not redeemable by this worker).
    Note that a refusal is a 400, not a 401 — the token endpoint is reporting a bad
    request, not challenging for credentials. No retry fixes any of these, so the
    interceptor returns no credential and lets the backend's 401 fail the activity
    non-retryably.
  * **The token endpoint is unreachable or broken** (transport failure, or 5xx). That
    is transient, so this raises a **retryable** `TokenEndpointUnavailable` instead.
    Returning None there would hand the activity no credential, earn a 401, and get
    classified as non-retryable - turning a restart of the token service into a
    permanently failed trip.

## Replay

Nothing here affects determinism. Activity interceptors are outside the sandbox and
their results are recorded, so a replaying workflow reads the recorded activity
outcome instead of re-running any of this.
"""

import time
from typing import Any, Optional

import httpx
import temporalio.converter
from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.worker import (
    ActivityInboundInterceptor,
    ExecuteActivityInput,
    Interceptor,
)

from workflows.auth import (
    BACKEND_AUDIENCE,
    EXCHANGE_GRANT_TYPE,
    TOKEN_TYPE_ACCESS,
    TOKEN_TYPE_JWT,
    WORKER_IDENTITY,
    current_access_token,
    decode_identity,
    mint_actor_token,
)
from workflows.config import BACKEND_URL
from workflows.interceptors.client_auth import GRANT_HEADER_KEY

# Re-exchange this many seconds before the access token actually expires, so a slow
# backend call cannot outlive the credential it started with.
_REFRESH_SKEW = 30

# Per-worker cache of access tokens, keyed by the grant that produced them. Keeps a
# burst of activities for one trip from hammering the token endpoint. Process-local
# and intentionally simple: it holds short-lived credentials in memory only.
_cache: dict[str, tuple[str, float]] = {}


class TokenExchangeInterceptor(Interceptor):
    """Worker interceptor: redeem the delegation grant for a delegated access token."""

    def intercept_activity(self, next: ActivityInboundInterceptor) -> ActivityInboundInterceptor:
        return _ExchangingActivityInbound(next)


class _ExchangingActivityInbound(ActivityInboundInterceptor):
    async def execute_activity(self, input: ExecuteActivityInput) -> Any:
        grant = _grant_from(input.headers)
        access = await _access_token_for(grant) if grant else None
        # Always set (reset), even to None, so an activity without a grant can never
        # read a credential left behind by a previous execution on this worker.
        current_access_token.set(access)
        try:
            return await super().execute_activity(input)
        finally:
            current_access_token.set(None)


def _rfc_error(resp) -> str:
    """Render an RFC 8693 §2.2.2 / RFC 6749 §5.2 error body for the log line."""
    try:
        body = resp.json()
        code = body.get("error", "unknown")
        described = body.get("error_description")
        return f"{code}: {described}" if described else code
    except Exception:
        return f"HTTP {resp.status_code}"


def _grant_from(headers) -> Optional[str]:
    payload = (headers or {}).get(GRANT_HEADER_KEY)
    if payload is None:
        return None
    try:
        return temporalio.converter.default().payload_converter.from_payload(payload, str)
    except Exception:
        return None


async def _access_token_for(grant: str) -> Optional[str]:
    """Return a cached or freshly redeemed access token, or None if refused."""
    now = time.time()
    cached = _cache.get(grant)
    if cached and cached[1] - _REFRESH_SKEW > now:
        return cached[0]

    traveler = decode_identity(grant)  # for the log line only; the endpoint verifies
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # RFC 8693 §2.1: the parameters go in the entity-body as
            # `application/x-www-form-urlencoded`, not JSON. httpx's `data=` does that.
            resp = await client.post(
                f"{BACKEND_URL}/oauth2/token",
                data={
                    "grant_type": EXCHANGE_GRANT_TYPE,
                    # `subject_token` is the RFC's name for "the token representing the
                    # party on behalf of whom the request is being made" — here that is
                    # the delegation grant, not the user's session token. Its companion
                    # `subject_token_type` is REQUIRED, not decorative: it is what stops
                    # the endpoint from having to guess at the format it was handed.
                    "subject_token": grant,
                    "subject_token_type": TOKEN_TYPE_JWT,
                    # The acting party — this worker. `actor_token_type` is REQUIRED
                    # whenever `actor_token` is present, and MUST NOT appear otherwise.
                    "actor_token": mint_actor_token(),
                    "actor_token_type": TOKEN_TYPE_JWT,
                    # Both OPTIONAL. We send them because they are what makes the
                    # issued token narrow: `audience` names the one service the token
                    # may be spent at, so a leaked token is useless elsewhere.
                    "audience": BACKEND_AUDIENCE,
                    "requested_token_type": TOKEN_TYPE_ACCESS,
                },
            )
    except Exception as exc:
        # Could not reach the token endpoint at all. This is transient, so raise a
        # RETRYABLE error rather than returning None. Returning None would leave the
        # activity with no credential, the backend would answer 401, and the activity
        # would classify that 4xx as non-retryable - turning a DNS blip or a restart
        # of the token service into a permanently failed trip.
        activity.logger.warning("[interceptor:exchange] token endpoint unreachable: %s", exc)
        raise ApplicationError(
            f"Token endpoint unreachable: {exc}",
            type="TokenEndpointUnavailable",
        ) from exc

    if resp.status_code >= 500:
        # The issuer is up but broken. Also transient, so also retryable.
        activity.logger.warning(
            "[interceptor:exchange] token endpoint error %s", resp.status_code
        )
        raise ApplicationError(
            f"Token endpoint returned {resp.status_code}",
            type="TokenEndpointUnavailable",
        )

    if resp.status_code != 200:
        # RFC 8693 §2.2.2: a refusal is a 400 carrying an OAuth 2.0 error body —
        # `invalid_grant` (forged, expired, wrong audience, not redeemable by this
        # worker), `invalid_request` (malformed), `invalid_target` (we asked for an
        # audience the issuer won't mint for). Retrying cannot fix any of those, so
        # fall through with no credential and let the backend's 401 end the activity
        # non-retryably.
        activity.logger.warning(
            "[interceptor:exchange] exchange refused: %s", _rfc_error(resp)
        )
        return None

    body = resp.json()
    token, expires_in = body.get("access_token"), body.get("expires_in", 0)
    if not token:
        # A 200 with no token is a contract mismatch, not something a retry fixes.
        activity.logger.warning("[interceptor:exchange] token endpoint returned no access_token")
        return None

    # §2.2.1 makes `issued_token_type` REQUIRED precisely so the client never has to
    # assume what it got back. Check it instead of assuming: an issuer that answered
    # with a SAML assertion or an ID token would otherwise have it pasted into an
    # `Authorization: Bearer` header, where it means nothing.
    issued, token_type = body.get("issued_token_type"), body.get("token_type", "")
    if issued != TOKEN_TYPE_ACCESS or token_type.lower() != "bearer":
        activity.logger.warning(
            "[interceptor:exchange] unusable token: issued_token_type=%r token_type=%r",
            issued,
            token_type,
        )
        return None

    _cache[grant] = (token, now + float(expires_in))
    activity.logger.info(
        "[interceptor:exchange] %s acting on behalf of %s (expires in %ss)",
        WORKER_IDENTITY,
        (traveler or {}).get("id", "unknown"),
        int(expires_in),
    )
    return token
