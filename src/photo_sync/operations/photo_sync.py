"""Photo sync operations - identify and sync photos between libraries."""

import logging
import sqlite3
import uuid as uuid_module

from lib.core_data import Z_ENT_MOMENT, core_data_now
from photo_sync.db.mutations import (
    delete_album_membership,
    insert_additional_attributes_from_row,
    insert_asset_from_row,
    insert_extended_attributes_from_row,
    insert_internal_resources_from_row,
    insert_moment,
    update_album_cached_counts,
    update_asset_fks,
    update_asset_trashed_state,
    update_moment_cached_counts,
)
from photo_sync.db.queries import (
    get_all_asset_uuids,
    get_asset_by_uuid,
    get_assets_by_uuids,
    get_moment_by_date,
)
from photo_sync.models import (
    Asset,
    Moment,
)

logger = logging.getLogger(__name__)


def fetch_asset_uuid_sets(
    source_conn: sqlite3.Connection,
    target_conn: sqlite3.Connection,
) -> tuple[set[str], set[str]]:
    """Fetch active asset UUID sets from both libraries (once).

    Returns:
        (source_uuids, target_uuids)
    """
    source_uuids = get_all_asset_uuids(source_conn, include_trashed=False)
    target_uuids = get_all_asset_uuids(target_conn, include_trashed=False)
    return source_uuids, target_uuids


def identify_new_photos(
    source_conn: sqlite3.Connection,
    target_conn: sqlite3.Connection,
    *,
    source_uuids: set[str] | None = None,
    target_uuids: set[str] | None = None,
) -> list[Asset]:
    """Identify photos in source that don't exist in target.

    Args:
        source_conn: Connection to source database (read-only)
        target_conn: Connection to target database
        source_uuids: Pre-fetched source UUIDs (avoids redundant query)
        target_uuids: Pre-fetched target UUIDs (avoids redundant query)

    Returns:
        List of Asset objects for photos to sync
    """
    if source_uuids is None or target_uuids is None:
        source_uuids, target_uuids = fetch_asset_uuid_sets(source_conn, target_conn)

    # Find UUIDs in source but not in target
    new_uuids = source_uuids - target_uuids

    if not new_uuids:
        logger.info("No new photos to sync")
        return []

    logger.info(f"Found {len(new_uuids)} new photos to sync")

    # Get full asset details for new photos
    new_assets = get_assets_by_uuids(source_conn, list(new_uuids))

    return new_assets


def identify_deleted_photos(
    source_conn: sqlite3.Connection,
    target_conn: sqlite3.Connection,
    *,
    source_uuids: set[str] | None = None,
    target_uuids: set[str] | None = None,
) -> list[str]:
    """Identify photos in target that were deleted from source.

    Args:
        source_conn: Connection to source database (read-only)
        target_conn: Connection to target database
        source_uuids: Pre-fetched source UUIDs (avoids redundant query)
        target_uuids: Pre-fetched target UUIDs (avoids redundant query)

    Returns:
        List of UUIDs for photos to delete from target
    """
    if source_uuids is None or target_uuids is None:
        source_uuids, target_uuids = fetch_asset_uuid_sets(source_conn, target_conn)

    # Find UUIDs in target but not in source (deleted from source)
    deleted_uuids = target_uuids - source_uuids

    if not deleted_uuids:
        logger.info("No deleted photos to sync")
        return []

    logger.info(f"Found {len(deleted_uuids)} deleted photos to sync")

    return list(deleted_uuids)


