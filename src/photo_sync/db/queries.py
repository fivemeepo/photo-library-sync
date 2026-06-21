"""SQL query functions for reading from Photos.sqlite.

All functions in this module are read-only operations.
"""

from __future__ import annotations

import logging
import sqlite3

from photo_sync.db.pk_manager import get_current_max_pk
from photo_sync.models import (
    AdditionalAssetAttributes,
    Album,
    AlbumAsset,
    Asset,
    ExtendedAttributes,
    InternalResource,
    Moment,
)

logger = logging.getLogger(__name__)


def get_all_asset_uuids(conn: sqlite3.Connection, include_trashed: bool = False) -> set[str]:
    """Get all asset UUIDs from the database.

    Args:
        conn: SQLite connection
        include_trashed: If True, include trashed assets

    Returns:
        Set of asset UUIDs
    """
    if include_trashed:
        cursor = conn.execute("SELECT ZUUID FROM ZASSET")
    else:
        cursor = conn.execute("SELECT ZUUID FROM ZASSET WHERE ZTRASHEDSTATE = 0")

    return {row[0] for row in cursor.fetchall()}


def get_asset_by_uuid(conn: sqlite3.Connection, uuid: str) -> Asset | None:
    """Get an asset by its UUID.

    Args:
        conn: SQLite connection
        uuid: Asset UUID

    Returns:
        Asset object or None if not found
    """
    cursor = conn.execute(
        """
        SELECT Z_PK, Z_ENT, Z_OPT, ZUUID, ZFILENAME, ZDIRECTORY,
               ZKIND, ZWIDTH, ZHEIGHT, ZORIENTATION, ZDURATION,
               ZDATECREATED, ZADDEDDATE, ZMODIFICATIONDATE,
               ZTRASHEDSTATE, ZTRASHEDDATE, ZFAVORITE, ZHIDDEN,
               ZVISIBILITYSTATE, ZCOMPLETE, ZUNIFORMTYPEIDENTIFIER,
               ZPLAYBACKSTYLE, ZSAVEDASSETTYPE,
               ZADDITIONALATTRIBUTES, ZEXTENDEDATTRIBUTES, ZMOMENT
        FROM ZASSET
        WHERE ZUUID = ?
        """,
        (uuid,)
    )
    row = cursor.fetchone()

    if row is None:
        return None

    return Asset(
        z_pk=row[0],
        z_ent=row[1],
        z_opt=row[2],
        uuid=row[3],
        filename=row[4] or "",
        directory=row[5] or "",
        kind=row[6] or 0,
        width=row[7] or 0,
        height=row[8] or 0,
        orientation=row[9] or 1,
        duration=row[10] or 0.0,
        date_created=row[11] or 0.0,
        added_date=row[12] or 0.0,
        modification_date=row[13] or 0.0,
        trashed_state=row[14] or 0,
        trashed_date=row[15],
        favorite=row[16] or 0,
        hidden=row[17] or 0,
        visibility_state=row[18] or 0,
        complete=row[19] if row[19] is not None else 1,
        uniform_type_identifier=row[20],
        playback_style=row[21] if row[21] is not None else 1,
        saved_asset_type=row[22] if row[22] is not None else 3,
        additional_attributes=row[23],
        extended_attributes=row[24],
        moment=row[25],
    )


_CHUNK_SIZE = 900  # safely below SQLite SQLITE_MAX_VARIABLE_NUMBER (999 on older builds)


