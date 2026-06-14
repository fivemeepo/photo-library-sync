# CLI Interface Contract: photo-sync

**Command**: `photo-sync`
**Version**: 1.0.0

## Synopsis

```
photo-sync [OPTIONS] <SOURCE> <TARGET>
photo-sync --help
photo-sync --version
```

## Description

Synchronize photos and albums from a source Apple Photos library to a target library. The sync is one-way (source → target) and uses UUID-based matching.

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| `SOURCE` | Yes | Path to source Photos library (`.photoslibrary`) |
| `TARGET` | Yes | Path to target Photos library (`.photoslibrary`) |

## Options

| Option | Short | Default | Description |
|--------|-------|---------|-------------|
| `--dry-run` | `-n` | false | Preview changes without executing |
| `--json` | `-j` | false | Output in JSON format |
| `--verbose` | `-v` | false | Enable verbose logging |
| `--quiet` | `-q` | false | Suppress non-error output |
| `--no-delete` | | false | Skip deletion sync (add-only mode) |
| `--no-albums` | | false | Skip album sync (photos only) |
| `--verify` | | false | Verify file integrity after copy |
| `--help` | `-h` | | Show help message |
| `--version` | | | Show version |

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Invalid arguments |
| 3 | Source library not found |
| 4 | Target library not found |
| 5 | Database locked |
| 6 | Disk full |
| 7 | Permission denied |

## Output Formats

### Human-Readable (default)

```
Syncing from: /path/to/source.photoslibrary
          to: /path/to/target.photoslibrary

Analyzing libraries...
  Source: 466 photos, 5 albums
  Target: 450 photos, 4 albums

Changes to sync:
  Photos to add: 16
  Photos to delete: 0
  Albums to add: 1
  Album memberships to add: 20
  Album memberships to remove: 5

Syncing photos...
  [============================] 16/16 (100%)
  Note: Progress bar updates in real-time showing current/total and percentage

Syncing albums...
  [============================] 1/1 (100%)
  Note: Progress bar updates for each operation phase

Sync complete!
  Photos added: 16
  Photos deleted: 0
  Albums added: 1
  Files copied: 16 (45.2 MB)
  Time elapsed: 12.3s
```

### JSON (`--json`)

```json
{
  "status": "success",
  "source": "/path/to/source.photoslibrary",
  "target": "/path/to/target.photoslibrary",
  "summary": {
    "photos_added": 16,
    "photos_deleted": 0,
    "albums_added": 1,
    "album_memberships_added": 20,
    "album_memberships_removed": 5,
    "files_copied": 16,
    "bytes_copied": 47395840
  },
  "elapsed_seconds": 12.3,
  "errors": [],
  "warnings": []
}
```

### Dry-Run Output

Human-readable:
```
DRY RUN - No changes will be made

Changes that would be synced:
  Photos to add: 16
    - IMG_1234.jpg (2.3 MB)
    - IMG_1235.jpg (1.8 MB)
    ...
  Photos to delete: 0
  Albums to add: 1
    - "Vacation 2026"
  Album memberships to add: 20
  Album memberships to remove: 5

Total data to copy: 45.2 MB
```

JSON:
```json
{
  "dry_run": true,
  "plan": {
    "photos_to_add": 16,
    "photos_to_delete": 0,
    "albums_to_add": 1,
    "memberships_to_add": 20,
    "memberships_to_remove": 5,
    "total_bytes_to_copy": 47395840
  },
  "details": {
    "photos_to_add": [
      {"uuid": "ABC123", "filename": "IMG_1234.jpg", "size": 2411724},
      ...
    ],
    "albums_to_add": [
      {"uuid": "DEF456", "title": "Vacation 2026"}
    ]
  }
}
```

## Examples

### Basic Sync

```bash
photo-sync ~/Pictures/Photos\ Library.photoslibrary \
           ~/Pictures/Photos\ Library\ copy.photoslibrary
```

### Preview Changes (Dry Run)

```bash
photo-sync --dry-run ~/Pictures/Source.photoslibrary \
                     ~/Pictures/Target.photoslibrary
```

### JSON Output for Scripting

```bash
photo-sync --json ~/Pictures/Source.photoslibrary \
                  ~/Pictures/Target.photoslibrary | jq '.summary'
```

### Add-Only Mode (No Deletions)

```bash
photo-sync --no-delete ~/Pictures/Source.photoslibrary \
                       ~/Pictures/Target.photoslibrary
```

### Photos Only (No Album Sync)

```bash
photo-sync --no-albums ~/Pictures/Source.photoslibrary \
                       ~/Pictures/Target.photoslibrary
```

### Verbose with Verification

```bash
photo-sync --verbose --verify ~/Pictures/Source.photoslibrary \
                              ~/Pictures/Target.photoslibrary
```

## Error Messages

| Error | Cause | Resolution |
|-------|-------|------------|
| `Source library not found` | SOURCE path doesn't exist | Check path spelling |
| `Target library not found` | TARGET path doesn't exist | Check path or create target |
| `Database is locked` | Photos app has exclusive access | Close Photos app or wait |
| `Insufficient disk space` | Target disk full | Free space or use different target |
| `Permission denied` | No read/write access | Check file permissions |
| `Invalid library format` | Not a Photos library | Verify `.photoslibrary` bundle |

## Logging

Logs are written to stderr. Use `--verbose` for detailed logs.

Log levels:
- ERROR: Critical failures (always shown)
- WARNING: Non-fatal issues (always shown)
- INFO: Progress updates (default)
- DEBUG: Detailed operations (`--verbose`)

## Environment Variables

| Variable | Description |
|----------|-------------|
| `PHOTO_SYNC_LOG_LEVEL` | Override log level (DEBUG, INFO, WARNING, ERROR) |
| `PHOTO_SYNC_TIMEOUT` | Database lock timeout in seconds (default: 30) |
