from photo_sync.db.queries import membership_invariant
from photo_sync.operations.incremental import plan_membership_sync
from _photoslib import add_album, add_asset, add_membership, make_db


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
