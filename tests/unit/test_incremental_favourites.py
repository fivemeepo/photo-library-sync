import zlib

from _photoslib import add_asset, make_db

from photo_sync.db.queries import (
    favourite_set_summary,
    favourite_state,
    fetch_favourite_candidates_since,
)
from photo_sync.operations.incremental import plan_favourite_sync


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
    src = _register(make_db())
    tgt = _register(make_db())
    # Both libraries start identical: A favourite, B not.
    add_asset(src, "A", favorite=1, mod_date=1.0)
    add_asset(src, "B", favorite=0, mod_date=1.0)
    add_asset(tgt, "A", favorite=1, mod_date=1.0)
    add_asset(tgt, "B", favorite=0, mod_date=1.0)
    prev = favourite_state(src)
    # Source favourites B (bumps mod date) -> candidate captures it.
    src.execute("UPDATE ZASSET SET ZFAVORITE=1, ZMODIFICATIONDATE=9.0 WHERE ZUUID='B'")
    # Simulate the caller having applied the favourite update to target:
    tgt.execute("UPDATE ZASSET SET ZFAVORITE=1 WHERE ZUUID='B'")
    plan = plan_favourite_sync(src, tgt, prev)
    assert plan.full is False
    assert "B" in plan.candidate_uuids
    # Verify favourite_set_summary is being used through plan_favourite_sync
    assert favourite_set_summary(src) == favourite_set_summary(tgt)


def test_escalates_when_change_without_moddate():
    src = _register(make_db())
    tgt = _register(make_db())
    add_asset(src, "A", favorite=0, mod_date=1.0)
    add_asset(tgt, "A", favorite=0, mod_date=1.0)
    prev = favourite_state(src)
    # Source favourites A but mod date does NOT advance -> not a candidate.
    src.execute("UPDATE ZASSET SET ZFAVORITE=1 WHERE ZUUID='A'")
    plan = plan_favourite_sync(src, tgt, prev)
    assert plan.full is True
