"""Tests for dedup operations."""

import sqlite3

import pytest


def create_test_db() -> sqlite3.Connection:
    """Create an in-memory database with Photos.sqlite schema for testing."""
    conn = sqlite3.connect(":memory:")
    conn.execute("""
        CREATE TABLE ZASSET (
            Z_PK INTEGER PRIMARY KEY,
            Z_ENT INTEGER DEFAULT 73,
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
        )
    """)
    conn.execute("""
        CREATE TABLE ZGENERICALBUM (
            Z_PK INTEGER PRIMARY KEY,
            Z_ENT INTEGER DEFAULT 55,
            Z_OPT INTEGER DEFAULT 1,
            ZUUID TEXT,
            ZTITLE TEXT,
            ZKIND INTEGER DEFAULT 2,
            ZPARENTFOLDER INTEGER,
            Z_FOK_PARENTFOLDER INTEGER,
            ZCREATIONDATE REAL,
            ZSTARTDATE REAL,
            ZENDDATE REAL,
            ZLASTMODIFIEDDATE REAL,
            ZTRASHEDSTATE INTEGER DEFAULT 0,
            ZCLOUDDELETESTATE INTEGER DEFAULT 0,
            ZCLOUDLOCALSTATE INTEGER DEFAULT 0,
            ZPRIVACYSTATE INTEGER DEFAULT 0,
            ZSYNCEVENTORDERKEY INTEGER DEFAULT 0,
            ZSEARCHINDEXREBUILDSTATE INTEGER DEFAULT 0,
            ZCUSTOMSORTASCENDING INTEGER DEFAULT 1,
            ZCUSTOMSORTKEY INTEGER DEFAULT 1,
            ZISPINNED INTEGER DEFAULT 0,
            ZISPROTOTYPE INTEGER DEFAULT 0,
            ZPENDINGITEMSCOUNT INTEGER DEFAULT 0,
            ZPENDINGITEMSTYPE INTEGER DEFAULT 1,
            ZIMPORTEDBYBUNDLEIDENTIFIER TEXT,
            ZCACHEDCOUNT INTEGER DEFAULT 0,
            ZCACHEDPHOTOSCOUNT INTEGER DEFAULT 0,
            ZCACHEDVIDEOSCOUNT INTEGER DEFAULT 0
        )
    """)
    conn.execute("""
        CREATE TABLE Z_33ASSETS (
            Z_33ALBUMS INTEGER,
            Z_3ASSETS INTEGER,
            Z_FOK_3ASSETS INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE ZADDITIONALASSETATTRIBUTES (
            Z_PK INTEGER PRIMARY KEY,
            Z_ENT INTEGER DEFAULT 1,
            Z_OPT INTEGER DEFAULT 1,
            ZASSET INTEGER,
            ZORIGINALFILENAME TEXT,
            ZORIGINALFILESIZE INTEGER,
            ZORIGINALWIDTH INTEGER,
            ZORIGINALHEIGHT INTEGER,
            ZIMPORTEDBYBUNDLEIDENTIFIER TEXT,
            ZIMPORTEDBYDISPLAYNAME TEXT,
            ZTIMEZONENAME TEXT,
            ZTIMEZONEOFFSET INTEGER,
            ZREVERSELOCATIONDATA BLOB
        )
    """)
    return conn


def test_get_album_by_title_found():
    from photo_sync.db.queries import get_album_by_title

    conn = create_test_db()
    conn.execute(
        "INSERT INTO ZGENERICALBUM (Z_PK, ZUUID, ZTITLE, ZKIND) VALUES (1, 'uuid1', 'Vacation', 2)"
    )
    album = get_album_by_title(conn, "Vacation")
    assert album is not None
    assert album.title == "Vacation"
    assert album.z_pk == 1


def test_get_album_by_title_not_found():
    from photo_sync.db.queries import get_album_by_title

    conn = create_test_db()
    album = get_album_by_title(conn, "NonExistent")
    assert album is None


def test_get_album_by_title_ignores_trashed():
    from photo_sync.db.queries import get_album_by_title

    conn = create_test_db()
    conn.execute(
        "INSERT INTO ZGENERICALBUM (Z_PK, ZUUID, ZTITLE, ZKIND, ZTRASHEDSTATE) VALUES (1, 'uuid1', 'Vacation', 2, 1)"
    )
    album = get_album_by_title(conn, "Vacation")
    assert album is None