def get_assets_by_uuids(conn: sqlite3.Connection, uuids: list[str]) -> list[Asset]:
    """Get multiple assets by their UUIDs.

    The UUID list is chunked into batches of at most _CHUNK_SIZE to avoid
    exceeding SQLite's SQLITE_MAX_VARIABLE_NUMBER limit on large deltas.

    Args:
        conn: SQLite connection
        uuids: List of asset UUIDs

    Returns:
        List of Asset objects (order follows input chunking order)
    """
    if not uuids:
        return []

    assets = []
    for i in range(0, len(uuids), _CHUNK_SIZE):
        batch = uuids[i : i + _CHUNK_SIZE]
        placeholders = ",".join("?" * len(batch))
        cursor = conn.execute(
            f"""
            SELECT Z_PK, Z_ENT, Z_OPT, ZUUID, ZFILENAME, ZDIRECTORY,
                   ZKIND, ZWIDTH, ZHEIGHT, ZORIENTATION, ZDURATION,
                   ZDATECREATED, ZADDEDDATE, ZMODIFICATIONDATE,
                   ZTRASHEDSTATE, ZTRASHEDDATE, ZFAVORITE, ZHIDDEN,
                   ZVISIBILITYSTATE, ZCOMPLETE, ZUNIFORMTYPEIDENTIFIER,
                   ZPLAYBACKSTYLE, ZSAVEDASSETTYPE,
                   ZADDITIONALATTRIBUTES, ZEXTENDEDATTRIBUTES, ZMOMENT
            FROM ZASSET
            WHERE ZUUID IN ({placeholders})
            """,
            batch,
        )
        for row in cursor.fetchall():
            assets.append(Asset(
                z_pk=row[0],
                z_ent=row[1],
                z_opt=row[2],
                uuid=row[3],
                filename=row[4] or "",
                directory=row[5] or "",
                kind=row[6] or 0,
                width=row[7] or 0,
                height=row[8] or 0,
                orientation=row[9] or 1,
                duration=row[10] or 0.0,
                date_created=row[11] or 0.0,
                added_date=row[12] or 0.0,
                modification_date=row[13] or 0.0,
                trashed_state=row[14] or 0,
                trashed_date=row[15],
                favorite=row[16] or 0,
                hidden=row[17] or 0,
                visibility_state=row[18] or 0,
                complete=row[19] if row[19] is not None else 1,
                uniform_type_identifier=row[20],
                playback_style=row[21] if row[21] is not None else 1,
                saved_asset_type=row[22] if row[22] is not None else 3,
                additional_attributes=row[23],
                extended_attributes=row[24],
                moment=row[25],
            ))

    return assets


def get_additional_attributes(
    conn: sqlite3.Connection,
    asset_pk: int
) -> AdditionalAssetAttributes | None:
    """Get additional attributes for an asset.

    Args:
        conn: SQLite connection
        asset_pk: Asset Z_PK

    Returns:
        AdditionalAssetAttributes or None
    """
    cursor = conn.execute(
        """
        SELECT Z_PK, Z_ENT, Z_OPT, ZASSET,
               ZORIGINALFILENAME, ZORIGINALFILESIZE,
               ZORIGINALWIDTH, ZORIGINALHEIGHT,
               ZIMPORTEDBYBUNDLEIDENTIFIER, ZIMPORTEDBYDISPLAYNAME,
               ZTIMEZONENAME, ZTIMEZONEOFFSET, ZREVERSELOCATIONDATA
        FROM ZADDITIONALASSETATTRIBUTES
        WHERE ZASSET = ?
        """,
        (asset_pk,)
    )
    row = cursor.fetchone()

    if row is None:
        return None

    return AdditionalAssetAttributes(
        z_pk=row[0],
        z_ent=row[1],
        z_opt=row[2],
        asset=row[3],
        original_filename=row[4],
        original_filesize=row[5],
        original_width=row[6],
        original_height=row[7],
        imported_by_bundle_id=row[8],
        imported_by_display_name=row[9],
        timezone_name=row[10],
        timezone_offset=row[11],
        reverse_location_data=row[12],
    )


def get_extended_attributes(
    conn: sqlite3.Connection,
    asset_pk: int
) -> ExtendedAttributes | None:
    """Get extended attributes for an asset.

    Args:
        conn: SQLite connection
        asset_pk: Asset Z_PK

    Returns:
        ExtendedAttributes or None
    """
    cursor = conn.execute(
        """
        SELECT Z_PK, Z_ENT, Z_OPT, ZASSET
        FROM ZEXTENDEDATTRIBUTES
        WHERE ZASSET = ?
        """,
        (asset_pk,)
    )
    row = cursor.fetchone()

    if row is None:
        return None

    return ExtendedAttributes(
        z_pk=row[0],
        z_ent=row[1],
        z_opt=row[2],
        asset=row[3],
    )


