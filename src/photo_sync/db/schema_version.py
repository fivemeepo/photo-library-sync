"""Photos library schema-version detection and compatibility checks.

Apple Photos migrates a library's Core Data schema when the library is opened by
a newer Photos app. Two libraries on different schema versions can have
divergent columns (e.g. ``ZASSET.ZISRECENTLYSAVED`` vs ``ZASSET.ZRECENCYTYPE``),
which makes the column-by-column row copy in :mod:`photo_sync.db.mutations`
fail on every asset. We detect that mismatch up front and refuse to sync,
asking the user to migrate the older library first.

The reliable compatibility signal is the Core Data *model* identity
(``NSStoreModelVersionHashes``), NOT Photos' own ``PLModelVersion`` counter:
``PLModelVersion`` can differ between two libraries whose schemas are actually
identical, so keying off it would wrongly block a working sync.
"""

from __future__ import annotations

import hashlib
import logging
import plistlib
import sqlite3
from dataclasses import dataclass

from photo_sync.db.connection import DatabaseError

logger = logging.getLogger(__name__)


class SchemaVersionMismatchError(DatabaseError):
    """Raised when source and target libraries have incompatible schemas."""
    pass


@dataclass(frozen=True)
class SchemaVersion:
    """Identifies a Photos library's Core Data schema version.

    Attributes:
        model_version: Photos' own schema counter (``PLModelVersion``).
            Human-readable, but NOT a reliable compatibility signal on its own —
            it can change without any column-level schema change.
        fingerprint: Stable hex digest of the Core Data model version hashes.
            Two libraries are schema-compatible iff their fingerprints match.
    """
    model_version: int | None
    fingerprint: str


def read_schema_version(conn: sqlite3.Connection) -> SchemaVersion:
    """Read the Core Data schema version from a Photos library connection.

    Args:
        conn: Open connection to a Photos.sqlite database.

    Returns:
        SchemaVersion with a model-version number and a compatibility fingerprint.

    Raises:
        DatabaseError: if Z_METADATA is missing, empty, or unparseable.
    """
    try:
        row = conn.execute("SELECT Z_PLIST FROM Z_METADATA LIMIT 1").fetchone()
    except sqlite3.Error as e:
        raise DatabaseError(f"Cannot read Z_METADATA: {e}") from e

    if not row or row[0] is None:
        raise DatabaseError("Z_METADATA.Z_PLIST is empty; not a Photos library?")

    try:
        plist = plistlib.loads(bytes(row[0]))
    except Exception as e:
        raise DatabaseError(f"Cannot parse Z_METADATA plist: {e}") from e

    model_version = plist.get("PLModelVersion")
    if not isinstance(model_version, int):
        model_version = None

    return SchemaVersion(
        model_version=model_version,
        fingerprint=_model_fingerprint(plist),
    )


def _model_fingerprint(plist: dict) -> str:
    """Compute a stable fingerprint of the Core Data model from its plist.

    Prefers the per-entity ``NSStoreModelVersionHashes`` (most precise). Falls
    back to ``NSStoreModelVersionHashesDigest`` and finally ``PLModelVersion``
    so the function always yields a comparable value.
    """
    hashes = plist.get("NSStoreModelVersionHashes")
    if isinstance(hashes, dict) and hashes:
        h = hashlib.sha256()
        for entity in sorted(hashes):
            value = hashes[entity]
            h.update(entity.encode("utf-8"))
            h.update(value if isinstance(value, bytes) else repr(value).encode("utf-8"))
        return h.hexdigest()

    digest = plist.get("NSStoreModelVersionHashesDigest")
    if isinstance(digest, bytes):
        return hashlib.sha256(digest).hexdigest()

    # Last resort: nothing model-specific available.
    return hashlib.sha256(f"plmodel:{plist.get('PLModelVersion')}".encode()).hexdigest()


def assert_schema_compatible(
    source_conn: sqlite3.Connection,
    target_conn: sqlite3.Connection,
) -> None:
    """Verify source and target libraries share the same Photos schema.

    Args:
        source_conn: Connection to the source library.
        target_conn: Connection to the target library.

    Raises:
        SchemaVersionMismatchError: if the two libraries' schemas differ.
    """
    source = read_schema_version(source_conn)
    target = read_schema_version(target_conn)

    if source.fingerprint != target.fingerprint:
        raise SchemaVersionMismatchError(
            "Source and target libraries are on different Photos schema versions "
            f"(source PLModelVersion={source.model_version}, "
            f"target PLModelVersion={target.model_version}). "
            "Open the older library in the latest Photos app so it migrates the "
            "schema, quit Photos, then retry the sync."
        )

    logger.debug(
        "Schema versions match (fingerprint=%s..., PLModelVersion=%s)",
        source.fingerprint[:12],
        source.model_version,
    )


__all__ = [
    "SchemaVersion",
    "SchemaVersionMismatchError",
    "read_schema_version",
    "assert_schema_compatible",
]
