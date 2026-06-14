# Quickstart: Library Sync

**Feature**: `20260208-library-sync-append`

## Prerequisites

- macOS with Photos app
- Python 3.10+
- Source Photos library at `/Users/you/Pictures/Photos Library.photoslibrary`
- Target Photos library at `/Users/you/Pictures/Photos Library copy.photoslibrary`

## Installation

```bash
# From repository root
cd /Users/you/work/photo_library

# Install in development mode
pip install -e .

# Or run directly
python -m photo_sync.cli --help
```

## Quick Start

### 1. Preview Changes (Recommended First Step)

Always preview before syncing:

```bash
photo-sync --dry-run \
    "/Users/you/Pictures/Photos Library.photoslibrary" \
    "/Users/you/Pictures/Photos Library copy.photoslibrary"
```

Expected output:
```
DRY RUN - No changes will be made

Changes that would be synced:
  Photos to add: 16
  Photos to delete: 0
  Albums to add: 1
  Album memberships to add: 20
  Album memberships to remove: 5
  Favourites to sync: 3

Total data to copy: 45.2 MB
```

### 2. Run Sync

If preview looks correct, run the actual sync:

```bash
photo-sync \
    "/Users/you/Pictures/Photos Library.photoslibrary" \
    "/Users/you/Pictures/Photos Library copy.photoslibrary"
```

### 3. Verify Results

Open target library in Photos app to verify:
1. New photos appear in library
2. Albums contain correct photos
3. No corruption warnings

## Common Workflows

### Sync Photos Only (No Albums)

```bash
photo-sync --no-albums \
    "/Users/you/Pictures/Photos Library.photoslibrary" \
    "/Users/you/Pictures/Photos Library copy.photoslibrary"
```

### Add-Only Mode (No Deletions)

```bash
photo-sync --no-delete \
    "/Users/you/Pictures/Photos Library.photoslibrary" \
    "/Users/you/Pictures/Photos Library copy.photoslibrary"
```

### JSON Output for Scripts

```bash
photo-sync --json \
    "/Users/you/Pictures/Photos Library.photoslibrary" \
    "/Users/you/Pictures/Photos Library copy.photoslibrary" \
    | jq '.summary'
```

### Verbose Mode for Debugging

```bash
photo-sync --verbose \
    "/Users/you/Pictures/Photos Library.photoslibrary" \
    "/Users/you/Pictures/Photos Library copy.photoslibrary"
```

## Troubleshooting

### "Database is locked"

Photos app has the database open. Solutions:
1. Close Photos app
2. Wait a few seconds and retry
3. Use `--timeout 60` for longer wait

### "Source library not found"

Check the path:
```bash
ls -la "/Users/you/Pictures/Photos Library.photoslibrary"
```

### "Permission denied"

Check permissions:
```bash
# Read access to source
ls -la "/Users/you/Pictures/Photos Library.photoslibrary/database/"

# Write access to target
touch "/Users/you/Pictures/Photos Library copy.photoslibrary/test" && rm -f "/Users/you/Pictures/Photos Library copy.photoslibrary/test"
```

### Photos Not Appearing After Sync

1. Quit Photos app completely
2. Reopen target library
3. Wait for Photos to rebuild indexes (may take a few minutes)

## Creating a Target Library

If you don't have a target library yet:

```bash
# Copy the entire library (first time only)
cp -R "/Users/you/Pictures/Photos Library.photoslibrary" \
      "/Users/you/Pictures/Photos Library copy.photoslibrary"
```

**Note**: This creates a full copy. Future syncs will only copy changes.

## Safety Notes

1. **Always preview first** with `--dry-run`
2. **Backup target library** before first sync
3. **Close Photos app** during sync to avoid conflicts
4. **Source is never modified** - only read operations
5. **Target modifications are intentional** - this is the sync destination

## Next Steps

- See [CLI Interface](./contracts/cli.md) for full command reference
- See [Data Model](./data-model.md) for database structure
- See [Research](./research.md) for technical decisions
