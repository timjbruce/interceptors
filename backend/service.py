"""Circuits of History — the JWT-authorized backend microservice.

This is the "real backend" the time-travel activities call over HTTP. It runs as
its own process so you can see the token actually cross the wire to a separate
service.

## What it accepts, and what it refuses

Resource endpoints require a **delegated access token** — `Authorization: Bearer
<jwt>` where the token's `sub` is the traveler, its `act` is the worker acting for
them, and its `aud` is this service. It validates signature, audience, type, and
**expiry** (this service has a clock, unlike the workflow sandbox).

It deliberately **refuses both a raw user license and a delegation grant**, even
perfectly valid ones. A subject token identifies a person; a grant only authorizes
asking for a credential. Neither is scoped to this service. That refusal is the point
of the on-behalf-of model: what you present here must name both who is acting and for
whom, and must have been minted for *this* audience.

  * no token                  -> 401
  * forged / expired          -> 401
  * raw subject license       -> 401 (wrong token type and audience)
  * delegation grant          -> 401 (its audience is the token endpoint)
  * delegated access token    -> 200, logged as "worker acting on behalf of user"
  * valid but unentitled      -> 403

## The /oauth2/token endpoint

Also hosted here: the RFC 8693 token endpoint the worker calls to redeem a grant.
That is a **demo shortcut** — an authorization server is not a resource server. In
production this lives in your IdP, on another host, holding a signing key this
service would never possess (it would verify with a public key from a JWKS endpoint
instead).

Start it with `./runbackend.sh` (defaults to :9000). Curl it directly to prove the
gate.
"""

import asyncio
import logging
import random
import time
from typing import Optional

from fastapi import FastAPI, Form, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from workflows.auth import (
    ACCESS_TTL,
    BACKEND_AUDIENCE,
    EXCHANGE_GRANT_TYPE,
    SUBJECT_TTL,
    TOKEN_TYPE_ACCESS,
    TOKEN_TYPE_JWT,
    USE_ACCESS,
    USE_SUBJECT,
    bearer_token,
    exchange_token,
    mission_entitlement_error,
    refresh_session_token,
    rejection_reason,
    verify_token,
)

# The message tags itself with [backend]; keep the format free of a second label.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)
logger = logging.getLogger("backend")

app = FastAPI(title="Circuits of History — backend")


class ScanBody(BaseModel):
    destination: str
    mission: str = ""
    force_review: bool = False


class JumpBody(BaseModel):
    destination: str


async def _simulated_latency() -> None:
    """Demo pacing: make each backend call take a few seconds so a trip is slow
    enough to observe. Not representative of real backend latency."""
    await asyncio.sleep(random.uniform(3, 7))


def _authorize(authorization: Optional[str], endpoint: str) -> dict:
    """Validate the delegated access token exactly like a real resource server would.

    Enforces four things a workflow interceptor could not: the token is of type
    `access` (not a raw user license), its audience is *this* service, it has not
    expired (we have a clock out here), and it names an actor.

    Rejects every failure with 401; the difference is only in the log line, not in
    the response the caller sees.
    """
    token = bearer_token(authorization)
    now = time.time()
    checks = dict(now=now, audience=BACKEND_AUDIENCE, expect_use=USE_ACCESS)
    caller = verify_token(token, **checks)
    if caller is None:
        # Log the precise reason; return a generic one. This is the disclosure policy
        # production should use everywhere — contrast the client interceptor, which
        # deliberately surfaces "forged" for demo purposes (see its module docstring).
        logger.warning(
            "[backend] 401 on %s (%s)", endpoint, rejection_reason(token, **checks)
        )
        raise HTTPException(
            status_code=401,
            detail="Bogus! Backend requires a delegated Circuits of History access token.",
        )

    # Delegation, not impersonation: both identities are present, so the audit line
    # records who acted and for whom.
    logger.info(
        "[backend] authorized %s — worker=%s acting on behalf of traveler=%s (%s)",
        endpoint,
        caller.get("act", "?"),
        caller["id"],
        caller["name"],
    )
    return caller


