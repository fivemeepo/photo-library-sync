"""Data models for photo library sync operations.

Models map to Photos.sqlite tables and handle Core Data conventions.
"""

from __future__ import annotations

from dataclasses import dataclass

from lib.core_data import (
    Z_ENT_ADDITIONAL_ASSET_ATTRIBUTES,
    Z_ENT_ASSET,
    Z_ENT_EXTENDED_ATTRIBUTES,
    Z_ENT_GENERIC_ALBUM,
    Z_ENT_INTERNAL_RESOURCE,
    Z_ENT_MOMENT,
)


@dataclass
class Asset:
    """Represents a photo or video in the library (ZASSET table)."""

    # Core Data fields
    z_pk: int
    z_ent: int = Z_ENT_ASSET
    z_opt: int = 1

    # Identity
    uuid: str = ""
    filename: str = ""
    directory: str = ""

    # Media properties
    kind: int = 0  # 0=photo, 1=video
    width: int = 0
    height: int = 0
    orientation: int = 1
    duration: float = 0.0

    # Timestamps (Core Data epoch)
    date_created: float = 0.0
    added_date: float = 0.0
    modification_date: float = 0.0

    # State
    trashed_state: int = 0  # 0=active, 1=trashed
    trashed_date: float | None = None
    favorite: int = 0
    hidden: int = 0
    visibility_state: int = 0

    # Completeness and type info (critical for Photos.app visibility)
    complete: int = 1  # 1=complete, ready to display
    uniform_type_identifier: str | None = None  # e.g. 'public.jpeg'
    playback_style: int = 1  # 1=photo
    saved_asset_type: int = 3  # 3=normal

    # Foreign keys
    additional_attributes: int | None = None
    extended_attributes: int | None = None
    moment: int | None = None

    @property
    def file_path(self) -> str:
        """Relative path within originals/"""
        return f"{self.directory}/{self.filename}"


@dataclass
class AdditionalAssetAttributes:
    """Extended metadata for an asset (ZADDITIONALASSETATTRIBUTES table)."""

    # Core Data fields
    z_pk: int
    z_ent: int = Z_ENT_ADDITIONAL_ASSET_ATTRIBUTES
    z_opt: int = 1

    # Link to asset
    asset: int = 0

    # Original file info
    original_filename: str | None = None
    original_filesize: int | None = None
    original_width: int | None = None
    original_height: int | None = None

    # Import info
    imported_by_bundle_id: str | None = None
    imported_by_display_name: str | None = None

    # Location/time
    timezone_name: str | None = None
    timezone_offset: int | None = None
    reverse_location_data: bytes | None = None


@dataclass
class ExtendedAttributes:
    """Extended attributes for an asset (ZEXTENDEDATTRIBUTES table)."""

    # Core Data fields
    z_pk: int
    z_ent: int = Z_ENT_EXTENDED_ATTRIBUTES
    z_opt: int = 1

    # Link to asset
    asset: int = 0


@dataclass
class InternalResource:
    """File resource for an asset (ZINTERNALRESOURCE table)."""

    # Core Data fields
    z_pk: int
    z_ent: int = Z_ENT_INTERNAL_RESOURCE
    z_opt: int = 1

    # Link to asset
    asset: int = 0

    # Resource info
    resource_type: int = 0  # 0=original, 1=edit, 3=derivative
    data_length: int = 0
    local_availability: int = 1  # 1=local, -1=cloud
    fingerprint: str | None = None


@dataclass
class Album:
    """Represents an album or folder (ZGENERICALBUM table)."""

    # Core Data fields
    z_pk: int
    z_ent: int = Z_ENT_GENERIC_ALBUM
    z_opt: int = 1

    # Identity
    uuid: str = ""
    title: str | None = None

    # Type
    kind: int = 2  # 2=album, 4000=folder

    # Hierarchy
    parent_folder: int | None = None
    z_fok_parent_folder: int | None = None  # Z_FOK_PARENTFOLDER

    # Timestamps
    creation_date: float | None = None
    start_date: float | None = None
    end_date: float | None = None
    last_modified_date: float | None = None

    # State
    trashed_state: int = 0

    # Cloud/sync state (required for Photos.app)
    cloud_delete_state: int = 0
    cloud_local_state: int = 0
    privacy_state: int = 0
    sync_event_order_key: int = 0
    search_index_rebuild_state: int = 0

    # Sort settings
    custom_sort_ascending: int = 1
    custom_sort_key: int = 1

    # Flags
    is_pinned: int = 0
    is_prototype: int = 0
    pending_items_count: int = 0
    pending_items_type: int = 1

    # Import info
    imported_by_bundle_id: str | None = None

    # Cached counts
    cached_count: int = 0
    cached_photos_count: int = 0
    cached_videos_count: int = 0


@dataclass
class AlbumAsset:
    """Album membership record (Z_33ASSETS join table)."""

    album_pk: int  # Z_33ALBUMS
    asset_pk: int  # Z_3ASSETS
    fok_asset: int | None = None  # Z_FOK_3ASSETS


@dataclass
class Moment:
    """Time/location cluster (ZMOMENT table)."""

    # Core Data fields
    z_pk: int
    z_ent: int = Z_ENT_MOMENT
    z_opt: int = 1

    # Identity
    uuid: str = ""

    # Time range
    start_date: float = 0.0
    end_date: float = 0.0
    representative_date: float | None = None

    # Location
    approximate_latitude: float | None = None
    approximate_longitude: float | None = None

    # Counts
    cached_count: int = 0
    cached_photos_count: int = 0
    cached_videos_count: int = 0

    # State
    trashed_state: int = 0


__all__ = [
    "Asset",
    "AdditionalAssetAttributes",
    "ExtendedAttributes",
    "InternalResource",
    "Album",
    "AlbumAsset",
    "Moment",
]
