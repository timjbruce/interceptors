"""Unit tests for the auth module (pure functions + the token-exchange logic)."""

import time

from workflows.auth import (
    BACKEND_AUDIENCE,
    FORGED_TOKENS,
    GOOD_TOKENS,
    TOKEN_AUDIENCE,
    USE_ACCESS,
    USE_GRANT,
    USE_SUBJECT,
    WORKER_IDENTITY,
    bearer_token,
    decode_identity,
    exchange_token,
    mint_access_token,
    mint_actor_token,
    mint_delegation_grant,
    mint_token,
    mission_entitlement_error,
    refresh_session_token,
    rejection_reason,
    verify_actor_token,
    verify_token,
)


def _grant(sub="bill", **kw):
    """A delegation grant for a registered user, as the client interceptor mints."""
    return mint_delegation_grant(verify_token(mint_token(sub, ttl=300)), **kw)


def test_verify_valid_token_returns_identity():
    t = verify_token(GOOD_TOKENS["bill"])
    assert t == {"id": "bill", "name": "Bill S. Preston, Esq.", "role": "traveler", "group": "premium"}


def test_identity_comes_from_claims_not_a_directory():
    # The claims ARE the identity: a validly signed token carries its own
    # name/role/group, with no lookup against ISSUER_USERS.
    t = verify_token(mint_token("gizmo", claims={"name": "Station", "role": "admin", "group": "premium"}))
    assert t == {"id": "gizmo", "name": "Station", "role": "admin", "group": "premium"}


def test_verify_rejects_unknown_role_or_group():
    bad_role = mint_token("bill", claims={"name": "Bill", "role": "wizard", "group": "premium"})
    bad_group = mint_token("bill", claims={"name": "Bill", "role": "traveler", "group": "gold"})
    no_name = mint_token("bill", claims={"role": "traveler", "group": "premium"})
    assert verify_token(bad_role) is None
    assert verify_token(bad_group) is None
    assert verify_token(no_name) is None


def test_verify_missing_token():
    assert verify_token(None) is None
    assert verify_token("") is None


def test_verify_malformed_token():
    assert verify_token("not-a-jwt") is None
    assert verify_token("only.two") is None


def test_verify_forged_token():
    # Correct JWT shape, wrong signing secret.
    assert verify_token(FORGED_TOKENS["evil-bill"]) is None


def test_verify_valid_signature_no_claims():
    # Correctly signed, but the issuer knows no such user, so it carries no
    # name/role/group claims and cannot be turned into an identity.
    assert verify_token(mint_token("nobody")) is None


def test_decode_identity_skips_signature_check():
    assert decode_identity(GOOD_TOKENS["ted"])["id"] == "ted"
    # A forged token has well-formed claims, so decode_identity — which does NOT
    # check the signature — accepts it. This is exactly why nothing authorizes on
    # decode_identity; verify_token is the gate.
    assert decode_identity(FORGED_TOKENS["evil-bill"])["id"] == "evil-bill"
    assert verify_token(FORGED_TOKENS["evil-bill"]) is None
    assert decode_identity(None) is None
    # Still rejects malformed claims, signature or no signature.
    assert decode_identity(mint_token("nobody")) is None


def test_mission_entitlement():
    bill = verify_token(GOOD_TOKENS["bill"])  # premium
    ted = verify_token(GOOD_TOKENS["ted"])  # standard
    assert mission_entitlement_error(ted, "Save the future") is not None
    assert mission_entitlement_error(bill, "Save the future") is None
    assert mission_entitlement_error(ted, "Ace our history report") is None
    assert mission_entitlement_error(None, "Save the future") is not None


# ---------------------------------------------------------------------------
# Expiry — and the determinism boundary around it.
# ---------------------------------------------------------------------------


def test_expiry_is_only_checked_when_a_clock_is_supplied():
    stale = mint_token("bill", ttl=60, now=time.time() - 10_000)
    # With a clock — which every caller in the demo supplies, because every caller
    # runs outside the sandbox (client interceptor, backend, web tier, and the
    # verify_grant activity): rejected.
    assert verify_token(stale, now=time.time()) is None
    # Without one, only the signature and claim shape are checked, so an expired
    # token still passes. That is exactly why the grant check is an activity rather
    # than inline in the workflow interceptor: in the sandbox this is all you get.
    assert verify_token(stale)["id"] == "bill"


def test_unexpired_token_passes_a_clocked_check():
    assert verify_token(mint_token("bill", ttl=300), now=time.time())["id"] == "bill"


# ---------------------------------------------------------------------------
# Token type confusion.
# ---------------------------------------------------------------------------


def test_token_use_prevents_type_confusion():
    subject = mint_token("bill", ttl=300)
    grant = _grant()
    access, _ = exchange_token(grant, mint_actor_token())

    # None of the three is usable in another's role.
    assert verify_token(subject, expect_use=USE_ACCESS) is None
    assert verify_token(subject, expect_use=USE_GRANT) is None
    assert verify_token(grant, expect_use=USE_ACCESS) is None
    assert verify_token(grant, expect_use=USE_SUBJECT) is None
    assert verify_token(access, expect_use=USE_SUBJECT) is None
    assert verify_token(access, expect_use=USE_GRANT) is None
    # Each is fine for its own purpose.
    assert verify_token(subject, expect_use=USE_SUBJECT)["id"] == "bill"
    assert verify_token(grant, expect_use=USE_GRANT)["id"] == "bill"
    assert verify_token(access, expect_use=USE_ACCESS)["id"] == "bill"


