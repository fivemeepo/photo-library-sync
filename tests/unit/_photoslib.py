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
            ZTRASHEDSTATE INTEGER DEFAULT 0, ZLASTMODIFIEDDATE REAL DEFAULT 0.0
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
        "INSERT INTO ZGENERICALBUM (Z_PK, ZUUID, ZTITLE, ZKIND, ZLASTMODIFIEDDATE)"
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