@app.get("/health")
async def health() -> dict:
    return {"ok": True}


def _oauth_error(code: str, description: str, endpoint: str = "oauth2/token"):
    """Build an RFC 6749 §5.2 / RFC 8693 §2.2.2 error response.

    Note the status code: **400, not 401**. A token endpoint refusing a grant is
    reporting a bad request, not challenging the caller for credentials — 401 is for
    the *resource* server (see `_authorize`). Getting this backwards is the most common
    way a hand-rolled exchange endpoint stops being interoperable, because clients key
    their retry and error handling off the status.
    """
    logger.warning("[backend] 400 on %s (%s: %s)", endpoint, code, description)
    return JSONResponse(
        status_code=400,
        content={"error": code, "error_description": description},
        # RFC 6749 §5.1: responses carrying tokens must not be cached. Applied to the
        # error path too, so a proxy can't serve a stale answer either.
        headers={"Cache-Control": "no-cache, no-store", "Pragma": "no-cache"},
    )


@app.post("/oauth2/token")
async def token_exchange(
    grant_type: str = Form(default=""),
    # RFC 8693's parameter name for the token representing the party being acted
    # for. Here it carries the delegation grant.
    subject_token: Optional[str] = Form(default=None),
    subject_token_type: Optional[str] = Form(default=None),
    actor_token: Optional[str] = Form(default=None),
    actor_token_type: Optional[str] = Form(default=None),
    audience: Optional[str] = Form(default=None),
    resource: Optional[str] = Form(default=None),
    requested_token_type: Optional[str] = Form(default=None),
):
    """RFC 8693 token exchange: delegation grant + worker identity -> access token.

    Stands in for your IdP's token endpoint. See the module docstring: hosting this
    on the resource server is a demo shortcut, not a pattern to copy.

    Parameters arrive `application/x-www-form-urlencoded` (§2.1) — hence `Form(...)`
    rather than a JSON body model. The validation order below follows the RFC: shape
    of the request first (`invalid_request`), then the target (`invalid_target`), then
    the credentials themselves (`invalid_grant`).
    """
    if grant_type != EXCHANGE_GRANT_TYPE:
        # §2.2.2 defers to RFC 6749, which defines this exact code for a grant_type
        # the endpoint does not implement.
        return _oauth_error("unsupported_grant_type", f"unsupported grant_type: {grant_type!r}")

    # §2.1: `subject_token` and `subject_token_type` are both REQUIRED. The type is
    # what lets an endpoint that accepts several token formats know which parser to
    # use; refusing to infer it is the point.
    if not subject_token:
        return _oauth_error("invalid_request", "subject_token is required")
    if not subject_token_type:
        return _oauth_error("invalid_request", "subject_token_type is required")
    if subject_token_type != TOKEN_TYPE_JWT:
        return _oauth_error(
            "invalid_request",
            f"unsupported subject_token_type: {subject_token_type!r} (this endpoint accepts {TOKEN_TYPE_JWT})",
        )

    # §2.1: `actor_token_type` is REQUIRED when `actor_token` is present and MUST NOT
    # be included otherwise. Both halves of that are enforced — an `actor_token_type`
    # with no `actor_token` is a malformed request, not something to shrug at.
    if actor_token and not actor_token_type:
        return _oauth_error(
            "invalid_request", "actor_token_type is required when actor_token is present"
        )
    if actor_token and actor_token_type != TOKEN_TYPE_JWT:
        return _oauth_error(
            "invalid_request",
            f"unsupported actor_token_type: {actor_token_type!r} (this endpoint accepts {TOKEN_TYPE_JWT})",
        )
    if actor_token_type and not actor_token:
        return _oauth_error(
            "invalid_request", "actor_token_type MUST NOT be sent without actor_token"
        )

    # §2.1: `requested_token_type` is OPTIONAL, but if the client asks for something
    # this endpoint cannot mint, say so rather than silently substituting.
    if requested_token_type and requested_token_type != TOKEN_TYPE_ACCESS:
        return _oauth_error(
            "invalid_request", f"cannot issue requested_token_type: {requested_token_type!r}"
        )

    # §2.1: `audience` and `resource` both name the intended target. §2.2.2 specifies
    # `invalid_target` for a target this server won't issue for. Honouring it is what
    # keeps the issued token narrow — the audience is not a formality, it is the reason
    # a stolen access token is useless anywhere but here.
    target = audience or resource
    if target and target != BACKEND_AUDIENCE:
        return _oauth_error("invalid_target", f"will not issue tokens for target: {target!r}")

    access, error = exchange_token(subject_token, actor_token)
    if error:
        # The grant or the actor credential was itself rejected. RFC 6749 §5.2:
        # "the provided authorization grant ... is invalid, expired, revoked".
        return _oauth_error("invalid_grant", error)

    claims = verify_token(access, expect_use=USE_ACCESS) or {}
    logger.info(
        "[backend] issued delegated token — worker=%s on behalf of traveler=%s",
        claims.get("act", "?"),
        claims.get("id", "?"),
    )
    return JSONResponse(
        content={
            "access_token": access,
            "issued_token_type": TOKEN_TYPE_ACCESS,
            "token_type": "Bearer",
            "expires_in": ACCESS_TTL,
        },
        headers={"Cache-Control": "no-cache, no-store", "Pragma": "no-cache"},
    )


