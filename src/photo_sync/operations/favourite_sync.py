"""Favourite sync operations - sync favourite status between libraries."""

import logging
import sqlite3

logger = logging.getLogger(__name__)


def identify_favourite_changes(
    source_conn: sqlite3.Connection,
    target_conn: sqlite3.Connection
) -> list[tuple[str, int, int]]:
    """Identify photos where favourite status differs between source and target.

    Compares ZASSET.ZFAVORITE between libraries for matching UUIDs.
    Only considers active (non-trashed) photos that exist in both libraries.

    Args:
        source_conn: Connection to source database (read-only)
        target_conn: Connection to target database

    Returns:
        List of (uuid, source_favourite, target_favourite) tuples where values differ
    """
    # Get favourite status from source for active photos
    source_cursor = source_conn.execute(
        """
        SELECT ZUUID, ZFAVORITE
        FROM ZASSET
        WHERE ZTRASHEDSTATE = 0
        """
    )
    source_favourites = {row[0]: row[1] for row in source_cursor.fetchall()}

    # Get favourite status from target for active photos
    target_cursor = target_conn.execute(
        """
        SELECT ZUUID, ZFAVORITE
        FROM ZASSET
        WHERE ZTRASHEDSTATE = 0
        """
    )
    target_favourites = {row[0]: row[1] for row in target_cursor.fetchall()}

    # Find photos that exist in both and have different favourite status
    changes = []
    for uuid, source_fav in source_favourites.items():
        if uuid in target_favourites:
            target_fav = target_favourites[uuid]
            if source_fav != target_fav:
                changes.append((uuid, source_fav, target_fav))

    if changes:
        logger.info(f"Found {len(changes)} photos with different favourite status")
    else:
        logger.info("No favourite status changes to sync")

    return changes


def sync_favourites(
    target_conn: sqlite3.Connection,
    favourite_changes: list[tuple[str, int, int]]
) -> int:
    """Update favourite status in target to match source.

    Args:
        target_conn: Connection to target database (read-write)
        favourite_changes: List of (uuid, source_favourite, target_favourite) tuples

    Returns:
        Number of photos updated
    """
    updated = 0

    for uuid, source_fav, _target_fav in favourite_changes:
        try:
            result = target_conn.execute(
                """
                UPDATE ZASSET
                SET ZFAVORITE = ?, Z_OPT = Z_OPT + 1
                WHERE ZUUID = ? AND ZTRASHEDSTATE = 0
                """,
                (source_fav, uuid)
            )
            if result.rowcount > 0:
                updated += 1
                logger.debug(f"Updated favourite status for {uuid} to {source_fav}")
        except Exception as e:
            logger.warning(f"Failed to update favourite for {uuid}: {e}")

    logger.info(f"Updated favourite status for {updated} photos")
    return updated


__all__ = [
    "identify_favourite_changes",
    "sync_favourites",
]
