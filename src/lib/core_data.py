"""Core Data helpers for Apple Photos database operations.

Core Data uses a custom epoch starting at 2001-01-01 00:00:00 UTC.
All timestamps in Photos.sqlite use this epoch.
"""

from __future__ import annotations

from datetime import datetime, timezone

# Core Data epoch: 2001-01-01 00:00:00 UTC
# Difference from Unix epoch (1970-01-01) in seconds
CORE_DATA_EPOCH = 978307200

# Z_ENT constants for each entity type (from Z_PRIMARYKEY table)
Z_ENT_ADDITIONAL_ASSET_ATTRIBUTES = 1
Z_ENT_ASSET = 3
Z_ENT_EXTENDED_ATTRIBUTES = 28
Z_ENT_GENERIC_ALBUM = 32
Z_ENT_INTERNAL_RESOURCE = 51
Z_ENT_MOMENT = 58


def core_data_to_unix(timestamp: float | None) -> float | None:
    """Convert Core Data timestamp to Unix timestamp.

    Args:
        timestamp: Core Data timestamp (seconds since 2001-01-01)

    Returns:
        Unix timestamp (seconds since 1970-01-01) or None if input is None
    """
    if timestamp is None:
        return None
    return timestamp + CORE_DATA_EPOCH


def unix_to_core_data(timestamp: float | None) -> float | None:
    """Convert Unix timestamp to Core Data timestamp.

    Args:
        timestamp: Unix timestamp (seconds since 1970-01-01)

    Returns:
        Core Data timestamp (seconds since 2001-01-01) or None if input is None
    """
    if timestamp is None:
        return None
    return timestamp - CORE_DATA_EPOCH


def core_data_now() -> float:
    """Get current time as Core Data timestamp.

    Returns:
        Current time as Core Data timestamp
    """
    return unix_to_core_data(datetime.now(timezone.utc).timestamp())


def core_data_to_datetime(timestamp: float | None) -> datetime | None:
    """Convert Core Data timestamp to datetime object.

    Args:
        timestamp: Core Data timestamp

    Returns:
        datetime object in UTC or None if input is None
    """
    if timestamp is None:
        return None
    unix_ts = core_data_to_unix(timestamp)
    return datetime.fromtimestamp(unix_ts, tz=timezone.utc)


def datetime_to_core_data(dt: datetime | None) -> float | None:
    """Convert datetime object to Core Data timestamp.

    Args:
        dt: datetime object

    Returns:
        Core Data timestamp or None if input is None
    """
    if dt is None:
        return None
    return unix_to_core_data(dt.timestamp())
