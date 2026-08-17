"""The credential check the workflow-startup interceptor schedules.

One activity, `verify_grant`, and it is deliberately not in `activities.py`: that module
is the trip's business steps, and this is not one of them. Nothing in `workflow.py` calls
this. It exists because an interceptor needed work done that an interceptor cannot do.

## Why the check is an activity and not interceptor code

The delegation grant on the workflow's start header is verified here rather than inside
the workflow interceptor that asks for the check
(`interceptors/workflow_startup.py`).

Workflow interceptors run inside the sandbox, where the wall clock and the network are
both off limits: reading the clock makes a replay diverge, and I/O is not available at
all. A JWT check under those constraints can only answer one question — *"was this signed
by the key I already hold, and is it well-formed?"* — and none of the questions that
actually decide whether a credential is good right now:

  * Is it **expired**? Needs a clock.
  * Has it been **revoked**, or the user deprovisioned? Needs the issuer (introspection,
    or a revocation list).
  * Is it signed by a key the issuer **still** publishes? Needs a JWKS fetch.

So an in-sandbox check has the shape of a security boundary while enforcing a strict
subset of one. An eight-hour-old grant belonging to an account disabled hours ago passes
it. Modelling that as "the guardrail" is misleading, which is why the check lives out
here.

Two properties make an activity the right home, and the second is the one that makes it
work: the clock and the network are legal here, **and** the result is recorded in Event
History. A replaying workflow reads the recorded verification outcome instead of
re-deciding it, so the workflow still replays identically forever — even though what
produced the outcome could not have run in the sandbox at all.

The general rule worth taking away: when a cross-cutting concern needs a clock, a
network, or anything else non-deterministic, the interceptor's job is to *schedule* the
work, not to do it.

## Failure classification

The two outcomes are deliberately different shapes:

  * **The grant is bad** (missing, malformed, forged, wrong type, wrong audience,
    expired) — that is a *result*, not an error. It returns a `GrantCheck` and the
    interceptor turns it into one non-retryable workflow failure. Retrying a forged token
    5 times just delays the same answer.
  * **The check could not be completed** — in this demo verification is local, so there
    is nothing to fail. Once a real JWKS fetch or introspection call lives here, that
    call being unreachable is *transient* and must raise a retryable error (as
    `interceptors/token_exchange.py` does with `TokenEndpointUnavailable`). Returning
    `valid=False` for an unreachable issuer would fail good trips whenever the IdP
    restarts — a check that fails closed on its own outage, in the one direction you did
    not intend.
"""

import time

from temporalio import activity

from workflows.auth import (
    REJECT_INVALID,
    TOKEN_AUDIENCE,
    USE_GRANT,
    current_grant,
    rejection_reason,
    verify_token,
)
from workflows.models import GrantCheck


@activity.defn
async def verify_grant() -> GrantCheck:
    """Verify the delegation grant from the workflow's start header — completely.

    Completely = signature, claim shape, token type, audience, **and expiry**. The last
    of those is the one the sandbox could never do, and the reason this check is an
    activity: `now=` reads the wall clock, which is legal out here.

    Takes no argument: the grant arrives on this activity's **header**, exactly as it
    does for the business activities, and the grant-propagation interceptor publishes it
    into `current_grant` before this code runs. An activity cannot read its own headers —
    only an activity interceptor can — so that contextvar is the seam. Removing
    `GrantPropagationInterceptor` from the worker would therefore make every grant look
    missing here, not just stop propagation.

    Where a real system would go further, all of it legal in an activity and none of it
    legal in the sandbox: fetch the issuer's JWKS instead of holding a shared secret, and
    call the IdP's introspection endpoint so a *revoked* grant is caught too. See the
    failure-classification note in this module's docstring before adding either — an
    unreachable issuer must be retryable, not a rejection.

    Returns a result rather than raising: a bad grant is an answer, and the interceptor is
    what converts it into a single non-retryable workflow failure.
    """
    grant = current_grant.get()
    now = time.time()
    traveler = verify_token(grant, now=now, audience=TOKEN_AUDIENCE, expect_use=USE_GRANT)
    if traveler is None:
        # Log the specific reason; the workflow failure message stays generic. A precise
        # reason handed back to the caller is an oracle — see the note in
        # `interceptors/client_auth.py`.
        reason = (
            rejection_reason(grant, now=now, audience=TOKEN_AUDIENCE, expect_use=USE_GRANT)
            or REJECT_INVALID
        )
        activity.logger.warning("[activity:verify-grant] grant rejected: %s", reason)
        return GrantCheck(valid=False, reason=reason)

    activity.logger.info(
        "[activity:verify-grant] grant verified for %s (%s)", traveler["id"], traveler["name"]
    )
    return GrantCheck(
        valid=True,
        traveler_id=traveler["id"],
        traveler_name=traveler["name"],
    )