def test_get_album_assets_for_dedup():
    from photo_sync.db.queries import get_album_assets_for_dedup

    conn = create_test_db()
    # Album
    conn.execute(
        "INSERT INTO ZGENERICALBUM (Z_PK, ZUUID, ZTITLE, ZKIND) VALUES (1, 'album-uuid', 'TestAlbum', 2)"
    )
    # Two assets (on-disk names are UUIDs, original names have real filenames)
    conn.execute(
        "INSERT INTO ZASSET (Z_PK, ZUUID, ZFILENAME, ZWIDTH, ZHEIGHT, ZDATECREATED, ZTRASHEDSTATE) "
        "VALUES (10, 'asset-1', 'AAAA-1111.PNG', 1080, 1920, 100.0, 0)"
    )
    conn.execute(
        "INSERT INTO ZASSET (Z_PK, ZUUID, ZFILENAME, ZWIDTH, ZHEIGHT, ZDATECREATED, ZTRASHEDSTATE) "
        "VALUES (11, 'asset-2', 'BBBB-2222.PNG', 1080, 1920, 200.0, 0)"
    )
    # Additional attributes with file sizes and original filenames
    conn.execute(
        "INSERT INTO ZADDITIONALASSETATTRIBUTES (Z_PK, ZASSET, ZORIGINALFILESIZE, ZORIGINALFILENAME) "
        "VALUES (100, 10, 5000, 'IMG_7153.PNG')"
    )
    conn.execute(
        "INSERT INTO ZADDITIONALASSETATTRIBUTES (Z_PK, ZASSET, ZORIGINALFILESIZE, ZORIGINALFILENAME) "
        "VALUES (101, 11, 5000, 'IMG_7153 (1).PNG')"
    )
    # Album memberships
    conn.execute("INSERT INTO Z_33ASSETS (Z_33ALBUMS, Z_3ASSETS) VALUES (1, 10)")
    conn.execute("INSERT INTO Z_33ASSETS (Z_33ALBUMS, Z_3ASSETS) VALUES (1, 11)")

    rows = get_album_assets_for_dedup(conn, album_pk=1)
    assert len(rows) == 2
    # Each row: (uuid, original_filename, file_size, width, height, date_created)
    assert rows[0][1] == "IMG_7153 (1).PNG"
    assert rows[1][1] == "IMG_7153.PNG"


def test_get_album_assets_for_dedup_excludes_trashed():
    from photo_sync.db.queries import get_album_assets_for_dedup

    conn = create_test_db()
    conn.execute(
        "INSERT INTO ZGENERICALBUM (Z_PK, ZUUID, ZTITLE, ZKIND) VALUES (1, 'album-uuid', 'TestAlbum', 2)"
    )
    conn.execute(
        "INSERT INTO ZASSET (Z_PK, ZUUID, ZFILENAME, ZWIDTH, ZHEIGHT, ZDATECREATED, ZTRASHEDSTATE) "
        "VALUES (10, 'asset-1', 'IMG_7153.PNG', 1080, 1920, 100.0, 1)"
    )
    conn.execute(
        "INSERT INTO ZADDITIONALASSETATTRIBUTES (Z_PK, ZASSET, ZORIGINALFILESIZE) VALUES (100, 10, 5000)"
    )
    conn.execute("INSERT INTO Z_33ASSETS (Z_33ALBUMS, Z_3ASSETS) VALUES (1, 10)")

    rows = get_album_assets_for_dedup(conn, album_pk=1)
    assert len(rows) == 0


def test_normalize_filename():
    from photo_sync.operations.dedup import normalize_filename

    assert normalize_filename("IMG_7153.PNG") == ("IMG_7153", ".PNG")
    assert normalize_filename("IMG_7153 (1).PNG") == ("IMG_7153", ".PNG")
    assert normalize_filename("IMG_7153 (2).PNG") == ("IMG_7153", ".PNG")
    assert normalize_filename("photo.edit.jpg") == ("photo.edit", ".jpg")
    assert normalize_filename("IMG_7153(1).PNG") == ("IMG_7153", ".PNG")
    assert normalize_filename("noextension") == ("noextension", "")


def test_find_duplicates_basic():
    from photo_sync.operations.dedup import find_duplicates

    # (uuid, filename, file_size, width, height, date_created)
    rows = [
        ("uuid-1", "IMG_7153.PNG", 5000, 1080, 1920, 100.0),
        ("uuid-2", "IMG_7153 (1).PNG", 5000, 1080, 1920, 200.0),
        ("uuid-3", "IMG_9999.JPG", 3000, 800, 600, 50.0),
    ]
    groups = find_duplicates(rows)
    assert len(groups) == 1
    keeper, duplicates = groups[0]
    assert keeper[0] == "uuid-1"  # earliest date_created
    assert len(duplicates) == 1
    assert duplicates[0][0] == "uuid-2"


