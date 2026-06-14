"""Z_PRIMARYKEY table management for Core Data primary keys.

Core Data uses the Z_PRIMARYKEY table to track the next available
primary key (Z_PK) for each entity type. This module provides
functions to safely get and increment these values.
"""

import logging
import sqlite3

logger = logging.getLogger(__name__)

# Entity names as they appear in Z_PRIMARYKEY.Z_NAME
ENTITY_ASSET = "Asset"
ENTITY_ADDITIONAL_ASSET_ATTRIBUTES = "AdditionalAssetAttributes"
ENTITY_EXTENDED_ATTRIBUTES = "ExtendedAttributes"
ENTITY_INTERNAL_RESOURCE = "InternalResource"
ENTITY_GENERIC_ALBUM = "GenericAlbum"
ENTITY_MOMENT = "Moment"


class PKError(Exception):
    """Error managing primary keys."""
    pass


def get_next_pk(conn: sqlite3.Connection, entity_name: str) -> int:
    """Get and increment the next primary key for an entity.

    This function atomically reads the current Z_MAX value from
    Z_PRIMARYKEY, increments it, updates the table, and returns
    the new value for use as Z_PK in a new record.

    Args:
        conn: SQLite connection (must be read-write)
        entity_name: Entity name from Z_PRIMARYKEY.Z_NAME
                    (e.g., "Asset", "GenericAlbum")

    Returns:
        The next available primary key value

    Raises:
        PKError: If entity name is not found or update fails
    """
    cursor = conn.execute(
        "SELECT Z_MAX FROM Z_PRIMARYKEY WHERE Z_NAME = ?",
        (entity_name,)
    )
    row = cursor.fetchone()

    if row is None:
        raise PKError(f"Unknown entity in Z_PRIMARYKEY: {entity_name}")

    current_max = row[0]
    next_pk = current_max + 1

    result = conn.execute(
        "UPDATE Z_PRIMARYKEY SET Z_MAX = ? WHERE Z_NAME = ?",
        (next_pk, entity_name)
    )

    if result.rowcount != 1:
        raise PKError(f"Failed to update Z_PRIMARYKEY for {entity_name}")

    logger.debug(f"Allocated PK {next_pk} for entity {entity_name}")
    return next_pk


def get_current_max_pk(conn: sqlite3.Connection, entity_name: str) -> int:
    """Get the current maximum primary key without incrementing.

    Args:
        conn: SQLite connection
        entity_name: Entity name from Z_PRIMARYKEY.Z_NAME

    Returns:
        Current maximum primary key value

    Raises:
        PKError: If entity name is not found
    """
    cursor = conn.execute(
        "SELECT Z_MAX FROM Z_PRIMARYKEY WHERE Z_NAME = ?",
        (entity_name,)
    )
    row = cursor.fetchone()

    if row is None:
        raise PKError(f"Unknown entity in Z_PRIMARYKEY: {entity_name}")

    return row[0]


def allocate_pk_range(
    conn: sqlite3.Connection,
    entity_name: str,
    count: int
) -> tuple[int, int]:
    """Allocate a range of primary keys for batch inserts.

    Args:
        conn: SQLite connection (must be read-write)
        entity_name: Entity name from Z_PRIMARYKEY.Z_NAME
        count: Number of PKs to allocate

    Returns:
        Tuple of (start_pk, end_pk) inclusive

    Raises:
        PKError: If entity name is not found or update fails
    """
    if count <= 0:
        raise PKError(f"Count must be positive, got {count}")

    cursor = conn.execute(
        "SELECT Z_MAX FROM Z_PRIMARYKEY WHERE Z_NAME = ?",
        (entity_name,)
    )
    row = cursor.fetchone()

    if row is None:
        raise PKError(f"Unknown entity in Z_PRIMARYKEY: {entity_name}")

    current_max = row[0]
    start_pk = current_max + 1
    end_pk = current_max + count

    result = conn.execute(
        "UPDATE Z_PRIMARYKEY SET Z_MAX = ? WHERE Z_NAME = ?",
        (end_pk, entity_name)
    )

    if result.rowcount != 1:
        raise PKError(f"Failed to update Z_PRIMARYKEY for {entity_name}")

    logger.debug(f"Allocated PK range {start_pk}-{end_pk} for entity {entity_name}")
    return start_pk, end_pk


__all__ = [
    "PKError",
    "get_next_pk",
    "get_current_max_pk",
    "allocate_pk_range",
    "ENTITY_ASSET",
    "ENTITY_ADDITIONAL_ASSET_ATTRIBUTES",
    "ENTITY_EXTENDED_ATTRIBUTES",
    "ENTITY_INTERNAL_RESOURCE",
    "ENTITY_GENERIC_ALBUM",
    "ENTITY_MOMENT",
]
