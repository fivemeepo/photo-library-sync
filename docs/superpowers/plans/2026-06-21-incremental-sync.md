# Incremental Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `sync_photos` examine only the rows that changed since the last sync (delta queries), falling back to a full comparison only on the runs where an untrackable removal/move actually happened — never missing a change.

**Architecture:** A per-target state file (`.photo_sync_meta/sync_state.json`) stores cheap source-side invariants + watermarks from the last successful sync. Each dimension (assets, membership, favourites, album-defs) computes a current invariant, fetches only rows past its watermark, and a checksum verifies the delta is complete; if it reconciles we apply just the delta, otherwise we escalate that one dimension to today's existing full comparison. Pure decision functions live in `operations/incremental.py`; the SQL lives in `db/queries.py`; orchestration + state I/O stays in `sync.py` / `operations/sync_state.py`.

**Tech Stack:** Python 3, stdlib `sqlite3`, `pytest`, `ruff`.

## Global Constraints

- Test + lint gate (run from repo root): `cd src && pytest && ruff check .` — must pass before every commit.
- Update `README.md` whenever CLI commands/features change (project rule in `CLAUDE.md`).
- Source→target identity is always by `ZUUID`. Primary keys (`Z_PK`) are per-library and must never be compared across libraries.
- Watermarks/invariants stored in state are **source-side**. Apply changes to the target via existing functions (`insert_photo_with_relations`, `soft_delete_photo`, `sync_favourites`, `sync_album_memberships`).
- The fixed join table is `Z_33ASSETS` (cols `Z_33ALBUMS`, `Z_3ASSETS`); the Core Data PK counter is `Z_PRIMARYKEY.Z_MAX`, read via `pk_manager.get_current_max_pk(conn, "Asset" | "GenericAlbum")`.
- Checksum SQL must stay within 64-bit range (avoid large multipliers that overflow SQLite's integer SUM). Use the four-component membership checksum below, not an `album*BIG+asset` packing.
- State-file writes are atomic (temp file + `os.replace`). A dimension's watermark is saved **only if that dimension completed without raising**.

---

## File Structure

- **Create** `src/photo_sync/operations/sync_state.py` — load/save `.photo_sync_meta/sync_state.json` (atomic), with `STATE_VERSION`.
- **Create** `src/photo_sync/operations/incremental.py` — pure decision functions `plan_asset_sync`, `plan_membership_sync`, `plan_favourite_sync`, `plan_album_defs_sync`, each returning a small result object describing delta-or-full + the fresh invariant to store.
- **Modify** `src/photo_sync/db/queries.py` — add invariant + delta SQL helpers.
- **Modify** `src/photo_sync/db/connection.py` — register a deterministic `_uuid_checksum` SQL function (used by the favourite cross-library verify).
- **Modify** `src/photo_sync/sync.py` — rewire `sync_photos` to the incremental orchestration; add `full: bool = False`; remove Phase 1b backfill.
- **Modify** `src/photo_sync/operations/file_copy.py` — remove the backfill functions/constant.
- **Modify** `src/photo_sync/cli.py` — add `--full` to `sync` and `sync-all`; thread into `sync_photos`.
- **Modify** `README.md` — document `--full` and incremental behavior.
- **Create** tests: `tests/unit/test_sync_state.py`, `test_incremental_assets.py`, `test_incremental_membership.py`, `test_incremental_favourites.py`, `test_incremental_albums.py`, `test_sync_incremental.py`, and a shared in-memory schema helper `tests/unit/_photoslib.py`.
- **Delete** `tests/unit/test_derivative_backfill_marker.py`.

---

## Task 1: Verify the favourite modification-date signal (investigation)

The favourite delta path queries `ZMODIFICATIONDATE > watermark`. Correctness does
**not** depend on favouriting bumping that column (the verify escalates if it
doesn't), but efficiency does. Record the empirical answer so Task 6's expectations
are grounded. This task is authorized by the user ("verify against a real library
during planning").

**Files:** none (produces a finding recorded in the commit message + a note appended to the spec's "Assumptions" section).

- [ ] **Step 1: Snapshot one photo's modification date**

Pick a real library (read-only). Record the current value for a chosen photo:

```bash
PL="$HOME/Pictures/Photos Library.photoslibrary"   # adjust to a real library
sqlite3 "file:$PL/database/Photos.sqlite?mode=ro" \
  "SELECT ZUUID, ZFAVORITE, ZMODIFICATIONDATE FROM ZASSET WHERE ZTRASHEDSTATE=0 ORDER BY Z_PK DESC LIMIT 1;"
```

Note the printed `ZUUID` and `ZMODIFICATIONDATE`.

- [ ] **Step 2: Toggle that photo's favourite in Photos.app**

In Photos.app, favourite (or unfavourite) exactly that photo, then quit Photos so it flushes the DB. (No automation — a manual toggle avoids GUI scripting risk.)

- [ ] **Step 3: Re-read and compare**

```bash
sqlite3 "file:$PL/database/Photos.sqlite?mode=ro" \
  "SELECT ZUUID, ZFAVORITE, ZMODIFICATIONDATE FROM ZASSET WHERE ZUUID='<uuid-from-step-1>';"
```

Expected outcomes:
- `ZMODIFICATIONDATE` increased → favourite toggles bump it → delta path will usually capture favourite changes (good).
- `ZMODIFICATIONDATE` unchanged → favourite toggles do **not** bump it → Task 6's verify will escalate to full on every favourite change (still correct, just not faster for favourites).

- [ ] **Step 4: Record the finding**

Append one line to `docs/superpowers/specs/2026-06-21-incremental-sync-design.md` under "Assumptions / risks":
`- **Favourite signal (measured 2026-06-21):** toggling favourite DID / DID NOT bump ZMODIFICATIONDATE on <macOS/Photos version>.`

```bash
git add docs/superpowers/specs/2026-06-21-incremental-sync-design.md
git commit -m "docs: record measured favourite modification-date behavior"
```

---

## Task 2: State file module (`sync_state.py`)

**Files:**
- Create: `src/photo_sync/operations/sync_state.py`
- Test: `tests/unit/test_sync_state.py`

**Interfaces:**
- Produces:
  - `STATE_VERSION: int` (= 1)
  - `sync_state_path(target_lib: Path) -> Path`
  - `load_sync_state(target_lib: str | Path) -> dict` — returns `{}` on missing/unreadable/version-mismatch.
  - `save_sync_state(target_lib: str | Path, state: dict) -> None` — atomic; stamps `state["version"] = STATE_VERSION`.

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_sync_state.py
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
```

- [ ] **Step 2: Run to verify failure**

Run: `cd src && pytest ../tests/unit/test_sync_state.py -v`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement the module**

```python
# src/photo_sync/operations/sync_state.py
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
```

- [ ] **Step 4: Run to verify pass**

Run: `cd src && pytest ../tests/unit/test_sync_state.py -v && ruff check .`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/photo_sync/operations/sync_state.py tests/unit/test_sync_state.py
git commit -m "feat: per-target incremental sync state file"
```

---

## Task 3: Shared in-memory Photos schema fixture

The delta/invariant tests need a real (tiny) SQLite DB shaped like Photos.sqlite.

**Files:**
- Create: `tests/unit/_photoslib.py`
- Test: covered by its consumers (Tasks 4–8); add one smoke test here.

**Interfaces:**
- Produces:
  - `make_db() -> sqlite3.Connection` — in-memory DB with `ZASSET`, `Z_33ASSETS`, `ZGENERICALBUM`, `Z_PRIMARYKEY` and Core Data PK rows for `Asset`/`GenericAlbum`.
  - `add_asset(conn, uuid, *, favorite=0, trashed=0, trashed_date=0.0, mod_date=0.0) -> int` (returns Z_PK, bumps `Z_PRIMARYKEY`).
  - `add_membership(conn, album_pk, asset_pk) -> None`
  - `add_album(conn, uuid, *, title="A", mod_date=0.0) -> int`

- [ ] **Step 1: Implement the helper + smoke test**

```python
# tests/unit/_photoslib.py
"""Minimal in-memory Photos.sqlite-shaped DB for incremental-sync tests."""

import sqlite3


def make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE ZASSET (
            Z_PK INTEGER PRIMARY KEY,
            Z_ENT INTEGER DEFAULT 1, Z_OPT INTEGER DEFAULT 1,
            ZUUID TEXT, ZFAVORITE INTEGER DEFAULT 0,
            ZTRASHEDSTATE INTEGER DEFAULT 0, ZTRASHEDDATE REAL DEFAULT 0.0,
            ZMODIFICATIONDATE REAL DEFAULT 0.0
        );
        CREATE TABLE ZGENERICALBUM (
            Z_PK INTEGER PRIMARY KEY,
            ZUUID TEXT, ZTITLE TEXT, ZKIND INTEGER DEFAULT 2,
            ZTRASHEDSTATE INTEGER DEFAULT 0, ZMODIFICATIONDATE REAL DEFAULT 0.0
        );
        CREATE TABLE Z_33ASSETS (
            Z_33ALBUMS INTEGER, Z_3ASSETS INTEGER, Z_FOK_3ASSETS INTEGER,
            PRIMARY KEY (Z_33ALBUMS, Z_3ASSETS)
        );
        CREATE TABLE Z_PRIMARYKEY (
            Z_ENT INTEGER PRIMARY KEY, Z_NAME TEXT, Z_SUPER INTEGER, Z_MAX INTEGER
        );
        INSERT INTO Z_PRIMARYKEY (Z_ENT, Z_NAME, Z_SUPER, Z_MAX) VALUES
            (1, 'Asset', 0, 0), (3, 'GenericAlbum', 0, 0);
        """
    )
    return conn


def _next_pk(conn: sqlite3.Connection, name: str) -> int:
    cur = conn.execute("SELECT Z_MAX FROM Z_PRIMARYKEY WHERE Z_NAME = ?", (name,))
    nxt = cur.fetchone()[0] + 1
    conn.execute("UPDATE Z_PRIMARYKEY SET Z_MAX = ? WHERE Z_NAME = ?", (nxt, name))
    return nxt


def add_asset(conn, uuid, *, favorite=0, trashed=0, trashed_date=0.0, mod_date=0.0) -> int:
    pk = _next_pk(conn, "Asset")
    conn.execute(
        "INSERT INTO ZASSET (Z_PK, ZUUID, ZFAVORITE, ZTRASHEDSTATE, ZTRASHEDDATE, ZMODIFICATIONDATE)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (pk, uuid, favorite, trashed, trashed_date, mod_date),
    )
    return pk


def add_album(conn, uuid, *, title="A", mod_date=0.0) -> int:
    pk = _next_pk(conn, "GenericAlbum")
    conn.execute(
        "INSERT INTO ZGENERICALBUM (Z_PK, ZUUID, ZTITLE, ZKIND, ZMODIFICATIONDATE)"
        " VALUES (?, ?, ?, 2, ?)",
        (pk, uuid, title, mod_date),
    )
    return pk


def add_membership(conn, album_pk, asset_pk) -> None:
    conn.execute(
        "INSERT INTO Z_33ASSETS (Z_33ALBUMS, Z_3ASSETS) VALUES (?, ?)",
        (album_pk, asset_pk),
    )


def test_smoke():
    conn = make_db()
    pk = add_asset(conn, "A", favorite=1)
    assert pk == 1
    assert conn.execute("SELECT COUNT(*) FROM ZASSET").fetchone()[0] == 1
```

- [ ] **Step 2: Run + commit**

Run: `cd src && pytest ../tests/unit/_photoslib.py -v && ruff check .`
Expected: PASS.

```bash
git add tests/unit/_photoslib.py
git commit -m "test: in-memory Photos schema helper for incremental tests"
```

---

## Task 4: Asset invariant + delta SQL (`queries.py`)

**Files:**
- Modify: `src/photo_sync/db/queries.py` (append functions; add `from photo_sync.db.pk_manager import get_current_max_pk` at top)
- Test: `tests/unit/test_incremental_assets.py` (queries portion)

**Interfaces:**
- Produces:
  - `asset_invariant(conn) -> dict` keys: `asset_zmax`, `active_count`, `active_pk_sum`, `max_trashed_date`.
  - `fetch_assets_added_since(conn, asset_pk_watermark: int) -> list[tuple[str, int]]` — `(uuid, z_pk)` for active assets with `Z_PK > watermark`.
  - `fetch_assets_trashed_since(conn, trashed_date_watermark: float) -> list[tuple[str, int]]` — `(uuid, z_pk)` for `ZTRASHEDSTATE=1 AND ZTRASHEDDATE > watermark`.

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_incremental_assets.py
from photo_sync.db.queries import (
    asset_invariant,
    fetch_assets_added_since,
    fetch_assets_trashed_since,
)
from tests.unit._photoslib import add_asset, make_db


def test_asset_invariant_basic():
    conn = make_db()
    add_asset(conn, "A")                       # pk 1, active
    add_asset(conn, "B", trashed=1, trashed_date=10.0)  # pk 2, trashed
    inv = asset_invariant(conn)
    assert inv["asset_zmax"] == 2
    assert inv["active_count"] == 1
    assert inv["active_pk_sum"] == 1
    assert inv["max_trashed_date"] == 10.0


def test_fetch_added_since():
    conn = make_db()
    add_asset(conn, "A")     # pk 1
    add_asset(conn, "B")     # pk 2
    assert fetch_assets_added_since(conn, 1) == [("B", 2)]


def test_fetch_trashed_since():
    conn = make_db()
    add_asset(conn, "A", trashed=1, trashed_date=5.0)
    add_asset(conn, "B", trashed=1, trashed_date=20.0)
    assert fetch_assets_trashed_since(conn, 10.0) == [("B", 2)]
```

Note: tests import `tests.unit._photoslib`; run pytest from repo root so `tests` is importable, or rely on the repo's existing rootdir config. Use `cd src && pytest ../tests/...` consistently (matches the project gate).

- [ ] **Step 2: Run to verify failure**

Run: `cd src && pytest ../tests/unit/test_incremental_assets.py -v`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement in `queries.py`**

```python
# add near the top imports of src/photo_sync/db/queries.py
from photo_sync.db.pk_manager import get_current_max_pk

# append at end of src/photo_sync/db/queries.py
def asset_invariant(conn: sqlite3.Connection) -> dict:
    """Cheap source-side summary of the asset table for delta verification."""
    active = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(Z_PK), 0) "
        "FROM ZASSET WHERE ZTRASHEDSTATE = 0"
    ).fetchone()
    max_trashed = conn.execute(
        "SELECT COALESCE(MAX(ZTRASHEDDATE), 0.0) "
        "FROM ZASSET WHERE ZTRASHEDSTATE = 1"
    ).fetchone()
    return {
        "asset_zmax": get_current_max_pk(conn, "Asset"),
        "active_count": active[0],
        "active_pk_sum": active[1],
        "max_trashed_date": max_trashed[0],
    }


def fetch_assets_added_since(
    conn: sqlite3.Connection, asset_pk_watermark: int
) -> list[tuple[str, int]]:
    """(uuid, z_pk) of active assets created since the watermark."""
    cur = conn.execute(
        "SELECT ZUUID, Z_PK FROM ZASSET "
        "WHERE Z_PK > ? AND ZTRASHEDSTATE = 0",
        (asset_pk_watermark,),
    )
    return [(r[0], r[1]) for r in cur.fetchall()]


def fetch_assets_trashed_since(
    conn: sqlite3.Connection, trashed_date_watermark: float
) -> list[tuple[str, int]]:
    """(uuid, z_pk) of assets trashed since the watermark."""
    cur = conn.execute(
        "SELECT ZUUID, Z_PK FROM ZASSET "
        "WHERE ZTRASHEDSTATE = 1 AND ZTRASHEDDATE > ?",
        (trashed_date_watermark,),
    )
    return [(r[0], r[1]) for r in cur.fetchall()]
```

- [ ] **Step 4: Run to verify pass**

Run: `cd src && pytest ../tests/unit/test_incremental_assets.py -v && ruff check .`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/photo_sync/db/queries.py tests/unit/test_incremental_assets.py
git commit -m "feat: asset invariant and delta queries"
```

---

## Task 5: Asset incremental decision (`incremental.py`)

**Files:**
- Create: `src/photo_sync/operations/incremental.py`
- Test: `tests/unit/test_incremental_assets.py` (append decision tests)

**Interfaces:**
- Consumes: `asset_invariant`, `fetch_assets_added_since`, `fetch_assets_trashed_since` (Task 4).
- Produces:
  - `@dataclass AssetPlan` with fields `full: bool`, `added_uuids: list[str]`, `trashed_uuids: list[str]`, `invariant: dict`.
  - `plan_asset_sync(source_conn, prev: dict | None) -> AssetPlan`.

- [ ] **Step 1: Write failing tests (append)**

```python
# append to tests/unit/test_incremental_assets.py
from photo_sync.db.queries import asset_invariant
from photo_sync.operations.incremental import plan_asset_sync
from tests.unit._photoslib import add_asset, make_db


def test_plan_full_when_no_prev():
    conn = make_db()
    add_asset(conn, "A")
    plan = plan_asset_sync(conn, None)
    assert plan.full is True
    assert plan.invariant["asset_zmax"] == 1


def test_plan_delta_additions_only():
    conn = make_db()
    add_asset(conn, "A")                 # pk1
    prev = asset_invariant(conn)
    add_asset(conn, "B")                 # pk2 (new)
    plan = plan_asset_sync(conn, prev)
    assert plan.full is False
    assert plan.added_uuids == ["B"]
    assert plan.trashed_uuids == []


def test_plan_delta_trash_based_deletion():
    conn = make_db()
    pk = add_asset(conn, "A")            # pk1 active
    prev = asset_invariant(conn)
    conn.execute(
        "UPDATE ZASSET SET ZTRASHEDSTATE=1, ZTRASHEDDATE=99.0 WHERE Z_PK=?", (pk,)
    )
    plan = plan_asset_sync(conn, prev)
    assert plan.full is False
    assert plan.trashed_uuids == ["A"]


def test_plan_escalates_on_restore():
    conn = make_db()
    pk = add_asset(conn, "A", trashed=1, trashed_date=1.0)   # starts trashed
    prev = asset_invariant(conn)
    conn.execute("UPDATE ZASSET SET ZTRASHEDSTATE=0 WHERE Z_PK=?", (pk,))  # restored, no new pk
    plan = plan_asset_sync(conn, prev)
    assert plan.full is True


def test_plan_escalates_on_hard_delete():
    conn = make_db()
    add_asset(conn, "A")                 # pk1
    add_asset(conn, "B")                 # pk2
    prev = asset_invariant(conn)
    conn.execute("DELETE FROM ZASSET WHERE ZUUID='A'")       # hard delete, no trash trace
    plan = plan_asset_sync(conn, prev)
    assert plan.full is True
```

- [ ] **Step 2: Run to verify failure**

Run: `cd src && pytest ../tests/unit/test_incremental_assets.py -v`
Expected: FAIL (no `incremental` module).

- [ ] **Step 3: Implement `incremental.py` (asset part)**

```python
# src/photo_sync/operations/incremental.py
"""Pure delta-vs-full decision functions for incremental sync.

Each plan_* function reads ONLY cheap aggregates + rows past a watermark, and
decides whether the delta fully explains the change (apply just the delta) or
whether to escalate to the existing full comparison this run.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from photo_sync.db.queries import (
    asset_invariant,
    fetch_assets_added_since,
    fetch_assets_trashed_since,
)


@dataclass
class AssetPlan:
    full: bool
    invariant: dict
    added_uuids: list[str] = field(default_factory=list)
    trashed_uuids: list[str] = field(default_factory=list)


def plan_asset_sync(source_conn: sqlite3.Connection, prev: dict | None) -> AssetPlan:
    cur = asset_invariant(source_conn)
    if not prev:
        return AssetPlan(full=True, invariant=cur)

    added = fetch_assets_added_since(source_conn, prev["asset_zmax"])
    trashed = fetch_assets_trashed_since(source_conn, prev["max_trashed_date"])
    # Only assets that were active at last sync are present in the target.
    prev_active_trashed = [(u, pk) for (u, pk) in trashed if pk <= prev["asset_zmax"]]

    predicted_count = prev["active_count"] + len(added) - len(prev_active_trashed)
    predicted_pk_sum = (
        prev["active_pk_sum"]
        + sum(pk for _, pk in added)
        - sum(pk for _, pk in prev_active_trashed)
    )

    if predicted_count == cur["active_count"] and predicted_pk_sum == cur["active_pk_sum"]:
        return AssetPlan(
            full=False,
            invariant=cur,
            added_uuids=[u for u, _ in added],
            trashed_uuids=[u for u, _ in prev_active_trashed],
        )
    return AssetPlan(full=True, invariant=cur)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd src && pytest ../tests/unit/test_incremental_assets.py -v && ruff check .`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/photo_sync/operations/incremental.py tests/unit/test_incremental_assets.py
git commit -m "feat: asset delta-vs-full decision with checksum verification"
```

---

## Task 6: Membership invariant, delta, and decision

**Files:**
- Modify: `src/photo_sync/db/queries.py`
- Modify: `src/photo_sync/operations/incremental.py`
- Test: `tests/unit/test_incremental_membership.py`

**Interfaces:**
- Produces (queries.py):
  - `membership_invariant(conn) -> dict` keys: `count`, `max_rowid`, `album_sum`, `asset_sum`, `prod_sum`.
  - `fetch_memberships_added_since(conn, rowid_watermark: int) -> list[tuple[int, int]]` — `(album_pk, asset_pk)` for `_rowid_ > watermark`.
- Produces (incremental.py):
  - `@dataclass MembershipPlan` fields `full: bool`, `invariant: dict`, `added: list[tuple[int, int]]`.
  - `plan_membership_sync(source_conn, prev: dict | None) -> MembershipPlan`.

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_incremental_membership.py
from photo_sync.db.queries import membership_invariant
from photo_sync.operations.incremental import plan_membership_sync
from tests.unit._photoslib import add_album, add_asset, add_membership, make_db


def _seed(conn):
    a1 = add_album(conn, "alb1"); a2 = add_album(conn, "alb2")
    p1 = add_asset(conn, "p1"); p2 = add_asset(conn, "p2")
    return a1, a2, p1, p2


def test_delta_additions_only():
    conn = make_db(); a1, a2, p1, p2 = _seed(conn)
    add_membership(conn, a1, p1)
    prev = membership_invariant(conn)
    add_membership(conn, a1, p2)                 # new row
    plan = plan_membership_sync(conn, prev)
    assert plan.full is False
    assert plan.added == [(a1, p2)]


def test_escalates_on_removal():
    conn = make_db(); a1, a2, p1, p2 = _seed(conn)
    add_membership(conn, a1, p1); add_membership(conn, a1, p2)
    prev = membership_invariant(conn)
    conn.execute("DELETE FROM Z_33ASSETS WHERE Z_3ASSETS=?", (p2,))   # removal, no trace
    plan = plan_membership_sync(conn, prev)
    assert plan.full is True


def test_escalates_on_move_same_count():
    conn = make_db(); a1, a2, p1, p2 = _seed(conn)
    add_membership(conn, a1, p1)
    prev = membership_invariant(conn)
    conn.execute("DELETE FROM Z_33ASSETS WHERE Z_33ALBUMS=? AND Z_3ASSETS=?", (a1, p1))
    add_membership(conn, a2, p1)                 # moved p1 from a1 to a2; count unchanged
    plan = plan_membership_sync(conn, prev)
    assert plan.full is True
```

- [ ] **Step 2: Run to verify failure**

Run: `cd src && pytest ../tests/unit/test_incremental_membership.py -v`
Expected: FAIL (ImportError).

- [ ] **Step 3: Implement queries**

```python
# append to src/photo_sync/db/queries.py
def membership_invariant(conn: sqlite3.Connection) -> dict:
    """Cheap summary of Z_33ASSETS for membership delta verification.

    Components stay within 64-bit range: album PKs ~1e4, asset PKs ~1e6, so
    SUM(album*asset) over a personal library stays well under 2**63.
    """
    row = conn.execute(
        "SELECT COUNT(*), COALESCE(MAX(_rowid_), 0), "
        "COALESCE(SUM(Z_33ALBUMS), 0), COALESCE(SUM(Z_3ASSETS), 0), "
        "COALESCE(SUM(Z_33ALBUMS * Z_3ASSETS), 0) "
        "FROM Z_33ASSETS"
    ).fetchone()
    return {
        "count": row[0],
        "max_rowid": row[1],
        "album_sum": row[2],
        "asset_sum": row[3],
        "prod_sum": row[4],
    }


def fetch_memberships_added_since(
    conn: sqlite3.Connection, rowid_watermark: int
) -> list[tuple[int, int]]:
    """(album_pk, asset_pk) for membership rows inserted since the watermark."""
    cur = conn.execute(
        "SELECT Z_33ALBUMS, Z_3ASSETS FROM Z_33ASSETS WHERE _rowid_ > ?",
        (rowid_watermark,),
    )
    return [(r[0], r[1]) for r in cur.fetchall()]
```

- [ ] **Step 4: Implement decision**

```python
# append to src/photo_sync/operations/incremental.py
from photo_sync.db.queries import (  # add to existing import block
    fetch_memberships_added_since,
    membership_invariant,
)


@dataclass
class MembershipPlan:
    full: bool
    invariant: dict
    added: list[tuple[int, int]] = field(default_factory=list)


def plan_membership_sync(source_conn: sqlite3.Connection, prev: dict | None) -> MembershipPlan:
    cur = membership_invariant(source_conn)
    if not prev:
        return MembershipPlan(full=True, invariant=cur)

    added = fetch_memberships_added_since(source_conn, prev["max_rowid"])
    predicted = {
        "count": prev["count"] + len(added),
        "album_sum": prev["album_sum"] + sum(a for a, _ in added),
        "asset_sum": prev["asset_sum"] + sum(p for _, p in added),
        "prod_sum": prev["prod_sum"] + sum(a * p for a, p in added),
    }
    if all(predicted[k] == cur[k] for k in predicted):
        return MembershipPlan(full=False, invariant=cur, added=added)
    return MembershipPlan(full=True, invariant=cur)
```

- [ ] **Step 5: Run + commit**

Run: `cd src && pytest ../tests/unit/test_incremental_membership.py -v && ruff check .`
Expected: PASS.

```bash
git add src/photo_sync/db/queries.py src/photo_sync/operations/incremental.py tests/unit/test_incremental_membership.py
git commit -m "feat: album-membership delta-vs-full decision"
```

---

## Task 7: Favourite delta + verify (UUID-based, cross-library)

Favourites have no monotonic per-row key, and `Z_PK` differs across libraries, so
the verify compares **source vs target favourite sets by UUID** after applying the
candidate updates. A deterministic SQL `_uuid_checksum` keeps it cheap.

**Files:**
- Modify: `src/photo_sync/db/connection.py` (register `_uuid_checksum`)
- Modify: `src/photo_sync/db/queries.py`
- Modify: `src/photo_sync/operations/incremental.py`
- Test: `tests/unit/test_incremental_favourites.py`

**Interfaces:**
- Produces (connection.py): registers SQL function `_uuid_checksum(text) -> int` on every connection (deterministic CRC32).
- Produces (queries.py):
  - `favourite_state(conn) -> dict` keys: `max_mod_date` (global active), used as the candidate watermark.
  - `favourite_set_summary(conn) -> tuple[int, int]` — `(count, uuid_checksum)` over `ZFAVORITE=1 AND ZTRASHEDSTATE=0`.
  - `fetch_favourite_candidates_since(conn, mod_date_watermark) -> list[tuple[str, int]]` — `(uuid, favorite)` for active assets with `ZMODIFICATIONDATE > watermark`.
- Produces (incremental.py):
  - `@dataclass FavouritePlan` fields `full: bool`, `state: dict`, `candidate_uuids: list[str]`.
  - `plan_favourite_sync(source_conn, target_conn, prev: dict | None) -> FavouritePlan`.

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_incremental_favourites.py
import zlib

from photo_sync.db.queries import (
    favourite_set_summary,
    favourite_state,
    fetch_favourite_candidates_since,
)
from photo_sync.operations.incremental import plan_favourite_sync
from tests.unit._photoslib import add_asset, make_db


def _register(conn):
    conn.create_function(
        "_uuid_checksum", 1, lambda s: zlib.crc32(s.encode()) if s else 0
    )
    return conn


def test_candidates_since():
    conn = _register(make_db())
    add_asset(conn, "A", mod_date=5.0, favorite=1)
    add_asset(conn, "B", mod_date=20.0, favorite=0)
    assert fetch_favourite_candidates_since(conn, 10.0) == [("B", 0)]


def test_delta_when_candidates_explain_change():
    src = _register(make_db()); tgt = _register(make_db())
    # Both libraries start identical: A favourite, B not.
    add_asset(src, "A", favorite=1, mod_date=1.0); add_asset(src, "B", favorite=0, mod_date=1.0)
    add_asset(tgt, "A", favorite=1, mod_date=1.0); add_asset(tgt, "B", favorite=0, mod_date=1.0)
    prev = favourite_state(src)
    # Source favourites B (bumps mod date) -> candidate captures it.
    src.execute("UPDATE ZASSET SET ZFAVORITE=1, ZMODIFICATIONDATE=9.0 WHERE ZUUID='B'")
    # Simulate the caller having applied the favourite update to target:
    tgt.execute("UPDATE ZASSET SET ZFAVORITE=1 WHERE ZUUID='B'")
    plan = plan_favourite_sync(src, tgt, prev)
    assert plan.full is False
    assert "B" in plan.candidate_uuids


def test_escalates_when_change_without_moddate():
    src = _register(make_db()); tgt = _register(make_db())
    add_asset(src, "A", favorite=0, mod_date=1.0)
    add_asset(tgt, "A", favorite=0, mod_date=1.0)
    prev = favourite_state(src)
    # Source favourites A but mod date does NOT advance -> not a candidate.
    src.execute("UPDATE ZASSET SET ZFAVORITE=1 WHERE ZUUID='A'")
    plan = plan_favourite_sync(src, tgt, prev)
    assert plan.full is True
```

- [ ] **Step 2: Run to verify failure**

Run: `cd src && pytest ../tests/unit/test_incremental_favourites.py -v`
Expected: FAIL (ImportError).

- [ ] **Step 3: Register `_uuid_checksum` in connection.py**

In `_register_core_data_stubs`, after the loop registering Core Data stubs, add:

```python
    # Deterministic checksum used by incremental favourite verification.
    import zlib

    conn.create_function(
        "_uuid_checksum", 1, lambda s: zlib.crc32(s.encode()) if s else 0
    )
```

- [ ] **Step 4: Implement queries**

```python
# append to src/photo_sync/db/queries.py
def favourite_state(conn: sqlite3.Connection) -> dict:
    """Watermark for the favourite candidate query: global max mod-date (active)."""
    row = conn.execute(
        "SELECT COALESCE(MAX(ZMODIFICATIONDATE), 0.0) "
        "FROM ZASSET WHERE ZTRASHEDSTATE = 0"
    ).fetchone()
    return {"max_mod_date": row[0]}


def favourite_set_summary(conn: sqlite3.Connection) -> tuple[int, int]:
    """(count, uuid_checksum) over active favourites — UUID-based, cross-library."""
    row = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(_uuid_checksum(ZUUID)), 0) "
        "FROM ZASSET WHERE ZFAVORITE = 1 AND ZTRASHEDSTATE = 0"
    ).fetchone()
    return (row[0], row[1])


