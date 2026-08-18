"""Circuits of History — licenses (JWTs), delegation, and token exchange.

The Wyld Stallyns time-travel booth runs on the Circuits of History. Every trip
needs a valid license; Rufus, from the future, administers the booth.

## Four kinds of token

This demo implements the **on-behalf-of** (delegation) model from RFC 8693,
OAuth 2.0 Token Exchange. Four distinct tokens, each with a `token_use` claim so
one can never be mistaken for another:

  * **subject** (`USE_SUBJECT`) — the user's session license, issued at login and
    held by the browser. Short-lived. Proves the user is present *right now*, which
    is what authorizes starting a trip. It never leaves the client tier.
  * **grant** (`USE_GRANT`) — a **delegation grant**: the artifact that actually
    rides on the Temporal header. Long-lived enough to span a workflow that waits
    on a human, but deliberately **not a credential for anything**: its audience is
    the token endpoint, not the backend, and its `may_act` names the single workload
    permitted to redeem it. Lifted out of Event History it is useless — it cannot
    call the backend, and it cannot be replayed against the web app as the user.
  * **actor** (`USE_ACTOR`) — the Temporal worker's own workload identity. In
    production this comes from your platform (a SPIFFE SVID, a Kubernetes service
    account token, cloud instance identity) and is rotated for you. Here the worker
    mints its own, which is a demo shortcut.
  * **access** (`USE_ACCESS`) — the short-lived result of redeeming a grant with an
    actor token. `sub` is the *user*, and `act` names the *worker*: "worker W acting
    on behalf of user U." Audience-restricted to the backend.

`mint_delegation_grant()` and `exchange_token()` are the authorization-server half of
that flow, reached over HTTP at `/oauth2/grant` and `/oauth2/token`. They live in this
module so the demo needs one fewer process; in production they are your IdP's, on a
different host, holding a key the resource server never sees.

## Why this shape, for Temporal specifically

The workflow never holds a usable credential. It propagates a *grant* as context;
each activity redeems it for a fresh access token at execution time, where a clock
and a network are legal. Three constraints force that shape:

  * **Event History is permanent.** Whatever rides on the header is durably stored,
    replicated, and readable by anyone with namespace read access — and it cannot be
    redacted. So the header must carry something useless on its own. Propagating the
    user's *session* token here would put a replayable credential in the log.
  * **Activity headers are frozen at scheduling.** They are written into
    `ActivityTaskScheduled` once, and retries reuse that event, so a token stamped
    at scheduling time goes stale and every retry presents an expired credential.
    Redemption has to happen per execution.
  * **Workflows outlive sessions.** A trip can wait on Rufus for hours. A user
    session token expires long before that, which is exactly why the long-lived
    thing on the header must be a tightly-scoped grant rather than a credential.

And nothing refreshed ever travels *back* through the workflow — that would write
live secrets into Event History permanently.

## Determinism

Every caller of `verify_token` in this demo passes `now=` and so gets the expiry
check, because every one of them runs *outside* the Workflow sandbox: the client
interceptor, the backend, the web tier, and `interceptors/auth_activities.verify_grant` — the
activity the workflow-startup interceptor schedules to check the header's grant.

Nothing verifies a token inside the sandbox, deliberately. Expiry needs a clock and
revocation needs a network, so an in-sandbox check is structurally limited to "was
this signed and well-formed," never "is this still valid right now" — a boundary
shaped like a security boundary while enforcing much less than one. Handing the
check to an activity gets the clock and the network back, and the recorded result is
what keeps replay deterministic. See `activities.py`.

(Omitting `now=` still makes this function pure — HMAC over bytes already in hand —
which is what the tests use to isolate the signature check from the clock.)

## Demo shortcuts (deliberate)

HS256 with the secret in this file, so every verifier is also a minter: anyone can
sign a token claiming `group: premium`. Production uses asymmetric keys (RS256/
ES256) so verifiers hold only public keys, plus real `aud` per service and
sender-constrained tokens (DPoP / mTLS binding).
"""

import base64
import contextvars
import hashlib
import hmac
import json
import os
import time
from typing import Optional

# Fake shared signing secret. In the real world this lives in your identity
# provider and is never committed to source control.
_SECRET = b"circuits-of-time-dev-secret-not-for-real-use"

