"""SQL mutation functions for writing to Photos.sqlite.

All functions in this module modify the database.
"""

from __future__ import annotations

import logging
import sqlite3

from lib.core_data import core_data_now
from photo_sync.db.pk_manager import (
    ENTITY_ADDITIONAL_ASSET_ATTRIBUTES,
    ENTITY_ASSET,
    ENTITY_EXTENDED_ATTRIBUTES,
    ENTITY_GENERIC_ALBUM,
    ENTITY_INTERNAL_RESOURCE,
    ENTITY_MOMENT,
    get_next_pk,
)
from photo_sync.models import (
    AdditionalAssetAttributes,
    Album,
    Asset,
    ExtendedAttributes,
    InternalResource,
    Moment,
)

logger = logging.getLogger(__name__)


def insert_asset(conn: sqlite3.Connection, asset: Asset) -> int:
    """Insert a new asset into ZASSET.

    DEPRECATED: Use insert_asset_from_row() for full field sync.

    Args:
        conn: SQLite connection (read-write)
        asset: Asset object to insert

    Returns:
        The Z_PK of the inserted asset
    """
    new_pk = get_next_pk(conn, ENTITY_ASSET)

    conn.execute(
        """
        INSERT INTO ZASSET (
            Z_PK, Z_ENT, Z_OPT, ZUUID, ZFILENAME, ZDIRECTORY,
            ZKIND, ZWIDTH, ZHEIGHT, ZORIENTATION, ZDURATION,
            ZDATECREATED, ZADDEDDATE, ZMODIFICATIONDATE,
            ZTRASHEDSTATE, ZTRASHEDDATE, ZFAVORITE, ZHIDDEN,
            ZVISIBILITYSTATE, ZCOMPLETE, ZUNIFORMTYPEIDENTIFIER,
            ZPLAYBACKSTYLE, ZSAVEDASSETTYPE,
            ZADDITIONALATTRIBUTES, ZEXTENDEDATTRIBUTES, ZMOMENT
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            new_pk, asset.z_ent, asset.z_opt, asset.uuid, asset.filename, asset.directory,
            asset.kind, asset.width, asset.height, asset.orientation, asset.duration,
            asset.date_created, asset.added_date, asset.modification_date,
            asset.trashed_state, asset.trashed_date, asset.favorite, asset.hidden,
            asset.visibility_state, asset.complete, asset.uniform_type_identifier,
            asset.playback_style, asset.saved_asset_type,
            asset.additional_attributes, asset.extended_attributes, asset.moment
        )
    )

    logger.debug(f"Inserted asset {asset.uuid} with PK {new_pk}")
    return new_pk


def insert_asset_from_row(
    target_conn: sqlite3.Connection,
    source_conn: sqlite3.Connection,
    source_asset_pk: int,
    moment_pk: int | None = None,
    added_date: float | None = None
) -> int:
    """Insert an asset by copying all fields from source row.

    This copies ALL columns from the source asset, ensuring complete data sync.
    Only Z_PK is regenerated; ZMOMENT and ZADDEDDATE can be overridden.

    Args:
        target_conn: Connection to target database (read-write)
        source_conn: Connection to source database (read-only)
        source_asset_pk: Z_PK of the asset in source database
        moment_pk: Optional moment Z_PK in target (will be set after creation)
        added_date: Optional override for ZADDEDDATE (defaults to current time)

    Returns:
        The Z_PK of the inserted asset
    """
    # Get column names (excluding Z_PK which we regenerate)
    cursor = target_conn.execute("PRAGMA table_info(ZASSET)")
    all_columns = [row[1] for row in cursor.fetchall()]
    copy_columns = [c for c in all_columns if c != "Z_PK"]

    # Fetch source row
    columns_str = ", ".join(copy_columns)
    cursor = source_conn.execute(
        f"SELECT {columns_str} FROM ZASSET WHERE Z_PK = ?",
        (source_asset_pk,)
    )
    source_row = cursor.fetchone()
    if not source_row:
        raise ValueError(f"Asset not found in source: Z_PK={source_asset_pk}")

    # Build values list with overrides
    values = []
    new_pk = get_next_pk(target_conn, ENTITY_ASSET)

    for i, col in enumerate(copy_columns):
        if col == "ZMOMENT" and moment_pk is not None:
            values.append(moment_pk)
        elif col == "ZADDEDDATE" and added_date is not None:
            values.append(added_date)
        elif col == "Z_OPT":
            values.append(1)  # Reset optimistic lock
        elif col == "ZTRASHEDSTATE":
            values.append(0)  # Ensure not trashed
        elif col == "ZTRASHEDDATE":
            values.append(None)  # Clear trashed date
        elif col in ("ZADDITIONALATTRIBUTES", "ZEXTENDEDATTRIBUTES"):
            values.append(None)  # FK refs will be updated after insert
        else:
            values.append(source_row[i])

    # Insert with new PK
    placeholders = ", ".join("?" * (len(copy_columns) + 1))
    insert_columns = "Z_PK, " + columns_str
    target_conn.execute(
        f"INSERT INTO ZASSET ({insert_columns}) VALUES ({placeholders})",
        [new_pk] + values
    )

    logger.debug(f"Inserted asset from source PK {source_asset_pk} with new PK {new_pk}")
    return new_pk


def insert_additional_attributes(
    conn: sqlite3.Connection,
    attrs: AdditionalAssetAttributes,
    asset_pk: int
) -> int:
    """Insert additional attributes for an asset.

    Args:
        conn: SQLite connection (read-write)
        attrs: AdditionalAssetAttributes object
        asset_pk: Z_PK of the associated asset

    Returns:
        The Z_PK of the inserted record
    """
    new_pk = get_next_pk(conn, ENTITY_ADDITIONAL_ASSET_ATTRIBUTES)

    conn.execute(
        """
        INSERT INTO ZADDITIONALASSETATTRIBUTES (
            Z_PK, Z_ENT, Z_OPT, ZASSET,
            ZORIGINALFILENAME, ZORIGINALFILESIZE,
            ZORIGINALWIDTH, ZORIGINALHEIGHT,
            ZIMPORTEDBYBUNDLEIDENTIFIER, ZIMPORTEDBYDISPLAYNAME,
            ZTIMEZONENAME, ZTIMEZONEOFFSET, ZREVERSELOCATIONDATA
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            new_pk, attrs.z_ent, attrs.z_opt, asset_pk,
            attrs.original_filename, attrs.original_filesize,
            attrs.original_width, attrs.original_height,
            attrs.imported_by_bundle_id, attrs.imported_by_display_name,
            attrs.timezone_name, attrs.timezone_offset, attrs.reverse_location_data
        )
    )

    logger.debug(f"Inserted additional attributes with PK {new_pk} for asset {asset_pk}")
    return new_pk


