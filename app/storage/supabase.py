"""Document File Storage Service (Local Filesystem & PostgreSQL persistence).
Replaces Supabase Storage with direct filesystem and memory blob storage.
"""

from pathlib import Path
from typing import Optional
from app.core.config import Settings
from app.core.errors import StorageUnavailableError
from app.core.logging import logger

_local_blob_store: dict[str, bytes] = {}


def _get_storage_path(relative_path: str, settings: Settings) -> Path:
    base_dir = Path(getattr(settings, "STORAGE_DIR", "./data/uploads"))
    safe_rel_path = relative_path.replace(":", "_")
    full_path = base_dir / safe_rel_path
    full_path.parent.mkdir(parents=True, exist_ok=True)
    return full_path


async def put_object(
    path: str,
    data: bytes,
    content_type: str,
    settings: Settings,
) -> None:
    """Save a document file to local filesystem storage."""
    _local_blob_store[path] = data
    try:
        file_path = _get_storage_path(path, settings)
        file_path.write_bytes(data)
    except Exception as e:
        logger.warning(f"Failed to persist file to disk {path}: {e}")


async def get_object(
    path: str,
    settings: Settings,
) -> bytes:
    """Retrieve a document file from storage."""
    if path in _local_blob_store:
        return _local_blob_store[path]

    try:
        file_path = _get_storage_path(path, settings)
        if file_path.exists():
            data = file_path.read_bytes()
            _local_blob_store[path] = data
            return data
    except Exception as e:
        logger.error(f"Error reading file from disk {path}: {e}")

    raise StorageUnavailableError("Document file not found in storage.")


async def delete_object(
    path: str,
    settings: Settings,
) -> None:
    """Delete a document file from storage."""
    _local_blob_store.pop(path, None)
    try:
        file_path = _get_storage_path(path, settings)
        if file_path.exists():
            file_path.unlink()
    except Exception as e:
        logger.warning(f"Failed to delete file from disk {path}: {e}")
