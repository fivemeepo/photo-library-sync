"""Photo Sync - Synchronize photos and albums between Apple Photos libraries."""

__version__ = "1.0.0"

from photo_sync.models.sync_result import SyncPlan, SyncResult
from photo_sync.sync import create_sync_plan, sync_albums, sync_photos

__all__ = [
    "__version__",
    "sync_photos",
    "sync_albums",
    "create_sync_plan",
    "SyncResult",
    "SyncPlan",
]
