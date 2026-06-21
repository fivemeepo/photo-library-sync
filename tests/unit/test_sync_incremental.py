"""Pure-decision wiring tests for the incremental orchestration in sync_photos.

The end-to-end file-copy + DB-insert behaviour is exercised by the existing sync
tests; these lock the delta-vs-full decision wiring that sync_photos drives.
"""

from _photoslib import add_album, add_asset, add_membership, make_db

from photo_sync.db.queries import (
    album_defs_invariant,
    asset_invariant,
    membership_invariant,
)
from photo_sync.operations.incremental import (
    plan_album_defs_sync,
    plan_asset_sync,
    plan_membership_sync,
)

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
