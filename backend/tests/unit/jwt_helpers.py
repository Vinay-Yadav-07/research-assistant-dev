"""Locally signed Supabase-style tokens and a fake JWKS, so auth tests need no network."""

import json
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import jwt
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from jwt.algorithms import ECAlgorithm, RSAAlgorithm

from app.core.auth import JWTVerifier

SUPABASE_URL = "https://test-project.supabase.co"
ISSUER = f"{SUPABASE_URL}/auth/v1"
AUDIENCE = "authenticated"


@dataclass
class SigningKey:
    """A private key and its public JWK."""

    kid: str
    algorithm: str
    private_key: Any
    jwk: dict[str, Any]


def ec_key(kid: str) -> SigningKey:
    private_key = ec.generate_private_key(ec.SECP256R1())
    jwk = json.loads(ECAlgorithm.to_jwk(private_key.public_key()))
    return SigningKey(kid, "ES256", private_key, {**jwk, "kid": kid, "alg": "ES256", "use": "sig"})


def rsa_key(kid: str) -> SigningKey:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
    return SigningKey(kid, "RS256", private_key, {**jwk, "kid": kid, "alg": "RS256", "use": "sig"})


@dataclass
class FakeJWKS:
    """The project's published keys; counts fetches and can be made to fail."""

    keys: list[SigningKey]
    fetches: int = 0
    fail: bool = False
    clock: list[float] = field(default_factory=lambda: [1000.0])

    async def fetch(self) -> dict[str, Any]:
        self.fetches += 1
        if self.fail:
            raise OSError("JWKS unreachable")
        return {"keys": [key.jwk for key in self.keys]}

    def now(self) -> float:
        return self.clock[0]

    def advance(self, seconds: float) -> None:
        self.clock[0] += seconds

    def verifier(self, *, cache_seconds: float = 600, leeway_seconds: float = 30) -> JWTVerifier:
        return JWTVerifier(
            issuer=ISSUER,
            audience=AUDIENCE,
            fetch_jwks=self.fetch,
            cache_seconds=cache_seconds,
            leeway_seconds=leeway_seconds,
            clock=self.now,
        )


def issue(
    key: SigningKey,
    user_id: UUID,
    *,
    kid: str | None = None,
    **claims: Any,
) -> str:
    """A token like Supabase issues; `claims` override or (with None) remove defaults."""
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "iss": ISSUER,
        "aud": AUDIENCE,
        "role": "authenticated",
        "iat": now,
        "exp": now + 3600,
    }
    payload.update(claims)
    payload = {name: value for name, value in payload.items() if value is not None}
    headers = {"kid": kid if kid is not None else key.kid}
    return jwt.encode(payload, key.private_key, algorithm=key.algorithm, headers=headers)
