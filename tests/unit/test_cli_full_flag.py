from unittest.mock import patch

from photo_sync.cli import create_parser, run_sync
from photo_sync.models.sync_result import SyncResult


def test_parser_accepts_full():
    parsed = create_parser().parse_args(
        ["sync", "/src.photoslibrary", "/dst.photoslibrary", "--full"]
    )
    assert parsed.full is True


def test_run_sync_passes_full():
    parsed = create_parser().parse_args(
        ["sync", "/src.photoslibrary", "/dst.photoslibrary", "--full", "-q"]
    )
    with patch("photo_sync.cli.validate_library_path", return_value=(True, 0, "")), \
         patch("photo_sync.cli.sync_photos", return_value=SyncResult()) as mock_sync:
        run_sync(parsed)
    assert mock_sync.call_args.kwargs["full"] is True
