"""Supabase Storage access for uploaded PDFs (NFR-09), through its REST API.

The secret key bypasses Storage policies, so it stays server-side (D-049). The bucket is
private and created by the team, never from code.
"""

from datetime import UTC, datetime, timedelta
from urllib.parse import quote

import httpx

from app.core.config import Settings
from app.core.errors import ExternalServiceError

PDF_CONTENT_TYPE = "application/pdf"


class SupabaseStorage:
    """Uploads, signs, and deletes objects in one private bucket."""

    def __init__(
        self,
        *,
        supabase_url: str,
        secret_key: str,
        bucket: str,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = f"{supabase_url}/storage/v1"
        self._bucket = bucket
        self._headers = {"apikey": secret_key}
        self._timeout = timeout_seconds
        self._transport = transport

    async def upload_pdf(self, path: str, data: bytes) -> None:
        """Store `data` at `path`, replacing an existing object (a retried upload)."""
        await self._request(
            "POST",
            f"/object/{self._bucket}/{_quoted(path)}",
            content=data,
            headers={"Content-Type": PDF_CONTENT_TYPE, "x-upsert": "true"},
        )

    async def signed_url(self, path: str, *, expires_in: int) -> tuple[str, datetime]:
        """A short-lived download URL for `path` and when it expires."""
        expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
        response = await self._request(
            "POST", f"/object/sign/{self._bucket}/{_quoted(path)}", json={"expiresIn": expires_in}
        )
        signed = response.json().get("signedURL")
        if not isinstance(signed, str):
            raise ExternalServiceError("Storage returned no signed URL.")
        return f"{self._base_url}{signed}", expires_at

    async def delete(self, paths: list[str]) -> None:
        """Delete the objects at `paths`; missing objects are ignored."""
        if paths:
            await self._request("DELETE", f"/object/{self._bucket}", json={"prefixes": paths})

    async def _request(
        self,
        method: str,
        url: str,
        *,
        content: bytes | None = None,
        json: object = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        async with httpx.AsyncClient(
            base_url=self._base_url,
            headers=self._headers,
            timeout=self._timeout,
            transport=self._transport,
        ) as client:
            try:
                response = await client.request(
                    method, url, content=content, json=json, headers=headers
                )
            except httpx.HTTPError as exc:
                raise ExternalServiceError(
                    "Document storage is unreachable.", details={"service": "storage"}
                ) from exc
        if response.is_error:
            raise ExternalServiceError(
                "Document storage rejected the request.",
                details={"service": "storage", "status": response.status_code},
            )
        return response


def _quoted(path: str) -> str:
    return quote(path, safe="/")


def create_storage_from_settings(settings: Settings) -> SupabaseStorage | None:
    """The bucket client, or None when `SUPABASE_URL` or `SUPABASE_SECRET_KEY` is not set."""
    if settings.supabase_url is None or settings.supabase_secret_key is None:
        return None
    return SupabaseStorage(
        supabase_url=settings.supabase_url,
        secret_key=settings.supabase_secret_key.get_secret_value(),
        bucket=settings.storage_bucket,
        timeout_seconds=settings.storage_timeout_seconds,
    )
