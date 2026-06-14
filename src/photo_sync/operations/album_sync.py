"""Album sync operations - identify and sync albums between libraries."""

import logging
import sqlite3

from photo_sync.db.mutations import (
    delete_album_membership,
    insert_album_from_row,
    insert_album_key_asset,
    insert_album_membership,
    update_album_cached_counts,
)
from photo_sync.db.queries import (
    get_album_key_assets_with_uuids,
    get_album_memberships_with_uuids,
    get_album_pk_by_uuid,
    get_all_albums,
    get_asset_pk_by_uuid,
)
from photo_sync.models import Album

logger = logging.getLogger(__name__)

# Album kinds
ALBUM_KIND_USER = 2
ALBUM_KIND_FOLDER = 4000


def identify_new_albums(
    source_conn: sqlite3.Connection,
    target_conn: sqlite3.Connection
) -> list[Album]:
    """Identify user albums in source that don't exist in target.

    Args:
        source_conn: Connection to source database (read-only)
        target_conn: Connection to target database

    Returns:
        List of Album objects for albums to sync
    """
    # Get user albums from both libraries
    source_albums = get_all_albums(source_conn, kind=ALBUM_KIND_USER)
    target_albums = get_all_albums(target_conn, kind=ALBUM_KIND_USER)

    # Build UUID sets
    source_uuids = {album.uuid for album in source_albums}
    target_uuids = {album.uuid for album in target_albums}

    # Find new albums
    new_uuids = source_uuids - target_uuids

    if not new_uuids:
        logger.info("No new albums to sync")
        return []

    logger.info(f"Found {len(new_uuids)} new albums to sync")

    # Return album objects for new albums
    return [album for album in source_albums if album.uuid in new_uuids]


