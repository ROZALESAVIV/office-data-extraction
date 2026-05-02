import uuid
from pathlib import Path
from config import settings


def _local_root() -> Path:
    root = Path(settings.LOCAL_STORAGE_PATH)
    root.mkdir(parents=True, exist_ok=True)
    return root


def save(content: bytes, original_filename: str, office_id: str) -> str:
    """Persist file bytes and return the storage_path."""
    if settings.STORAGE_BACKEND == "s3":
        raise NotImplementedError("S3 backend not yet implemented")

    office_dir = _local_root() / office_id
    office_dir.mkdir(parents=True, exist_ok=True)

    unique_name = f"{uuid.uuid4()}_{original_filename}"
    file_path = office_dir / unique_name
    file_path.write_bytes(content)

    return str(file_path.relative_to(Path(".")))


def get_url(storage_path: str) -> str:
    """Return a URL the frontend can use to fetch the file."""
    if settings.STORAGE_BACKEND == "s3":
        raise NotImplementedError("S3 backend not yet implemented")

    return f"/files/{storage_path}"


def read_bytes(storage_path: str) -> bytes:
    """Read raw bytes from storage — used by text-extraction services."""
    if settings.STORAGE_BACKEND == "s3":
        raise NotImplementedError("S3 backend not yet implemented")

    return Path(storage_path).read_bytes()