def fetch_favourite_candidates_since(
    conn: sqlite3.Connection, mod_date_watermark: float
) -> list[tuple[str, int]]:
    """(uuid, favorite) for active assets modified since the watermark."""
    cur = conn.execute(
        "SELECT ZUUID, ZFAVORITE FROM ZASSET "
        "WHERE ZTRASHEDSTATE = 0 AND ZMODIFICATIONDATE > ?",
        (mod_date_watermark,),
    )
    return [(r[0], r[1]) for r in cur.fetchall()]
```

- [ ] **Step 5: Implement decision**

The decision is called **after** the caller has applied candidate favourite
updates to the target (so the verify reflects the post-apply state). It compares
source vs target favourite summaries; equal → delta was complete, mismatch →
escalate.

```python
# append to src/photo_sync/operations/incremental.py
from photo_sync.db.queries import (  # add to existing import block
    favourite_set_summary,
    favourite_state,
    fetch_favourite_candidates_since,
)


@dataclass
class FavouritePlan:
    full: bool
    state: dict
    candidate_uuids: list[str] = field(default_factory=list)


def plan_favourite_sync(
    source_conn: sqlite3.Connection,
    target_conn: sqlite3.Connection,
    prev: dict | None,
) -> FavouritePlan:
    state = favourite_state(source_conn)
    if not prev:
        return FavouritePlan(full=True, state=state)

    candidates = fetch_favourite_candidates_since(source_conn, prev["max_mod_date"])
    # The caller applies candidate favourite changes to the target before this
    # verify. If the candidates captured every favourite change, source and
    # target favourite sets now match (by UUID).
    if favourite_set_summary(source_conn) == favourite_set_summary(target_conn):
        return FavouritePlan(
            full=False, state=state, candidate_uuids=[u for u, _ in candidates]
        )
    return FavouritePlan(full=True, state=state)
