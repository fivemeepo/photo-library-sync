"""Main sync orchestration for photo library sync."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from photo_sync.db.connection import connect_readonly, connect_readwrite
from photo_sync.db.queries import (
    fetch_favourite_candidates_since,
    get_assets_by_uuids,
)
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
    check_disk_space,
    copy_asset_derivatives,
    copy_photo_file,
    get_asset_derivative_size,
    get_photo_file_size,
)
from photo_sync.operations.incremental import (
    plan_album_defs_sync,
    plan_asset_sync,
    plan_favourite_sync,
    plan_membership_sync,
)
from photo_sync.operations.photo_sync import (
    fetch_asset_uuid_sets,
    identify_deleted_photos,
    identify_new_photos,
    insert_photo_with_relations,
    soft_delete_photo,
)
from photo_sync.operations.sync_state import load_sync_state, save_sync_state

logger = logging.getLogger(__name__)


def _apply_new_photos(
    source_lib: Path,
    target_lib: Path,
    source_conn,
    target_conn,
    new_photos: list,
    result: SyncResult,
    report_progress: Callable[[int, int, str], None],
) -> bool:
    """Copy + insert new photos (originals + derivatives).

    Returns False (and records an error) if there is not enough disk space for
    the originals + their derivatives; True otherwise. A per-photo failure is
    recorded as a warning and does not stop the loop.
    """
    if not new_photos:
        return True

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
        return False

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

    return True


def _apply_deleted_photos(
    target_conn,
    deleted_uuids: list[str],
    result: SyncResult,
    report_progress: Callable[[int, int, str], None],
) -> None:
    """Soft-delete photos that no longer exist in the source.

    A per-photo failure is recorded as a warning and does not stop the loop.
    """
    if not deleted_uuids:
        return

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


def _apply_album_definitions(
    source_conn,
    target_conn,
    result: SyncResult,
    report_progress: Callable[[int, int, str], None],
) -> None:
    """Full album-definition sync: folders first, then new user albums.

    A per-album failure is recorded as a warning and does not stop the loop.
    """
    # Sync folders first (for parent references)
    logger.info("Syncing album folders...")
    sync_album_folders(source_conn, target_conn)

    # Sync new albums
    logger.info("Identifying new albums...")
    new_albums = identify_new_albums(source_conn, target_conn)
    if not new_albums:
        return

    logger.info(f"Syncing {len(new_albums)} new albums...")
    for i, album in enumerate(new_albums):
        report_progress(
            i + 1, len(new_albums),
            f"Creating album {album.title or album.uuid[:8]}",
        )
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


def _apply_membership_full(source_conn, target_conn, result: SyncResult) -> None:
    """Full membership sync: diff source vs target and apply adds + removes."""
    logger.info("Syncing album memberships...")
    to_add, to_remove = diff_album_memberships(source_conn, target_conn)
    if not (to_add or to_remove):
        return

    logger.info(f"Syncing {len(to_add)} additions, {len(to_remove)} removals...")
    target_conn.execute("BEGIN TRANSACTION")
    try:
        added, removed = sync_album_memberships(target_conn, to_add, to_remove)
        target_conn.execute("COMMIT")
        result.album_memberships_added += added
        result.album_memberships_removed += removed
    except Exception as e:
        target_conn.execute("ROLLBACK")
        raise e


def _resolve_membership_uuids(
    source_conn, added: list[tuple[int, int]]
) -> list[tuple[str, str]]:
    """Map source (album_pk, asset_pk) membership rows to (album_uuid, asset_uuid).

    The existing add path (sync_album_memberships) resolves UUIDs against the
    target, so the source PKs must be translated to stable UUIDs first.
    """
    album_pks = {a for a, _ in added}
    asset_pks = {p for _, p in added}
    album_uuid = _pk_to_uuid(source_conn, "ZGENERICALBUM", album_pks)
    asset_uuid = _pk_to_uuid(source_conn, "ZASSET", asset_pks)
    resolved = []
    for a_pk, p_pk in added:
        a_uuid = album_uuid.get(a_pk)
        p_uuid = asset_uuid.get(p_pk)
        if a_uuid and p_uuid:
            resolved.append((a_uuid, p_uuid))
        else:
            logger.warning(
                f"Skipping membership with unresolved UUIDs: "
                f"album_pk={a_pk}, asset_pk={p_pk}"
            )
    return resolved


def _pk_to_uuid(conn, table: str, pks: set[int]) -> dict[int, str]:
    """Map Z_PK -> ZUUID for the given table and set of PKs."""
    if not pks:
        return {}
    placeholders = ",".join("?" * len(pks))
    cursor = conn.execute(
        f"SELECT Z_PK, ZUUID FROM {table} WHERE Z_PK IN ({placeholders})",
        list(pks),
    )
    return {row[0]: row[1] for row in cursor.fetchall()}


def sync_photos(
    source_lib: str | Path,
    target_lib: str | Path,
    skip_delete: bool = False,
    skip_albums: bool = False,
    verify: bool = False,
    full: bool = False,
    progress_callback: Callable[[int, int, str], None] | None = None,
) -> SyncResult:
    """Synchronize photos and albums from source to target library.

    Each dimension (assets, favourites, album definitions, memberships) is
    synced incrementally: a cheap delta is computed against the per-target
    state saved by the last run, and only the delta is applied. If the delta
    cannot be proven to fully explain the change, that dimension escalates to a
    full source-vs-target comparison for this run. State is persisted at the end
    for every dimension that completed without raising, so a dimension that
    fails re-runs next time from its previous watermark.

    Args:
        source_lib: Path to source .photoslibrary
        target_lib: Path to target .photoslibrary
        skip_delete: If True, skip deletion sync
        skip_albums: If True, skip album sync
        verify: If True, verify file integrity after copy
        full: If True, ignore saved state and run a full comparison for every
            dimension (refreshing state afterwards).
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

            # Per-target incremental state from the last run. full=True ignores
            # it so every dimension takes its full-comparison path.
            state = {} if full else load_sync_state(target_lib)
            new_state = dict(state)

            # ----- Assets (new + deleted + derivatives) -----
            asset_ok = True
            try:
                plan = plan_asset_sync(source_conn, None if full else state.get("assets"))
                if plan.full:
                    logger.info("Identifying new/deleted photos (full comparison)...")
                    source_uuids, target_uuids = fetch_asset_uuid_sets(
                        source_conn, target_conn
                    )
                    new_assets = identify_new_photos(
                        source_conn, target_conn,
                        source_uuids=source_uuids, target_uuids=target_uuids,
                    )
                    deleted_uuids = ([] if skip_delete else identify_deleted_photos(
                        source_conn, target_conn,
                        source_uuids=source_uuids, target_uuids=target_uuids,
                    ))
                else:
                    new_assets = (
                        get_assets_by_uuids(source_conn, plan.added_uuids)
                        if plan.added_uuids else []
                    )
                    deleted_uuids = [] if skip_delete else plan.trashed_uuids

                had_space = _apply_new_photos(
                    source_lib, target_lib, source_conn, target_conn,
                    new_assets, result, report_progress,
                )
                if not had_space:
                    return result
                if not skip_delete:
                    _apply_deleted_photos(
                        target_conn, deleted_uuids, result, report_progress
                    )
                new_state["assets"] = plan.invariant
            except Exception as e:  # noqa: BLE001 - record, don't abort other dimensions
                asset_ok = False
                result.warnings.append(f"Asset sync failed: {e}")
                logger.warning(f"Asset sync failed: {e}")

            # ----- Favourites -----
            fav_ok = True
            try:
                prev_fav = None if full else state.get("favourites")
                if prev_fav:
                    # Delta: apply favourite differences for candidate UUIDs
                    # FIRST (compare candidate source ZFAVORITE to target), then
                    # verify with plan_favourite_sync.
                    candidates = fetch_favourite_candidates_since(
                        source_conn, prev_fav["max_mod_date"]
                    )
                    candidate_changes = []
                    for uuid, source_fav in candidates:
                        row = target_conn.execute(
                            "SELECT ZFAVORITE FROM ZASSET "
                            "WHERE ZUUID = ? AND ZTRASHEDSTATE = 0",
                            (uuid,),
                        ).fetchone()
                        if row is not None and row[0] != source_fav:
                            candidate_changes.append((uuid, source_fav, row[0]))
                    if candidate_changes:
                        logger.info(
                            f"Syncing {len(candidate_changes)} favourite changes (delta)..."
                        )
                        target_conn.execute("BEGIN TRANSACTION")
                        try:
                            result.favourites_synced += sync_favourites(
                                target_conn, candidate_changes
                            )
                            target_conn.execute("COMMIT")
                        except Exception as e:
                            target_conn.execute("ROLLBACK")
                            raise e

                fav_plan = plan_favourite_sync(source_conn, target_conn, prev_fav)
                if fav_plan.full:
                    logger.info("Syncing favourite status (full comparison)...")
                    favourite_changes = identify_favourite_changes(
                        source_conn, target_conn
                    )
                    if favourite_changes:
                        logger.info(
                            f"Syncing {len(favourite_changes)} favourite changes..."
                        )
                        target_conn.execute("BEGIN TRANSACTION")
                        try:
                            result.favourites_synced += sync_favourites(
                                target_conn, favourite_changes
                            )
                            target_conn.execute("COMMIT")
                        except Exception as e:
                            target_conn.execute("ROLLBACK")
                            raise e
                new_state["favourites"] = fav_plan.state
            except Exception as e:  # noqa: BLE001 - record, don't abort other dimensions
                fav_ok = False
                result.warnings.append(f"Favourite sync failed: {e}")
                logger.warning(f"Favourite sync failed: {e}")

            # ----- Album definitions (folders + new albums) -----
            # Skipped when skip_albums: state is not refreshed, so a later
            # non-skip run re-runs the full comparison.
            album_ok = True
            if not skip_albums:
                try:
                    needs_full, cur_defs = plan_album_defs_sync(
                        source_conn, None if full else state.get("albums")
                    )
                    if needs_full:
                        logger.info("Syncing album definitions (full comparison)...")
                        _apply_album_definitions(
                            source_conn, target_conn, result, report_progress
                        )
                    new_state["albums"] = cur_defs
                except Exception as e:  # noqa: BLE001 - record, don't abort other dimensions
                    album_ok = False
                    result.warnings.append(f"Album definition sync failed: {e}")
                    logger.warning(f"Album definition sync failed: {e}")

            # ----- Album memberships -----
            membership_ok = True
            if not skip_albums:
                try:
                    m_plan = plan_membership_sync(
                        source_conn, None if full else state.get("membership")
                    )
                    if m_plan.full:
                        logger.info("Syncing album memberships (full comparison)...")
                        _apply_membership_full(source_conn, target_conn, result)
                    elif m_plan.added:
                        # Delta: source (album_pk, asset_pk) -> (uuid, uuid),
                        # then apply through the existing add path.
                        to_add = _resolve_membership_uuids(source_conn, m_plan.added)
                        logger.info(
                            f"Syncing {len(to_add)} album memberships (delta)..."
                        )
                        target_conn.execute("BEGIN TRANSACTION")
                        try:
                            added, _removed = sync_album_memberships(
                                target_conn, to_add, []
                            )
                            target_conn.execute("COMMIT")
                            result.album_memberships_added += added
                        except Exception as e:
                            target_conn.execute("ROLLBACK")
                            raise e
                    new_state["membership"] = m_plan.invariant
                except Exception as e:  # noqa: BLE001 - record, don't abort other dimensions
                    membership_ok = False
                    result.warnings.append(f"Membership sync failed: {e}")
                    logger.warning(f"Membership sync failed: {e}")

            # Persist state for dimensions that completed cleanly; a failed
            # dimension keeps its previous watermark so it re-runs next time.
            to_save = dict(state)
            if asset_ok and "assets" in new_state:
                to_save["assets"] = new_state["assets"]
            if fav_ok and "favourites" in new_state:
                to_save["favourites"] = new_state["favourites"]
            if not skip_albums and album_ok and "albums" in new_state:
                to_save["albums"] = new_state["albums"]
            if not skip_albums and membership_ok and "membership" in new_state:
                to_save["membership"] = new_state["membership"]
            save_sync_state(target_lib, to_save)

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
