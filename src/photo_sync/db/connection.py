"""Database connection management for Photos.sqlite."""

from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

# Default retry configuration
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY = 1.0  # seconds


class DatabaseError(Exception):
    """Base exception for database errors."""
    pass


class DatabaseLockedError(DatabaseError):
    """Raised when database is locked after max retries."""
    pass


class DatabaseNotFoundError(DatabaseError):
    """Raised when database file is not found."""
    pass


def get_database_path(library_path: str | Path) -> Path:
    """Get the Photos.sqlite path from a library path.

    Args:
        library_path: Path to .photoslibrary bundle

    Returns:
        Path to Photos.sqlite database
    """
    lib_path = Path(library_path)
    db_path = lib_path / "database" / "Photos.sqlite"
    return db_path


def _register_core_data_stubs(conn: sqlite3.Connection) -> None:
    """Register stub functions for Core Data triggers.

    Photos.sqlite has triggers that call custom SQLite functions registered
    by Apple's Core Data framework. These functions are not available when
    connecting directly via sqlite3, so we register no-op stubs to prevent
    trigger failures.

    Args:
        conn: SQLite connection to register functions on
    """
    # Known Core Data trigger functions used in Photos.sqlite
    # These are discovered by examining triggers in the database:
    # sqlite3 Photos.sqlite "SELECT DISTINCT sql FROM sqlite_master WHERE type='trigger'" | grep -oE 'NSCoreData[A-Za-z]+' | sort -u
    core_data_functions = [
        "NSCoreDataDATriggerInsertUpdatedAffectedObjectValue",
        "NSCoreDataDATriggerUpdatedAffectedObjectValue",
        "NSCoreDataTriggerUpdateAffectedObjectValue",
    ]

    # Register no-op stubs (-1 means variable number of arguments)
    for func_name in core_data_functions:
        conn.create_function(func_name, -1, lambda *args: None)

    logger.debug("Registered Core Data trigger stub functions")


def connect_with_retry(
    db_path: str | Path,
    mode: Literal["ro", "rw"] = "ro",
    max_retries: int = DEFAULT_MAX_RETRIES,
    base_delay: float = DEFAULT_BASE_DELAY,
) -> sqlite3.Connection:
    """Connect to SQLite database with retry logic for locked databases.

    Args:
        db_path: Path to the SQLite database file
        mode: Connection mode - "ro" for read-only, "rw" for read-write
        max_retries: Maximum number of retry attempts
        base_delay: Base delay in seconds (doubles each retry)

    Returns:
        SQLite connection object

    Raises:
        DatabaseNotFoundError: If database file doesn't exist
        DatabaseLockedError: If database is locked after max retries
        DatabaseError: For other database errors
    """
    db_path = Path(db_path)

    if not db_path.exists():
        raise DatabaseNotFoundError(f"Database not found: {db_path}")

    last_error = None
    for attempt in range(max_retries):
        try:
            # Use URI mode for read-only/read-write specification
            uri = f"file:{db_path}?mode={mode}"
            conn = sqlite3.connect(uri, uri=True, timeout=30.0)
            conn.row_factory = sqlite3.Row

            # Register stub functions for Core Data triggers
            _register_core_data_stubs(conn)

            logger.debug(f"Connected to database: {db_path} (mode={mode})")
            return conn
        except sqlite3.OperationalError as e:
            error_msg = str(e).lower()
            if "database is locked" in error_msg or "unable to open" in error_msg:
                last_error = e
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    f"Database locked, retrying in {delay}s (attempt {attempt + 1}/{max_retries})"
                )
                time.sleep(delay)
            else:
                raise DatabaseError(f"Database error: {e}") from e

    raise DatabaseLockedError(
        f"Database locked after {max_retries} retries: {db_path}"
    ) from last_error


def connect_readonly(library_path: str | Path) -> sqlite3.Connection:
    """Connect to a Photos library database in read-only mode.

    Args:
        library_path: Path to .photoslibrary bundle

    Returns:
        SQLite connection object (read-only)
    """
    db_path = get_database_path(library_path)
    return connect_with_retry(db_path, mode="ro")


def connect_readwrite(library_path: str | Path) -> sqlite3.Connection:
    """Connect to a Photos library database in read-write mode.

    Args:
        library_path: Path to .photoslibrary bundle

    Returns:
        SQLite connection object (read-write)
    """
    db_path = get_database_path(library_path)
    return connect_with_retry(db_path, mode="rw")


__all__ = [
    "DatabaseError",
    "DatabaseLockedError",
    "DatabaseNotFoundError",
    "get_database_path",
    "connect_with_retry",
    "connect_readonly",
    "connect_readwrite",
]