def get_internal_resources(
    conn: sqlite3.Connection,
    asset_pk: int
) -> list[InternalResource]:
    """Get internal resources for an asset.

    Args:
        conn: SQLite connection
        asset_pk: Asset Z_PK

    Returns:
        List of InternalResource objects
    """
    cursor = conn.execute(
        """
        SELECT Z_PK, Z_ENT, Z_OPT, ZASSET,
               ZRESOURCETYPE, ZDATALENGTH, ZLOCALAVAILABILITY, ZFINGERPRINT
        FROM ZINTERNALRESOURCE
        WHERE ZASSET = ?
        """,
        (asset_pk,)
    )

    resources = []
    for row in cursor.fetchall():
        resources.append(InternalResource(
            z_pk=row[0],
            z_ent=row[1],
            z_opt=row[2],
            asset=row[3],
            resource_type=row[4] or 0,
            data_length=row[5] or 0,
            local_availability=row[6] or 1,
            fingerprint=row[7],
        ))

    return resources


def get_all_albums(
    conn: sqlite3.Connection,
    kind: int | None = None,
    include_trashed: bool = False
) -> list[Album]:
    """Get all albums from the database.

    Args:
        conn: SQLite connection
        kind: Filter by album kind (2=album, 4000=folder)
        include_trashed: If True, include trashed albums

    Returns:
        List of Album objects
    """
    conditions = []
    params = []

    if kind is not None:
        conditions.append("ZKIND = ?")
        params.append(kind)

    if not include_trashed:
        conditions.append("ZTRASHEDSTATE = 0")

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    cursor = conn.execute(
        f"""
        SELECT Z_PK, Z_ENT, Z_OPT, ZUUID, ZTITLE, ZKIND,
               ZPARENTFOLDER, Z_FOK_PARENTFOLDER, ZCREATIONDATE, ZSTARTDATE, ZENDDATE,
               ZLASTMODIFIEDDATE, ZTRASHEDSTATE,
               ZCLOUDDELETESTATE, ZCLOUDLOCALSTATE, ZPRIVACYSTATE,
               ZSYNCEVENTORDERKEY, ZSEARCHINDEXREBUILDSTATE,
               ZCUSTOMSORTASCENDING, ZCUSTOMSORTKEY,
               ZISPINNED, ZISPROTOTYPE, ZPENDINGITEMSCOUNT, ZPENDINGITEMSTYPE,
               ZIMPORTEDBYBUNDLEIDENTIFIER,
               ZCACHEDCOUNT, ZCACHEDPHOTOSCOUNT, ZCACHEDVIDEOSCOUNT
        FROM ZGENERICALBUM
        {where_clause}
        """,
        params
    )

    albums = []
    for row in cursor.fetchall():
        albums.append(Album(
            z_pk=row[0],
            z_ent=row[1],
            z_opt=row[2],
            uuid=row[3] or "",
            title=row[4],
            kind=row[5] or 2,
            parent_folder=row[6],
            z_fok_parent_folder=row[7],
            creation_date=row[8],
            start_date=row[9],
            end_date=row[10],
            last_modified_date=row[11],
            trashed_state=row[12] or 0,
            cloud_delete_state=row[13] or 0,
            cloud_local_state=row[14] or 0,
            privacy_state=row[15] or 0,
            sync_event_order_key=row[16] or 0,
            search_index_rebuild_state=row[17] or 0,
            custom_sort_ascending=row[18] if row[18] is not None else 1,
            custom_sort_key=row[19] if row[19] is not None else 1,
            is_pinned=row[20] or 0,
            is_prototype=row[21] or 0,
            pending_items_count=row[22] or 0,
            pending_items_type=row[23] if row[23] is not None else 1,
            imported_by_bundle_id=row[24],
            cached_count=row[25] or 0,
            cached_photos_count=row[26] or 0,
            cached_videos_count=row[27] or 0,
        ))

    return albums


