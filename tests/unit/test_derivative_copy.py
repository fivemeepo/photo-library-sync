"""Tests for per-asset derivative (thumbnail/preview) copying.

Photos stores an asset's rendered thumbnails/previews under bucketed subtrees of
``resources/`` (``derivatives/<bucket>``, ``derivatives/masters/<bucket>``,
``derivatives/cvt/<bucket>/<UUID>/`` and ``renders/<bucket>``), where
``<bucket>`` is the first hex char of the asset UUID (== ``ZASSET.ZDIRECTORY``).
The shared packed caches (``derivatives/thumbs/*.ithmb``) are NOT per-asset and
must be left for Photos to rebuild.
"""

from __future__ import annotations

from pathlib import Path

from photo_sync.models import Asset
from photo_sync.operations.file_copy import (
    backfill_derivatives,
    copy_asset_derivatives,
    get_asset_derivative_size,
)

UUID = "A1B2C3D4-0000-0000-0000-000000000001"
OTHER = "A9999999-0000-0000-0000-000000000099"
BUCKET = "A"

# (relative path under the library, bytes) for the asset's own derivatives.
ASSET_DERIVATIVES = {
    f"resources/derivatives/{BUCKET}/{UUID}_1_105_c.jpeg": b"DISPLAY",          # 7
    f"resources/derivatives/masters/{BUCKET}/{UUID}_4_5005_c.jpeg": b"MASTERDATA",  # 10
    f"resources/derivatives/cvt/{BUCKET}/{UUID}/{UUID}_cvt_t0000.jpeg": b"CVT0",     # 4
    f"resources/derivatives/cvt/{BUCKET}/{UUID}/{UUID}_cvt_t0001.jpeg": b"CVT1!",    # 5
    f"resources/renders/{BUCKET}/{UUID}.plist": b"<plist/>",                          # 8
}
ASSET_FILES = len(ASSET_DERIVATIVES)
ASSET_BYTES = sum(len(v) for v in ASSET_DERIVATIVES.values())  # 34

# Files that share the bucket but must NOT be copied for this asset.
UNRELATED = {
    "resources/derivatives/thumbs/4133.ithmb": b"SHAREDPACKEDCACHE",
    f"resources/derivatives/{BUCKET}/{OTHER}_1_105_c.jpeg": b"OTHERASSET",
}


def _write(root: Path, rel: str, data: bytes) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _make_source(tmp_path: Path) -> Path:
    src = tmp_path / "src.photoslibrary"
    for rel, data in {**ASSET_DERIVATIVES, **UNRELATED}.items():
        _write(src, rel, data)
    return src


def _asset() -> Asset:
    return Asset(z_pk=1, uuid=UUID, directory=BUCKET, filename=f"{UUID}.jpeg")


def test_copies_all_per_asset_derivatives(tmp_path):
    src = _make_source(tmp_path)
    tgt = tmp_path / "tgt.photoslibrary"

    files, nbytes = copy_asset_derivatives(src, tgt, _asset())

    assert files == ASSET_FILES
    assert nbytes == ASSET_BYTES
    for rel, data in ASSET_DERIVATIVES.items():
        assert (tgt / rel).read_bytes() == data


def test_does_not_copy_shared_or_unrelated_files(tmp_path):
    src = _make_source(tmp_path)
    tgt = tmp_path / "tgt.photoslibrary"

    copy_asset_derivatives(src, tgt, _asset())

    for rel in UNRELATED:
        assert not (tgt / rel).exists(), f"should not have copied {rel}"


def test_skips_already_copied_same_size(tmp_path):
    src = _make_source(tmp_path)
    tgt = tmp_path / "tgt.photoslibrary"

    copy_asset_derivatives(src, tgt, _asset())  # first run copies everything
    files, nbytes = copy_asset_derivatives(src, tgt, _asset())  # second is a no-op

    assert files == 0
    assert nbytes == 0


def test_size_matches_copied_bytes(tmp_path):
    src = _make_source(tmp_path)
    assert get_asset_derivative_size(src, _asset()) == ASSET_BYTES


def test_asset_without_derivatives_is_noop(tmp_path):
    src = tmp_path / "empty.photoslibrary"
    src.mkdir()
    tgt = tmp_path / "tgt.photoslibrary"

    assert copy_asset_derivatives(src, tgt, _asset()) == (0, 0)
    assert get_asset_derivative_size(src, _asset()) == 0


def test_backfill_copies_missing_derivatives_by_uuid(tmp_path):
    # backfill takes bare UUID strings (no Asset.directory) and must derive the
    # bucket from the UUID's first character.
    src = _make_source(tmp_path)
    tgt = tmp_path / "tgt.photoslibrary"

    files, nbytes, warnings = backfill_derivatives(src, tgt, [UUID])

    assert files == ASSET_FILES
    assert nbytes == ASSET_BYTES
    assert warnings == []
    for rel in ASSET_DERIVATIVES:
        assert (tgt / rel).exists()


def test_backfill_unknown_uuid_is_noop(tmp_path):
    src = _make_source(tmp_path)
    tgt = tmp_path / "tgt.photoslibrary"

    files, nbytes, warnings = backfill_derivatives(
        src, tgt, ["FFFFFFFF-0000-0000-0000-000000000000"]
    )

    assert (files, nbytes, warnings) == (0, 0, [])