_ISSUER = "circuits-of-time"
_SCOPE = "time-travel"

# The worker's workload identity. In production this is issued by your platform
# (SPIFFE / k8s service account / cloud IAM), not self-minted.
WORKER_IDENTITY = os.getenv("WORKER_IDENTITY", "worker-wyld-stallyns")

# The resource server's audience. An access token minted for this audience must
# not be replayable against any other service.
BACKEND_AUDIENCE = os.getenv("BACKEND_AUDIENCE", "circuits-of-time-backend")

# The token endpoint's audience. A delegation grant is scoped to *this* and nothing
# else, which is what makes it useless as a credential: the backend will refuse it
# because the audience does not match.
TOKEN_AUDIENCE = os.getenv("TOKEN_AUDIENCE", "circuits-of-time-token-endpoint")

# Token lifetimes, in seconds.
SUBJECT_TTL = 900       # user session license — short: proves the user is present
ACTOR_TTL = 300         # worker workload credential
ACCESS_TTL = 120        # redeemed access token: outlives one backend call, no more
# A grant must span the whole workflow, including a wait on a human reviewer, so it
# is long-lived — affordable only because it is audience- and actor-restricted and
# authorizes nothing by itself. In production, bound this to the workflow's expected
# lifetime and revoke it when the workflow closes.
GRANT_TTL = 8 * 3600

# How long after a session license expires it can still be refreshed. Past this, the
# traveller logs in again. Stands in for a refresh token's lifetime.
REFRESH_GRACE = 3600

# Refresh this many seconds *before* expiry, so a booking cannot start with a token
# that dies mid-request.
REFRESH_SKEW = 60

# Pre-minted demo fixtures (CLI, tests) get a long life so a demo session does not
# expire mid-run. Real logins use SUBJECT_TTL.
_FIXTURE_TTL = 12 * 3600

# `token_use` values. Checking this prevents token-type confusion — a grant must
# never be usable where an access token is required, and vice versa.
USE_SUBJECT = "subject"
USE_GRANT = "grant"
USE_ACTOR = "actor"
USE_ACCESS = "access"

# RFC 8693 wire vocabulary, shared by both halves of the exchange so the client and
# the token endpoint cannot drift. These are the registered URIs from the RFC, not
# names of our own choosing:
#   grant type       — §2.1
#   token type URIs  — §3 ("Token Type Identifiers")
# Our grant and actor credentials are both JWTs, so they are declared as `:jwt`;
# what we ask for back is an access token.
EXCHANGE_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:token-exchange"
TOKEN_TYPE_JWT = "urn:ietf:params:oauth:token-type:jwt"
TOKEN_TYPE_ACCESS = "urn:ietf:params:oauth:token-type:access_token"

# The claim vocabulary. A token is only well-formed if its `role` and `group` are
# drawn from these sets, so a token minted for an unknown subject (or one missing
# its claims) is rejected without any directory lookup.
#
# Keep these stable. They are evaluated inside the Workflow sandbox, so changing
# them is a workflow-code change: an in-flight run could replay differently.
# (Adding or removing *users* is safe — the validation path never reads the
# directory.)
ROLES: frozenset[str] = frozenset({"traveler", "admin"})
GROUPS: frozenset[str] = frozenset({"premium", "standard"})

# The issuer's user directory — stands in for the user table in an IdP.
# Read ONLY by mint_token(). Never consulted when validating a token.
ISSUER_USERS: dict[str, dict] = {
    "bill": {"name": "Bill S. Preston, Esq.", "role": "traveler", "group": "premium"},
    "ted": {"name": 'Ted "Theodore" Logan', "role": "traveler", "group": "standard"},
    "rufus": {"name": "Rufus", "role": "admin", "group": "premium"},
}

# Impostor dudes — the evil robot doubles from Bogus Journey. Their claims are
# perfectly well-formed; the *only* thing wrong with their licenses is the
# signature (minted below with the wrong secret). That keeps the demo honest:
# a forged token fails signature verification, not a shape or lookup check.
IMPOSTOR_CLAIMS: dict[str, dict] = {
    "evil-bill": {"name": "Evil Bill (robot double)", "role": "traveler", "group": "premium"},
    "evil-ted": {"name": "Evil Ted (robot double)", "role": "traveler", "group": "standard"},
}

