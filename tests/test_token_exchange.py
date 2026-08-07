"""Unit tests for the token-exchange interceptor's failure classification.

The distinction under test is the one that matters operationally: a refused grant is
permanent and must not retry, while an unreachable or broken token endpoint is
transient and must retry. Conflating them turns a restart of the token service into a
permanently failed trip.
"""

import httpx
import pytest
from temporalio.exceptions import ApplicationError

from workflows.auth import mint_delegation_grant, mint_token, verify_token
from workflows.interceptors import token_exchange as tx


@pytest.fixture(autouse=True)
def _clear_cache():
    tx._cache.clear()
    yield
    tx._cache.clear()


def _grant(sub="bill"):
    return mint_delegation_grant(verify_token(mint_token(sub, ttl=300)))


class _FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = str(self._payload)

    def json(self):
        return self._payload


def _patch_post(monkeypatch, behaviour, seen=None):
    """Replace the httpx POST the interceptor makes.

    Pass a list as `seen` to capture the kwargs of each call, so a test can assert on
    what actually went on the wire.
    """
    class _Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, *args, **kwargs):
            if seen is not None:
                seen.append(kwargs)
            return behaviour()
    monkeypatch.setattr(tx.httpx, "AsyncClient", lambda *a, **k: _Client())


def _ok_body(**overrides) -> dict:
    """A conformant RFC 8693 §2.2.1 success body."""
    return {
        "access_token": "tok-abc",
        "issued_token_type": tx.TOKEN_TYPE_ACCESS,
        "token_type": "Bearer",
        "expires_in": 120,
        **overrides,
    }


async def test_unreachable_token_endpoint_is_retryable(monkeypatch):
    def boom(): raise httpx.ConnectError("connection refused")
    _patch_post(monkeypatch, boom)

    with pytest.raises(ApplicationError) as excinfo:
        await tx._access_token_for(_grant())
    assert excinfo.value.type == "TokenEndpointUnavailable"
    assert excinfo.value.non_retryable is False


async def test_token_endpoint_5xx_is_retryable(monkeypatch):
    _patch_post(monkeypatch, lambda: _FakeResponse(503))

    with pytest.raises(ApplicationError) as excinfo:
        await tx._access_token_for(_grant())
    assert excinfo.value.type == "TokenEndpointUnavailable"
    assert excinfo.value.non_retryable is False


async def test_refused_grant_returns_no_credential(monkeypatch):
    """RFC 8693 §2.2.2: a refusal is a 400 with an OAuth error body. No exception here:
    the activity proceeds without a credential and the backend's 401 ends it
    non-retryably."""
    _patch_post(
        monkeypatch,
        lambda: _FakeResponse(400, {"error": "invalid_grant", "error_description": "expired"}),
    )
    assert await tx._access_token_for(_grant()) is None


async def test_200_without_a_token_returns_no_credential(monkeypatch):
    _patch_post(monkeypatch, lambda: _FakeResponse(200, {"expires_in": 120}))
    assert await tx._access_token_for(_grant()) is None


@pytest.mark.parametrize(
    "overrides",
    [
        # An issuer that answered with some other token format. Pasting one of these
        # into an `Authorization: Bearer` header would be meaningless.
        {"issued_token_type": tx.TOKEN_TYPE_JWT},
        {"issued_token_type": "urn:ietf:params:oauth:token-type:id_token"},
        # §2.2.1 marks it REQUIRED, so its absence is a broken issuer.
        {"issued_token_type": None},
        # Not a bearer token, so it cannot be used as one.
        {"token_type": "N_A"},
    ],
)
async def test_unusable_issued_token_type_returns_no_credential(monkeypatch, overrides):
    body = _ok_body(**overrides)
    body = {k: v for k, v in body.items() if v is not None}
    _patch_post(monkeypatch, lambda: _FakeResponse(200, body))
    assert await tx._access_token_for(_grant()) is None


async def test_request_is_form_encoded_and_rfc8693_shaped(monkeypatch):
    """§2.1: form-encoded, with the REQUIRED type parameters alongside each token."""
    seen = []
    _patch_post(monkeypatch, lambda: _FakeResponse(200, _ok_body()), seen=seen)
    await tx._access_token_for(_grant())

    kwargs = seen[0]
    assert "json" not in kwargs, "§2.1 requires application/x-www-form-urlencoded"
    form = kwargs["data"]
    assert form["grant_type"] == tx.EXCHANGE_GRANT_TYPE
    # Each token is accompanied by its type. That pairing is the REQUIRED part.
    assert form["subject_token_type"] == tx.TOKEN_TYPE_JWT
    assert form["actor_token"] and form["actor_token_type"] == tx.TOKEN_TYPE_JWT
    assert form["requested_token_type"] == tx.TOKEN_TYPE_ACCESS
    assert form["audience"] == tx.BACKEND_AUDIENCE
    # All values must be form-encodable scalars, not nested structures.
    assert all(isinstance(v, str) for v in form.values())


async def test_success_returns_and_caches_the_token(monkeypatch):
    calls = []
    def ok():
        calls.append(1)
        return _FakeResponse(200, _ok_body())
    _patch_post(monkeypatch, ok)

    grant = _grant()
    assert await tx._access_token_for(grant) == "tok-abc"
    assert await tx._access_token_for(grant) == "tok-abc"   # served from cache
    assert len(calls) == 1, "second call should not hit the token endpoint"
