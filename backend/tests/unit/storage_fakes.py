"""In-memory stand-in for `SupabaseStorage` (the `FileStorage` protocol)."""

from datetime import UTC, datetime, timedelta

from app.core.errors import ExternalServiceError


class InMemoryFileStorage:
    """Keeps objects in a dict; `fail_uploads` simulates a Storage outage."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.deleted: list[list[str]] = []
        self.fail_uploads = False

    async def upload_pdf(self, path: str, data: bytes) -> None:
        if self.fail_uploads:
            raise ExternalServiceError("Document storage is unreachable.")
        self.objects[path] = data

    async def signed_url(self, path: str, *, expires_in: int) -> tuple[str, datetime]:
        if path not in self.objects:
            raise ExternalServiceError("Document storage rejected the request.")
        expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
        return f"https://storage.test/sign/{path}?token=t", expires_at

    async def delete(self, paths: list[str]) -> None:
        self.deleted.append(list(paths))
        for path in paths:
            self.objects.pop(path, None)