# Business policy: some missions are premium-only. Enforced from the `group` claim
# in the client interceptor (fast reject) AND at the backend.
PREMIUM_ONLY_MISSIONS: set[str] = {"Save the future"}

# The propagated **delegation grant** — context, deliberately NOT a usable
# credential. The header-propagation interceptor sets this (always, even to None)
# from the workflow header. Setting it unconditionally on every execution prevents a
# header-less run from reading a value left by a previous execution on the same
# worker.
current_grant: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "current_grant", default=None
)

# The exchanged **access** token the activity actually presents to the backend.
# Set per activity execution by the token-exchange interceptor.
current_access_token: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "current_access_token", default=None
)


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def _encode(payload: dict, *, secret: bytes) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    signing_input = (
        _b64url_encode(json.dumps(header, separators=(",", ":")).encode())
        + "."
        + _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    )
    signature = hmac.new(secret, signing_input.encode(), hashlib.sha256).digest()
    return signing_input + "." + _b64url_encode(signature)


def _decode_claims(token: Optional[str]) -> Optional[dict]:
    """Decode a JWT's payload claims WITHOUT verifying the signature."""
    if not token:
        return None
    try:
        return json.loads(_b64url_decode(token.split(".")[1]))
    except Exception:
        return None


def _signature_ok(token: str) -> bool:
    try:
        header_b64, payload_b64, sig_b64 = token.split(".")
        expected = hmac.new(_SECRET, f"{header_b64}.{payload_b64}".encode(), hashlib.sha256).digest()
        return hmac.compare_digest(expected, _b64url_decode(sig_b64))
    except Exception:
        return False


def _claims_identity(claims: Optional[dict]) -> Optional[dict]:
    """Build an identity from the token's own claims, or None if malformed.

    No directory lookup: the claims *are* the identity. A token is well-formed only
    if it carries a subject, a display name, and a `role`/`group` drawn from the
    known vocabulary — which is what rejects a token minted for an unknown subject,
    since such a token has no role/group claims to begin with.

    When the token carries an `act` (actor) claim, the returned identity includes
    `act` — that is the "on behalf of" half of the delegation.
    """
    if not claims:
        return None
    sub, name = claims.get("sub"), claims.get("name")
    role, group = claims.get("role"), claims.get("group")
    if not sub or not name or role not in ROLES or group not in GROUPS:
        return None
    identity = {"id": sub, "name": name, "role": role, "group": group}
    actor = (claims.get("act") or {}).get("sub")
    if actor:
        identity["act"] = actor
    return identity


def mint_token(
    sub: str,
    *,
    secret: bytes = _SECRET,
    claims: Optional[dict] = None,
    ttl: int = _FIXTURE_TTL,
    now: Optional[float] = None,
) -> str:
    """Issue a **subject** license (HS256 JWT): the user's session credential.

    This is the ONLY function that reads the issuer's user directory — exactly as a
    real IdP reads its user table when issuing a token. Pass `claims` to mint from
    an explicit record instead (used for the impostors' forged licenses).

    A subject token proves the user is present *now* and is what authorizes starting
    a trip. It carries no `may_act` and is never propagated to a worker — delegation
    is a separate artifact (`mint_delegation_grant`) with its own audience and TTL.

    An unknown `sub` with no `claims` still mints a syntactically valid JWT, but one
    carrying no `name`/`role`/`group` — so `verify_token` rejects it.
    """
    user = claims if claims is not None else ISSUER_USERS.get(sub, {})
    issued = time.time() if now is None else now
    # `scope` is illustrative only — nothing in the demo reads it. Entitlement
    # rides on `group`; in a real OAuth 2.0 system it would likely live here.
    payload: dict = {
        "sub": sub,
        "iss": _ISSUER,
        "scope": _SCOPE,
        "token_use": USE_SUBJECT,
        "iat": int(issued),
        "exp": int(issued + ttl),
    }
    payload.update({k: user[k] for k in ("name", "role", "group") if k in user})
    return _encode(payload, secret=secret)