```

> Implementation note for Task 9 wiring: in delta mode the orchestrator first
> applies favourite differences for `candidate_uuids` (compare each candidate's
> source `ZFAVORITE` to target via the existing `sync_favourites` path), *then*
> calls `plan_favourite_sync` to verify. To keep the decision function pure and
> testable, the tests above pre-apply the target update; the orchestrator does
> the same ordering.

- [ ] **Step 6: Run + commit**

Run: `cd src && pytest ../tests/unit/test_incremental_favourites.py -v && ruff check .`
Expected: PASS.

```bash
git add src/photo_sync/db/connection.py src/photo_sync/db/queries.py \
        src/photo_sync/operations/incremental.py tests/unit/test_incremental_favourites.py
git commit -m "feat: favourite delta + UUID-based cross-library verify"
```

---

## Task 8: Album-definitions gate (checksum-gated)

Lower volume — skip-or-full only (no per-row delta).

**Files:**
- Modify: `src/photo_sync/db/queries.py`
- Modify: `src/photo_sync/operations/incremental.py`
- Test: `tests/unit/test_incremental_albums.py`

**Interfaces:**
- Produces (queries.py): `album_defs_invariant(conn) -> dict` keys `album_zmax`, `active_count`, `mod_max`.
- Produces (incremental.py): `plan_album_defs_sync(source_conn, prev: dict | None) -> tuple[bool, dict]` — `(needs_full, invariant)`. `needs_full` is True when prev is empty or any component changed.

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_incremental_albums.py
from photo_sync.db.queries import album_defs_invariant
from photo_sync.operations.incremental import plan_album_defs_sync
from tests.unit._photoslib import add_album, make_db


def test_skip_when_unchanged():
    conn = make_db(); add_album(conn, "a1", mod_date=1.0)
    prev = album_defs_invariant(conn)
    needs_full, inv = plan_album_defs_sync(conn, prev)
    assert needs_full is False
    assert inv == prev


def test_full_on_new_album():
    conn = make_db(); add_album(conn, "a1", mod_date=1.0)
    prev = album_defs_invariant(conn)
    add_album(conn, "a2", mod_date=1.0)
    needs_full, _ = plan_album_defs_sync(conn, prev)
    assert needs_full is True


def test_full_on_rename():
    conn = make_db(); add_album(conn, "a1", mod_date=1.0)
    prev = album_defs_invariant(conn)
    conn.execute("UPDATE ZGENERICALBUM SET ZTITLE='new', ZMODIFICATIONDATE=9.0 WHERE ZUUID='a1'")
    needs_full, _ = plan_album_defs_sync(conn, prev)
    assert needs_full is True
```