def get_album_by_uuid(conn: sqlite3.Connection, uuid: str) -> Album | None:
    """Get an album by its UUID.

    Args:
        conn: SQLite connection
        uuid: Album UUID

    Returns:
        Album object or None if not found
    """
    cursor = conn.execute(
        """
        SELECT Z_PK, Z_ENT, Z_OPT, ZUUID, ZTITLE, ZKIND,
               ZPARENTFOLDER, Z_FOK_PARENTFOLDER, ZCREATIONDATE, ZSTARTDATE, ZENDDATE,
               ZLASTMODIFIEDDATE, ZTRASHEDSTATE,
               ZCLOUDDELETESTATE, ZCLOUDLOCALSTATE, ZPRIVACYSTATE,
               ZSYNCEVENTORDERKEY, ZSEARCHINDEXREBUILDSTATE,
               ZCUSTOMSORTASCENDING, ZCUSTOMSORTKEY,
               ZISPINNED, ZISPROTOTYPE, ZPENDINGITEMSCOUNT, ZPENDINGITEMSTYPE,
               ZIMPORTEDBYBUNDLEIDENTIFIER,
               ZCACHEDCOUNT, ZCACHEDPHOTOSCOUNT, ZCACHEDVIDEOSCOUNT
        FROM ZGENERICALBUM
        WHERE ZUUID = ?
        """,
        (uuid,)
    )
    row = cursor.fetchone()

    if row is None:
        return None

    return Album(
        z_pk=row[0],
        z_ent=row[1],
        z_opt=row[2],
        uuid=row[3] or "",
        title=row[4],
        kind=row[5] or 2,
        parent_folder=row[6],
        z_fok_parent_folder=row[7],
        creation_date=row[8],
        start_date=row[9],
        end_date=row[10],
        last_modified_date=row[11],
        trashed_state=row[12] or 0,
        cloud_delete_state=row[13] or 0,
        cloud_local_state=row[14] or 0,
        privacy_state=row[15] or 0,
        sync_event_order_key=row[16] or 0,
        search_index_rebuild_state=row[17] or 0,
        custom_sort_ascending=row[18] if row[18] is not None else 1,
        custom_sort_key=row[19] if row[19] is not None else 1,
        is_pinned=row[20] or 0,
        is_prototype=row[21] or 0,
        pending_items_count=row[22] or 0,
        pending_items_type=row[23] if row[23] is not None else 1,
        imported_by_bundle_id=row[24],
        cached_count=row[25] or 0,
        cached_photos_count=row[26] or 0,
        cached_videos_count=row[27] or 0,
    )


def get_album_memberships(conn: sqlite3.Connection) -> list[AlbumAsset]:
    """Get all album-asset memberships.

    Args:
        conn: SQLite connection

    Returns:
        List of AlbumAsset objects
    """
    cursor = conn.execute(
        """
        SELECT Z_33ALBUMS, Z_3ASSETS, Z_FOK_3ASSETS
        FROM Z_33ASSETS
        """
    )

    memberships = []
    for row in cursor.fetchall():
        memberships.append(AlbumAsset(
            album_pk=row[0],
            asset_pk=row[1],
            fok_asset=row[2],
        ))

    return memberships


def get_album_memberships_with_uuids(
    conn: sqlite3.Connection
) -> list[tuple[str, str]]:
    """Get all album-asset memberships with UUIDs.

    Args:
        conn: SQLite connection

    Returns:
        List of (album_uuid, asset_uuid) tuples
    """
    cursor = conn.execute(
        """
        SELECT G.ZUUID, A.ZUUID
        FROM Z_33ASSETS J
        JOIN ZGENERICALBUM G ON G.Z_PK = J.Z_33ALBUMS
        JOIN ZASSET A ON A.Z_PK = J.Z_3ASSETS
        WHERE G.ZKIND = 2 AND G.ZTRASHEDSTATE = 0 AND A.ZTRASHEDSTATE = 0
        """
    )

    return [(row[0], row[1]) for row in cursor.fetchall()]


def get_moment_by_date(
    conn: sqlite3.Connection,
    date_created: float
) -> Moment | None:
    """Find a moment that contains the given date.

    Args:
        conn: SQLite connection
        date_created: Core Data timestamp

    Returns:
        Moment object or None if not found
    """
    cursor = conn.execute(
        """
        SELECT Z_PK, Z_ENT, Z_OPT, ZUUID, ZSTARTDATE, ZENDDATE,
               ZREPRESENTATIVEDATE, ZAPPROXIMATELATITUDE, ZAPPROXIMATELONGITUDE,
               ZCACHEDCOUNT, ZCACHEDPHOTOSCOUNT, ZCACHEDVIDEOSCOUNT, ZTRASHEDSTATE
        FROM ZMOMENT
        WHERE ZSTARTDATE <= ? AND ZENDDATE >= ? AND ZTRASHEDSTATE = 0
        ORDER BY ZSTARTDATE DESC
        LIMIT 1
        """,
        (date_created, date_created)
    )
    row = cursor.fetchone()

    if row is None:
        return None

    return Moment(
        z_pk=row[0],
        z_ent=row[1],
        z_opt=row[2],
        uuid=row[3] or "",
        start_date=row[4] or 0.0,
        end_date=row[5] or 0.0,
        representative_date=row[6],
        approximate_latitude=row[7],
        approximate_longitude=row[8],
        cached_count=row[9] or 0,
        cached_photos_count=row[10] or 0,
        cached_videos_count=row[11] or 0,
        trashed_state=row[12] or 0,
    )


