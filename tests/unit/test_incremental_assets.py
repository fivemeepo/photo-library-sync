from photo_sync.db.queries import (
    asset_invariant,
    fetch_assets_added_since,
    fetch_assets_trashed_since,
)
from _photoslib import add_asset, make_db


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


# Asset delta-vs-full decision tests
from photo_sync.operations.incremental import plan_asset_sync


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
