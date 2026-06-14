"""Result models for sync operations."""

from dataclasses import dataclass, field
from typing import Any


def format_bytes(num_bytes: int) -> str:
    """Format bytes as human-readable string (e.g., '7.4 GB')."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num_bytes) < 1024:
            if unit == "B":
                return f"{num_bytes} {unit}"
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024  # type: ignore[assignment]
    return f"{num_bytes:.1f} PB"


@dataclass
class SyncResult:
    """Result of sync operation."""

    # Counts
    photos_added: int = 0
    photos_deleted: int = 0
    albums_added: int = 0
    album_memberships_added: int = 0
    album_memberships_removed: int = 0
    favourites_synced: int = 0

    # File operations
    files_copied: int = 0
    bytes_copied: int = 0

    # Errors
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """Check if sync completed without errors."""
        return len(self.errors) == 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON output."""
        return {
            "photos_added": self.photos_added,
            "photos_deleted": self.photos_deleted,
            "albums_added": self.albums_added,
            "album_memberships_added": self.album_memberships_added,
            "album_memberships_removed": self.album_memberships_removed,
            "favourites_synced": self.favourites_synced,
            "files_copied": self.files_copied,
            "bytes_copied": self.bytes_copied,
            "bytes_copied_human": format_bytes(self.bytes_copied),
            "errors": self.errors,
            "warnings": self.warnings,
            "success": self.success,
        }

    def merge(self, other: "SyncResult") -> "SyncResult":
        """Merge another SyncResult into this one."""
        self.photos_added += other.photos_added
        self.photos_deleted += other.photos_deleted
        self.albums_added += other.albums_added
        self.album_memberships_added += other.album_memberships_added
        self.album_memberships_removed += other.album_memberships_removed
        self.favourites_synced += other.favourites_synced
        self.files_copied += other.files_copied
        self.bytes_copied += other.bytes_copied
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)
        return self


@dataclass
class SyncPlan:
    """Plan for sync operation (dry-run output)."""

    # Photos
    photos_to_add: list[str] = field(default_factory=list)  # UUIDs
    photos_to_delete: list[str] = field(default_factory=list)  # UUIDs

    # Albums
    albums_to_add: list[str] = field(default_factory=list)  # UUIDs

    # Memberships
    memberships_to_add: list[tuple[str, str]] = field(default_factory=list)  # (album_uuid, asset_uuid)
    memberships_to_remove: list[tuple[str, str]] = field(default_factory=list)

    # Favourites
    favourites_to_sync: list[str] = field(default_factory=list)  # UUIDs of photos with differing favourite status

    # Size
    total_bytes_to_copy: int = 0

    # Details for verbose output
    photo_details: list[dict[str, Any]] = field(default_factory=list)
    album_details: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON output."""
        return {
            "photos_to_add": len(self.photos_to_add),
            "photos_to_delete": len(self.photos_to_delete),
            "albums_to_add": len(self.albums_to_add),
            "memberships_to_add": len(self.memberships_to_add),
            "memberships_to_remove": len(self.memberships_to_remove),
            "favourites_to_sync": len(self.favourites_to_sync),
            "total_bytes_to_copy": self.total_bytes_to_copy,
            "total_bytes_to_copy_human": format_bytes(self.total_bytes_to_copy),
        }

    def to_detailed_dict(self) -> dict[str, Any]:
        """Convert to detailed dictionary including item lists."""
        return {
            "dry_run": True,
            "plan": self.to_dict(),
            "details": {
                "photos_to_add": self.photo_details,
                "photos_to_delete": self.photos_to_delete,
                "albums_to_add": self.album_details,
                "memberships_to_add": [
                    {"album_uuid": a, "asset_uuid": p} for a, p in self.memberships_to_add
                ],
                "memberships_to_remove": [
                    {"album_uuid": a, "asset_uuid": p} for a, p in self.memberships_to_remove
                ],
                "favourites_to_sync": self.favourites_to_sync,
            },
        }


__all__ = ["SyncResult", "SyncPlan"]