- [ ] **Step 2: Run to verify failure**

Run: `cd src && pytest ../tests/unit/test_incremental_albums.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement**

```python
# append to src/photo_sync/db/queries.py
def album_defs_invariant(conn: sqlite3.Connection) -> dict:
    """Cheap summary of album definitions (ZGENERICALBUM)."""
    row = conn.execute(
        "SELECT COUNT(*), COALESCE(MAX(ZMODIFICATIONDATE), 0.0) "
        "FROM ZGENERICALBUM WHERE ZTRASHEDSTATE = 0"
    ).fetchone()
    return {
        "album_zmax": get_current_max_pk(conn, "GenericAlbum"),
        "active_count": row[0],
        "mod_max": row[1],
    }
```

```python
# append to src/photo_sync/operations/incremental.py
from photo_sync.db.queries import album_defs_invariant  # add to import block


def plan_album_defs_sync(
    source_conn: sqlite3.Connection, prev: dict | None
) -> tuple[bool, dict]:
    cur = album_defs_invariant(source_conn)
    if not prev:
        return True, cur
    return (cur != prev), cur
```

- [ ] **Step 4: Run + commit**

Run: `cd src && pytest ../tests/unit/test_incremental_albums.py -v && ruff check .`
Expected: PASS.

```bash
git add src/photo_sync/db/queries.py src/photo_sync/operations/incremental.py tests/unit/test_incremental_albums.py
git commit -m "feat: album-definitions skip-or-full gate"
```

---

## Task 9: Remove the derivative backfill

**Files:**
- Modify: `src/photo_sync/sync.py` (delete the Phase 1b block, lines ~152–183; drop the four backfill imports)
- Modify: `src/photo_sync/operations/file_copy.py` (delete `backfill_derivatives`, `is_derivatives_backfilled`, `mark_derivatives_backfilled`, `derivatives_backfill_marker_path`, `BACKFILL_MARKER_RELPATH`; keep `copy_asset_derivatives`, `get_asset_derivative_size`, `copy_photo_file`, `get_photo_file_size`, `check_disk_space`, `DiskFullError`, `verify_file_copy`)
- Delete: `tests/unit/test_derivative_backfill_marker.py`

- [ ] **Step 1: Delete the backfill test file**

```bash
git rm tests/unit/test_derivative_backfill_marker.py
```

- [ ] **Step 2: Remove backfill code from file_copy.py**

Delete the five symbols listed above. Remove any now-unused imports (e.g. `json` if only the marker used it — verify with `ruff check .`). Update `__all__` to drop the removed names.

- [ ] **Step 3: Remove Phase 1b and its imports from sync.py**

In `src/photo_sync/sync.py`, change the `from photo_sync.operations.file_copy import (...)` block to drop `backfill_derivatives`, `is_derivatives_backfilled`, `mark_derivatives_backfilled` (keep `check_disk_space`, `copy_asset_derivatives`, `copy_photo_file`, `get_asset_derivative_size`, `get_photo_file_size`). Delete the entire `# Phase 1b ...` block (the `if is_derivatives_backfilled(...) ... else ... mark_derivatives_backfilled(...)`).

