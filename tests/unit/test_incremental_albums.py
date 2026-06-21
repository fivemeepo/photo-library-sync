"""Tests for album-definitions skip-or-full gate."""

from photo_sync.db.queries import album_defs_invariant
from photo_sync.operations.incremental import plan_album_defs_sync
from _photoslib import add_album, make_db


def test_skip_when_unchanged():
    conn = make_db()
    add_album(conn, "a1", mod_date=1.0)
    prev = album_defs_invariant(conn)
    needs_full, inv = plan_album_defs_sync(conn, prev)
    assert needs_full is False
    assert inv == prev


def test_full_on_new_album():
    conn = make_db()
    add_album(conn, "a1", mod_date=1.0)
    prev = album_defs_invariant(conn)
    add_album(conn, "a2", mod_date=1.0)
    needs_full, _ = plan_album_defs_sync(conn, prev)
    assert needs_full is True


def test_full_on_rename():
    conn = make_db()
    add_album(conn, "a1", mod_date=1.0)
    prev = album_defs_invariant(conn)
    conn.execute("UPDATE ZGENERICALBUM SET ZTITLE='new', ZMODIFICATIONDATE=9.0 WHERE ZUUID='a1'")
    needs_full, _ = plan_album_defs_sync(conn, prev)
    assert needs_full is True
