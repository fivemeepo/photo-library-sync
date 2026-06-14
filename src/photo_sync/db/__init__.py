"""Database operations for photo library sync."""

from photo_sync.db.connection import connect_readonly, connect_readwrite, connect_with_retry
from photo_sync.db.mutations import (
    delete_album_membership,
    insert_album,
    insert_album_membership,
    insert_asset,
    update_asset_trashed_state,
)
from photo_sync.db.pk_manager import get_next_pk
from photo_sync.db.queries import (
    get_album_memberships,
    get_all_albums,
    get_all_asset_uuids,
    get_asset_by_uuid,
)

__all__ = [
    "connect_readonly",
    "connect_readwrite",
    "connect_with_retry",
    "get_next_pk",
    "get_all_asset_uuids",
    "get_asset_by_uuid",
    "get_all_albums",
    "get_album_memberships",
    "insert_asset",
    "update_asset_trashed_state",
    "insert_album",
    "insert_album_membership",
    "delete_album_membership",
]
