"""File copy operations for photo sync."""

from __future__ import annotations

import hashlib
import logging
import shutil
from pathlib import Path

from photo_sync.models import Asset

logger = logging.getLogger(__name__)


class FileCopyError(Exception):
    """Error during file copy operation."""
    pass


class FileNotFoundError(FileCopyError):
    """Source file not found."""
    pass


class DiskFullError(FileCopyError):
    """Insufficient disk space."""
    pass


def get_photo_file_path(library_path: Path, asset: Asset) -> Path:
    """Get the full path to a photo file.

    Args:
        library_path: Path to .photoslibrary bundle
        asset: Asset object

    Returns:
        Full path to the photo file
    """
    return library_path / "originals" / asset.directory / asset.filename


def get_photo_file_size(library_path: Path, asset: Asset) -> int | None:
    """Get the size of a photo file.

    Args:
        library_path: Path to .photoslibrary bundle
        asset: Asset object

    Returns:
        File size in bytes, or None if file doesn't exist
    """
    file_path = get_photo_file_path(library_path, asset)
    if file_path.exists():
        return file_path.stat().st_size
    return None


def copy_photo_file(
    source_lib_path: Path,
    target_lib_path: Path,
    asset: Asset
) -> int:
    """Copy a photo file from source to target library.

    Args:
        source_lib_path: Path to source .photoslibrary bundle
        target_lib_path: Path to target .photoslibrary bundle
        asset: Asset object with directory and filename

    Returns:
        Number of bytes copied

    Raises:
        FileNotFoundError: If source file doesn't exist
        DiskFullError: If target disk is full
        FileCopyError: For other copy errors
    """
    source_path = get_photo_file_path(source_lib_path, asset)
    target_path = get_photo_file_path(target_lib_path, asset)

    # Check source exists
    if not source_path.exists():
        raise FileNotFoundError(f"Source file not found: {source_path}")

    # Get file size
    file_size = source_path.stat().st_size

    # Create target directory if needed
    target_path.parent.mkdir(parents=True, exist_ok=True)

    # Check if target already exists (skip if same size)
    if target_path.exists():
        if target_path.stat().st_size == file_size:
            logger.debug(f"File already exists with same size, skipping: {target_path}")
            return 0
        else:
            logger.warning(f"File exists with different size, overwriting: {target_path}")

    try:
        # Copy with metadata preservation
        shutil.copy2(source_path, target_path)
        logger.debug(f"Copied {file_size} bytes: {source_path} -> {target_path}")
        return file_size
    except OSError as e:
        if "No space left" in str(e) or e.errno == 28:
            raise DiskFullError(f"Disk full while copying {source_path}") from e
        raise FileCopyError(f"Failed to copy {source_path}: {e}") from e


def verify_file_copy(source_path: Path, target_path: Path) -> bool:
    """Verify file integrity by comparing SHA256 checksums.

    Args:
        source_path: Path to source file
        target_path: Path to target file

    Returns:
        True if checksums match, False otherwise
    """
    if not source_path.exists() or not target_path.exists():
        return False

    source_hash = _compute_sha256(source_path)
    target_hash = _compute_sha256(target_path)

    match = source_hash == target_hash
    if not match:
        logger.warning(f"Checksum mismatch: {source_path} vs {target_path}")
    return match


def _compute_sha256(file_path: Path) -> str:
    """Compute SHA256 hash of a file.

    Args:
        file_path: Path to file

    Returns:
        Hex-encoded SHA256 hash
    """
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def check_disk_space(target_path: Path, required_bytes: int) -> tuple[bool, int, int]:
    """Check if target has enough disk space.

    Args:
        target_path: Path on target filesystem
        required_bytes: Bytes needed

    Returns:
        Tuple of (has_space, available_bytes, required_bytes)
    """
    import os
    stat = os.statvfs(target_path)
    available = stat.f_bavail * stat.f_frsize
    return (available >= required_bytes, available, required_bytes)


__all__ = [
    "FileCopyError",
    "FileNotFoundError",
    "DiskFullError",
    "get_photo_file_path",
    "get_photo_file_size",
    "copy_photo_file",
    "verify_file_copy",
    "check_disk_space",
]
