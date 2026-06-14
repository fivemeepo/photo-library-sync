# Data Model: Library Sync

**Feature**: `20260208-library-sync-append`
**Date**: 2026-02-08

## Overview

This document defines the Python data models for the library sync feature. Models map to Photos.sqlite tables and handle Core Data conventions.

## Core Data Conventions

All tables use these Core Data columns:
- `Z_PK`: Primary key (INTEGER)
- `Z_ENT`: Entity type ID (INTEGER) - fixed per table
- `Z_OPT`: Optimistic locking version (INTEGER) - starts at 1

Timestamps use Core Data epoch: 2001-01-01 00:00:00 UTC
- Convert to Unix: `timestamp + 978307200`
- Convert from Unix: `timestamp - 978307200`

## Entity Models

### Asset (ZASSET)

Core photo/video entity.

```python
@dataclass
class Asset:
    """Represents a photo or video in the library."""

    # Core Data fields
    z_pk: int
    z_ent: int = 3  # Asset entity type
    z_opt: int = 1

    # Identity
    uuid: str  # ZUUID - unique identifier
    filename: str  # ZFILENAME - e.g., "ABC123.jpeg"
    directory: str  # ZDIRECTORY - e.g., "A"

    # Media properties
    kind: int  # ZKIND - 0=photo, 1=video
    width: int  # ZWIDTH
    height: int  # ZHEIGHT
    orientation: int  # ZORIENTATION
    duration: float = 0.0  # ZDURATION (videos only)

    # Timestamps (Core Data epoch)
    date_created: float  # ZDATECREATED
    added_date: float  # ZADDEDDATE
    modification_date: float  # ZMODIFICATIONDATE

    # State
    trashed_state: int = 0  # ZTRASHEDSTATE - 0=active, 1=trashed
    trashed_date: Optional[float] = None  # ZTRASHEDDATE
    favorite: int = 0  # ZFAVORITE
    hidden: int = 0  # ZHIDDEN

    # Foreign keys
    additional_attributes: Optional[int] = None  # ZADDITIONALATTRIBUTES
    extended_attributes: Optional[int] = None  # ZEXTENDEDATTRIBUTES
    moment: Optional[int] = None  # ZMOMENT

    @property
    def file_path(self) -> str:
        """Relative path within originals/"""
        return f"{self.directory}/{self.filename}"
```

### AdditionalAssetAttributes (ZADDITIONALASSETATTRIBUTES)

Extended metadata for assets. 1:1 relationship with Asset.

```python
@dataclass
class AdditionalAssetAttributes:
    """Extended metadata for an asset."""

    # Core Data fields
    z_pk: int
    z_ent: int = 1  # AdditionalAssetAttributes entity type
    z_opt: int = 1

    # Link to asset
    asset: int  # ZASSET - FK to ZASSET.Z_PK

    # Original file info
    original_filename: Optional[str] = None  # ZORIGINALFILENAME
    original_filesize: Optional[int] = None  # ZORIGINALFILESIZE
    original_width: Optional[int] = None  # ZORIGINALWIDTH
    original_height: Optional[int] = None  # ZORIGINALHEIGHT

    # Import info
    imported_by_bundle_id: Optional[str] = None  # ZIMPORTEDBYBUNDLEIDENTIFIER
    imported_by_display_name: Optional[str] = None  # ZIMPORTEDBYDISPLAYNAME

    # Location/time
    timezone_name: Optional[str] = None  # ZTIMEZONENAME
    timezone_offset: Optional[int] = None  # ZTIMEZONEOFFSET
    reverse_location_data: Optional[bytes] = None  # ZREVERSELOCATIONDATA
```

### ExtendedAttributes (ZEXTENDEDATTRIBUTES)

Additional extended attributes. 1:1 relationship with Asset.

```python
@dataclass
class ExtendedAttributes:
    """Extended attributes for an asset."""

    # Core Data fields
    z_pk: int
    z_ent: int = 28  # ExtendedAttributes entity type
    z_opt: int = 1

    # Link to asset
    asset: int  # ZASSET - FK to ZASSET.Z_PK
```

### InternalResource (ZINTERNALRESOURCE)

File variants (original, edits, derivatives). 1:N relationship with Asset.

```python
@dataclass
class InternalResource:
    """File resource for an asset."""

    # Core Data fields
    z_pk: int
    z_ent: int = 51  # InternalResource entity type
    z_opt: int = 1

    # Link to asset
    asset: int  # ZASSET - FK to ZASSET.Z_PK

    # Resource info
    resource_type: int  # ZRESOURCETYPE - 0=original, 1=edit, 3=derivative
    data_length: int  # ZDATALENGTH - file size in bytes
    local_availability: int = 1  # ZLOCALAVAILABILITY - 1=local, -1=cloud
    fingerprint: Optional[str] = None  # ZFINGERPRINT
```

### Album (ZGENERICALBUM)

Album or folder definition.

```python
@dataclass
class Album:
    """Represents an album or folder."""

    # Core Data fields
    z_pk: int
    z_ent: int = 32  # GenericAlbum entity type
    z_opt: int = 1

    # Identity
    uuid: str  # ZUUID
    title: Optional[str] = None  # ZTITLE

    # Type
    kind: int  # ZKIND - 2=album, 4000=folder

    # Hierarchy
    parent_folder: Optional[int] = None  # ZPARENTFOLDER - FK to self

    # Timestamps
    creation_date: Optional[float] = None  # ZCREATIONDATE
    start_date: Optional[float] = None  # ZSTARTDATE
    end_date: Optional[float] = None  # ZENDDATE

    # State
    trashed_state: int = 0  # ZTRASHEDSTATE

    # Cached counts
    cached_count: int = 0  # ZCACHEDCOUNT
    cached_photos_count: int = 0  # ZCACHEDPHOTOSCOUNT
    cached_videos_count: int = 0  # ZCACHEDVIDEOSCOUNT
```