def test_find_duplicates_keeps_earliest():
    from photo_sync.operations.dedup import find_duplicates

    rows = [
        ("uuid-a", "IMG_100 (1).PNG", 5000, 1080, 1920, 300.0),
        ("uuid-b", "IMG_100.PNG", 5000, 1080, 1920, 100.0),
        ("uuid-c", "IMG_100 (2).PNG", 5000, 1080, 1920, 200.0),
    ]
    groups = find_duplicates(rows)
    assert len(groups) == 1
    keeper, duplicates = groups[0]
    assert keeper[0] == "uuid-b"  # no suffix takes priority, also earliest
    assert len(duplicates) == 2


def test_find_duplicates_prefers_no_suffix_over_earlier_date():
    from photo_sync.operations.dedup import find_duplicates

    # The (1) suffix file was created earlier, but the no-suffix file should be kept
    rows = [
        ("uuid-a", "IMG_100 (1).PNG", 5000, 1080, 1920, 50.0),   # earlier but has suffix
        ("uuid-b", "IMG_100.PNG", 5000, 1080, 1920, 200.0),       # later but no suffix
    ]
    groups = find_duplicates(rows)
    assert len(groups) == 1
    keeper, duplicates = groups[0]
    assert keeper[0] == "uuid-b"  # no-suffix wins despite later date
    assert duplicates[0][0] == "uuid-a"


def test_find_duplicates_different_size_not_duplicates():
    from photo_sync.operations.dedup import find_duplicates

    rows = [
        ("uuid-1", "IMG_7153.PNG", 5000, 1080, 1920, 100.0),
        ("uuid-2", "IMG_7153 (1).PNG", 9999, 1080, 1920, 200.0),
    ]
    groups = find_duplicates(rows)
    assert len(groups) == 0


def test_find_duplicates_different_resolution_not_duplicates():
    from photo_sync.operations.dedup import find_duplicates

    rows = [
        ("uuid-1", "IMG_7153.PNG", 5000, 1080, 1920, 100.0),
        ("uuid-2", "IMG_7153 (1).PNG", 5000, 800, 600, 200.0),
    ]
    groups = find_duplicates(rows)
    assert len(groups) == 0


def test_find_duplicates_same_filename_different_dates():
    from photo_sync.operations.dedup import find_duplicates

    # Two files with the exact same filename (possible from different imports)
    rows = [
        ("uuid-1", "IMG_7153.PNG", 5000, 1080, 1920, 300.0),
        ("uuid-2", "IMG_7153.PNG", 5000, 1080, 1920, 100.0),
    ]
    groups = find_duplicates(rows)
    assert len(groups) == 1
    keeper, duplicates = groups[0]
    assert keeper[0] == "uuid-2"  # earlier date
    assert duplicates[0][0] == "uuid-1"


def test_dedup_album_dry_run():
    from photo_sync.operations.dedup import dedup_album_dry_run

    conn = create_test_db()
    # Album
    conn.execute(
        "INSERT INTO ZGENERICALBUM (Z_PK, ZUUID, ZTITLE, ZKIND) VALUES (1, 'album-uuid', 'TestAlbum', 2)"
    )
    # Original + duplicate (on-disk names are UUIDs)
    conn.execute(
        "INSERT INTO ZASSET (Z_PK, ZUUID, ZFILENAME, ZWIDTH, ZHEIGHT, ZDATECREATED, ZTRASHEDSTATE) "
        "VALUES (10, 'asset-1', 'AAAA-1111.PNG', 1080, 1920, 100.0, 0)"
    )
    conn.execute(
        "INSERT INTO ZASSET (Z_PK, ZUUID, ZFILENAME, ZWIDTH, ZHEIGHT, ZDATECREATED, ZTRASHEDSTATE) "
        "VALUES (11, 'asset-2', 'BBBB-2222.PNG', 1080, 1920, 200.0, 0)"
    )
    conn.execute(
        "INSERT INTO ZADDITIONALASSETATTRIBUTES (Z_PK, ZASSET, ZORIGINALFILESIZE, ZORIGINALFILENAME, ZORIGINALWIDTH, ZORIGINALHEIGHT) "
        "VALUES (100, 10, 5000, 'IMG_7153.PNG', 1080, 1920)"
    )
    conn.execute(
        "INSERT INTO ZADDITIONALASSETATTRIBUTES (Z_PK, ZASSET, ZORIGINALFILESIZE, ZORIGINALFILENAME, ZORIGINALWIDTH, ZORIGINALHEIGHT) "
        "VALUES (101, 11, 5000, 'IMG_7153 (1).PNG', 1080, 1920)"
    )
    conn.execute("INSERT INTO Z_33ASSETS (Z_33ALBUMS, Z_3ASSETS) VALUES (1, 10)")
    conn.execute("INSERT INTO Z_33ASSETS (Z_33ALBUMS, Z_3ASSETS) VALUES (1, 11)")

    report = dedup_album_dry_run(conn, album_title="TestAlbum")
    assert report["album"] == "TestAlbum"
    assert report["total_duplicates"] == 1
    assert report["total_to_delete"] == 1
    assert len(report["groups"]) == 1
    group = report["groups"][0]
    assert group["keep"]["uuid"] == "asset-1"
    assert len(group["delete"]) == 1
    assert group["delete"][0]["uuid"] == "asset-2"


