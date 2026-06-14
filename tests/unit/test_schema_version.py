"""Tests for Photos schema-version detection and compatibility checks."""

import plistlib
import sqlite3

import pytest

from photo_sync.db.connection import DatabaseError
from photo_sync.db.schema_version import (
    SchemaVersionMismatchError,
    assert_schema_compatible,
    read_schema_version,
)

# Per-entity Core Data model hashes. HASHES_A and HASHES_B differ only in the
# "Asset" entity — mirroring the real ZISRECENTLYSAVED/ZRECENCYTYPE divergence.
HASHES_A = {"Asset": b"\x01\x02", "Album": b"\x03"}
HASHES_B = {"Asset": b"\xaa\xbb", "Album": b"\x03"}


def _make_lib(model_version, hashes):
    """Build an in-memory Photos-like DB carrying a Z_METADATA plist."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE Z_METADATA (Z_VERSION INTEGER, Z_UUID VARCHAR, Z_PLIST BLOB)"
    )
    plist = {
        "PLModelVersion": model_version,
        "NSStoreModelVersionHashes": hashes,
    }
    conn.execute(
        "INSERT INTO Z_METADATA VALUES (1, 'x', ?)",
        (plistlib.dumps(plist, fmt=plistlib.FMT_BINARY),),
    )
    conn.commit()
    return conn


def test_read_schema_version_basic():
    sv = read_schema_version(_make_lib(19607, HASHES_A))
    assert sv.model_version == 19607
    assert isinstance(sv.fingerprint, str) and len(sv.fingerprint) == 64


def test_same_hashes_compatible_even_if_model_version_differs():
    """Mirrors the real Sx pair: PLModelVersion 19607 vs 19606, identical schema.

    The raw version number differs, but the schemas are compatible, so the
    sync must NOT be blocked.
    """
    src = _make_lib(19607, HASHES_A)
    dst = _make_lib(19606, HASHES_A)
    assert read_schema_version(src).fingerprint == read_schema_version(dst).fingerprint
    # Compatible -> returns without raising.
    assert assert_schema_compatible(src, dst) is None


def test_diverged_hashes_raise():
    """Different Asset-entity hash -> incompatible -> raise with both versions."""
    src = _make_lib(19607, HASHES_A)
    dst = _make_lib(19500, HASHES_B)
    with pytest.raises(SchemaVersionMismatchError) as exc:
        assert_schema_compatible(src, dst)
    msg = str(exc.value)
    assert "19607" in msg and "19500" in msg
    assert "Photos" in msg  # tells the user to upgrade/migrate via Photos


def test_mismatch_error_is_database_error():
    assert issubclass(SchemaVersionMismatchError, DatabaseError)


def test_missing_metadata_raises_databaseerror():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE Z_METADATA (Z_PLIST BLOB)")
    conn.execute("INSERT INTO Z_METADATA VALUES (NULL)")
    conn.commit()
    with pytest.raises(DatabaseError):
        read_schema_version(conn)