def insert_additional_attributes_from_row(
    target_conn: sqlite3.Connection,
    source_conn: sqlite3.Connection,
    source_asset_pk: int,
    target_asset_pk: int
) -> int | None:
    """Insert additional attributes by copying all fields from source.

    Args:
        target_conn: Connection to target database (read-write)
        source_conn: Connection to source database (read-only)
        source_asset_pk: Z_PK of the asset in source database
        target_asset_pk: Z_PK of the asset in target database

    Returns:
        The Z_PK of the inserted record, or None if source has no additional attributes
    """
    # Get column names
    cursor = target_conn.execute("PRAGMA table_info(ZADDITIONALASSETATTRIBUTES)")
    all_columns = [row[1] for row in cursor.fetchall()]
    copy_columns = [c for c in all_columns if c != "Z_PK"]

    # Fetch source row by asset PK
    columns_str = ", ".join(copy_columns)
    cursor = source_conn.execute(
        f"SELECT {columns_str} FROM ZADDITIONALASSETATTRIBUTES WHERE ZASSET = ?",
        (source_asset_pk,)
    )
    source_row = cursor.fetchone()
    if not source_row:
        return None

    # Build values list
    values = []
    new_pk = get_next_pk(target_conn, ENTITY_ADDITIONAL_ASSET_ATTRIBUTES)

    for i, col in enumerate(copy_columns):
        if col == "ZASSET":
            values.append(target_asset_pk)
        elif col == "Z_OPT":
            values.append(1)
        else:
            values.append(source_row[i])

    # Insert
    placeholders = ", ".join("?" * (len(copy_columns) + 1))
    insert_columns = "Z_PK, " + columns_str
    target_conn.execute(
        f"INSERT INTO ZADDITIONALASSETATTRIBUTES ({insert_columns}) VALUES ({placeholders})",
        [new_pk] + values
    )

    logger.debug(f"Inserted additional attributes from source asset {source_asset_pk} with PK {new_pk}")
    return new_pk