def mint_delegation_grant(
    identity: dict,
    *,
    may_act: str = WORKER_IDENTITY,
    audience: str = TOKEN_AUDIENCE,
    secret: bytes = _SECRET,
    ttl: int = GRANT_TTL,
    now: Optional[float] = None,
) -> str:
    """Issue a **delegation grant** — the only auth artifact that rides the header
    from the client to the workflow.

    Three properties make it safe to store in Event History for the life of a
    workflow, which is the entire reason this token type exists:

      * `aud` is the **token endpoint**, so the backend refuses it outright,
      * `may_act` names **one** workload, so nobody else can redeem it,
      * it authorizes nothing by itself — the only thing you can do with it is ask
        the token endpoint for a short-lived access token, as that one worker.

    Consequently a grant lifted out of Event History is inert: it cannot call the
    backend, and it cannot be replayed against the web app as the user (the web tier
    requires a `subject` token). That is the whole trade — long-lived, but useless.

    Signed by the authorization server, never by the client: the client interceptor
    requests one at `POST /oauth2/grant` (`backend/service.py`) and only stamps what
    comes back. A client able to mint its own grants could name any subject it liked,
    which is the whole reason this function lives on the IdP's side of the demo.
    """
    issued = time.time() if now is None else now
    return _encode(
        {
            "sub": identity["id"],
            "iss": _ISSUER,
            "aud": audience,
            "token_use": USE_GRANT,
            "name": identity["name"],
            "role": identity["role"],
            "group": identity["group"],
            "may_act": {"sub": may_act},
            "iat": int(issued),
            "exp": int(issued + ttl),
        },
        secret=secret,
    )


def mint_actor_token(
    sub: str = WORKER_IDENTITY,
    *,
    secret: bytes = _SECRET,
    ttl: int = ACTOR_TTL,
    now: Optional[float] = None,
) -> str:
    """Issue the worker's own **actor** (workload identity) credential.

    Demo shortcut: the worker signs its own. In production this is issued by the
    platform — a SPIFFE SVID, a projected Kubernetes service account token, or a
    cloud instance identity document — and rotated without your code involved.
    """
    issued = time.time() if now is None else now
    return _encode(
        {
            "sub": sub,
            "iss": _ISSUER,
            "token_use": USE_ACTOR,
            "iat": int(issued),
            "exp": int(issued + ttl),
        },
        secret=secret,
    )


def mint_access_token(
    identity: dict,
    *,
    actor_sub: str,
    audience: str = BACKEND_AUDIENCE,
    secret: bytes = _SECRET,
    ttl: int = ACCESS_TTL,
    now: Optional[float] = None,
) -> str:
    """Issue a delegated **access** token: `sub` is the user, `act` is the worker.

    This is RFC 8693 *delegation* rather than *impersonation*: both identities stay
    present in the token, so the resource server can log and authorize on "worker W
    acting on behalf of user U" instead of losing the actor.
    """
    issued = time.time() if now is None else now
    return _encode(
        {
            "sub": identity["id"],
            "iss": _ISSUER,
            "aud": audience,
            "token_use": USE_ACCESS,
            "name": identity["name"],
            "role": identity["role"],
            "group": identity["group"],
            "act": {"sub": actor_sub},
            "iat": int(issued),
            "exp": int(issued + ttl),
        },
        secret=secret,
    )


def verify_token(
    token: Optional[str],
    *,
    now: Optional[float] = None,
    audience: Optional[str] = None,
    expect_use: Optional[str] = None,
) -> Optional[dict]:
    """Return the identity for a validly signed, well-formed token, else None.

    Returns None for every "should fail" case: a missing token, a malformed token, a
    bad signature (forged license), or a valid signature whose claims are missing or
    outside the known `role`/`group` vocabulary.

    Optional, caller-selected checks:
      * `now`        — reject an expired token. **Reads a clock, so only pass this
                       outside the Workflow sandbox.** Omit it and this function is
                       pure and replay-safe.
      * `audience`   — reject a token minted for a different service.
      * `expect_use` — reject a token of the wrong kind (see USE_* above).

    Pass `now=`. Every caller in this demo does, because every caller runs outside
    the sandbox — including the grant check, which is an activity precisely so that
    it can. Omitting it leaves an expired credential looking valid.
    """
    if not token or not _signature_ok(token):
        return None
    claims = _decode_claims(token)
    if not claims:
        return None
    if expect_use is not None and claims.get("token_use") != expect_use:
        return None
    if expect_use == USE_ACCESS and not (claims.get("act") or {}).get("sub"):
        # An access token without `act` names no actor, so it is impersonation
        # rather than delegation. Refuse it: the whole point of this model is that
        # the resource server can see who acted and for whom.
        return None
    if audience is not None and claims.get("aud") != audience:
        return None
    if now is not None:
        exp = claims.get("exp")
        if exp is None or float(exp) <= now:
            return None
    return _claims_identity(claims)


