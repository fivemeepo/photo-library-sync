"""Tests for SyncResult derivative-copy counters."""

from photo_sync.models.sync_result import SyncResult


def test_merge_sums_derivative_counters():
    a = SyncResult(derivative_files_copied=2, derivative_bytes_copied=100)
    b = SyncResult(derivative_files_copied=3, derivative_bytes_copied=50)

    a.merge(b)

    assert a.derivative_files_copied == 5
    assert a.derivative_bytes_copied == 150


def test_to_dict_includes_derivative_counts():
    result = SyncResult(derivative_files_copied=4, derivative_bytes_copied=2048)

    data = result.to_dict()

    assert data["derivative_files_copied"] == 4
    assert data["derivative_bytes_copied"] == 2048