def insert_extended_attributes(
    conn: sqlite3.Connection,
    attrs: ExtendedAttributes,
    asset_pk: int
) -> int:
    """Insert extended attributes for an asset.

    Args:
        conn: SQLite connection (read-write)
        attrs: ExtendedAttributes object
        asset_pk: Z_PK of the associated asset

    Returns:
        The Z_PK of the inserted record
    """
    new_pk = get_next_pk(conn, ENTITY_EXTENDED_ATTRIBUTES)

    conn.execute(
        """
        INSERT INTO ZEXTENDEDATTRIBUTES (Z_PK, Z_ENT, Z_OPT, ZASSET)
        VALUES (?, ?, ?, ?)
        """,
        (new_pk, attrs.z_ent, attrs.z_opt, asset_pk)
    )

    logger.debug(f"Inserted extended attributes with PK {new_pk} for asset {asset_pk}")
    return new_pk


def insert_extended_attributes_from_row(
    target_conn: sqlite3.Connection,
    source_conn: sqlite3.Connection,
    source_asset_pk: int,
    target_asset_pk: int
) -> int | None:
    """Insert extended attributes by copying all fields from source.

    Args:
        target_conn: Connection to target database (read-write)
        source_conn: Connection to source database (read-only)
        source_asset_pk: Z_PK of the asset in source database
        target_asset_pk: Z_PK of the asset in target database

    Returns:
        The Z_PK of the inserted record, or None if source has no extended attributes
    """
    # Get column names
    cursor = target_conn.execute("PRAGMA table_info(ZEXTENDEDATTRIBUTES)")
    all_columns = [row[1] for row in cursor.fetchall()]
    copy_columns = [c for c in all_columns if c != "Z_PK"]

    # Fetch source row by asset PK
    columns_str = ", ".join(copy_columns)
    cursor = source_conn.execute(
        f"SELECT {columns_str} FROM ZEXTENDEDATTRIBUTES WHERE ZASSET = ?",
        (source_asset_pk,)
    )
    source_row = cursor.fetchone()
    if not source_row:
        return None

    # Build values list
    values = []
    new_pk = get_next_pk(target_conn, ENTITY_EXTENDED_ATTRIBUTES)

    for i, col in enumerate(copy_columns):
        if col == "ZASSET":
            values.append(target_asset_pk)
        elif col == "Z_OPT":
            values.append(1)
        else:
            values.append(source_row[i])

    # Insert
    placeholders = ", ".join("?" * (len(copy_columns) + 1))
    insert_columns = "Z_PK, " + columns_str
    target_conn.execute(
        f"INSERT INTO ZEXTENDEDATTRIBUTES ({insert_columns}) VALUES ({placeholders})",
        [new_pk] + values
    )

    logger.debug(f"Inserted extended attributes from source asset {source_asset_pk} with PK {new_pk}")
    return new_pk