# Reason codes explaining why `verify_token` refused a token. Used for *logging* at
# every tier, and — only because this is a teaching demo — surfaced to the user by
# the client interceptor. See `rejection_reason` on why production would not.
REJECT_MISSING = "missing"
REJECT_MALFORMED = "malformed"
REJECT_FORGED = "forged"
REJECT_EXPIRED = "expired"
REJECT_WRONG_TYPE = "wrong-type"
REJECT_WRONG_AUDIENCE = "wrong-audience"
REJECT_UNKNOWN_SUBJECT = "unknown-subject"
REJECT_INVALID = "invalid"


def rejection_reason(
    token: Optional[str],
    *,
    now: Optional[float] = None,
    audience: Optional[str] = None,
    expect_use: Optional[str] = None,
) -> Optional[str]:
    """Explain why `verify_token` would refuse this token; None if it would accept.

    Takes the same arguments as `verify_token` so a caller can ask "why?" using
    exactly the checks it applied itself.

    **This is diagnostic, not a response body.** A precise failure reason is an
    oracle: it tells someone probing tokens which part to fix next. Production
    should log this and return something generic — which is what `backend/service.py`
    does. The client interceptor in this demo deliberately does the opposite, because
    showing "that license is forged" is the whole point of the Evil Bill persona; see
    the note in `interceptors/client_auth.py`.

    Of these, only `REJECT_EXPIRED` is safe to surface in production: it is
    actionable ("log in again") and reveals nothing the holder does not know.
    """
    if not token:
        return REJECT_MISSING
    claims = _decode_claims(token)
    if claims is None:
        return REJECT_MALFORMED
    if not _signature_ok(token):
        return REJECT_FORGED
    if expect_use is not None and claims.get("token_use") != expect_use:
        return REJECT_WRONG_TYPE
    if audience is not None and claims.get("aud") != audience:
        return REJECT_WRONG_AUDIENCE
    if now is not None:
        exp = claims.get("exp")
        if exp is None or float(exp) <= now:
            return REJECT_EXPIRED
    if _claims_identity(claims) is None:
        return REJECT_UNKNOWN_SUBJECT
    # Belt and braces: never report "acceptable" if verify_token disagrees.
    if verify_token(token, now=now, audience=audience, expect_use=expect_use) is None:
        return REJECT_INVALID
    return None


def verify_actor_token(token: Optional[str], *, now: Optional[float] = None) -> Optional[dict]:
    """Return `{"id": <workload sub>}` for a valid actor credential, else None.

    Deliberately separate from `verify_token`: a workload identity is not a person,
    so it carries no `name`/`role`/`group` and must not flow into code expecting a
    traveler.
    """
    if not token or not _signature_ok(token):
        return None
    claims = _decode_claims(token) or {}
    if claims.get("token_use") != USE_ACTOR or not claims.get("sub"):
        return None
    if now is not None:
        exp = claims.get("exp")
        if exp is None or float(exp) <= now:
            return None
    return {"id": claims["sub"]}


def exchange_token(
    grant_token: Optional[str],
    actor_token: Optional[str],
    *,
    audience: str = BACKEND_AUDIENCE,
    now: Optional[float] = None,
    ttl: int = ACCESS_TTL,
) -> tuple[Optional[str], Optional[str]]:
    """Authorization-server half of RFC 8693. Returns `(access_token, error)`.

    Redeems a **delegation grant** (not a user session token) plus the worker's own
    workload credential for a short-lived delegated access token. Four checks, in
    order — each one is a real control, not ceremony:

      1. the **actor** credential is valid and unexpired (who is redeeming this?),
      2. the **grant** is valid, unexpired, of type `grant`, and scoped to *this*
         endpoint's audience (this is the expiry check the sandbox cannot do),
      3. the grant's **`may_act`** names this specific actor (without it, any
         authenticated workload could redeem any grant — a confused deputy),
      4. only then mint a short-lived, backend-audience access token carrying `act`.

    In production this is your IdP's `/token` endpoint. It is here so the demo runs
    one fewer process.
    """
    when = time.time() if now is None else now

    actor = verify_actor_token(actor_token, now=when)
    if actor is None:
        return None, "invalid or expired actor (workload) credential"

    subject = verify_token(
        grant_token, now=when, expect_use=USE_GRANT, audience=TOKEN_AUDIENCE
    )
    if subject is None:
        return None, "invalid, expired, wrong-audience, or wrong-type delegation grant"

    permitted = ((_decode_claims(grant_token) or {}).get("may_act") or {}).get("sub")
    if permitted != actor["id"]:
        return None, f"grant does not permit {actor['id']} to act on its behalf"

    return mint_access_token(
        subject, actor_sub=actor["id"], audience=audience, ttl=ttl, now=when
    ), None


