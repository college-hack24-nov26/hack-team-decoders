"""Blob storage interface + local-disk implementation.

Architecture: all file I/O goes through `StorageBackend`.  The demo uses
`LocalDiskStorage` (writes to a configurable directory).  Swapping to S3/MinIO
later is a single class swap in `get_storage_backend()` — no caller changes.

The stored URI is an opaque string that `get_storage_backend().read()` can
resolve.  For LocalDiskStorage it's a relative path under the storage root.
"""

from __future__ import annotations

import os
import uuid
from abc import ABC, abstractmethod
from pathlib import Path


class StorageBackend(ABC):
    """Interface for blob storage (images, documents)."""

    @abstractmethod
    def save(self, data: bytes, filename: str, patient_id: uuid.UUID) -> str:
        """Store bytes, return a URI string (opaque to callers)."""
        ...

    @abstractmethod
    def read(self, uri: str) -> bytes:
        """Read raw bytes from a previously stored URI."""
        ...

    @abstractmethod
    def delete(self, uri: str) -> None:
        """Remove a stored blob."""
        ...

    @abstractmethod
    def resolve_path(self, uri: str) -> Path:
        """Resolve the URI to a local file path (for OCR / processing)."""
        ...


class LocalDiskStorage(StorageBackend):
    """Stores files on local disk under `./storage/<patient_id>/`.

    For the hackathon demo this is sufficient.  A production deployment would
    use MinIO or S3 via an equivalent class implementing StorageBackend.
    """

    def __init__(self, root_dir: str | Path | None = None) -> None:
        if root_dir is None:
            root_dir = Path(os.environ.get("FILE_STORAGE_ROOT", "./storage"))
        self._root = Path(root_dir)
        self._root.mkdir(parents=True, exist_ok=True)

    def _patient_dir(self, patient_id: uuid.UUID) -> Path:
        d = self._root / str(patient_id)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def save(self, data: bytes, filename: str, patient_id: uuid.UUID) -> str:
        safe_name = f"{uuid.uuid4().hex}_{filename}"
        dest = self._patient_dir(patient_id) / safe_name
        dest.write_bytes(data)
        # URI is the relative path from the storage root
        return str(dest.relative_to(self._root))

    def read(self, uri: str) -> bytes:
        path = self._root / uri
        return path.read_bytes()

    def delete(self, uri: str) -> None:
        path = self._root / uri
        if path.exists():
            path.unlink()

    def resolve_path(self, uri: str) -> Path:
        return self._root / uri


class SupabaseStorageBackend(StorageBackend):
    """Store files in Supabase Storage via the REST API.

    Uses httpx (already a dependency) — no supabase Python client needed.
    Requires: SUPABASE_URL, SUPABASE_SERVICE_KEY, SUPABASE_BUCKET.
    """

    def __init__(self, url: str, key: str, bucket: str) -> None:
        self._url = url.rstrip("/")
        self._key = key
        self._bucket = bucket
        self._local_cache = Path(os.environ.get("FILE_STORAGE_ROOT", "./storage"))
        self._local_cache.mkdir(parents=True, exist_ok=True)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._key}",
            "apikey": self._key,
        }

    def save(self, data: bytes, filename: str, patient_id: uuid.UUID) -> str:
        import httpx

        safe_name = f"{uuid.uuid4().hex}_{filename}"
        object_path = f"{patient_id}/{safe_name}"
        upload_url = f"{self._url}/storage/v1/object/{self._bucket}/{object_path}"
        # Guess content type
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        content_type = {
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
            "pdf": "application/pdf",
            "webp": "image/webp",
        }.get(ext, "application/octet-stream")

        resp = httpx.post(
            upload_url,
            content=data,
            headers={**self._headers(), "Content-Type": content_type},
            timeout=30.0,
        )
        resp.raise_for_status()
        return object_path

    def read(self, uri: str) -> bytes:
        import httpx

        # Check local cache first
        cached = self._local_cache / uri.replace("/", "_")
        if cached.exists():
            return cached.read_bytes()

        download_url = f"{self._url}/storage/v1/object/{self._bucket}/{uri}"
        resp = httpx.get(download_url, headers=self._headers(), timeout=30.0)
        resp.raise_for_status()

        # Cache locally for OCR processing
        cached.write_bytes(resp.content)
        return resp.content

    def delete(self, uri: str) -> None:
        import httpx

        delete_url = f"{self._url}/storage/v1/object/{self._bucket}"
        resp = httpx.delete(
            delete_url,
            json={"prefixes": [uri]},
            headers=self._headers(),
            timeout=30.0,
        )
        # Supabase returns 200 even if the file didn't exist
        resp.raise_for_status()

        # Remove local cache too
        cached = self._local_cache / uri.replace("/", "_")
        if cached.exists():
            cached.unlink()

    def resolve_path(self, uri: str) -> Path:
        """Download to local cache and return the path (needed for OCR)."""
        cached = self._local_cache / uri.replace("/", "_")
        if not cached.exists():
            data = self.read(uri)
            cached.write_bytes(data)
        return cached


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_instance: StorageBackend | None = None


def get_storage_backend() -> StorageBackend:
    """Return the singleton storage backend.

    Selects based on FILE_STORAGE_BACKEND env var:
    - "local" (default) → LocalDiskStorage
    - "supabase" → SupabaseStorageBackend
    """
    global _instance  # noqa: PLW0603
    if _instance is None:
        from app.core.config import get_settings

        settings = get_settings()
        backend = settings.file_storage_backend.lower()

        if backend == "supabase":
            if not settings.supabase_url or not settings.supabase_service_key:
                raise RuntimeError(
                    "FILE_STORAGE_BACKEND=supabase but SUPABASE_URL or "
                    "SUPABASE_SERVICE_KEY is not set"
                )
            _instance = SupabaseStorageBackend(
                url=settings.supabase_url,
                key=settings.supabase_service_key,
                bucket=settings.supabase_bucket,
            )
        else:
            _instance = LocalDiskStorage()
    return _instance