### AlbumAsset (Z_33ASSETS)

Join table for album-asset membership.

```python
@dataclass
class AlbumAsset:
    """Album membership record."""

    album_pk: int  # Z_33ALBUMS - FK to ZGENERICALBUM.Z_PK
    asset_pk: int  # Z_3ASSETS - FK to ZASSET.Z_PK
    fok_asset: Optional[int] = None  # Z_FOK_3ASSETS
```

### Moment (ZMOMENT)

Time+location cluster for photos.

```python
@dataclass
class Moment:
    """Time/location cluster."""

    # Core Data fields
    z_pk: int
    z_ent: int = 58  # Moment entity type
    z_opt: int = 1

    # Identity
    uuid: str  # ZUUID

    # Time range
    start_date: float  # ZSTARTDATE
    end_date: float  # ZENDDATE
    representative_date: Optional[float] = None  # ZREPRESENTATIVEDATE

    # Location
    approximate_latitude: Optional[float] = None  # ZAPPROXIMATELATITUDE
    approximate_longitude: Optional[float] = None  # ZAPPROXIMATELONGITUDE

    # Counts
    cached_count: int = 0  # ZCACHEDCOUNT
    cached_photos_count: int = 0  # ZCACHEDPHOTOSCOUNT
    cached_videos_count: int = 0  # ZCACHEDVIDEOSCOUNT

    # State
    trashed_state: int = 0  # ZTRASHEDSTATE
```

## Result Models

### SyncResult

Result of a sync operation.

```python
@dataclass
class SyncResult:
    """Result of sync operation."""

    # Counts
    photos_added: int = 0
    photos_deleted: int = 0
    albums_added: int = 0
    album_memberships_added: int = 0
    album_memberships_removed: int = 0
    favourites_synced: int = 0  # P5 feature

    # File operations
    files_copied: int = 0
    bytes_copied: int = 0

    # Errors
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return len(self.errors) == 0
```

### SyncPlan

Preview of what will be synced (dry-run mode).

```python
@dataclass
class SyncPlan:
    """Plan for sync operation (dry-run output)."""

    # Photos
    photos_to_add: List[str]  # UUIDs
    photos_to_delete: List[str]  # UUIDs

    # Albums
    albums_to_add: List[str]  # UUIDs

    # Memberships
    memberships_to_add: List[Tuple[str, str]]  # (album_uuid, asset_uuid)
    memberships_to_remove: List[Tuple[str, str]]

    # Favourites (P5)
    favourites_to_sync: List[str]  # UUIDs of photos with differing favourite status

    # Size
    total_bytes_to_copy: int

    def to_dict(self) -> dict:
        return {
            "photos_to_add": len(self.photos_to_add),
            "photos_to_delete": len(self.photos_to_delete),
            "albums_to_add": len(self.albums_to_add),
            "memberships_to_add": len(self.memberships_to_add),
            "memberships_to_remove": len(self.memberships_to_remove),
            "favourites_to_sync": len(self.favourites_to_sync),
            "total_bytes_to_copy": self.total_bytes_to_copy,
        }
```

## Entity Relationships

```
ZASSET (1) ←──────────────────→ (1) ZADDITIONALASSETATTRIBUTES
   │                                      via ZASSET.ZADDITIONALATTRIBUTES
   │
   ├──→ (1) ZEXTENDEDATTRIBUTES
   │         via ZASSET.ZEXTENDEDATTRIBUTES
   │
   ├──→ (N) ZINTERNALRESOURCE
   │         via ZINTERNALRESOURCE.ZASSET
   │
   ├──→ (1) ZMOMENT
   │         via ZASSET.ZMOMENT
   │
   └──→ (N) Z_33ASSETS ←──→ (1) ZGENERICALBUM
             via Z_3ASSETS      via Z_33ALBUMS

ZGENERICALBUM (self-referencing)
   └──→ ZPARENTFOLDER → ZGENERICALBUM.Z_PK
```

## Z_PRIMARYKEY Management

```python
def get_next_pk(conn: sqlite3.Connection, entity_name: str) -> int:
    """Get and increment the next primary key for an entity."""
    cursor = conn.execute(
        "SELECT Z_MAX FROM Z_PRIMARYKEY WHERE Z_NAME = ?",
        (entity_name,)
    )
    row = cursor.fetchone()
    if not row:
        raise ValueError(f"Unknown entity: {entity_name}")

    next_pk = row[0] + 1
    conn.execute(
        "UPDATE Z_PRIMARYKEY SET Z_MAX = ? WHERE Z_NAME = ?",
        (next_pk, entity_name)
    )
    return next_pk
```

Entity names for Z_PRIMARYKEY:
- `Asset` → ZASSET
- `AdditionalAssetAttributes` → ZADDITIONALASSETATTRIBUTES
- `ExtendedAttributes` → ZEXTENDEDATTRIBUTES
- `InternalResource` → ZINTERNALRESOURCE
- `GenericAlbum` → ZGENERICALBUM
- `Moment` → ZMOMENT
