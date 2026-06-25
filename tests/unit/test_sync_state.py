import json
from pathlib import Path

from photo_sync.operations.sync_state import (
    STATE_VERSION,
    load_sync_state,
    save_sync_state,
    sync_state_path,
)


def test_roundtrip(tmp_path: Path):
    save_sync_state(tmp_path, {"assets": {"asset_zmax": 5}})
    loaded = load_sync_state(tmp_path)
    assert loaded["version"] == STATE_VERSION
    assert loaded["assets"]["asset_zmax"] == 5


def test_missing_returns_empty(tmp_path: Path):
    assert load_sync_state(tmp_path) == {}


def test_corrupt_returns_empty(tmp_path: Path):
    p = sync_state_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not json")
    assert load_sync_state(tmp_path) == {}


def test_version_mismatch_returns_empty(tmp_path: Path):
    p = sync_state_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"version": STATE_VERSION + 1, "assets": {}}))
    assert load_sync_state(tmp_path) == {}


def test_save_is_atomic_no_tmp_left(tmp_path: Path):
    save_sync_state(tmp_path, {"assets": {}})
    leftovers = list(sync_state_path(tmp_path).parent.glob("*.tmp"))
    assert leftovers == []
