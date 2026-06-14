"""Tests for identify_new_photos / identify_deleted_photos UUID caching."""

from unittest.mock import MagicMock, patch

from photo_sync.models import Asset
from photo_sync.operations.photo_sync import (
    fetch_asset_uuid_sets,
    identify_deleted_photos,
    identify_new_photos,
)

MODULE = "photo_sync.operations.photo_sync"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_asset(uuid: str) -> Asset:
    return Asset(z_pk=1, uuid=uuid, filename=f"{uuid}.jpg")


def _fake_get_all_asset_uuids(conn, *, include_trashed=False):
    """Return the set stashed on the mock connection."""
    return conn._uuid_set


def _conns(source_uuids: set[str], target_uuids: set[str]):
    """Build two mock connections carrying UUID sets."""
    src = MagicMock()
    src._uuid_set = source_uuids
    tgt = MagicMock()
    tgt._uuid_set = target_uuids
    return src, tgt


# ---------------------------------------------------------------------------
# fetch_asset_uuid_sets
# ---------------------------------------------------------------------------

@patch(f"{MODULE}.get_all_asset_uuids", side_effect=_fake_get_all_asset_uuids)
def test_fetch_asset_uuid_sets(mock_get):
    src, tgt = _conns({"A", "B"}, {"B", "C"})
    s, t = fetch_asset_uuid_sets(src, tgt)
    assert s == {"A", "B"}
    assert t == {"B", "C"}
    assert mock_get.call_count == 2


# ---------------------------------------------------------------------------
# identify_new_photos — with pre-fetched UUIDs (no extra query)
# ---------------------------------------------------------------------------

@patch(f"{MODULE}.get_assets_by_uuids")
@patch(f"{MODULE}.get_all_asset_uuids")
def test_new_photos_with_prefetched_uuids(mock_get_uuids, mock_get_assets):
    src, tgt = _conns(set(), set())
    asset_a = _make_asset("A")
    mock_get_assets.return_value = [asset_a]

    result = identify_new_photos(
        src, tgt, source_uuids={"A", "B"}, target_uuids={"B"},
    )

    # Should NOT call get_all_asset_uuids when sets are provided
    mock_get_uuids.assert_not_called()
    # Should fetch details for the new UUID "A"
    mock_get_assets.assert_called_once()
    uuids_arg = mock_get_assets.call_args[0][1]
    assert set(uuids_arg) == {"A"}
    assert result == [asset_a]


# ---------------------------------------------------------------------------
# identify_new_photos — without pre-fetched UUIDs (falls back to query)
# ---------------------------------------------------------------------------

@patch(f"{MODULE}.get_assets_by_uuids")
@patch(f"{MODULE}.get_all_asset_uuids", side_effect=_fake_get_all_asset_uuids)
def test_new_photos_without_prefetched_uuids(mock_get_uuids, mock_get_assets):
    src, tgt = _conns({"A", "B"}, {"B"})
    asset_a = _make_asset("A")
    mock_get_assets.return_value = [asset_a]

    result = identify_new_photos(src, tgt)

    assert mock_get_uuids.call_count == 2
    assert result == [asset_a]


# ---------------------------------------------------------------------------
# identify_new_photos — no diff → empty list
# ---------------------------------------------------------------------------

@patch(f"{MODULE}.get_assets_by_uuids")
def test_new_photos_none_new(mock_get_assets):
    src, tgt = MagicMock(), MagicMock()
    result = identify_new_photos(
        src, tgt, source_uuids={"A"}, target_uuids={"A"},
    )
    assert result == []
    mock_get_assets.assert_not_called()


# ---------------------------------------------------------------------------
# identify_deleted_photos — with pre-fetched UUIDs
# ---------------------------------------------------------------------------

@patch(f"{MODULE}.get_all_asset_uuids")
def test_deleted_photos_with_prefetched_uuids(mock_get_uuids):
    src, tgt = MagicMock(), MagicMock()
    result = identify_deleted_photos(
        src, tgt, source_uuids={"A"}, target_uuids={"A", "B", "C"},
    )

    mock_get_uuids.assert_not_called()
    assert set(result) == {"B", "C"}


# ---------------------------------------------------------------------------
# identify_deleted_photos — without pre-fetched UUIDs (falls back)
# ---------------------------------------------------------------------------

@patch(f"{MODULE}.get_all_asset_uuids", side_effect=_fake_get_all_asset_uuids)
def test_deleted_photos_without_prefetched_uuids(mock_get_uuids):
    src, tgt = _conns({"A"}, {"A", "B"})
    result = identify_deleted_photos(src, tgt)

    assert mock_get_uuids.call_count == 2
    assert set(result) == {"B"}


# ---------------------------------------------------------------------------
# identify_deleted_photos — no diff → empty list
# ---------------------------------------------------------------------------

def test_deleted_photos_none_deleted():
    src, tgt = MagicMock(), MagicMock()
    result = identify_deleted_photos(
        src, tgt, source_uuids={"A", "B"}, target_uuids={"A", "B"},
    )
    assert result == []


# ---------------------------------------------------------------------------
# Partial pre-fetch: only one set provided → still fetches both
# ---------------------------------------------------------------------------

@patch(f"{MODULE}.get_assets_by_uuids", return_value=[])
@patch(f"{MODULE}.get_all_asset_uuids", side_effect=_fake_get_all_asset_uuids)
def test_partial_prefetch_source_only(mock_get_uuids, mock_get_assets):
    """If only source_uuids is provided but target_uuids is None, re-fetch both."""
    src, tgt = _conns({"X"}, {"X"})
    result = identify_new_photos(src, tgt, source_uuids={"A"}, target_uuids=None)

    # Falls back because target_uuids is None
    assert mock_get_uuids.call_count == 2
    assert result == []


@patch(f"{MODULE}.get_all_asset_uuids", side_effect=_fake_get_all_asset_uuids)
def test_partial_prefetch_target_only(mock_get_uuids):
    """If only target_uuids is provided but source_uuids is None, re-fetch both."""
    src, tgt = _conns({"X"}, {"X"})
    result = identify_deleted_photos(src, tgt, source_uuids=None, target_uuids={"A"})

    assert mock_get_uuids.call_count == 2
    assert result == []