> This task leaves `sync_photos` temporarily without backfill but otherwise
> intact (Phase 1 still copies new-photo derivatives inline). Task 10 rewires the
> phases; keeping this as its own commit isolates the removal.

- [ ] **Step 4: Run the full suite**

Run: `cd src && pytest && ruff check .`
Expected: PASS (no references to the removed symbols remain).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor: remove one-time derivative backfill"
```

---

## Task 10: Wire incremental orchestration into `sync_photos`

**Files:**
- Modify: `src/photo_sync/sync.py`
- Test: `tests/unit/test_sync_incremental.py`

**Interfaces:**
- Consumes: all `plan_*` functions (Tasks 5–8), `load_sync_state`/`save_sync_state` (Task 2), existing `identify_new_photos`, `identify_deleted_photos`, `insert_photo_with_relations`, `soft_delete_photo`, `identify_favourite_changes`, `sync_favourites`, `diff_album_memberships`, `sync_album_memberships`, `identify_new_albums`, `insert_album_with_hierarchy`, `get_asset_by_uuid`, `get_assets_by_uuids`.
- Produces: `sync_photos(..., full: bool = False)` — when `full=True`, every dimension takes the full path and state is refreshed; otherwise each dimension is delta-or-escalate. After a successful run, `save_sync_state` persists the fresh invariants for dimensions that did not raise.

- [ ] **Step 1: Write integration tests (behavioral, using temp libraries)**

These exercise the orchestration via the real DB helpers. Build two temp
`.photoslibrary`-shaped dirs by copying a fixture, OR test the orchestration with
the in-memory helper by injecting connections. Use the existing connection
seam: factor the per-dimension orchestration into small helpers that accept
connections so they're unit-testable. Concretely, add and test:

```python
# tests/unit/test_sync_incremental.py
from photo_sync.operations.incremental import plan_asset_sync
from photo_sync.db.queries import asset_invariant, get_all_asset_uuids
from tests.unit._photoslib import add_asset, make_db


