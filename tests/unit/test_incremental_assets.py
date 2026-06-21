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
