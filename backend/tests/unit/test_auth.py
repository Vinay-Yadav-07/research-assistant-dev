import base64
import time
from uuid import uuid4

import jwt
import pytest

from app.core.errors import AuthenticationError, DependencyUnavailableError
from tests.unit.jwt_helpers import FakeJWKS, SigningKey, ec_key, issue, rsa_key

USER = uuid4()


@pytest.fixture
def key_a() -> SigningKey:
    return ec_key("key-a")


@pytest.fixture
def jwks(key_a: SigningKey) -> FakeJWKS:
    return FakeJWKS(keys=[key_a])


async def test_valid_es256_token_returns_user(jwks: FakeJWKS, key_a: SigningKey) -> None:
    user = await jwks.verifier().verify(issue(key_a, USER))

    assert user.id == USER


async def test_valid_rs256_token_returns_user() -> None:
    key = rsa_key("rsa-key")
    user = await FakeJWKS(keys=[key]).verifier().verify(issue(key, USER))

    assert user.id == USER


@pytest.mark.parametrize(
    "claims",
    [
        {"iss": "https://other-project.supabase.co/auth/v1"},
        {"aud": "anon"},
        {"exp": int(time.time()) - 3600},
        {"exp": None},
        {"sub": None},
        {"sub": "not-a-uuid"},
    ],
    ids=["wrong-issuer", "wrong-audience", "expired", "no-exp", "no-sub", "sub-not-uuid"],
)
async def test_invalid_claims_are_rejected(
    jwks: FakeJWKS, key_a: SigningKey, claims: dict[str, object]
) -> None:
    with pytest.raises(AuthenticationError):
        await jwks.verifier().verify(issue(key_a, USER, **claims))


async def test_signature_from_another_key_is_rejected(jwks: FakeJWKS) -> None:
    forged = issue(ec_key("key-a"), USER)  # same kid, different private key

    with pytest.raises(AuthenticationError):
        await jwks.verifier().verify(forged)


@pytest.mark.parametrize("token", ["", "not-a-jwt", "a.b.c"])
async def test_malformed_token_is_rejected(jwks: FakeJWKS, token: str) -> None:
    with pytest.raises(AuthenticationError):
        await jwks.verifier().verify(token)


async def test_hs256_token_is_rejected(jwks: FakeJWKS) -> None:
    # Symmetric tokens (e.g. the legacy Supabase JWT secret) are never accepted.
    token = jwt.encode(
        {"sub": str(USER), "iss": "x", "aud": "authenticated", "exp": int(time.time()) + 60},
        "a-shared-secret-that-is-long-enough-for-hs256",
        algorithm="HS256",
        headers={"kid": "key-a"},
    )
    with pytest.raises(AuthenticationError):
        await jwks.verifier().verify(token)


async def test_alg_none_token_is_rejected(jwks: FakeJWKS, key_a: SigningKey) -> None:
    signed = issue(key_a, USER)
    _, payload, _ = signed.split(".")
    header = base64.urlsafe_b64encode(b'{"alg":"none","kid":"key-a"}').rstrip(b"=").decode()

    with pytest.raises(AuthenticationError):
        await jwks.verifier().verify(f"{header}.{payload}.")


async def test_algorithm_must_match_the_key(key_a: SigningKey) -> None:
    rsa = rsa_key("key-a")  # RS256 token whose kid points at the ES256 key
    jwks = FakeJWKS(keys=[key_a])

    with pytest.raises(AuthenticationError):
        await jwks.verifier().verify(issue(rsa, USER))


@pytest.mark.parametrize(("offset", "accepted"), [(-28, True), (-32, False)])
async def test_exp_leeway_is_30_seconds(
    jwks: FakeJWKS, key_a: SigningKey, offset: int, accepted: bool
) -> None:
    token = issue(key_a, USER, exp=int(time.time()) + offset)

    if accepted:
        assert (await jwks.verifier().verify(token)).id == USER
    else:
        with pytest.raises(AuthenticationError):
            await jwks.verifier().verify(token)


@pytest.mark.parametrize(("offset", "accepted"), [(28, True), (32, False)])
async def test_nbf_leeway_is_30_seconds(
    jwks: FakeJWKS, key_a: SigningKey, offset: int, accepted: bool
) -> None:
    token = issue(key_a, USER, nbf=int(time.time()) + offset)

    if accepted:
        assert (await jwks.verifier().verify(token)).id == USER
    else:
        with pytest.raises(AuthenticationError):
            await jwks.verifier().verify(token)


async def test_keys_are_cached(jwks: FakeJWKS, key_a: SigningKey) -> None:
    verifier = jwks.verifier()
    for _ in range(3):
        await verifier.verify(issue(key_a, USER))

    assert jwks.fetches == 1


async def test_cache_expires(jwks: FakeJWKS, key_a: SigningKey) -> None:
    verifier = jwks.verifier(cache_seconds=600)
    await verifier.verify(issue(key_a, USER))
    jwks.advance(601)
    await verifier.verify(issue(key_a, USER))

    assert jwks.fetches == 2


async def test_rotated_key_is_fetched_on_unknown_kid(jwks: FakeJWKS, key_a: SigningKey) -> None:
    verifier = jwks.verifier()
    await verifier.verify(issue(key_a, USER))
    key_b = ec_key("key-b")
    jwks.keys = [key_a, key_b]
    jwks.advance(31)

    user = await verifier.verify(issue(key_b, USER))

    assert user.id == USER
    assert jwks.fetches == 2


async def test_unknown_kid_refetch_is_rate_limited(jwks: FakeJWKS, key_a: SigningKey) -> None:
    verifier = jwks.verifier()
    await verifier.verify(issue(key_a, USER))
    stranger = ec_key("unknown")

    for _ in range(5):
        with pytest.raises(AuthenticationError):
            await verifier.verify(issue(stranger, USER))

    assert jwks.fetches == 1


async def test_jwks_unreachable_without_cached_keys_is_unavailable(
    jwks: FakeJWKS, key_a: SigningKey
) -> None:
    jwks.fail = True

    with pytest.raises(DependencyUnavailableError):
        await jwks.verifier().verify(issue(key_a, USER))


async def test_jwks_unreachable_keeps_cached_keys(jwks: FakeJWKS, key_a: SigningKey) -> None:
    verifier = jwks.verifier(cache_seconds=600)
    await verifier.verify(issue(key_a, USER))
    jwks.fail = True
    jwks.advance(601)

    assert (await verifier.verify(issue(key_a, USER))).id == USER
    await verifier.verify(issue(key_a, USER))
    assert jwks.fetches == 2  # the failed refresh is not retried on every request


async def test_jwks_without_usable_keys_rejects() -> None:
    jwks = FakeJWKS(keys=[])

    with pytest.raises(AuthenticationError):
        await jwks.verifier().verify(issue(ec_key("key-a"), USER))