def test_actor_token_is_not_a_traveler_identity():
    actor = mint_actor_token()
    assert verify_actor_token(actor) == {"id": WORKER_IDENTITY}
    # A workload identity carries no name/role/group, so it can never flow into
    # code that expects a person.
    assert verify_token(actor) is None


# ---------------------------------------------------------------------------
# Audience restriction.
# ---------------------------------------------------------------------------


def test_audience_restriction():
    access, _ = exchange_token(_grant(), mint_actor_token())
    assert verify_token(access, audience=BACKEND_AUDIENCE, expect_use=USE_ACCESS)["id"] == "bill"
    assert verify_token(access, audience="some-other-service", expect_use=USE_ACCESS) is None


def test_grant_is_inert_as_a_credential():
    """The security property that justifies putting a grant in Event History."""
    grant = _grant()
    # The backend's check (access type + its own audience) refuses it.
    assert verify_token(grant, audience=BACKEND_AUDIENCE, expect_use=USE_ACCESS) is None
    # The web tier's session check refuses it, so it cannot be replayed as the user.
    assert verify_token(grant, expect_use=USE_SUBJECT) is None
    # Its audience is the token endpoint and nothing else.
    assert verify_token(grant, audience=TOKEN_AUDIENCE, expect_use=USE_GRANT)["id"] == "bill"
    assert verify_token(grant, audience=BACKEND_AUDIENCE, expect_use=USE_GRANT) is None


def test_grant_outlives_the_user_session():
    """Why the header carries a grant and not the session token: a trip can wait on a
    human far longer than a session lasts."""
    from workflows.auth import GRANT_TTL, SUBJECT_TTL

    assert GRANT_TTL > SUBJECT_TTL
    # Simulate a workflow that has been running longer than the user's session.
    later = time.time() + SUBJECT_TTL + 60
    assert verify_token(mint_token("bill", ttl=SUBJECT_TTL), now=later) is None
    grant = _grant()
    access, error = exchange_token(grant, mint_actor_token(now=later), now=later)
    assert error is None, "a grant must still redeem after the user's session expires"
    assert verify_token(access, now=later, expect_use=USE_ACCESS)["act"] == WORKER_IDENTITY


# ---------------------------------------------------------------------------
# RFC 8693 delegation: "worker acting on behalf of user".
# ---------------------------------------------------------------------------


def test_exchange_produces_delegated_token_naming_both_parties():
    access, error = exchange_token(_grant(), mint_actor_token())
    assert error is None
    identity = verify_token(access, now=time.time(), audience=BACKEND_AUDIENCE, expect_use=USE_ACCESS)
    # Delegation, not impersonation: the user is the subject, the worker is the actor.
    assert identity["id"] == "bill"
    assert identity["name"] == "Bill S. Preston, Esq."
    assert identity["act"] == WORKER_IDENTITY


def test_exchange_preserves_entitlement_group():
    access, _ = exchange_token(_grant("ted"), mint_actor_token())
    delegated = verify_token(access, expect_use=USE_ACCESS)
    assert delegated["group"] == "standard"
    # Policy still applies to the delegated token, so the backend can re-enforce it.
    assert mission_entitlement_error(delegated, "Save the future") is not None


def test_exchange_requires_a_valid_actor_credential():
    grant = _grant()
    assert exchange_token(grant, None)[1] is not None
    assert exchange_token(grant, "not-a-jwt")[1] is not None
    # A grant is not a workload credential.
    assert exchange_token(grant, grant)[1] is not None
    # An expired workload credential is refused too.
    stale_actor = mint_actor_token(ttl=60, now=time.time() - 10_000)
    assert exchange_token(grant, stale_actor)[1] is not None


def test_exchange_refuses_bad_expired_or_wrong_type_grant():
    actor = mint_actor_token()
    assert exchange_token(None, actor)[1] is not None
    assert exchange_token(FORGED_TOKENS["evil-bill"], actor)[1] is not None
    # A user session token is NOT a grant, even a valid one.
    assert exchange_token(mint_token("bill", ttl=300), actor)[1] is not None
    # An expired grant is refused (the expiry check the sandbox cannot do).
    stale = _grant(ttl=60, now=time.time() - 10_000)
    assert exchange_token(stale, actor)[1] is not None
    # A grant minted for another audience is refused.
    assert exchange_token(_grant(audience="somewhere-else"), actor)[1] is not None


def test_may_act_stops_an_unauthorized_worker():
    # The grant names which workload may redeem it (RFC 8693 `may_act`). Without this
    # check any authenticated workload could redeem any grant — a confused deputy.
    other = _grant(may_act="some-other-worker")
    access, error = exchange_token(other, mint_actor_token())
    assert access is None
    assert "act on its behalf" in error


