"""The derivative backfill must run once per target, not on every sync.

Backfill repairs libraries synced before thumbnail-copying existed. It is a
one-time migration: new photos get their thumbnails via the new-photo path, so
once a target has been fully backfilled there is nothing left to repair. A
marker inside the target bundle records completion so subsequent syncs skip the
whole-library rescan.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from photo_sync import sync as sync_mod
from photo_sync.models.sync_result import SyncResult
from photo_sync.operations.file_copy import (
    is_derivatives_backfilled,
    mark_derivatives_backfilled,
)

MODULE = sync_mod.__name__


# --- marker helpers --------------------------------------------------------

def test_marker_absent_on_fresh_target(tmp_path):
    target = tmp_path / "tgt.photoslibrary"
    target.mkdir()
    assert is_derivatives_backfilled(target) is False


def test_mark_then_detect(tmp_path):
    target = tmp_path / "tgt.photoslibrary"
    target.mkdir()

    mark_derivatives_backfilled(target, 42)

    assert is_derivatives_backfilled(target) is True


def test_marker_lives_inside_the_target_bundle(tmp_path):
    target = tmp_path / "tgt.photoslibrary"
    target.mkdir()

    mark_derivatives_backfilled(target, 1)

    # Every file written by marking must be under the bundle so it travels with
    # the library and never touches the source.
    written = [p for p in target.rglob("*") if p.is_file()]
    assert written, "marking should create at least one file"
    for p in written:
        assert target in p.parents


# --- sync integration: backfill runs once, then is skipped -----------------

def _patch_sync(existing_uuids, backfill_mock):
    """Patch sync_photos' collaborators so only the backfill path is exercised.

    Returns a context-manager list the caller enters; new photos / deletes /
    albums / favourites are all neutralised, leaving Phase 1b under test.
    """
    return [
        patch(f"{MODULE}.connect_readonly", return_value=MagicMock()),
        patch(f"{MODULE}.connect_readwrite", return_value=MagicMock()),
        patch(f"{MODULE}.assert_schema_compatible", return_value=None),
        patch(
            f"{MODULE}.fetch_asset_uuid_sets",
            return_value=(set(existing_uuids), set(existing_uuids)),
        ),
        patch(f"{MODULE}.identify_new_photos", return_value=[]),
        patch(f"{MODULE}.identify_deleted_photos", return_value=[]),
        patch(f"{MODULE}.sync_albums", return_value=SyncResult()),
        patch(f"{MODULE}.identify_favourite_changes", return_value=[]),
        patch(f"{MODULE}.backfill_derivatives", backfill_mock),
    ]


def test_backfill_runs_on_first_sync_then_skips(tmp_path):
    source = tmp_path / "src.photoslibrary"
    target = tmp_path / "tgt.photoslibrary"
    source.mkdir()
    target.mkdir()

    backfill = MagicMock(return_value=(0, 0, []))
    existing = ["A1B2C3D4-0000-0000-0000-000000000001"]

    # First sync: target not yet marked -> backfill must run.
    patches = _patch_sync(existing, backfill)
    for p in patches:
        p.start()
    try:
        sync_mod.sync_photos(source, target)
    finally:
        for p in patches:
            p.stop()

    assert backfill.call_count == 1, "first sync should backfill"
    assert is_derivatives_backfilled(target) is True, "first sync should mark done"

    # Second sync: marker present -> backfill must be skipped entirely.
    backfill2 = MagicMock(return_value=(0, 0, []))
    patches = _patch_sync(existing, backfill2)
    for p in patches:
        p.start()
    try:
        sync_mod.sync_photos(source, target)
    finally:
        for p in patches:
            p.stop()

    assert backfill2.call_count == 0, "second sync must not rescan the library"


def test_fresh_target_marked_without_rescanning_next_run(tmp_path):
    # A brand-new target (nothing pre-existing in common) still gets marked, so
    # the *next* sync — when those photos now overlap — does not rescan them.
    source = tmp_path / "src.photoslibrary"
    target = tmp_path / "tgt.photoslibrary"
    source.mkdir()
    target.mkdir()

    backfill = MagicMock(return_value=(0, 0, []))
    patches = _patch_sync([], backfill)  # no overlapping UUIDs this run
    for p in patches:
        p.start()
    try:
        sync_mod.sync_photos(source, target)
    finally:
        for p in patches:
            p.stop()

    assert is_derivatives_backfilled(target) is True