def test_second_run_is_noop_for_assets():
    """After capturing state, a source with no new rows yields an empty delta."""
    conn = make_db()
    add_asset(conn, "A")
    prev = asset_invariant(conn)            # represents state saved last run
    plan = plan_asset_sync(conn, prev)
    assert plan.full is False
    assert plan.added_uuids == []
    assert plan.trashed_uuids == []


def test_delta_added_matches_full_diff():
    """Delta additions equal what a full source−target diff would return."""
    conn = make_db()
    add_asset(conn, "A")
    prev = asset_invariant(conn)
    add_asset(conn, "B"); add_asset(conn, "C")
    plan = plan_asset_sync(conn, prev)
    assert set(plan.added_uuids) == {"B", "C"}
```

> Full end-to-end coverage (file copying + DB inserts across two real bundles) is
> exercised by the existing sync tests; this task's new tests lock the delta
> decision wiring. Keep the orchestration thin so existing apply-functions remain
> the tested workhorses.

- [ ] **Step 2: Run to verify failure / baseline**

Run: `cd src && pytest ../tests/unit/test_sync_incremental.py -v`
Expected: PASS for the pure-decision tests above (they use Task 5 code). If you add helpers that don't yet exist, they fail first — implement in Step 3.

- [ ] **Step 3: Rewire `sync_photos`**

Add `full: bool = False` to the signature and docstring. Replace the phase bodies
with the incremental flow. Keep transactions and progress callbacks. Skeleton
(fill into the existing `try:` body, preserving disk-space checks for additions):

```python
from photo_sync.operations.sync_state import load_sync_state, save_sync_state
from photo_sync.operations.incremental import (
    plan_asset_sync, plan_membership_sync, plan_favourite_sync, plan_album_defs_sync,
)
from photo_sync.db.queries import asset_invariant, membership_invariant, get_assets_by_uuids

