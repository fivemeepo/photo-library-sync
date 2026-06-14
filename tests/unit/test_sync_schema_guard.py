"""sync_photos / create_sync_plan must abort on a Photos schema-version mismatch."""

import plistlib
import sqlite3
from unittest.mock import patch

import pytest

from photo_sync import sync as sync_mod
from photo_sync.db.schema_version import SchemaVersionMismatchError

MODULE = sync_mod.__name__


def _lib(asset_hash: bytes):
    """In-memory DB whose only relevant content is its Z_METADATA model hash."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE Z_METADATA (Z_PLIST BLOB)")
    plist = {"PLModelVersion": 19607, "NSStoreModelVersionHashes": {"Asset": asset_hash}}
    conn.execute(
        "INSERT INTO Z_METADATA VALUES (?)",
        (plistlib.dumps(plist, fmt=plistlib.FMT_BINARY),),
    )
    conn.commit()
    return conn


@patch(f"{MODULE}.connect_readwrite")
@patch(f"{MODULE}.connect_readonly")
def test_sync_photos_aborts_on_mismatch(mock_ro, mock_rw):
    mock_ro.return_value = _lib(b"\x01")
    mock_rw.return_value = _lib(b"\x02")
    with pytest.raises(SchemaVersionMismatchError):
        sync_mod.sync_photos("src.photoslibrary", "dst.photoslibrary")


@patch(f"{MODULE}.connect_readonly")
def test_create_sync_plan_aborts_on_mismatch(mock_ro):
    # create_sync_plan opens both connections via connect_readonly.
    mock_ro.side_effect = [_lib(b"\x01"), _lib(b"\x02")]
    with pytest.raises(SchemaVersionMismatchError):
        sync_mod.create_sync_plan("src.photoslibrary", "dst.photoslibrary")