def insert_internal_resource(
    conn: sqlite3.Connection,
    resource: InternalResource,
    asset_pk: int
) -> int:
    """Insert an internal resource for an asset.

    Args:
        conn: SQLite connection (read-write)
        resource: InternalResource object
        asset_pk: Z_PK of the associated asset

    Returns:
        The Z_PK of the inserted record
    """
    new_pk = get_next_pk(conn, ENTITY_INTERNAL_RESOURCE)

    conn.execute(
        """
        INSERT INTO ZINTERNALRESOURCE (
            Z_PK, Z_ENT, Z_OPT, ZASSET,
            ZRESOURCETYPE, ZDATALENGTH, ZLOCALAVAILABILITY, ZFINGERPRINT
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            new_pk, resource.z_ent, resource.z_opt, asset_pk,
            resource.resource_type, resource.data_length,
            resource.local_availability, resource.fingerprint
        )
    )

    logger.debug(f"Inserted internal resource with PK {new_pk} for asset {asset_pk}")
    return new_pk


def insert_internal_resources_from_row(
    target_conn: sqlite3.Connection,
    source_conn: sqlite3.Connection,
    source_asset_pk: int,
    target_asset_pk: int
) -> list[int]:
    """Insert internal resources by copying all fields from source.

    Args:
        target_conn: Connection to target database (read-write)
        source_conn: Connection to source database (read-only)
        source_asset_pk: Z_PK of the asset in source database
        target_asset_pk: Z_PK of the asset in target database

    Returns:
        List of Z_PKs of the inserted records
    """
    # Get column names
    cursor = target_conn.execute("PRAGMA table_info(ZINTERNALRESOURCE)")
    all_columns = [row[1] for row in cursor.fetchall()]
    copy_columns = [c for c in all_columns if c != "Z_PK"]

    # Fetch all source rows by asset PK
    columns_str = ", ".join(copy_columns)
    cursor = source_conn.execute(
        f"SELECT {columns_str} FROM ZINTERNALRESOURCE WHERE ZASSET = ?",
        (source_asset_pk,)
    )
    source_rows = cursor.fetchall()

    inserted_pks = []
    for source_row in source_rows:
        # Build values list
        values = []
        new_pk = get_next_pk(target_conn, ENTITY_INTERNAL_RESOURCE)

        for i, col in enumerate(copy_columns):
            if col == "ZASSET":
                values.append(target_asset_pk)
            elif col == "Z_OPT":
                values.append(1)
            else:
                values.append(source_row[i])

        # Insert
        placeholders = ", ".join("?" * (len(copy_columns) + 1))
        insert_columns = "Z_PK, " + columns_str
        target_conn.execute(
            f"INSERT INTO ZINTERNALRESOURCE ({insert_columns}) VALUES ({placeholders})",
            [new_pk] + values
        )
        inserted_pks.append(new_pk)

    logger.debug(f"Inserted {len(inserted_pks)} internal resources from source asset {source_asset_pk}")
    return inserted_pks


def update_asset_trashed_state(
    conn: sqlite3.Connection,
    uuid: str,
    trashed_state: int
) -> bool:
    """Update the trashed state of an asset.

    Args:
        conn: SQLite connection (read-write)
        uuid: Asset UUID
        trashed_state: New trashed state (0=active, 1=trashed)

    Returns:
        True if update succeeded, False if asset not found
    """
    trashed_date = core_data_now() if trashed_state == 1 else None

    result = conn.execute(
        """
        UPDATE ZASSET
        SET ZTRASHEDSTATE = ?, ZTRASHEDDATE = ?, Z_OPT = Z_OPT + 1
        WHERE ZUUID = ?
        """,
        (trashed_state, trashed_date, uuid)
    )

    if result.rowcount > 0:
        logger.debug(f"Updated trashed state for asset {uuid} to {trashed_state}")
        return True
    return False


def update_asset_fks(
    conn: sqlite3.Connection,
    asset_pk: int,
    additional_attrs_pk: int | None = None,
    extended_attrs_pk: int | None = None,
    moment_pk: int | None = None
) -> bool:
    """Update foreign key references in an asset.

    Args:
        conn: SQLite connection (read-write)
        asset_pk: Asset Z_PK
        additional_attrs_pk: Z_PK of additional attributes
        extended_attrs_pk: Z_PK of extended attributes
        moment_pk: Z_PK of moment

    Returns:
        True if update succeeded
    """
    updates = []
    params = []

    if additional_attrs_pk is not None:
        updates.append("ZADDITIONALATTRIBUTES = ?")
        params.append(additional_attrs_pk)

    if extended_attrs_pk is not None:
        updates.append("ZEXTENDEDATTRIBUTES = ?")
        params.append(extended_attrs_pk)

    if moment_pk is not None:
        updates.append("ZMOMENT = ?")
        params.append(moment_pk)

    if not updates:
        return True

    params.append(asset_pk)
    result = conn.execute(
        f"UPDATE ZASSET SET {', '.join(updates)} WHERE Z_PK = ?",
        params
    )

    return result.rowcount > 0


def insert_album(conn: sqlite3.Connection, album: Album) -> int:
    """Insert a new album into ZGENERICALBUM.

    DEPRECATED: Use insert_album_from_row() for full field sync.

    Args:
        conn: SQLite connection (read-write)
        album: Album object to insert

    Returns:
        The Z_PK of the inserted album
    """
    new_pk = get_next_pk(conn, ENTITY_GENERIC_ALBUM)

    conn.execute(
        """
        INSERT INTO ZGENERICALBUM (
            Z_PK, Z_ENT, Z_OPT, ZUUID, ZTITLE, ZKIND,
            ZPARENTFOLDER, Z_FOK_PARENTFOLDER, ZCREATIONDATE, ZSTARTDATE, ZENDDATE,
            ZLASTMODIFIEDDATE, ZTRASHEDSTATE,
            ZCLOUDDELETESTATE, ZCLOUDLOCALSTATE, ZPRIVACYSTATE,
            ZSYNCEVENTORDERKEY, ZSEARCHINDEXREBUILDSTATE,
            ZCUSTOMSORTASCENDING, ZCUSTOMSORTKEY,
            ZISPINNED, ZISPROTOTYPE, ZPENDINGITEMSCOUNT, ZPENDINGITEMSTYPE,
            ZIMPORTEDBYBUNDLEIDENTIFIER,
            ZCACHEDCOUNT, ZCACHEDPHOTOSCOUNT, ZCACHEDVIDEOSCOUNT
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            new_pk, album.z_ent, album.z_opt, album.uuid, album.title, album.kind,
            album.parent_folder, album.z_fok_parent_folder,
            album.creation_date, album.start_date, album.end_date, album.last_modified_date,
            album.trashed_state,
            album.cloud_delete_state, album.cloud_local_state, album.privacy_state,
            album.sync_event_order_key, album.search_index_rebuild_state,
            album.custom_sort_ascending, album.custom_sort_key,
            album.is_pinned, album.is_prototype, album.pending_items_count, album.pending_items_type,
            album.imported_by_bundle_id,
            album.cached_count, album.cached_photos_count, album.cached_videos_count
        )
    )

    logger.debug(f"Inserted album {album.uuid} with PK {new_pk}")
    return new_pk


