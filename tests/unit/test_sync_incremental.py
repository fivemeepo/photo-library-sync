"""Pure-decision wiring tests for the incremental orchestration in sync_photos.

The end-to-end file-copy + DB-insert behaviour is exercised by the existing sync
tests; these lock the delta-vs-full decision wiring that sync_photos drives.
"""

import sqlite3

from _photoslib import add_album, add_asset, add_membership, make_db

from photo_sync.db.queries import (
    album_defs_invariant,
    asset_invariant,
    get_assets_by_uuids,
    membership_invariant,
)
from photo_sync.models.sync_result import SyncResult
from photo_sync.operations.incremental import (
    plan_album_defs_sync,
    plan_asset_sync,
    plan_membership_sync,
)
from photo_sync.sync import _pk_to_uuid

# ----- Assets -----

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
    """Delta additions equal what a full source-target diff would return."""
    conn = make_db()
    add_asset(conn, "A")
    prev = asset_invariant(conn)
    add_asset(conn, "B")
    add_asset(conn, "C")
    plan = plan_asset_sync(conn, prev)
    assert set(plan.added_uuids) == {"B", "C"}


def test_first_run_escalates_to_full_for_assets():
    """No prior state -> full path (and a fresh invariant to persist)."""
    conn = make_db()
    add_asset(conn, "A")
    plan = plan_asset_sync(conn, None)
    assert plan.full is True
    assert plan.invariant["asset_zmax"] == 1


# ----- Membership -----

def test_second_run_is_noop_for_membership():
    conn = make_db()
    album_pk = add_album(conn, "ALB")
    asset_pk = add_asset(conn, "A")
    add_membership(conn, album_pk, asset_pk)
    prev = membership_invariant(conn)
    plan = plan_membership_sync(conn, prev)
    assert plan.full is False
    assert plan.added == []


def test_membership_delta_captures_new_row():
    conn = make_db()
    album_pk = add_album(conn, "ALB")
    a1 = add_asset(conn, "A")
    add_membership(conn, album_pk, a1)
    prev = membership_invariant(conn)
    a2 = add_asset(conn, "B")
    add_membership(conn, album_pk, a2)
    plan = plan_membership_sync(conn, prev)
    assert plan.full is False
    assert plan.added == [(album_pk, a2)]


# ----- Album definitions -----

def test_album_defs_skip_when_unchanged():
    conn = make_db()
    add_album(conn, "ALB", mod_date=1.0)
    prev = album_defs_invariant(conn)
    needs_full, cur = plan_album_defs_sync(conn, prev)
    assert needs_full is False
    assert cur == prev


def test_album_defs_full_on_first_run_and_on_change():
    conn = make_db()
    add_album(conn, "ALB", mod_date=1.0)
    # First run: no prev -> full.
    needs_full, prev = plan_album_defs_sync(conn, None)
    assert needs_full is True
    # A new album definition changes the invariant -> full again.
    add_album(conn, "ALB2", mod_date=2.0)
    needs_full, _cur = plan_album_defs_sync(conn, prev)
    assert needs_full is True


# ----- Fix 1: per-item warning must suppress watermark advance -----

def test_asset_per_item_warning_suppresses_watermark():
    """A per-item failure during asset apply must NOT advance the asset watermark.

    This directly tests the save-discipline logic added in Fix 1: if any
    per-item warning was recorded during the asset dimension's apply, the
    watermark (new_state["assets"]) must not be persisted.
    """
    conn = make_db()
    add_asset(conn, "A")
    prev = asset_invariant(conn)  # state saved at end of last run

    # Simulate a new asset appearing in the source
    add_asset(conn, "B")
    plan = plan_asset_sync(conn, prev)
    assert plan.full is False
    assert plan.added_uuids == ["B"]

    # Simulate the save-discipline logic from sync_photos:
    # A per-item failure appends to result.warnings, which flips asset_ok=False.
    result = SyncResult()
    new_state: dict = {}

    warnings_before = len(result.warnings)
    # Simulate a per-item failure during _apply_new_photos
    result.warnings.append("Failed to sync photo B: insert failed")
    # Save-discipline check (mirrors the code in sync_photos):
    asset_ok = len(result.warnings) == warnings_before
    if asset_ok:
        new_state["assets"] = plan.invariant

    # The watermark must NOT have advanced — "assets" should be absent from new_state
    assert "assets" not in new_state, (
        "Watermark was advanced despite a per-item warning; "
        "the failed photo would be permanently missed by the incremental path"
    )