def find_or_create_moment(
    conn: sqlite3.Connection,
    date_created: float
) -> int:
    """Find an existing moment for the date or create a new one.

    Args:
        conn: Connection to target database (read-write)
        date_created: Core Data timestamp for the photo

    Returns:
        Z_PK of the moment
    """
    # Try to find existing moment
    existing = get_moment_by_date(conn, date_created)
    if existing:
        logger.debug(f"Found existing moment {existing.z_pk} for date {date_created}")
        return existing.z_pk

    # Create new moment
    new_uuid = str(uuid_module.uuid4()).upper()
    moment = Moment(
        z_pk=0,  # Will be assigned
        z_ent=Z_ENT_MOMENT,
        z_opt=1,
        uuid=new_uuid,
        start_date=date_created,
        end_date=date_created,
        representative_date=date_created,
        cached_count=1,
        cached_photos_count=1,
        cached_videos_count=0,
        trashed_state=0,
    )

    moment_pk = insert_moment(conn, moment)
    logger.debug(f"Created new moment {moment_pk} for date {date_created}")

    return moment_pk


def insert_photo_with_relations(
    target_conn: sqlite3.Connection,
    asset: Asset,
    source_conn: sqlite3.Connection
) -> int:
    """Insert a photo by copying ALL fields from source database.

    This function copies all columns from:
    - ZASSET record
    - ZADDITIONALASSETATTRIBUTES record
    - ZEXTENDEDATTRIBUTES record
    - ZINTERNALRESOURCE records (1-2 per photo)
    - Links to or creates ZMOMENT

    Args:
        target_conn: Connection to target database (read-write)
        asset: Asset object from source (used for z_pk and date_created)
        source_conn: Connection to source database (read-only)

    Returns:
        Z_PK of the inserted asset
    """
    # Find or create moment in target
    moment_pk = find_or_create_moment(target_conn, asset.date_created)

    # Insert asset by copying ALL fields from source
    new_asset_pk = insert_asset_from_row(
        target_conn, source_conn, asset.z_pk,
        moment_pk=moment_pk,
        added_date=core_data_now()
    )

    # Insert additional attributes (copying ALL fields)
    additional_pk = insert_additional_attributes_from_row(
        target_conn, source_conn, asset.z_pk, new_asset_pk
    )

    # Insert extended attributes (copying ALL fields)
    extended_pk = insert_extended_attributes_from_row(
        target_conn, source_conn, asset.z_pk, new_asset_pk
    )

    # Update asset with FK references
    update_asset_fks(target_conn, new_asset_pk, additional_pk, extended_pk, moment_pk)

    # Insert internal resources (copying ALL fields)
    insert_internal_resources_from_row(
        target_conn, source_conn, asset.z_pk, new_asset_pk
    )

    # Update moment counts
    update_moment_cached_counts(target_conn, moment_pk)

    logger.debug(f"Inserted photo {asset.uuid} with PK {new_asset_pk}")
    return new_asset_pk


def soft_delete_photo(
    target_conn: sqlite3.Connection,
    uuid: str
) -> bool:
    """Soft delete a photo by setting ZTRASHEDSTATE=1.

    This also removes the photo from all album memberships.

    Args:
        target_conn: Connection to target database (read-write)
        uuid: UUID of the photo to delete

    Returns:
        True if deletion succeeded
    """
    # Get the asset to find its PK
    asset = get_asset_by_uuid(target_conn, uuid)
    if not asset:
        logger.warning(f"Photo not found for soft delete: {uuid}")
        return False

    # Remove from all albums
    cursor = target_conn.execute(
        "SELECT Z_33ALBUMS FROM Z_33ASSETS WHERE Z_3ASSETS = ?",
        (asset.z_pk,)
    )
    album_pks = [row[0] for row in cursor.fetchall()]

    for album_pk in album_pks:
        delete_album_membership(target_conn, album_pk, asset.z_pk)
        update_album_cached_counts(target_conn, album_pk)

    # Set trashed state
    success = update_asset_trashed_state(target_conn, uuid, trashed_state=1)

    if success:
        logger.debug(f"Soft deleted photo {uuid}")
    else:
        logger.warning(f"Failed to soft delete photo {uuid}")

    return success


__all__ = [
    "fetch_asset_uuid_sets",
    "identify_new_photos",
    "identify_deleted_photos",
    "find_or_create_moment",
    "insert_photo_with_relations",
    "soft_delete_photo",
]
