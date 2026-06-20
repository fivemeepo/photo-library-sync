# Photo Library Sync

Synchronize photos and albums between Apple Photos libraries.

## Features

- **Photo Sync**: Copy new photos from source to target library
- **Thumbnail Sync**: Copy each photo's rendered thumbnails/previews so the target browses fast without regenerating them
- **Deletion Sync**: Remove photos from target that were deleted from source
- **Album Sync**: Sync album definitions and photo-album memberships
- **Favourite Sync**: Sync favourite status between libraries
- **Deduplication**: Remove duplicate photos within an album
- **Dry-Run Mode**: Preview changes before executing
- **Progress Reporting**: Real-time progress during sync operations

## Installation

No install required — just run `./photo_sync.py` from the project root:

```bash
./photo_sync.py --help
```

Or install as a console script:

```bash
pip install -e .
photo-sync --help
```

## Quick Start

### Sync Libraries

```bash
# Preview changes first (recommended)
./photo_sync.py sync --dry-run \
    "/path/to/Source.photoslibrary" \
    "/path/to/Target.photoslibrary"

# Run sync
./photo_sync.py sync \
    "/path/to/Source.photoslibrary" \
    "/path/to/Target.photoslibrary"
```

### Sync Several Libraries at Once

Create `sync-all.config.json` (copy `sync-all.config.example.json` and edit the
pairs), then:

```bash
# Preview changes for all configured pairs
./photo_sync.py sync-all --dry-run

# Run sync for all configured pairs
./photo_sync.py sync-all
```

### Deduplicate an Album

```bash
# Preview duplicates first
./photo_sync.py dedup --dry-run \
    "/path/to/Library.photoslibrary" \
    --album "Vacation"

# Remove duplicates
./photo_sync.py dedup \
    "/path/to/Library.photoslibrary" \
    --album "Vacation"
```

## Usage

### `photo-sync sync`

Synchronize photos and albums from source to target library.

For every new photo this copies the original file **and** its rendered
derivatives — the grid thumbnail, the display-size preview, video/Live Photo
transcodes, and edit renders (`resources/derivatives/…` and `resources/renders/…`).
Without them the target's database still points at derivatives that aren't on
disk, so Photos has to regenerate every thumbnail on first view, making the
library slow to open and browse.

It also **backfills** missing derivatives for photos that are already in the
target (e.g. synced by an older version that copied only originals), so an
existing slow target is repaired on the next sync. This backfill is a one-time
repair: once it completes, a marker (`.photo_sync_meta/` inside the target
bundle) records it so later syncs skip the whole-library rescan. New photos
keep getting their derivatives through the new-photo path above, so nothing is
missed. (Delete that marker to force a full re-backfill.)

The shared packed thumbnail caches (`derivatives/thumbs/*.ithmb`) and the
Spotlight-style search index (`database/search/psi.sqlite`) are **not** copied —
those are rebuilt by Photos itself the first time you open the target.

```
./photo_sync.py sync [OPTIONS] SOURCE TARGET
```

| Option | Description |
|--------|-------------|
| `-n, --dry-run` | Preview changes without executing |
| `-j, --json` | Output in JSON format |
| `-v, --verbose` | Enable verbose logging |
| `-q, --quiet` | Suppress non-error output |
| `--no-delete` | Skip deletion sync (add-only mode) |
| `--no-albums` | Skip album sync (photos only) |
| `--verify` | Verify file integrity after copy |

### `photo-sync sync-all`

Sync every source/target library pair listed in a config file, in sequence.
Copy `sync-all.config.example.json` to `sync-all.config.json` and list your
pairs:

```json
{
  "pairs": [
    {
      "source": "/Volumes/Source/Photos/Family.photoslibrary",
      "target": "/Volumes/Backup/Photos/Family.photoslibrary"
    }
  ]
}
```

If any configured path lives under `/Volumes/<drive>`, that drive is checked for
being mounted before the run starts. `sync-all.config.json` is gitignored so your
personal paths stay local.

```
./photo_sync.py sync-all [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--config PATH` | JSON file listing library pairs (default: `sync-all.config.json`) |
| `-n, --dry-run` | Preview changes for all libraries without executing |
| `-v, --verbose` | Enable verbose logging |
| `-q, --quiet` | Suppress non-error output |
| `--no-delete` | Skip deletion sync (add-only mode) |
| `--no-albums` | Skip album sync (photos only) |
| `--verify` | Verify file integrity after copy |

### `photo-sync dedup`

Remove duplicate photos within a specific album. Duplicates are detected by matching original filename pattern, file size, and resolution. The original file (without macOS `(N)` suffix) is kept; if all copies have suffixes, the earliest by creation date is kept.

```
./photo_sync.py dedup [OPTIONS] LIBRARY --album ALBUM
```

| Option | Description |
|--------|-------------|
| `--album` | Album name to deduplicate (required) |
| `-n, --dry-run` | Preview duplicates without deleting |
| `-j, --json` | Output in JSON format |
| `-v, --verbose` | Enable verbose logging |
| `-q, --quiet` | Suppress non-error output |

### `photo-sync fix-trash`

Fix the Recently Deleted album cached counts. Use this when soft-deleted photos don't appear in Recently Deleted in Photos.app.

```
./photo_sync.py fix-trash [OPTIONS] LIBRARY
```

| Option | Description |
|--------|-------------|
| `-v, --verbose` | Enable verbose logging |
| `-q, --quiet` | Suppress non-error output |

## Project Structure

```
src/
  photo_sync/
    cli.py              # CLI entry point with subcommands
    sync.py             # Sync orchestration
    models/             # Data models (Asset, Album, Moment, etc.)
    db/                 # Database queries and mutations
    operations/         # Photo sync, album sync, dedup, file copy
tests/
  unit/                 # Unit tests
```

## Development

```bash
# Run tests and lint
cd src && pytest && ruff check .
```

## Requirements

- macOS with Photos app
- Python 3.10+
- Source and target Photos libraries

## Safety Notes

1. **Always preview first** with `--dry-run`
2. **Backup target library** before first sync
3. **Close Photos app** during sync to avoid conflicts
4. **Source is never modified** - only read operations
5. **Dedup uses soft-delete** - photos go to Recently Deleted, not permanently removed
6. **Schema-version check** - sync aborts if the libraries are on different Photos schemas

## Schema Version Compatibility

`sync` and `sync-all` verify before doing any work that the source and target
libraries share the same Apple Photos schema. Apple migrates a library's schema
when it is opened by a newer Photos app, and two libraries on different schema
versions have divergent columns (e.g. `ZASSET.ZISRECENTLYSAVED` vs
`ZASSET.ZRECENCYTYPE`) that would make the row copy fail on every photo.

If the schemas differ, the sync stops immediately (exit code `8`) with an error
like:

```
Error: Source and target libraries are on different Photos schema versions
(source PLModelVersion=19607, target PLModelVersion=19500). Open the older
library in the latest Photos app so it migrates the schema, quit Photos, then
retry the sync.
```

**To resolve it**, open the older `.photoslibrary` in the latest Photos app
(this triggers Apple's schema migration), let it finish, quit Photos, and re-run
the sync.

Compatibility is determined by the Core Data model fingerprint, not Photos'
`PLModelVersion` counter — two libraries with the same columns but a different
`PLModelVersion` are still treated as compatible and sync normally.
