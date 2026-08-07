"""Client interceptor — validate the license, enforce entitlement, stamp the header.

This is the demo's **primary** auth point. It runs in your own process, before
the request leaves for the Temporal service, and on every `start_workflow` it:

  1. **Validates** the caller's session license (`verify_token`) and rejects a
     missing, forged, expired, or unknown token *before the workflow starts* — so a
     bad request never becomes a (billable) Workflow Execution.
  2. **Enforces business entitlement** — some missions are premium-only
     (`mission_entitlement_error`), rejected here too.
  3. **Mints a delegation grant** and stamps *that* onto the Temporal header, so the
     workflow and its activities can act on the user's behalf without ever holding
     the user's own credential.

Client interceptors are the right home for all three: they run outside the Workflow
sandbox, so a clock (expiry) and real I/O (a JWKS fetch, or requesting the grant
from a real IdP) are legal here, and rejecting early avoids the billed start.

Step 3 is the security-critical one. The header's value is persisted in Event
History forever, so it must be something that cannot be replayed — see
`mint_delegation_grant`. The grant authorizes nothing by itself; activities redeem
it for a short-lived access token at execution time (`token_exchange.py`), and the
backend re-verifies that token as the real enforcement boundary.

## Error messages: this file is deliberately NOT production-shaped

When a license is refused, this interceptor tells the caller **which** check failed —
including "that license is forged." Do not copy that. A precise failure reason is an
**oracle**: it tells someone probing tokens exactly which part to fix next, turning
guesswork into a checklist. Production should return one generic rejection and put
the reason in a log, which is what `backend/service.py` does using the same
`rejection_reason` helper. The contrast between the two files is intentional.

The demo does it this way because a *caught forgery* is the whole point of the Evil
Bill / Evil Ted personas — "invalid license" would hide the thing you came to see.

The one reason worth surfacing for real is **expiry**: it is actionable ("log in
again") and reveals nothing the token's holder does not already know.
"""

import inspect
import logging
import time
from typing import Awaitable, Callable, Optional, Union

import temporalio.converter
from temporalio.client import (
    Interceptor,
    OutboundInterceptor,
    StartWorkflowInput,
    WorkflowHandle,
)

from workflows.auth import (
    REJECT_EXPIRED,
    REJECT_FORGED,
    REJECT_MISSING,
    USE_SUBJECT,
    mint_delegation_grant,
    mission_entitlement_error,
    rejection_reason,
    verify_token,
)

logger = logging.getLogger(__name__)

# The token source may be sync or async. An async one is what lets a client
# interceptor do real I/O — a refresh call, a JWKS fetch — which is legal here
# precisely because this runs outside the Workflow sandbox.
TokenSource = Callable[[], Union[Optional[str], Awaitable[Optional[str]]]]

# What the traveller is told when their license is refused.
#
# **This demo tells them more than production should.** Naming the specific fault —
# "that license is forged" — is an oracle: it tells someone probing tokens which part
# to fix next. It is here because demonstrating a *caught forgery* is the entire point
# of the Evil Bill / Evil Ted personas, and a generic "invalid license" would hide the
# thing you came to see.
#
# In production, keep the response generic and put the reason in the log only — which
# is exactly what `backend/service.py` does with the same `rejection_reason` helper.
# The one exception worth surfacing for real is **expiry**: it is actionable ("log in
# again") and tells the holder nothing they do not already know.
_GENERIC_REJECTION = "Bogus! A valid Circuits of Time license is required to travel."
_REJECTION_MESSAGES = {
    REJECT_MISSING: "Bogus! You need a Circuits of Time license to travel. Log in first.",
    REJECT_EXPIRED: "Whoa! Your Circuits of Time license has expired. Log in again.",
    # Demo-only specificity — see the note above.
    REJECT_FORGED: (
        "Bogus! That license is forged — the Circuits of Time know De Nomolos's "
        "handiwork. Nice try, evil robot double."
    ),
}

# What rides on the Temporal header. Named for what it is: a delegation grant, not
# a credential. An admin reading Event History should be able to tell at a glance
# that this value cannot be replayed anywhere.
GRANT_HEADER_KEY = "delegation-grant"


class LicenseError(Exception):
    """Raised client-side when a booking is rejected before it ever starts."""


class JWTClientInterceptor(Interceptor):
    """Client interceptor that validates + authorizes + stamps the license."""

    def __init__(self, get_token: TokenSource) -> None:
        # `get_token` is a callback rather than a fixed string so callers can plug in
        # real refresh logic. It may be **sync or async**: the web app passes an async
        # one that calls the IdP's refresh endpoint when the session is expiring
        # (network I/O, which is legal out here), while the CLI passes a plain lambda.
        self._get_token = get_token

    def intercept_client(self, next: OutboundInterceptor) -> OutboundInterceptor:
        return _JWTOutboundInterceptor(next, self._get_token)


class _JWTOutboundInterceptor(OutboundInterceptor):
    def __init__(self, next: OutboundInterceptor, get_token: TokenSource) -> None:
        super().__init__(next)
        self._get_token = get_token

    async def start_workflow(self, input: StartWorkflowInput) -> WorkflowHandle:
        # Await an async token source. This is the seam where token refresh happens:
        # `start_workflow` is already async, so the callback may do network I/O.
        token = self._get_token()
        if inspect.isawaitable(token):
            token = await token

        # 1. Authenticate. Reject before the workflow starts (no Action billed).
        #    This runs outside the sandbox, so it is the right place to check
        #    **expiry** — passing `now` reads the clock, which nothing inside a
        #    workflow may do (which is why the workflow-edge check of the grant is an
        #    activity). It also pins the token *type*, so a delegated access token
        #    cannot be replayed here to start a workflow.
        now = time.time()
        traveler = verify_token(token, now=now, expect_use=USE_SUBJECT)
        if traveler is None:
            reason = rejection_reason(token, now=now, expect_use=USE_SUBJECT)
            logger.warning("[interceptor:client] rejected start: %s", reason)
            raise LicenseError(_REJECTION_MESSAGES.get(reason, _GENERIC_REJECTION))

        # 2. Authorize. Business policy: some missions are premium-only. The
        #    mission is the TripRequest.mission the UI/CLI passed as the first arg.
        mission = getattr(input.args[0], "mission", "") if input.args else ""
        entitlement_error = mission_entitlement_error(traveler, mission)
        if entitlement_error:
            raise LicenseError(entitlement_error)

        # 3. Mint a DELEGATION GRANT and stamp that onto the header — never the
        #    user's session token.
        #
        #    Two reasons, and both matter:
        #      * Lifetime. A trip can wait hours on Rufus's review; the user's
        #        session token expires long before that, so propagating it would
        #        strand every long-running workflow when its activities could no
        #        longer obtain a credential.
        #      * Blast radius. Whatever goes on the header is written to Event
        #        History permanently and is readable by anyone with namespace read
        #        access. The session token would be replayable against this very web
        #        app as the user. A grant is not: its audience is the token endpoint,
        #        and only the named worker may redeem it.
        grant = mint_delegation_grant(traveler)
        payload_converter = temporalio.converter.default().payload_converter
        input.headers = {
            **(input.headers or {}),
            GRANT_HEADER_KEY: payload_converter.to_payload(grant),
        }
        return await super().start_workflow(input)