def diff_album_memberships(
    source_conn: sqlite3.Connection,
    target_conn: sqlite3.Connection
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Compare album memberships between source and target.

    Args:
        source_conn: Connection to source database (read-only)
        target_conn: Connection to target database

    Returns:
        Tuple of (memberships_to_add, memberships_to_remove)
        Each list contains (album_uuid, asset_uuid) tuples
    """
    # Get memberships from both libraries
    source_memberships = set(get_album_memberships_with_uuids(source_conn))
    target_memberships = set(get_album_memberships_with_uuids(target_conn))

    # Find differences
    to_add = source_memberships - target_memberships
    to_remove = target_memberships - source_memberships

    logger.info(f"Album membership diff: {len(to_add)} to add, {len(to_remove)} to remove")

    return list(to_add), list(to_remove)


def insert_album_with_hierarchy(
    target_conn: sqlite3.Connection,
    album: Album,
    source_conn: sqlite3.Connection
) -> int:
    """Insert an album by copying ALL fields from source, resolving parent folder references.

    This copies all columns from ZGENERICALBUM to ensure complete data sync.

    Args:
        target_conn: Connection to target database (read-write)
        album: Album object from source (used for z_pk and parent_folder lookup)
        source_conn: Connection to source database (read-only)

    Returns:
        Z_PK of the inserted album
    """
    # Resolve parent folder PK in target
    parent_pk = None
    if album.parent_folder:
        # Get parent folder UUID from source
        cursor = source_conn.execute(
            "SELECT ZUUID FROM ZGENERICALBUM WHERE Z_PK = ?",
            (album.parent_folder,)
        )
        row = cursor.fetchone()
        if row:
            parent_uuid = row[0]
            # Find parent in target by UUID
            parent_pk = get_album_pk_by_uuid(target_conn, parent_uuid)

    # Insert album copying ALL fields from source
    new_pk = insert_album_from_row(
        target_conn, source_conn, album.z_pk, parent_folder_pk=parent_pk
    )
    logger.debug(f"Inserted album {album.uuid} ({album.title}) with PK {new_pk}")

    return new_pk


def sync_album_memberships(
    target_conn: sqlite3.Connection,
    memberships_to_add: list[tuple[str, str]],
    memberships_to_remove: list[tuple[str, str]]
) -> tuple[int, int]:
    """Sync album memberships in target database.

    Args:
        target_conn: Connection to target database (read-write)
        memberships_to_add: List of (album_uuid, asset_uuid) to add
        memberships_to_remove: List of (album_uuid, asset_uuid) to remove

    Returns:
        Tuple of (added_count, removed_count)
    """
    added = 0
    removed = 0
    affected_albums = set()

    # Add memberships
    for album_uuid, asset_uuid in memberships_to_add:
        album_pk = get_album_pk_by_uuid(target_conn, album_uuid)
        asset_pk = get_asset_pk_by_uuid(target_conn, asset_uuid)

        if album_pk and asset_pk:
            if insert_album_membership(target_conn, album_pk, asset_pk):
                added += 1
                affected_albums.add(album_pk)
        else:
            logger.warning(
                f"Cannot add membership: album={album_uuid} ({album_pk}), "
                f"asset={asset_uuid} ({asset_pk})"
            )

    # Remove memberships
    for album_uuid, asset_uuid in memberships_to_remove:
        album_pk = get_album_pk_by_uuid(target_conn, album_uuid)
        asset_pk = get_asset_pk_by_uuid(target_conn, asset_uuid)

        if album_pk and asset_pk:
            if delete_album_membership(target_conn, album_pk, asset_pk):
                removed += 1
                affected_albums.add(album_pk)
        else:
            logger.warning(
                f"Cannot remove membership: album={album_uuid} ({album_pk}), "
                f"asset={asset_uuid} ({asset_pk})"
            )

    # Update cached counts for affected albums
    for album_pk in affected_albums:
        update_album_cached_counts(target_conn, album_pk)

    logger.info(f"Synced memberships: {added} added, {removed} removed")
    return added, removed


def sync_album_folders(
    source_conn: sqlite3.Connection,
    target_conn: sqlite3.Connection
) -> int:
    """Sync album folders from source to target.

    Folders must be synced before albums to establish parent references.

    Args:
        source_conn: Connection to source database (read-only)
        target_conn: Connection to target database (read-write)

    Returns:
        Number of folders synced
    """
    # Get folders from both libraries
    source_folders = get_all_albums(source_conn, kind=ALBUM_KIND_FOLDER)
    target_folders = get_all_albums(target_conn, kind=ALBUM_KIND_FOLDER)

    # Build UUID sets
    source_uuids = {folder.uuid for folder in source_folders}
    target_uuids = {folder.uuid for folder in target_folders}

    # Find new folders
    new_uuids = source_uuids - target_uuids

    if not new_uuids:
        logger.debug("No new folders to sync")
        return 0

    # Sort folders by hierarchy (parents first)
    new_folders = [f for f in source_folders if f.uuid in new_uuids]
    sorted_folders = _sort_by_hierarchy(new_folders, source_conn)

    # Insert folders (commits implicit transaction started by auto-commit mode)
    count = 0
    try:
        for folder in sorted_folders:
            try:
                insert_album_with_hierarchy(target_conn, folder, source_conn)
                count += 1
            except Exception as e:
                logger.warning(f"Failed to sync folder {folder.uuid}: {e}")
        # Commit the implicit transaction started by INSERT statements
        target_conn.commit()
    except Exception as e:
        target_conn.rollback()
        raise e

    logger.info(f"Synced {count} album folders")
    return count


def _sort_by_hierarchy(
    albums: list[Album],
    conn: sqlite3.Connection
) -> list[Album]:
    """Sort albums so parents come before children.

    Args:
        albums: List of albums to sort
        conn: Database connection for looking up parents

    Returns:
        Sorted list of albums
    """
    # Build parent map
    uuid_to_album = {a.uuid: a for a in albums}

    # Get parent UUIDs
    parent_map = {}
    for album in albums:
        if album.parent_folder:
            cursor = conn.execute(
                "SELECT ZUUID FROM ZGENERICALBUM WHERE Z_PK = ?",
                (album.parent_folder,)
            )
            row = cursor.fetchone()
            if row:
                parent_map[album.uuid] = row[0]

    # Topological sort
    result = []
    visited = set()

    def visit(uuid: str):
        if uuid in visited:
            return
        visited.add(uuid)

        # Visit parent first
        parent_uuid = parent_map.get(uuid)
        if parent_uuid and parent_uuid in uuid_to_album:
            visit(parent_uuid)

        if uuid in uuid_to_album:
            result.append(uuid_to_album[uuid])

    for album in albums:
        visit(album.uuid)

    return result


def sync_album_key_assets(
    source_conn: sqlite3.Connection,
    target_conn: sqlite3.Connection
) -> tuple[int, int]:
    """Sync album key assets (thumbnails) from source to target.

    Album key assets determine which photos are used for album thumbnails.

    Args:
        source_conn: Connection to source database (read-only)
        target_conn: Connection to target database (read-write)

    Returns:
        Tuple of (added_count, removed_count)
    """
    # Get key assets from both libraries (album_uuid, asset_uuid, fok)
    source_key_assets = set(get_album_key_assets_with_uuids(source_conn))
    target_key_assets = set(get_album_key_assets_with_uuids(target_conn))

    # Compare by (album_uuid, asset_uuid) only
    source_pairs = {(ka[0], ka[1]): ka[2] for ka in source_key_assets}
    target_pairs = {(ka[0], ka[1]): ka[2] for ka in target_key_assets}

    to_add = set(source_pairs.keys()) - set(target_pairs.keys())
    to_remove = set(target_pairs.keys()) - set(source_pairs.keys())

    added = 0
    removed = 0

    # Remove key assets
    for album_uuid, asset_uuid in to_remove:
        album_pk = get_album_pk_by_uuid(target_conn, album_uuid)
        asset_pk = get_asset_pk_by_uuid(target_conn, asset_uuid)

        if album_pk and asset_pk:
            target_conn.execute(
                """
                DELETE FROM Z_32KEYASSETS
                WHERE Z_32ALBUMSBEINGKEYASSETS = ? AND Z_3KEYASSETS = ?
                """,
                (album_pk, asset_pk)
            )
            removed += 1
        else:
            logger.warning(
                f"Cannot remove key asset: album={album_uuid}, asset={asset_uuid}"
            )

    # Add key assets
    for album_uuid, asset_uuid in to_add:
        album_pk = get_album_pk_by_uuid(target_conn, album_uuid)
        asset_pk = get_asset_pk_by_uuid(target_conn, asset_uuid)
        fok = source_pairs.get((album_uuid, asset_uuid))

        if album_pk and asset_pk:
            if insert_album_key_asset(target_conn, album_pk, asset_pk, fok):
                added += 1
        else:
            logger.warning(
                f"Cannot add key asset: album={album_uuid} ({album_pk}), "
                f"asset={asset_uuid} ({asset_pk})"
            )

    logger.info(f"Synced key assets: {added} added, {removed} removed")
    return added, removed


__all__ = [
    "identify_new_albums",
    "diff_album_memberships",
    "insert_album_with_hierarchy",
    "sync_album_memberships",
    "sync_album_folders",
    "sync_album_key_assets",
]