class RefreshBody(BaseModel):
    session_token: Optional[str] = None


@app.post("/oauth2/refresh")
async def refresh(body: RefreshBody) -> dict:
    """Re-issue an expiring session license. The IdP's refresh endpoint, in miniature.

    Called by the **client interceptor's `get_token` callback** (see `web/app.py`), so
    it is a live demonstration that real network I/O is legal in a client interceptor —
    the same call would be illegal inside a workflow interceptor.

    Demo shortcut, stated plainly: this accepts the expiring session token itself as
    proof of continuity. A real IdP requires a **refresh token** or a session cookie,
    and would never treat an expired access token as authorization to mint a new one.
    """
    fresh, error = refresh_session_token(body.session_token)
    if error:
        logger.warning("[backend] 401 on oauth2/refresh (%s)", error)
        raise HTTPException(status_code=401, detail=error)

    claims = verify_token(fresh, expect_use=USE_SUBJECT) or {}
    logger.info("[backend] refreshed session license for traveler=%s", claims.get("id", "?"))
    return {"session_token": fresh, "token_type": "Bearer", "expires_in": SUBJECT_TTL}


@app.post("/paradox-scan")
async def paradox_scan(body: ScanBody, authorization: Optional[str] = Header(default=None)) -> dict:
    traveler = _authorize(authorization, "paradox-scan")
    await _simulated_latency()
    # Defense in depth: re-enforce the premium-mission entitlement here, so a
    # request that bypassed the client interceptor still can't run a premium-only
    # mission from the standard group.
    entitlement_error = mission_entitlement_error(traveler, body.mission)
    if entitlement_error:
        logger.warning("[backend] 403 on paradox-scan: %s (%s)", traveler["id"], entitlement_error)
        raise HTTPException(status_code=403, detail=entitlement_error)
    if body.force_review:
        return {"flagged": True, "reason": "Bogus timeline! This journey could change history — Rufus must sign off."}
    if random.random() < 0.5:
        return {"flagged": True, "reason": "Whoa — the Circuits of History detected a most bogus paradox risk!"}
    return {"flagged": False, "reason": ""}


@app.post("/engage-booth")
async def engage_booth(body: JumpBody, authorization: Optional[str] = Header(default=None)) -> dict:
    traveler = _authorize(authorization, "engage-booth")
    await _simulated_latency()
    return {
        "arrival": f"Most excellent! Traveler {traveler['id']} arrived at {body.destination}. Party on, dudes!",
    }