state = {} if full else load_sync_state(target_lib)
new_state = dict(state)

# ----- Assets (new + deleted + derivatives) -----
asset_ok = True
try:
    plan = plan_asset_sync(source_conn, None if full else state.get("assets"))
    if plan.full:
        # existing full path
        source_uuids, target_uuids = fetch_asset_uuid_sets(source_conn, target_conn)
        new_assets = identify_new_photos(source_conn, target_conn,
                                         source_uuids=source_uuids, target_uuids=target_uuids)
        deleted_uuids = ([] if skip_delete else
                         identify_deleted_photos(source_conn, target_conn,
                                                 source_uuids=source_uuids, target_uuids=target_uuids))
    else:
        new_assets = get_assets_by_uuids(source_conn, plan.added_uuids) if plan.added_uuids else []
        deleted_uuids = [] if skip_delete else plan.trashed_uuids
    _apply_new_photos(source_lib, target_lib, source_conn, target_conn, new_assets, result, report_progress)
    if not skip_delete:
        _apply_deleted_photos(target_conn, deleted_uuids, result, report_progress)
    new_state["assets"] = plan.invariant
except Exception as e:   # noqa: BLE001 - record, don't abort other dimensions
    asset_ok = False
    result.warnings.append(f"Asset sync failed: {e}")
    logger.warning(f"Asset sync failed: {e}")
