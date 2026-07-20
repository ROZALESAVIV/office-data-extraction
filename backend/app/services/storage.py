from fastapi import HTTPException
from supabase import create_client

from config import settings

supabase = create_client(settings.supabase_url, settings.supabase_service_key)

_bucket = settings.supabase_bucket


def upload_file(file_bytes: bytes, tenant_id: str, case_id: str, filename: str) -> str:
    path = f"{tenant_id}/{case_id}/{filename}"
    try:
        supabase.storage.from_(_bucket).upload(path, file_bytes)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Storage upload failed: {e}")
    return path


def delete_file(storage_path: str) -> None:
    try:
        supabase.storage.from_(_bucket).remove([storage_path])
    except Exception:
        pass  # already gone or bucket missing — safe to ignore


def get_signed_url(storage_path: str, expires_in_seconds: int = 3600) -> str:
    try:
        result = supabase.storage.from_(_bucket).create_signed_url(storage_path, expires_in_seconds)
        return result["signedURL"]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not generate signed URL: {e}")


def get_file_bytes(storage_path: str) -> bytes:
    try:
        return supabase.storage.from_(_bucket).download(storage_path)
    except Exception as e:
        if "not found" in str(e).lower() or "404" in str(e):
            raise HTTPException(status_code=404, detail="File not found in storage")
        raise HTTPException(status_code=500, detail=f"Storage download failed: {e}")
