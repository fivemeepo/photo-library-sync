"""Per-target incremental-sync state (.photo_sync_meta/sync_state.json)."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

STATE_VERSION = 1
STATE_RELPATH = Path(".photo_sync_meta") / "sync_state.json"


def sync_state_path(target_lib: str | Path) -> Path:
    """Path to the incremental-sync state file inside a target bundle."""
    return Path(target_lib) / STATE_RELPATH


def load_sync_state(target_lib: str | Path) -> dict:
    """Load saved state, or return {} on missing/unreadable/version mismatch."""
    path = sync_state_path(target_lib)
    try:
        data = json.loads(path.read_text())
    except (FileNotFoundError, ValueError, OSError):
        return {}
    if not isinstance(data, dict) or data.get("version") != STATE_VERSION:
        return {}
    return data


def save_sync_state(target_lib: str | Path, state: dict) -> None:
    """Atomically write state (temp file + os.replace), stamping the version."""
    path = sync_state_path(target_lib)
    path.parent.mkdir(parents=True, exist_ok=True)
    out = dict(state)
    out["version"] = STATE_VERSION
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out))
    os.replace(tmp, path)
    logger.debug(f"Saved sync state to {path}")
