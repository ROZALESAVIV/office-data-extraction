"""Supabase Storage.

Two rules this module exists to enforce:

1. The storage key is built from UUIDs only and validated before every call.
   A user-supplied filename never reaches it, so path traversal is impossible
   by construction rather than by filtering.
2. No HTTP exceptions. This is called from background jobs where there is no
   request to return a status code to; routers translate these errors.
"""

import re
from functools import lru_cache

from app.core.config import settings

# {tenant}/{case}/{document}.{ext} - three UUIDs and a known extension.
_KEY_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r"(?:\.preview)?\.(pdf|docx|eml)$"
)


class StorageError(RuntimeError):
    """Storage operation failed."""


class StorageNotFound(StorageError):
    """The object does not exist."""


def build_key(tenant_id, case_id, document_id, ext: str, preview: bool = False) -> str:
    suffix = ".preview" if preview else ""
    return f"{tenant_id}/{case_id}/{document_id}{suffix}.{ext}"


def _check(key: str) -> str:
    if not _KEY_RE.fullmatch(key):
        raise StorageError(f"unsafe storage key: {key!r}")
    return key


@lru_cache(maxsize=1)
def _client():
    """Built on first use, not at import.

    A module-level client makes this module unimportable without Supabase
    credentials, which alone blocks every unit test that merely imports a
    router.
    """
    from supabase import create_client

    if not settings.supabase_url or not settings.supabase_service_key:
        raise StorageError("Supabase storage is not configured")
    return create_client(settings.supabase_url, settings.supabase_service_key)


def _bucket():
    return _client().storage.from_(settings.supabase_bucket)


def upload(key: str, blob: bytes, content_type: str) -> str:
    _check(key)
    try:
        _bucket().upload(key, blob, {"content-type": content_type, "upsert": "false"})
    except Exception as exc:
        raise StorageError(f"upload failed for {key}") from exc
    return key


def download(key: str) -> bytes:
    _check(key)
    try:
        return _bucket().download(key)
    except Exception as exc:
        if "not found" in str(exc).lower() or "404" in str(exc):
            raise StorageNotFound(key) from exc
        raise StorageError(f"download failed for {key}") from exc


def signed_url(key: str, expires_in_seconds: int = 900) -> str:
    _check(key)
    try:
        result = _bucket().create_signed_url(key, expires_in_seconds)
    except Exception as exc:
        raise StorageError(f"could not sign {key}") from exc
    url = result.get("signedURL") or result.get("signedUrl") or result.get("signed_url")
    if not url:
        raise StorageError(f"storage returned no signed URL for {key}")
    return url


def delete(key: str) -> None:
    """Best effort, but never silent: the caller decides what a failure means."""
    _check(key)
    try:
        _bucket().remove([key])
    except Exception as exc:
        raise StorageError(f"delete failed for {key}") from exc