def test_dedup_album_dry_run_no_duplicates():
    from photo_sync.operations.dedup import dedup_album_dry_run

    conn = create_test_db()
    conn.execute(
        "INSERT INTO ZGENERICALBUM (Z_PK, ZUUID, ZTITLE, ZKIND) VALUES (1, 'album-uuid', 'TestAlbum', 2)"
    )
    conn.execute(
        "INSERT INTO ZASSET (Z_PK, ZUUID, ZFILENAME, ZWIDTH, ZHEIGHT, ZDATECREATED, ZTRASHEDSTATE) "
        "VALUES (10, 'asset-1', 'AAAA-1111.PNG', 1080, 1920, 100.0, 0)"
    )
    conn.execute(
        "INSERT INTO ZADDITIONALASSETATTRIBUTES (Z_PK, ZASSET, ZORIGINALFILESIZE, ZORIGINALFILENAME) "
        "VALUES (100, 10, 5000, 'IMG_7153.PNG')"
    )
    conn.execute("INSERT INTO Z_33ASSETS (Z_33ALBUMS, Z_3ASSETS) VALUES (1, 10)")

    report = dedup_album_dry_run(conn, album_title="TestAlbum")
    assert report["total_duplicates"] == 0
    assert report["total_to_delete"] == 0


def test_dedup_album_dry_run_album_not_found():
    from photo_sync.operations.dedup import dedup_album_dry_run

    conn = create_test_db()
    with pytest.raises(ValueError, match="Album not found"):
        dedup_album_dry_run(conn, album_title="NonExistent")


def test_dedup_album_execute():
    from photo_sync.operations.dedup import dedup_album_execute

    conn = create_test_db()
    # Album
    conn.execute(
        "INSERT INTO ZGENERICALBUM (Z_PK, ZUUID, ZTITLE, ZKIND, ZCACHEDCOUNT, ZCACHEDPHOTOSCOUNT) "
        "VALUES (1, 'album-uuid', 'TestAlbum', 2, 2, 2)"
    )
    # Original + duplicate (on-disk names are UUIDs)
    conn.execute(
        "INSERT INTO ZASSET (Z_PK, ZUUID, ZFILENAME, ZWIDTH, ZHEIGHT, ZDATECREATED, ZTRASHEDSTATE) "
        "VALUES (10, 'asset-1', 'AAAA-1111.PNG', 1080, 1920, 100.0, 0)"
    )
    conn.execute(
        "INSERT INTO ZASSET (Z_PK, ZUUID, ZFILENAME, ZWIDTH, ZHEIGHT, ZDATECREATED, ZTRASHEDSTATE) "
        "VALUES (11, 'asset-2', 'BBBB-2222.PNG', 1080, 1920, 200.0, 0)"
    )
    conn.execute(
        "INSERT INTO ZADDITIONALASSETATTRIBUTES (Z_PK, ZASSET, ZORIGINALFILESIZE, ZORIGINALFILENAME, ZORIGINALWIDTH, ZORIGINALHEIGHT) "
        "VALUES (100, 10, 5000, 'IMG_7153.PNG', 1080, 1920)"
    )
    conn.execute(
        "INSERT INTO ZADDITIONALASSETATTRIBUTES (Z_PK, ZASSET, ZORIGINALFILESIZE, ZORIGINALFILENAME, ZORIGINALWIDTH, ZORIGINALHEIGHT) "
        "VALUES (101, 11, 5000, 'IMG_7153 (1).PNG', 1080, 1920)"
    )
    conn.execute("INSERT INTO Z_33ASSETS (Z_33ALBUMS, Z_3ASSETS) VALUES (1, 10)")
    conn.execute("INSERT INTO Z_33ASSETS (Z_33ALBUMS, Z_3ASSETS) VALUES (1, 11)")

    result = dedup_album_execute(conn, album_title="TestAlbum")
    assert result["deleted"] == 1
    assert result["groups"] == 1

    # Verify the duplicate is trashed
    row = conn.execute("SELECT ZTRASHEDSTATE FROM ZASSET WHERE ZUUID = 'asset-2'").fetchone()
    assert row[0] == 1

    # Verify the original is untouched
    row = conn.execute("SELECT ZTRASHEDSTATE FROM ZASSET WHERE ZUUID = 'asset-1'").fetchone()
    assert row[0] == 0

    # Verify album membership removed for duplicate
    count = conn.execute("SELECT COUNT(*) FROM Z_33ASSETS WHERE Z_3ASSETS = 11").fetchone()[0]
    assert count == 0