def get_asset_pk_by_uuid(conn: sqlite3.Connection, uuid: str) -> int | None:
    """Get asset Z_PK by UUID.

    Args:
        conn: SQLite connection
        uuid: Asset UUID

    Returns:
        Asset Z_PK or None if not found
    """
    cursor = conn.execute(
        "SELECT Z_PK FROM ZASSET WHERE ZUUID = ?",
        (uuid,)
    )
    row = cursor.fetchone()
    return row[0] if row else None


def get_album_pk_by_uuid(conn: sqlite3.Connection, uuid: str) -> int | None:
    """Get album Z_PK by UUID.

    Args:
        conn: SQLite connection
        uuid: Album UUID

    Returns:
        Album Z_PK or None if not found
    """
    cursor = conn.execute(
        "SELECT Z_PK FROM ZGENERICALBUM WHERE ZUUID = ?",
        (uuid,)
    )
    row = cursor.fetchone()
    return row[0] if row else None


def get_album_key_assets_with_uuids(
    conn: sqlite3.Connection
) -> list[tuple[str, str, int | None]]:
    """Get all album key assets with UUIDs.

    Args:
        conn: SQLite connection

    Returns:
        List of (album_uuid, asset_uuid, z_fok_3keyassets) tuples
    """
    cursor = conn.execute(
        """
        SELECT G.ZUUID, A.ZUUID, K.Z_FOK_3KEYASSETS
        FROM Z_32KEYASSETS K
        JOIN ZGENERICALBUM G ON G.Z_PK = K.Z_32ALBUMSBEINGKEYASSETS
        JOIN ZASSET A ON A.Z_PK = K.Z_3KEYASSETS
        WHERE G.ZKIND = 2 AND G.ZTRASHEDSTATE = 0 AND A.ZTRASHEDSTATE = 0
        """
    )

    return [(row[0], row[1], row[2]) for row in cursor.fetchall()]


def get_album_by_title(
    conn: sqlite3.Connection,
    title: str,
    kind: int = 2,
) -> Album | None:
    """Get an album by its title.

    Args:
        conn: SQLite connection
        title: Album title to search for
        kind: Album kind (2=album, 4000=folder)

    Returns:
        Album object or None if not found
    """
    cursor = conn.execute(
        """
        SELECT Z_PK, Z_ENT, Z_OPT, ZUUID, ZTITLE, ZKIND,
               ZPARENTFOLDER, Z_FOK_PARENTFOLDER, ZCREATIONDATE, ZSTARTDATE, ZENDDATE,
               ZLASTMODIFIEDDATE, ZTRASHEDSTATE,
               ZCLOUDDELETESTATE, ZCLOUDLOCALSTATE, ZPRIVACYSTATE,
               ZSYNCEVENTORDERKEY, ZSEARCHINDEXREBUILDSTATE,
               ZCUSTOMSORTASCENDING, ZCUSTOMSORTKEY,
               ZISPINNED, ZISPROTOTYPE, ZPENDINGITEMSCOUNT, ZPENDINGITEMSTYPE,
               ZIMPORTEDBYBUNDLEIDENTIFIER,
               ZCACHEDCOUNT, ZCACHEDPHOTOSCOUNT, ZCACHEDVIDEOSCOUNT
        FROM ZGENERICALBUM
        WHERE ZTITLE = ? AND ZKIND = ? AND ZTRASHEDSTATE = 0
        """,
        (title, kind)
    )
    row = cursor.fetchone()

    if row is None:
        return None

    return Album(
        z_pk=row[0],
        z_ent=row[1],
        z_opt=row[2],
        uuid=row[3] or "",
        title=row[4],
        kind=row[5] or 2,
        parent_folder=row[6],
        z_fok_parent_folder=row[7],
        creation_date=row[8],
        start_date=row[9],
        end_date=row[10],
        last_modified_date=row[11],
        trashed_state=row[12] or 0,
        cloud_delete_state=row[13] or 0,
        cloud_local_state=row[14] or 0,
        privacy_state=row[15] or 0,
        sync_event_order_key=row[16] or 0,
        search_index_rebuild_state=row[17] or 0,
        custom_sort_ascending=row[18] if row[18] is not None else 1,
        custom_sort_key=row[19] if row[19] is not None else 1,
        is_pinned=row[20] or 0,
        is_prototype=row[21] or 0,
        pending_items_count=row[22] or 0,
        pending_items_type=row[23] if row[23] is not None else 1,
        imported_by_bundle_id=row[24],
        cached_count=row[25] or 0,
        cached_photos_count=row[26] or 0,
        cached_videos_count=row[27] or 0,
    )