```

Add the analogous blocks for favourites, album-defs, and membership, each:
- compute its plan,
- delta mode → apply only the delta via the existing apply functions,
- full mode → run today's existing full comparison + apply,
- on success set `new_state[<dim>] = plan.invariant/state`, on exception set its `_ok = False` and append a warning.

For favourites, follow the ordering note from Task 7: in delta mode, apply the
candidate favourite differences first (reuse `identify_favourite_changes` filtered
to candidates, or compare candidate source values to target then `sync_favourites`),
then call `plan_favourite_sync` to verify; if it returns `full`, run the full
`identify_favourite_changes` + `sync_favourites`.

Extract the existing Phase 1 new-photo loop into `_apply_new_photos(...)` and the
Phase 2 deletion loop into `_apply_deleted_photos(...)` (pure moves of current
code, preserving the disk-space check, per-photo transaction, derivative copy, and
progress reporting). This keeps `sync_photos` readable and the apply logic
unchanged/tested.

At the end of the `try` (before `finally`), persist state for dimensions that
succeeded:

```python
# Only save dimensions that completed cleanly; a failed dimension keeps its
# previous watermark so it re-runs next time.
to_save = dict(state)
if asset_ok and "assets" in new_state: to_save["assets"] = new_state["assets"]
if fav_ok and "favourites" in new_state: to_save["favourites"] = new_state["favourites"]
if album_ok and "albums" in new_state: to_save["albums"] = new_state["albums"]
if membership_ok and "membership" in new_state: to_save["membership"] = new_state["membership"]
save_sync_state(target_lib, to_save)
```

Leave `create_sync_plan` (dry-run) untouched — it always does the full comparison.

- [ ] **Step 4: Run the full suite**

Run: `cd src && pytest && ruff check .`
Expected: PASS (existing sync tests still green; new decision tests green).

- [ ] **Step 5: Commit**

```bash
git add src/photo_sync/sync.py tests/unit/test_sync_incremental.py
git commit -m "feat: incremental orchestration in sync_photos with full fallback"
```

---

## Task 11: CLI `--full` flag

**Files:**
- Modify: `src/photo_sync/cli.py`
- Test: `tests/unit/test_cli_full_flag.py`

**Interfaces:**
- Consumes: `sync_photos(..., full=...)`.
- Produces: `sync` and `sync-all` accept `--full` (alias `--reconcile`); `run_sync`/`run_sync_all` pass `full=parsed.full` to `sync_photos`. Dry-run ignores it.

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_cli_full_flag.py
from unittest.mock import patch

from photo_sync.cli import create_parser, run_sync
from photo_sync.models.sync_result import SyncResult


def test_parser_accepts_full():
    parsed = create_parser().parse_args(
        ["sync", "/src.photoslibrary", "/dst.photoslibrary", "--full"]
    )
    assert parsed.full is True


def test_run_sync_passes_full():
    parsed = create_parser().parse_args(
        ["sync", "/src.photoslibrary", "/dst.photoslibrary", "--full", "-q"]
    )
    with patch("photo_sync.cli.validate_library_path", return_value=(True, 0, "")), \
         patch("photo_sync.cli.sync_photos", return_value=SyncResult()) as mock_sync:
        run_sync(parsed)
    assert mock_sync.call_args.kwargs["full"] is True
```

- [ ] **Step 2: Run to verify failure**

Run: `cd src && pytest ../tests/unit/test_cli_full_flag.py -v`
Expected: FAIL (`full` not an attribute / not passed).

- [ ] **Step 3: Implement**

Add to the `sync` subparser (after `--verify`) and the `sync-all` subparser:

```python
    sync_parser.add_argument(
        "--full", "--reconcile",
        dest="full",
        action="store_true",
        help="Ignore incremental state; do a full comparison of all dimensions",
    )
```

(Repeat for `sync_all_parser`.) In `run_sync`, pass `full=parsed.full` to the
`sync_photos(...)` call. In `run_sync_all`, add `full=parsed.full` to its
`sync_photos(...)` call.

- [ ] **Step 4: Run + commit**

Run: `cd src && pytest && ruff check .`
Expected: PASS.

```bash
git add src/photo_sync/cli.py tests/unit/test_cli_full_flag.py
git commit -m "feat: --full/--reconcile flag to force a full sync"
```

---

## Task 12: README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Document incremental behavior + `--full`**

Find the `sync` command section and its options table/list. Add `--full` (alias
`--reconcile`) with: "Ignore incremental state and re-compare the whole library."
Add a short "Incremental sync" paragraph: the tool records per-target state in
`.photo_sync_meta/sync_state.json` and normally syncs only what changed since the
last run; it automatically falls back to a full comparison for any dimension whose
cheap checksum shows an untrackable change (e.g. an album membership removal or a
deletion older than the Recently-Deleted window). Use `--full` to force a complete
reconcile. Note the dry-run (`-n`) always does a full comparison.

- [ ] **Step 2: Verify + commit**

Run: `cd src && pytest && ruff check .` (sanity; README has no tests)

```bash
git add README.md
git commit -m "docs: document incremental sync and --full flag"
```

---

## Self-Review

**1. Spec coverage:**
- Delta additions (assets) → Tasks 4–5. Trash-based deletions → Tasks 4–5. Checksum verify/escalation → Tasks 5,6,7. Membership delta + escalation → Task 6. Favourites delta + UUID verify → Task 7. Album-defs gate → Task 8. State file (atomic, version, save discipline) → Tasks 2,10. `--full` + dry-run-always-full → Tasks 10–11. Derivative-backfill removal → Task 9. README → Task 12. Favourite-signal empirical check → Task 1. All spec sections map to a task.

**2. Placeholder scan:** No "TBD/TODO". Task 10's orchestration shows the asset block in full and specifies the analogous blocks concretely (same structure, named apply-functions); the favourite ordering is spelled out. No code step defers content.

**3. Type consistency:** `plan_asset_sync→AssetPlan(full, invariant, added_uuids, trashed_uuids)`; `plan_membership_sync→MembershipPlan(full, invariant, added)`; `plan_favourite_sync→FavouritePlan(full, state, candidate_uuids)`; `plan_album_defs_sync→(bool, dict)`. State keys: `assets`(asset_zmax, active_count, active_pk_sum, max_trashed_date), `membership`(count, max_rowid, album_sum, asset_sum, prod_sum), `favourites`(max_mod_date), `albums`(album_zmax, active_count, mod_max). `load_sync_state`/`save_sync_state` used consistently in Tasks 2 and 10. SQL helpers' names match between queries.py (definition) and incremental.py (import).