def test_delegated_token_expires_independently_of_the_grant():
    # The access token is short-lived by design; redemption happens per activity
    # execution, so it only has to outlive one backend call.
    identity = verify_token(mint_token("bill", ttl=300), expect_use=USE_SUBJECT)
    stale_access = mint_access_token(
        identity, actor_sub=WORKER_IDENTITY, ttl=60, now=time.time() - 10_000
    )
    assert verify_token(stale_access, now=time.time(), expect_use=USE_ACCESS) is None
    assert verify_token(stale_access, expect_use=USE_ACCESS)["id"] == "bill"


# ---------------------------------------------------------------------------
# Rejection triage (diagnostic; see rejection_reason's docstring on disclosure).
# ---------------------------------------------------------------------------


def test_rejection_reason_distinguishes_causes():
    now = time.time()
    r = lambda tok: rejection_reason(tok, now=now, expect_use=USE_SUBJECT)
    assert r(None) == "missing"
    assert r("") == "missing"
    assert r("not-a-jwt") == "malformed"
    assert r("only.two") == "malformed"
    # Evil Bill's license is well-formed and UNEXPIRED — only the signature is wrong.
    assert r(FORGED_TOKENS["evil-bill"]) == "forged"
    assert r(mint_token("bill", ttl=60, now=now - 10_000)) == "expired"
    assert r(mint_token("nobody")) == "unknown-subject"
    assert r(_grant()) == "wrong-type"          # a grant cannot start a workflow
    # A good session token has no reason to be refused.
    assert r(mint_token("bill", ttl=300)) is None


def test_rejection_reason_agrees_with_verify_token():
    """The helper must never report acceptable when verify_token refuses."""
    now = time.time()
    checks = dict(now=now, audience=BACKEND_AUDIENCE, expect_use=USE_ACCESS)
    access, _ = exchange_token(_grant(), mint_actor_token())
    for tok in (None, "", "not-a-jwt", FORGED_TOKENS["evil-bill"], GOOD_TOKENS["bill"],
                _grant(), mint_token("nobody"), access):
        refused = verify_token(tok, **checks) is None
        assert (rejection_reason(tok, **checks) is not None) == refused, tok


# ---------------------------------------------------------------------------
# Session refresh (called from the client interceptor's get_token callback).
# ---------------------------------------------------------------------------


def test_refresh_reissues_a_recently_expired_license():
    from workflows.auth import REFRESH_GRACE

    now = time.time()
    stale = mint_token("bill", ttl=60, now=now - 120)          # expired 60s ago
    assert verify_token(stale, now=now) is None                 # confirm it is dead
    fresh, error = refresh_session_token(stale, now=now)
    assert error is None
    # The new license is live, still Bill, and still a subject token.
    identity = verify_token(fresh, now=now, expect_use=USE_SUBJECT)
    assert identity["id"] == "bill"
    assert identity["group"] == "premium"


def test_refresh_preserves_claims_without_a_directory_lookup():
    # Refresh must not re-derive identity from ISSUER_USERS, or it would reintroduce
    # the registry dependency D6 removed.
    now = time.time()
    odd = mint_token("gizmo", claims={"name": "Station", "role": "admin", "group": "premium"},
                     ttl=60, now=now - 120)
    fresh, error = refresh_session_token(odd, now=now)
    assert error is None
    assert verify_token(fresh, now=now) == {
        "id": "gizmo", "name": "Station", "role": "admin", "group": "premium",
    }


def test_refresh_refuses_beyond_the_grace_window():
    from workflows.auth import REFRESH_GRACE

    now = time.time()
    ancient = mint_token("bill", ttl=60, now=now - REFRESH_GRACE - 600)
    fresh, error = refresh_session_token(ancient, now=now)
    assert fresh is None
    assert "log in again" in error


def test_refresh_refuses_forged_and_wrong_type():
    now = time.time()
    # A forged license can never be refreshed — signature is still checked.
    assert refresh_session_token(FORGED_TOKENS["evil-bill"], now=now)[0] is None
    # Neither can a grant or an access token masquerade as a session.
    assert refresh_session_token(_grant(), now=now)[0] is None
    access, _ = exchange_token(_grant(), mint_actor_token())
    assert refresh_session_token(access, now=now)[0] is None
    assert refresh_session_token(None, now=now)[0] is None


def test_refresh_skew_triggers_before_actual_expiry():
    """The callback refreshes proactively, so a booking never starts with a license
    that dies mid-request."""
    from workflows.auth import REFRESH_SKEW

    now = time.time()
    expiring = mint_token("bill", ttl=REFRESH_SKEW // 2, now=now)
    # Still valid right now...
    assert verify_token(expiring, now=now) is not None
    # ...but the callback's skewed check already calls it expired.
    assert rejection_reason(expiring, now=now + REFRESH_SKEW, expect_use=USE_SUBJECT) == "expired"


def test_bearer_token():
    assert bearer_token("Bearer abc.def") == "abc.def"
    assert bearer_token("bearer abc") == "abc"
    assert bearer_token("abc") is None
    assert bearer_token("Bearer ") is None
    assert bearer_token(None) is None