def insert_album_from_row(
    target_conn: sqlite3.Connection,
    source_conn: sqlite3.Connection,
    source_album_pk: int,
    parent_folder_pk: int | None = None
) -> int:
    """Insert an album by copying all fields from source row.

    This copies ALL columns from the source album, ensuring complete data sync.
    Only Z_PK is regenerated and ZPARENTFOLDER can be remapped.

    Args:
        target_conn: Connection to target database (read-write)
        source_conn: Connection to source database (read-only)
        source_album_pk: Z_PK of the album in source database
        parent_folder_pk: Optional remapped parent folder Z_PK in target

    Returns:
        The Z_PK of the inserted album
    """
    # Get column names (excluding Z_PK which we regenerate)
    cursor = target_conn.execute("PRAGMA table_info(ZGENERICALBUM)")
    all_columns = [row[1] for row in cursor.fetchall()]
    copy_columns = [c for c in all_columns if c != "Z_PK"]

    # Fetch source row
    columns_str = ", ".join(copy_columns)
    cursor = source_conn.execute(
        f"SELECT {columns_str} FROM ZGENERICALBUM WHERE Z_PK = ?",
        (source_album_pk,)
    )
    source_row = cursor.fetchone()
    if not source_row:
        raise ValueError(f"Album not found in source: Z_PK={source_album_pk}")

    # Build values list, remapping parent folder if needed
    values = []
    new_pk = get_next_pk(target_conn, ENTITY_GENERIC_ALBUM)

    for i, col in enumerate(copy_columns):
        if col == "ZPARENTFOLDER" and parent_folder_pk is not None:
            values.append(parent_folder_pk)
        elif col == "Z_OPT":
            values.append(1)  # Reset optimistic lock
        else:
            values.append(source_row[i])

    # Insert with new PK
    placeholders = ", ".join("?" * (len(copy_columns) + 1))
    insert_columns = "Z_PK, " + columns_str
    target_conn.execute(
        f"INSERT INTO ZGENERICALBUM ({insert_columns}) VALUES ({placeholders})",
        [new_pk] + values
    )

    logger.debug(f"Inserted album from source PK {source_album_pk} with new PK {new_pk}")
    return new_pk