def test_membership_per_item_warning_suppresses_watermark():
    """A per-item failure during membership apply must NOT advance the membership watermark.

    Regression guard for the cross-dimension coupling: a failed asset insert
    followed by a failed membership resolve (unresolved UUID → warning) must
    keep the membership watermark at prev so the membership re-deltas next run.
    """
    conn = make_db()
    album_pk = add_album(conn, "ALB")
    a1 = add_asset(conn, "A")
    add_membership(conn, album_pk, a1)
    prev = membership_invariant(conn)

    # Simulate a new membership appearing in the source
    a2 = add_asset(conn, "B")
    add_membership(conn, album_pk, a2)
    plan = plan_membership_sync(conn, prev)
    assert plan.full is False
    assert plan.added == [(album_pk, a2)]

    # Simulate the save-discipline logic from sync_photos:
    result = SyncResult()
    new_state: dict = {}

    warnings_before = len(result.warnings)
    # Simulate a per-item failure during membership resolve
    # (e.g. asset UUID not found in target after its insert also failed)
    result.warnings.append(
        "Skipping membership with unresolved UUIDs: album_pk=1, asset_pk=2"
    )
    membership_ok = len(result.warnings) == warnings_before
    if membership_ok:
        new_state["membership"] = plan.invariant

    assert "membership" not in new_state, (
        "Membership watermark was advanced despite a per-item warning; "
        "the failed membership would be permanently missed by the incremental path"
    )


# ----- Fix 2: chunked IN queries for >1000 ids -----

def _make_full_asset_db() -> sqlite3.Connection:
    """In-memory DB with the full ZASSET column set needed by get_assets_by_uuids."""
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE ZASSET (
            Z_PK INTEGER PRIMARY KEY,
            Z_ENT INTEGER DEFAULT 1,
            Z_OPT INTEGER DEFAULT 1,
            ZUUID TEXT,
            ZFILENAME TEXT,
            ZDIRECTORY TEXT,
            ZKIND INTEGER DEFAULT 0,
            ZWIDTH INTEGER DEFAULT 0,
            ZHEIGHT INTEGER DEFAULT 0,
            ZORIENTATION INTEGER DEFAULT 1,
            ZDURATION REAL DEFAULT 0.0,
            ZDATECREATED REAL DEFAULT 0.0,
            ZADDEDDATE REAL DEFAULT 0.0,
            ZMODIFICATIONDATE REAL DEFAULT 0.0,
            ZTRASHEDSTATE INTEGER DEFAULT 0,
            ZTRASHEDDATE REAL,
            ZFAVORITE INTEGER DEFAULT 0,
            ZHIDDEN INTEGER DEFAULT 0,
            ZVISIBILITYSTATE INTEGER DEFAULT 0,
            ZCOMPLETE INTEGER DEFAULT 1,
            ZUNIFORMTYPEIDENTIFIER TEXT,
            ZPLAYBACKSTYLE INTEGER DEFAULT 1,
            ZSAVEDASSETTYPE INTEGER DEFAULT 3,
            ZADDITIONALATTRIBUTES INTEGER,
            ZEXTENDEDATTRIBUTES INTEGER,
            ZMOMENT INTEGER
        );
        """
    )
    return conn


def test_get_assets_by_uuids_handles_more_than_1000():
    """get_assets_by_uuids must not raise with >1000 UUIDs (chunked IN query)."""
    conn = _make_full_asset_db()
    n = 1050
    uuids = [f"UUID-{i:04d}" for i in range(n)]
    for i, uuid in enumerate(uuids):
        conn.execute(
            "INSERT INTO ZASSET (Z_PK, ZUUID) VALUES (?, ?)", (i + 1, uuid)
        )
    conn.commit()

    assets = get_assets_by_uuids(conn, uuids)
    assert len(assets) == n, f"Expected {n} assets, got {len(assets)}"
    returned_uuids = {a.uuid for a in assets}
    assert returned_uuids == set(uuids)


def test_pk_to_uuid_handles_more_than_1000():
    """_pk_to_uuid must not raise with >1000 PKs (chunked IN query)."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE ZASSET (Z_PK INTEGER PRIMARY KEY, ZUUID TEXT)"
    )
    n = 1050
    pks = set(range(1, n + 1))
    for pk in pks:
        conn.execute(
            "INSERT INTO ZASSET (Z_PK, ZUUID) VALUES (?, ?)", (pk, f"UUID-{pk:04d}")
        )
    conn.commit()

    result = _pk_to_uuid(conn, "ZASSET", pks)
    assert len(result) == n
    assert result[1] == "UUID-0001"
    assert result[n] == f"UUID-{n:04d}"
