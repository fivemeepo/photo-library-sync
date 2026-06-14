"""Deduplication operations for photos within an album."""

from __future__ import annotations

import logging
import re
import sqlite3

from photo_sync.db.queries import get_album_assets_for_dedup, get_album_by_title
from photo_sync.operations.photo_sync import soft_delete_photo

# Kind value for the "Recently Deleted" trash album
_TRASH_ALBUM_KIND = 3999

logger = logging.getLogger(__name__)

# Matches macOS duplicate suffixes like " (1)", "(2)", " (10)" before the extension
_DUPE_SUFFIX_RE = re.compile(r"^(?P<base>.+?)\s*\(\d+\)(?P<ext>\.[^.]+)$")


def normalize_filename(filename: str) -> tuple[str, str]:
    """Extract base name and extension, stripping macOS duplicate suffixes.

    Args:
        filename: Original filename (e.g. "IMG_7153 (1).PNG")

    Returns:
        Tuple of (base_name, extension) — e.g. ("IMG_7153", ".PNG").
        Extension includes the leading dot. Empty string if no extension.
    """
    m = _DUPE_SUFFIX_RE.match(filename)
    if m:
        return m.group("base"), m.group("ext")

    # No duplicate suffix — split on last dot
    dot_pos = filename.rfind(".")
    if dot_pos <= 0:
        return filename, ""
    return filename[:dot_pos], filename[dot_pos:]


# Type alias for an asset row from get_album_assets_for_dedup
# (uuid, filename, file_size, width, height, date_created)
AssetRow = tuple[str, str, int, int, int, float]


def find_duplicates(
    rows: list[AssetRow],
) -> list[tuple[AssetRow, list[AssetRow]]]:
    """Find duplicate photo groups based on filename, file size, and resolution.

    Args:
        rows: List of (uuid, filename, file_size, width, height, date_created) tuples

    Returns:
        List of (keeper, [duplicates]) tuples. The keeper is the asset with
        the earliest date_created. Only groups with at least one duplicate are returned.
    """
    # Group by normalized filename
    groups: dict[tuple[str, str], list[AssetRow]] = {}
    for row in rows:
        base, ext = normalize_filename(row[1])
        key = (base, ext.lower())
        groups.setdefault(key, []).append(row)

    result = []
    for members in groups.values():
        if len(members) < 2:
            continue

        # Sub-group by (file_size, width, height), skip assets with unknown file size
        size_groups: dict[tuple[int, int, int], list[AssetRow]] = {}
        for member in members:
            if member[2] == 0:  # Skip assets with no file size info
                continue
            size_key = (member[2], member[3], member[4])  # file_size, width, height
            size_groups.setdefault(size_key, []).append(member)

        for candidates in size_groups.values():
            if len(candidates) < 2:
                continue

            # Keeper selection: prioritize files without (N) suffix, then earliest date
            def _keeper_sort_key(r: AssetRow) -> tuple[bool, float]:
                has_suffix = _DUPE_SUFFIX_RE.match(r[1]) is not None
                return (has_suffix, r[5])  # False < True, so no-suffix comes first

            sorted_candidates = sorted(candidates, key=_keeper_sort_key)
            keeper = sorted_candidates[0]
            duplicates = sorted_candidates[1:]
            result.append((keeper, duplicates))

    return result


def dedup_album_dry_run(
    conn: sqlite3.Connection,
    album_title: str,
) -> dict:
    """Analyze an album for duplicates without making changes.

    Args:
        conn: SQLite connection (read-only is sufficient)
        album_title: Title of the album to deduplicate

    Returns:
        Report dict with keys: album, total_assets, total_duplicates, total_to_delete, groups.
        Each group has: keep (dict with uuid, filename), delete (list of dicts).

    Raises:
        ValueError: If album is not found
    """
    album = get_album_by_title(conn, album_title)
    if album is None:
        raise ValueError(f"Album not found: '{album_title}'")

    rows = get_album_assets_for_dedup(conn, album.z_pk)
    groups = find_duplicates(rows)

    report_groups = []
    total_to_delete = 0
    for keeper, duplicates in groups:
        report_groups.append({
            "keep": {"uuid": keeper[0], "filename": keeper[1]},
            "delete": [
                {"uuid": d[0], "filename": d[1]} for d in duplicates
            ],
        })
        total_to_delete += len(duplicates)

    return {
        "album": album_title,
        "total_assets": len(rows),
        "total_duplicates": len(groups),
        "total_to_delete": total_to_delete,
        "groups": report_groups,
    }


def dedup_album_execute(
    conn: sqlite3.Connection,
    album_title: str,
) -> dict:
    """Remove duplicates from an album by soft-deleting them.

    Args:
        conn: SQLite connection (read-write)
        album_title: Title of the album to deduplicate

    Returns:
        Result dict with keys: album, groups, deleted, errors.

    Raises:
        ValueError: If album is not found
    """
    album = get_album_by_title(conn, album_title)
    if album is None:
        raise ValueError(f"Album not found: '{album_title}'")

    rows = get_album_assets_for_dedup(conn, album.z_pk)
    groups = find_duplicates(rows)

    deleted = 0
    errors: list[str] = []

    for keeper, duplicates in groups:
        for dup in duplicates:
            try:
                if soft_delete_photo(conn, dup[0]):
                    deleted += 1
                    logger.info(f"Deleted duplicate {dup[1]} (uuid={dup[0]}), kept {keeper[1]}")
                else:
                    errors.append(f"Failed to delete {dup[0]}")
                conn.commit()
            except Exception as e:
                conn.rollback()
                errors.append(f"Error deleting {dup[0]}: {e}")
                logger.warning(f"Error deleting duplicate {dup[0]}: {e}")

    # Update the "Recently Deleted" trash album cached counts so Photos.app shows them
    if deleted > 0:
        try:
            _update_trash_album_counts(conn)
            conn.commit()
        except Exception as e:
            logger.warning(f"Failed to update trash album counts: {e}")

    return {
        "album": album_title,
        "groups": len(groups),
        "deleted": deleted,
        "errors": errors,
    }


def _update_trash_album_counts(conn: sqlite3.Connection) -> None:
    """Update the Recently Deleted (trash) album cached counts.

    Photos.app uses the trash album (kind=3999) cached counts to display
    items in "Recently Deleted". Without updating these, trashed photos
    won't appear there.
    """
    # Find the trash album
    row = conn.execute(
        "SELECT Z_PK FROM ZGENERICALBUM WHERE ZKIND = ?",
        (_TRASH_ALBUM_KIND,)
    ).fetchone()
    if row is None:
        return

    trash_pk = row[0]

    # Count all trashed assets
    counts = conn.execute(
        """
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN ZKIND = 0 THEN 1 ELSE 0 END) as photos,
            SUM(CASE WHEN ZKIND = 1 THEN 1 ELSE 0 END) as videos
        FROM ZASSET
        WHERE ZTRASHEDSTATE = 1
        """
    ).fetchone()

    conn.execute(
        """
        UPDATE ZGENERICALBUM
        SET ZCACHEDCOUNT = ?, ZCACHEDPHOTOSCOUNT = ?, ZCACHEDVIDEOSCOUNT = ?,
            Z_OPT = Z_OPT + 1
        WHERE Z_PK = ?
        """,
        (counts[0] or 0, counts[1] or 0, counts[2] or 0, trash_pk)
    )