def insert_album_membership(
    conn: sqlite3.Connection,
    album_pk: int,
    asset_pk: int
) -> bool:
    """Insert an album-asset membership.

    Args:
        conn: SQLite connection (read-write)
        album_pk: Album Z_PK
        asset_pk: Asset Z_PK

    Returns:
        True if insert succeeded
    """
    try:
        conn.execute(
            """
            INSERT INTO Z_33ASSETS (Z_33ALBUMS, Z_3ASSETS)
            VALUES (?, ?)
            """,
            (album_pk, asset_pk)
        )
        logger.debug(f"Inserted album membership: album={album_pk}, asset={asset_pk}")
        return True
    except sqlite3.IntegrityError:
        # Already exists
        logger.debug(f"Album membership already exists: album={album_pk}, asset={asset_pk}")
        return False


def delete_album_membership(
    conn: sqlite3.Connection,
    album_pk: int,
    asset_pk: int
) -> bool:
    """Delete an album-asset membership.

    Args:
        conn: SQLite connection (read-write)
        album_pk: Album Z_PK
        asset_pk: Asset Z_PK

    Returns:
        True if delete succeeded
    """
    result = conn.execute(
        """
        DELETE FROM Z_33ASSETS
        WHERE Z_33ALBUMS = ? AND Z_3ASSETS = ?
        """,
        (album_pk, asset_pk)
    )

    if result.rowcount > 0:
        logger.debug(f"Deleted album membership: album={album_pk}, asset={asset_pk}")
        return True
    return False


def update_album_cached_counts(conn: sqlite3.Connection, album_pk: int) -> bool:
    """Update cached counts for an album.

    Args:
        conn: SQLite connection (read-write)
        album_pk: Album Z_PK

    Returns:
        True if update succeeded
    """
    # Count photos and videos in the album
    cursor = conn.execute(
        """
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN A.ZKIND = 0 THEN 1 ELSE 0 END) as photos,
            SUM(CASE WHEN A.ZKIND = 1 THEN 1 ELSE 0 END) as videos
        FROM Z_33ASSETS J
        JOIN ZASSET A ON A.Z_PK = J.Z_3ASSETS
        WHERE J.Z_33ALBUMS = ? AND A.ZTRASHEDSTATE = 0
        """,
        (album_pk,)
    )
    row = cursor.fetchone()

    total = row[0] or 0
    photos = row[1] or 0
    videos = row[2] or 0

    result = conn.execute(
        """
        UPDATE ZGENERICALBUM
        SET ZCACHEDCOUNT = ?, ZCACHEDPHOTOSCOUNT = ?, ZCACHEDVIDEOSCOUNT = ?,
            Z_OPT = Z_OPT + 1
        WHERE Z_PK = ?
        """,
        (total, photos, videos, album_pk)
    )

    logger.debug(f"Updated album {album_pk} counts: total={total}, photos={photos}, videos={videos}")
    return result.rowcount > 0