def refresh_session_token(
    token: Optional[str],
    *,
    now: Optional[float] = None,
    grace: int = REFRESH_GRACE,
    ttl: int = SUBJECT_TTL,
) -> tuple[Optional[str], Optional[str]]:
    """Re-issue a session license from one that is expiring or recently expired.

    Returns `(session_token, error)`. What it tolerates and what it does not:

      * **Signature and claim shape must be intact.** A forged license can never be
        refreshed — `verify_token` is called *without* `now`, so expiry is the only
        thing overlooked.
      * **Expiry is tolerated within `grace`.** Past that the session is too old and
        the traveller logs in again, exactly as a refresh token's own lifetime works.
      * **The new license is minted from the old one's claims**, not a directory
        lookup, so refresh keeps the claims-are-the-identity model intact.

    Demo shortcut: a real IdP proves continuity with a **refresh token** or a session
    cookie, and would never accept the expired access token itself as proof. The
    shape of the call is right; the credential presented is not.
    """
    when = time.time() if now is None else now
    identity = verify_token(token, expect_use=USE_SUBJECT)  # no `now`: ignore expiry
    if identity is None:
        return None, "not a valid session license"
    exp = float((_decode_claims(token) or {}).get("exp") or 0)
    if exp + grace <= when:
        return None, "session too old to refresh; log in again"
    return mint_token(identity["id"], claims=identity, ttl=ttl, now=when), None


def decode_identity(token: Optional[str]) -> Optional[dict]:
    """Read who a token belongs to WITHOUT verifying its signature.

    Cheaper than `verify_token` and used only *after* something upstream has already
    verified the same token — e.g. the workflow body reads the traveler's display
    name from a grant the startup interceptor's `verify_grant` activity has already
    verified, so the workflow itself never has to decide anything. Never
    authorize with this: an unsigned token that merely *looks* well-formed will
    pass. Use `verify_token` for any decision.
    """
    return _claims_identity(_decode_claims(token))


_PREMIUM_ONLY_NORMALIZED = {m.strip().casefold() for m in PREMIUM_ONLY_MISSIONS}


def mission_entitlement_error(traveler: Optional[dict], mission: str) -> Optional[str]:
    """Business policy: return a rejection message if this traveler's group can't
    run this mission, else None. Enforced client-side (fast reject) AND at the
    backend (defense in depth). The mission is normalized so casing/whitespace
    can't slip a premium-only mission past the check."""
    if (mission or "").strip().casefold() in _PREMIUM_ONLY_NORMALIZED and (traveler or {}).get("group") != "premium":
        group = (traveler or {}).get("group", "no")
        return f"Bogus! Saving the future requires a premium license (you're in the {group} group)."
    return None


def bearer_token(authorization: Optional[str]) -> Optional[str]:
    """Pull the token out of an `Authorization: Bearer <token>` header value."""
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return None


# De Nomolos's secret — wrong, so anything signed with it fails verification.
_WRONG_SECRET = b"de-nomolos-bogus-secret"

# Pre-minted good licenses, handy for the CLI demo...
GOOD_TOKENS: dict[str, str] = {sub: mint_token(sub) for sub in ISSUER_USERS}

# ...and forged licenses: correct JWT shape, correct claims, but signed with the
# wrong secret, so verify_token() rejects them exactly like a real tampered token.
FORGED_TOKENS: dict[str, str] = {
    sub: mint_token(sub, secret=_WRONG_SECRET, claims=claims)
    for sub, claims in IMPOSTOR_CLAIMS.items()
}