def get_album_assets_for_dedup(
    conn: sqlite3.Connection,
    album_pk: int,
) -> list[tuple[str, str, int, int, int, float]]:
    """Get assets in an album with fields needed for dedup detection.

    Args:
        conn: SQLite connection
        album_pk: Album Z_PK

    Returns:
        List of (uuid, original_filename, file_size, width, height, date_created) tuples.
        All fields except uuid and date_created come from ZADDITIONALASSETATTRIBUTES,
        falling back to ZASSET fields when not available.
    """
    cursor = conn.execute(
        """
        SELECT A.ZUUID, COALESCE(AA.ZORIGINALFILENAME, A.ZFILENAME),
               COALESCE(AA.ZORIGINALFILESIZE, 0),
               COALESCE(AA.ZORIGINALWIDTH, A.ZWIDTH),
               COALESCE(AA.ZORIGINALHEIGHT, A.ZHEIGHT),
               A.ZDATECREATED
        FROM Z_33ASSETS J
        JOIN ZASSET A ON A.Z_PK = J.Z_3ASSETS
        LEFT JOIN ZADDITIONALASSETATTRIBUTES AA ON AA.ZASSET = A.Z_PK
        WHERE J.Z_33ALBUMS = ? AND A.ZTRASHEDSTATE = 0
        ORDER BY COALESCE(AA.ZORIGINALFILENAME, A.ZFILENAME)
        """,
        (album_pk,)
    )
    return [(row[0], row[1], row[2], row[3], row[4], row[5]) for row in cursor.fetchall()]


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


def favourite_state(conn: sqlite3.Connection) -> dict:
    """Watermark for the favourite candidate query: global max mod-date (active)."""
    row = conn.execute(
        "SELECT COALESCE(MAX(ZMODIFICATIONDATE), 0.0) "
        "FROM ZASSET WHERE ZTRASHEDSTATE = 0"
    ).fetchone()
    return {"max_mod_date": row[0]}


def favourite_set_summary(conn: sqlite3.Connection) -> tuple[int, int]:
    """(count, uuid_checksum) over active favourites — UUID-based, cross-library.

    The uuid_checksum is SUM(CRC32(uuid)), which is a heuristic — it is not
    collision-proof (two different favourite sets could share the same sum).
    Use ``--full`` as the deterministic fallback when precise verification
    is required.
    """
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


def album_defs_invariant(conn: sqlite3.Connection) -> dict:
    """Cheap summary of album definitions (ZGENERICALBUM)."""
    row = conn.execute(
        "SELECT COUNT(*), COALESCE(MAX(ZLASTMODIFIEDDATE), 0.0) "
        "FROM ZGENERICALBUM WHERE ZTRASHEDSTATE = 0"
    ).fetchone()
    return {
        "album_zmax": get_current_max_pk(conn, "GenericAlbum"),
        "active_count": row[0],
        "mod_max": row[1],
    }


__all__ = [
    "get_all_asset_uuids",
    "get_asset_by_uuid",
    "get_assets_by_uuids",
    "get_additional_attributes",
    "get_extended_attributes",
    "get_internal_resources",
    "get_all_albums",
    "get_album_by_uuid",
    "get_album_memberships",
    "get_album_memberships_with_uuids",
    "get_moment_by_date",
    "get_asset_pk_by_uuid",
    "get_album_pk_by_uuid",
    "get_album_key_assets_with_uuids",
    "get_album_by_title",
    "get_album_assets_for_dedup",
    "album_defs_invariant",
    "asset_invariant",
    "fetch_assets_added_since",
    "fetch_assets_trashed_since",
    "membership_invariant",
    "fetch_memberships_added_since",
    "favourite_state",
    "favourite_set_summary",
    "fetch_favourite_candidates_since",
]