def insert_moment(conn: sqlite3.Connection, moment: Moment) -> int:
    """Insert a new moment into ZMOMENT.

    Args:
        conn: SQLite connection (read-write)
        moment: Moment object to insert

    Returns:
        The Z_PK of the inserted moment
    """
    new_pk = get_next_pk(conn, ENTITY_MOMENT)

    conn.execute(
        """
        INSERT INTO ZMOMENT (
            Z_PK, Z_ENT, Z_OPT, ZUUID, ZSTARTDATE, ZENDDATE,
            ZREPRESENTATIVEDATE, ZAPPROXIMATELATITUDE, ZAPPROXIMATELONGITUDE,
            ZCACHEDCOUNT, ZCACHEDPHOTOSCOUNT, ZCACHEDVIDEOSCOUNT, ZTRASHEDSTATE
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            new_pk, moment.z_ent, moment.z_opt, moment.uuid,
            moment.start_date, moment.end_date, moment.representative_date,
            moment.approximate_latitude, moment.approximate_longitude,
            moment.cached_count, moment.cached_photos_count,
            moment.cached_videos_count, moment.trashed_state
        )
    )

    logger.debug(f"Inserted moment {moment.uuid} with PK {new_pk}")
    return new_pk


def update_moment_cached_counts(conn: sqlite3.Connection, moment_pk: int) -> bool:
    """Update cached counts for a moment.

    Args:
        conn: SQLite connection (read-write)
        moment_pk: Moment Z_PK

    Returns:
        True if update succeeded
    """
    cursor = conn.execute(
        """
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN ZKIND = 0 THEN 1 ELSE 0 END) as photos,
            SUM(CASE WHEN ZKIND = 1 THEN 1 ELSE 0 END) as videos
        FROM ZASSET
        WHERE ZMOMENT = ? AND ZTRASHEDSTATE = 0
        """,
        (moment_pk,)
    )
    row = cursor.fetchone()

    total = row[0] or 0
    photos = row[1] or 0
    videos = row[2] or 0

    result = conn.execute(
        """
        UPDATE ZMOMENT
        SET ZCACHEDCOUNT = ?, ZCACHEDPHOTOSCOUNT = ?, ZCACHEDVIDEOSCOUNT = ?,
            Z_OPT = Z_OPT + 1
        WHERE Z_PK = ?
        """,
        (total, photos, videos, moment_pk)
    )

    return result.rowcount > 0


def insert_album_key_asset(
    conn: sqlite3.Connection,
    album_pk: int,
    asset_pk: int,
    fok_asset: int | None = None
) -> bool:
    """Insert an album key asset (used for album thumbnail).

    Args:
        conn: SQLite connection (read-write)
        album_pk: Album Z_PK (Z_32ALBUMSBEINGKEYASSETS)
        asset_pk: Asset Z_PK (Z_3KEYASSETS)
        fok_asset: Optional Z_FOK_3KEYASSETS value

    Returns:
        True if insert succeeded
    """
    try:
        conn.execute(
            """
            INSERT INTO Z_32KEYASSETS (Z_32ALBUMSBEINGKEYASSETS, Z_3KEYASSETS, Z_FOK_3KEYASSETS)
            VALUES (?, ?, ?)
            """,
            (album_pk, asset_pk, fok_asset)
        )
        logger.debug(f"Inserted album key asset: album={album_pk}, asset={asset_pk}")
        return True
    except sqlite3.IntegrityError:
        logger.debug(f"Album key asset already exists: album={album_pk}, asset={asset_pk}")
        return False


def delete_album_key_assets(conn: sqlite3.Connection, album_pk: int) -> int:
    """Delete all key assets for an album.

    Args:
        conn: SQLite connection (read-write)
        album_pk: Album Z_PK

    Returns:
        Number of rows deleted
    """
    result = conn.execute(
        "DELETE FROM Z_32KEYASSETS WHERE Z_32ALBUMSBEINGKEYASSETS = ?",
        (album_pk,)
    )
    logger.debug(f"Deleted {result.rowcount} key assets for album {album_pk}")
    return result.rowcount


__all__ = [
    "insert_asset",
    "insert_asset_from_row",
    "insert_additional_attributes",
    "insert_additional_attributes_from_row",
    "insert_extended_attributes",
    "insert_extended_attributes_from_row",
    "insert_internal_resource",
    "insert_internal_resources_from_row",
    "update_asset_trashed_state",
    "update_asset_fks",
    "insert_album",
    "insert_album_from_row",
    "insert_album_membership",
    "delete_album_membership",
    "update_album_cached_counts",
    "insert_moment",
    "update_moment_cached_counts",
    "insert_album_key_asset",
    "delete_album_key_assets",
]
