"""Main sync orchestration for photo library sync."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from photo_sync.db.connection import connect_readonly, connect_readwrite
from photo_sync.db.schema_version import (
    SchemaVersionMismatchError,
    assert_schema_compatible,
)
from photo_sync.models.sync_result import SyncPlan, SyncResult
from photo_sync.operations.album_sync import (
    diff_album_memberships,
    identify_new_albums,
    insert_album_with_hierarchy,
    sync_album_folders,
    sync_album_memberships,
)
from photo_sync.operations.favourite_sync import (
    identify_favourite_changes,
    sync_favourites,
)
from photo_sync.operations.file_copy import (
    backfill_derivatives,
    check_disk_space,
    copy_asset_derivatives,
    copy_photo_file,
    get_asset_derivative_size,
    get_photo_file_size,
)
from photo_sync.operations.photo_sync import (
    fetch_asset_uuid_sets,
    identify_deleted_photos,
    identify_new_photos,
    insert_photo_with_relations,
    soft_delete_photo,
)

logger = logging.getLogger(__name__)


def sync_photos(
    source_lib: str | Path,
    target_lib: str | Path,
    skip_delete: bool = False,
    skip_albums: bool = False,
    verify: bool = False,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> SyncResult:
    """Synchronize photos and albums from source to target library.

    Args:
        source_lib: Path to source .photoslibrary
        target_lib: Path to target .photoslibrary
        skip_delete: If True, skip deletion sync
        skip_albums: If True, skip album sync
        verify: If True, verify file integrity after copy
        progress_callback: Optional callback(current, total, message) for progress updates

    Returns:
        SyncResult with counts and any errors
    """
    source_lib = Path(source_lib)
    target_lib = Path(target_lib)
    result = SyncResult()

    def report_progress(current: int, total: int, message: str):
        if progress_callback:
            progress_callback(current, total, message)

    try:
        # Connect to databases
        source_conn = connect_readonly(source_lib)
        target_conn = connect_readwrite(target_lib)

        try:
            # Refuse to sync across a Photos schema-version mismatch — it would
            # fail the column-by-column row copy on every asset.
            assert_schema_compatible(source_conn, target_conn)

            # Fetch UUID sets once for both new and deleted photo identification
            logger.info("Identifying new photos...")
            source_uuids, target_uuids = fetch_asset_uuid_sets(source_conn, target_conn)

            # Phase 1: Sync new photos
            new_photos = identify_new_photos(
                source_conn, target_conn,
                source_uuids=source_uuids, target_uuids=target_uuids,
            )

            if new_photos:
                # Check disk space (originals + their derivative thumbnails)
                total_size = sum(
                    (get_photo_file_size(source_lib, asset) or 0)
                    + get_asset_derivative_size(source_lib, asset)
                    for asset in new_photos
                )
                has_space, available, required = check_disk_space(target_lib, total_size)
                if not has_space:
                    result.errors.append(
                        f"Insufficient disk space: need {required} bytes, have {available} bytes"
                    )
                    return result

                logger.info(f"Syncing {len(new_photos)} new photos...")
                for i, asset in enumerate(new_photos):
                    report_progress(i + 1, len(new_photos), f"Copying {asset.filename}")
                    try:
                        # Copy file
                        bytes_copied = copy_photo_file(source_lib, target_lib, asset)
                        if bytes_copied > 0:
                            result.files_copied += 1
                            result.bytes_copied += bytes_copied

                        # Insert database records
                        target_conn.execute("BEGIN TRANSACTION")
                        try:
                            insert_photo_with_relations(target_conn, asset, source_conn)
                            target_conn.execute("COMMIT")
                            result.photos_added += 1
                        except Exception as e:
                            target_conn.execute("ROLLBACK")
                            raise e

                        # Copy the asset's derivative thumbnails/previews so
                        # Photos doesn't have to regenerate them on first view.
                        # Best-effort: a derivative failure never fails the photo
                        # (Photos can always rebuild them).
                        try:
                            d_files, d_bytes = copy_asset_derivatives(
                                source_lib, target_lib, asset
                            )
                            result.derivative_files_copied += d_files
                            result.derivative_bytes_copied += d_bytes
                        except Exception as e:
                            result.warnings.append(
                                f"Failed to copy derivatives for {asset.uuid}: {e}"
                            )
                            logger.warning(
                                f"Failed to copy derivatives for {asset.uuid}: {e}"
                            )

                    except Exception as e:
                        result.warnings.append(f"Failed to sync photo {asset.uuid}: {e}")
                        logger.warning(f"Failed to sync photo {asset.uuid}: {e}")

            # Phase 1b: Backfill derivatives for photos already in the target.
            # Photos synced before thumbnail-copying existed have their originals
            # but no derivatives, so Photos regenerates every thumbnail on view.
            # This copies the missing ones (skipping any already present).
            existing_uuids = source_uuids & target_uuids
            if existing_uuids:
                logger.info(
                    f"Backfilling thumbnails for {len(existing_uuids)} existing photos..."
                )
                d_files, d_bytes, d_warnings = backfill_derivatives(
                    source_lib, target_lib, existing_uuids,
                    progress_callback=(
                        (lambda c, t, m: report_progress(c, t, m))
                        if progress_callback else None
                    ),
                )
                result.derivative_files_copied += d_files
                result.derivative_bytes_copied += d_bytes
                result.warnings.extend(d_warnings)

            # Phase 2: Sync deleted photos
            if not skip_delete:
                logger.info("Identifying deleted photos...")
                deleted_uuids = identify_deleted_photos(
                    source_conn, target_conn,
                    source_uuids=source_uuids, target_uuids=target_uuids,
                )

                if deleted_uuids:
                    logger.info(f"Syncing {len(deleted_uuids)} deleted photos...")
                    for i, uuid in enumerate(deleted_uuids):
                        report_progress(i + 1, len(deleted_uuids), f"Deleting {uuid[:8]}...")
                        try:
                            target_conn.execute("BEGIN TRANSACTION")
                            try:
                                if soft_delete_photo(target_conn, uuid):
                                    result.photos_deleted += 1
                                target_conn.execute("COMMIT")
                            except Exception as e:
                                target_conn.execute("ROLLBACK")
                                raise e
                        except Exception as e:
                            result.warnings.append(f"Failed to delete photo {uuid}: {e}")
                            logger.warning(f"Failed to delete photo {uuid}: {e}")

            # Phase 3: Sync albums
            if not skip_albums:
                album_result = sync_albums(
                    source_lib, target_lib,
                    source_conn=source_conn,
                    target_conn=target_conn,
                    progress_callback=progress_callback,
                )
                result.merge(album_result)

            # Phase 4: Sync favourites
            logger.info("Syncing favourite status...")
            favourite_changes = identify_favourite_changes(source_conn, target_conn)
            if favourite_changes:
                logger.info(f"Syncing {len(favourite_changes)} favourite changes...")
                target_conn.execute("BEGIN TRANSACTION")
                try:
                    result.favourites_synced = sync_favourites(target_conn, favourite_changes)
                    target_conn.execute("COMMIT")
                except Exception as e:
                    target_conn.execute("ROLLBACK")
                    result.warnings.append(f"Failed to sync favourites: {e}")
                    logger.warning(f"Failed to sync favourites: {e}")

        finally:
            source_conn.close()
            target_conn.close()

    except SchemaVersionMismatchError:
        # Surfaced to the caller (CLI) for a dedicated message and exit code.
        raise
    except Exception as e:
        result.errors.append(f"Sync failed: {e}")
        logger.error(f"Sync failed: {e}")

    return result


def sync_albums(
    source_lib: str | Path,
    target_lib: str | Path,
    source_conn=None,
    target_conn=None,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> SyncResult:
    """Synchronize albums and memberships from source to target library.

    Args:
        source_lib: Path to source .photoslibrary
        target_lib: Path to target .photoslibrary
        source_conn: Optional existing source connection
        target_conn: Optional existing target connection
        progress_callback: Optional callback for progress updates

    Returns:
        SyncResult with album sync counts
    """
    source_lib = Path(source_lib)
    target_lib = Path(target_lib)
    result = SyncResult()

    def report_progress(current: int, total: int, message: str):
        if progress_callback:
            progress_callback(current, total, message)

    # Use existing connections or create new ones
    own_connections = source_conn is None
    if own_connections:
        source_conn = connect_readonly(source_lib)
        target_conn = connect_readwrite(target_lib)

    try:
        # Sync folders first (for parent references)
        logger.info("Syncing album folders...")
        sync_album_folders(source_conn, target_conn)

        # Sync new albums
        logger.info("Identifying new albums...")
        new_albums = identify_new_albums(source_conn, target_conn)

        if new_albums:
            logger.info(f"Syncing {len(new_albums)} new albums...")
            for i, album in enumerate(new_albums):
                report_progress(i + 1, len(new_albums), f"Creating album {album.title or album.uuid[:8]}")
                try:
                    target_conn.execute("BEGIN TRANSACTION")
                    try:
                        insert_album_with_hierarchy(target_conn, album, source_conn)
                        target_conn.execute("COMMIT")
                        result.albums_added += 1
                    except Exception as e:
                        target_conn.execute("ROLLBACK")
                        raise e
                except Exception as e:
                    result.warnings.append(f"Failed to sync album {album.uuid}: {e}")
                    logger.warning(f"Failed to sync album {album.uuid}: {e}")

        # Sync album memberships
        logger.info("Syncing album memberships...")
        to_add, to_remove = diff_album_memberships(source_conn, target_conn)

        if to_add or to_remove:
            logger.info(f"Syncing {len(to_add)} additions, {len(to_remove)} removals...")
            target_conn.execute("BEGIN TRANSACTION")
            try:
                added, removed = sync_album_memberships(
                    target_conn, to_add, to_remove
                )
                target_conn.execute("COMMIT")
                result.album_memberships_added = added
                result.album_memberships_removed = removed
            except Exception as e:
                target_conn.execute("ROLLBACK")
                result.errors.append(f"Failed to sync memberships: {e}")
                logger.error(f"Failed to sync memberships: {e}")

    finally:
        if own_connections:
            source_conn.close()
            target_conn.close()

    return result


def create_sync_plan(
    source_lib: str | Path,
    target_lib: str | Path,
    skip_delete: bool = False,
    skip_albums: bool = False,
) -> SyncPlan:
    """Create a plan of what would be synced (dry-run mode).

    Args:
        source_lib: Path to source .photoslibrary
        target_lib: Path to target .photoslibrary
        skip_delete: If True, skip deletion analysis
        skip_albums: If True, skip album analysis

    Returns:
        SyncPlan with details of planned changes
    """
    source_lib = Path(source_lib)
    target_lib = Path(target_lib)
    plan = SyncPlan()

    source_conn = connect_readonly(source_lib)
    target_conn = connect_readonly(target_lib)  # Read-only for planning

    try:
        # Refuse to plan a sync we could not execute (schema-version mismatch).
        assert_schema_compatible(source_conn, target_conn)

        # Fetch UUID sets once for both new and deleted photo analysis
        source_uuids, target_uuids = fetch_asset_uuid_sets(source_conn, target_conn)

        # Analyze new photos
        new_photos = identify_new_photos(
            source_conn, target_conn,
            source_uuids=source_uuids, target_uuids=target_uuids,
        )
        plan.photos_to_add = [asset.uuid for asset in new_photos]

        # Calculate total size and collect details (originals + derivatives)
        for asset in new_photos:
            size = get_photo_file_size(source_lib, asset) or 0
            plan.total_bytes_to_copy += size + get_asset_derivative_size(source_lib, asset)
            plan.photo_details.append({
                "uuid": asset.uuid,
                "filename": asset.filename,
                "size": size,
            })

        # Analyze deleted photos
        if not skip_delete:
            deleted_uuids = identify_deleted_photos(
                source_conn, target_conn,
                source_uuids=source_uuids, target_uuids=target_uuids,
            )
            plan.photos_to_delete = deleted_uuids

        # Analyze albums
        if not skip_albums:
            new_albums = identify_new_albums(source_conn, target_conn)
            plan.albums_to_add = [album.uuid for album in new_albums]
            plan.album_details = [
                {"uuid": album.uuid, "title": album.title}
                for album in new_albums
            ]

            to_add, to_remove = diff_album_memberships(source_conn, target_conn)
            plan.memberships_to_add = to_add
            plan.memberships_to_remove = to_remove

        # Analyze favourites
        favourite_changes = identify_favourite_changes(source_conn, target_conn)
        plan.favourites_to_sync = [uuid for uuid, _, _ in favourite_changes]

    finally:
        source_conn.close()
        target_conn.close()

    return plan


__all__ = [
    "sync_photos",
    "sync_albums",
    "create_sync_plan",
]
