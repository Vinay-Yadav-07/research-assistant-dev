"""Supabase access-token verification against the project's JWKS (FR-01, D-049)."""

import asyncio
import json
import logging
import time
import urllib.request
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import jwt
from jwt import PyJWK

from app.core.errors import AuthenticationError, DependencyUnavailableError

logger = logging.getLogger(__name__)

# Supabase signs with asymmetric keys only; never accept HS256 or "none" (algorithm confusion).
ALLOWED_ALGORITHMS = frozenset({"ES256", "RS256"})
# An unknown `kid` refetches the key set at most this often, so forged tokens cannot hammer Auth.
UNKNOWN_KID_REFETCH_SECONDS = 30.0

JWKSFetcher = Callable[[], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class CurrentUser:
    """The authenticated caller; `id` is the Supabase `auth.users.id`."""

    id: UUID


def http_jwks_fetcher(url: str, *, timeout_seconds: float) -> JWKSFetcher:
    """Return a fetcher that downloads the JWKS document from `url`."""

    def fetch_sync() -> dict[str, Any]:
        with urllib.request.urlopen(url, timeout=timeout_seconds) as response:
            data: dict[str, Any] = json.load(response)
            return data

    async def fetch() -> dict[str, Any]:
        return await asyncio.to_thread(fetch_sync)

    return fetch


class JWTVerifier:
    """Verifies access tokens; keys are cached and refetched on expiry or an unknown `kid`."""

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        fetch_jwks: JWKSFetcher,
        cache_seconds: float,
        leeway_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._issuer = issuer
        self._audience = audience
        self._fetch_jwks = fetch_jwks
        self._cache_seconds = cache_seconds
        self._leeway_seconds = leeway_seconds
        self._clock = clock
        self._keys: dict[str, PyJWK] = {}
        self._fetched_at: float | None = None
        self._lock = asyncio.Lock()

    async def verify(self, token: str) -> CurrentUser:
        """Return the token's user, or raise `AuthenticationError` (the reason is logged)."""
        try:
            header = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError:
            raise self._reject("malformed token") from None
        algorithm = header.get("alg")
        if algorithm not in ALLOWED_ALGORITHMS:
            raise self._reject(f"algorithm {algorithm!r} not allowed")
        kid = header.get("kid")
        if not isinstance(kid, str):
            raise self._reject("no key id")
        key = await self._key(kid)
        if key is None:
            raise self._reject("unknown key id")
        if key.algorithm_name != algorithm:
            raise self._reject("algorithm does not match the key")
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=[algorithm],
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._leeway_seconds,
                options={"require": ["exp", "sub", "iss", "aud"]},
            )
        except jwt.InvalidTokenError as error:
            raise self._reject(f"{type(error).__name__}: {error}") from None
        try:
            return CurrentUser(id=UUID(str(claims["sub"])))
        except ValueError:
            raise self._reject("subject is not a user id") from None

    @staticmethod
    def _reject(reason: str) -> AuthenticationError:
        # Only the reason is logged: tokens are credentials and must never reach the logs.
        logger.info("Access token rejected: %s", reason)
        return AuthenticationError()

    async def _key(self, kid: str) -> PyJWK | None:
        if not self._expired() and kid in self._keys:
            return self._keys[kid]
        async with self._lock:
            if self._expired() or (kid not in self._keys and self._may_refetch()):
                await self._refresh()
            return self._keys.get(kid)

    def _expired(self) -> bool:
        return self._fetched_at is None or self._age() >= self._cache_seconds

    def _may_refetch(self) -> bool:
        return self._fetched_at is None or self._age() >= UNKNOWN_KID_REFETCH_SECONDS

    def _age(self) -> float:
        assert self._fetched_at is not None
        return self._clock() - self._fetched_at

    async def _refresh(self) -> None:
        try:
            document = await self._fetch_jwks()
        except Exception as error:
            if self._keys:
                # Keep serving with the last known keys; Auth may be briefly unreachable.
                logger.warning("JWKS refresh failed, using cached keys", exc_info=True)
                # Retry after the refetch interval rather than on every request.
                self._fetched_at = self._clock() - self._cache_seconds + UNKNOWN_KID_REFETCH_SECONDS
                return
            raise DependencyUnavailableError("Token verification is unavailable.") from error
        self._keys = _usable_keys(document)
        self._fetched_at = self._clock()
        if not self._keys:
            logger.warning("JWKS has no usable %s keys", "/".join(sorted(ALLOWED_ALGORITHMS)))


def _usable_keys(document: dict[str, Any]) -> dict[str, PyJWK]:
    """Parse the JWKS, keeping signing keys with a `kid` and an allowed algorithm."""
    keys: dict[str, PyJWK] = {}
    for data in document.get("keys", []):
        try:
            key = PyJWK(data)
        except jwt.PyJWTError:
            continue
        kid = data.get("kid")
        if isinstance(kid, str) and key.algorithm_name in ALLOWED_ALGORITHMS:
            keys[kid] = key
    return keys
