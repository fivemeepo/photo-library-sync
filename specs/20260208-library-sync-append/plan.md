# Implementation Plan: Library Sync

**Feature**: `20260208-library-sync-append` | **Date**: 2026-02-08 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/20260208-library-sync-append/spec.md`

## Summary

Synchronize photos and albums between two Apple Photos libraries using UUID-based matching. The sync is one-way (source → target) and handles:
- Adding new photos from source to target
- Syncing photo deletions
- Syncing album membership changes
- Syncing favourite status (P5, nice-to-have)

**Technical Approach**: Python CLI tool that reads source database (read-only), writes to target database (read-write), and copies photo files. Uses UUID matching since target is a copy of source.

## Technical Context

**Language/Version**: Python 3.10+ with type hints
**Primary Dependencies**: sqlite3 (stdlib), shutil (stdlib), argparse (stdlib), pathlib (stdlib)
**Storage**: SQLite (Photos.sqlite - Core Data managed), file system (originals/)
**Testing**: pytest with test fixtures (mock Photos libraries)
**Target Platform**: macOS (Photos.app libraries)
**Project Type**: single
**Performance Goals**: Sync 1000 photos in <10 minutes (excluding file I/O)
**Constraints**: Source DB read-only, target DB read-write, handle DB locks gracefully
**Scale/Scope**: Libraries with 10K-100K photos, 89 database tables, ~7 core tables per photo

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Principle I: Data Safety First

| Rule | Status | Notes |
|------|--------|-------|
| Source DB read-only | ✅ PASS | Source opened with `?mode=ro` |
| Target DB read-only | ⚠️ **VIOLATION** | Target requires INSERT/UPDATE/DELETE |
| No file modifications in source | ✅ PASS | Only reading from source |
| Handle DB locks | ✅ PASS | Retry logic with timeout |

**VIOLATION JUSTIFICATION**: The sync feature inherently requires writing to the target library. This is explicitly approved by the user who requested the sync functionality. The source library remains read-only (data safety preserved for primary library). Target library modifications are intentional and user-requested.

### Principle II: Python CLI Tools

| Rule | Status | Notes |
|------|--------|-------|
| Python 3.10+ with type hints | ✅ PASS | Using Python 3.10+ |
| CLI arguments and stdin | ✅ PASS | argparse for CLI |
| stdout/stderr separation | ✅ PASS | Data to stdout, logs to stderr |
| JSON and human-readable output | ✅ PASS | `--json` flag supported |
| Exit codes | ✅ PASS | 0=success, 1=error |

### Principle III: Documentation First

| Rule | Status | Notes |
|------|--------|-------|
| Schema documented in docs/ | ✅ PASS | docs/Photos_Library_Schema.md exists |
| Example queries | ✅ PASS | Included in schema doc |
| Timestamp conversions | ✅ PASS | Core Data epoch documented |

## Project Structure

### Documentation (this feature)

```
specs/20260208-library-sync-append/
├── spec.md              # Feature specification
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (CLI interface)
└── tasks.md             # Phase 2 output (/adk:tasks)
```

### Source Code (repository root)

```
src/
├── photo_sync/
│   ├── __init__.py
│   ├── cli.py           # CLI entry point
│   ├── sync.py          # Main sync orchestration
│   ├── db/
│   │   ├── __init__.py
│   │   ├── connection.py    # Database connections (read-only/read-write)
│   │   ├── queries.py       # SQL queries for reading
│   │   ├── mutations.py     # SQL for inserts/updates/deletes
│   │   └── pk_manager.py    # Z_PRIMARYKEY management
│   ├── models/
│   │   ├── __init__.py
│   │   ├── asset.py         # ZASSET model
│   │   ├── album.py         # ZGENERICALBUM model
│   │   └── sync_result.py   # Sync operation results
│   └── operations/
│       ├── __init__.py
│       ├── photo_sync.py    # Photo add/delete operations
│       ├── album_sync.py    # Album sync operations
│       └── file_copy.py     # File system operations
└── lib/
    └── core_data.py         # Core Data helpers (Z_ENT, Z_OPT, timestamps)

tests/
├── fixtures/
│   ├── source_library/      # Test source library
│   └── target_library/      # Test target library
├── unit/
│   ├── test_queries.py
│   ├── test_models.py
│   └── test_pk_manager.py
└── integration/
    ├── test_photo_sync.py
    ├── test_album_sync.py
    └── test_full_sync.py

docs/
└── Photos_Library_Schema.md  # Database schema documentation
```

**Structure Decision**: Single project structure with clear separation between database operations, models, and sync operations. The `db/` module handles all SQLite interactions, `models/` defines data structures, and `operations/` implements sync logic.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Target DB write access | User explicitly requested sync to target library | Read-only would make sync impossible |
| Multiple table inserts | Core Data requires related records in multiple tables | Single table insert would corrupt database |
| Z_PRIMARYKEY management | Core Data tracks PKs in this table | Auto-increment would conflict with Core Data |

## Architecture Decisions

### Sync Strategy: Minimal Core Tables (Option A)

Based on spec analysis, we will sync only core tables and let Photos app regenerate ML data:

**Tables to Sync**:
1. `ZASSET` - Core photo record
2. `ZADDITIONALASSETATTRIBUTES` - Original filename, import info
3. `ZEXTENDEDATTRIBUTES` - Extended attributes
4. `ZINTERNALRESOURCE` - File variants (~2 per photo)
5. `ZGENERICALBUM` - Album definitions
6. `Z_33ASSETS` - Album memberships
7. `Z_PRIMARYKEY` - Must update for each entity type

**Tables NOT Synced** (Photos app regenerates):
- `ZPHOTOANALYSISASSETATTRIBUTES`
- `ZMEDIAANALYSISASSETATTRIBUTES`
- `ZCOMPUTEDASSETATTRIBUTES`
- `ZSCENECLASSIFICATION` (~42 per photo)
- `ZDETECTEDFACE`, `ZFACECROP`, `ZDETECTEDFACEPRINT`
- `ZCHARACTERRECOGNITIONATTRIBUTES`
- `ZVISUALSEARCHATTRIBUTES`

**Rationale**:
- Reduces complexity from ~17 tables to 7 tables
- Avoids conflicts with Photos app ML analysis
- Photos app will rebuild ML data when library is opened
- Lower risk of database corruption

### UUID-Based Matching

Since target is a copy of source:
- Match photos by `ZASSET.ZUUID` (not Z_PK)
- Match albums by `ZGENERICALBUM.ZUUID`
- Z_PK values may differ between libraries

### Deletion Strategy: Soft Delete

For deleted photos:
- Set `ZTRASHEDSTATE = 1` and `ZTRASHEDDATE = now`
- Keep related records (Photos app handles cleanup)
- Matches Photos app "Recently Deleted" behavior

### Favourites Sync Strategy

For favourite status changes (P5 feature):
- Compare `ZASSET.ZFAVORITE` between source and target for matching UUIDs
- Update target's `ZFAVORITE` to match source (one-way sync)
- New photos synced via photo sync will automatically include favourite status
- Only sync favourites for photos that exist in both libraries

### File Operations

- Copy files using `shutil.copy2()` to preserve metadata
- Verify file integrity after copy (optional checksum)
- Create directories as needed
- Display progress percentage during batch file operations (e.g., "Syncing photos... [====] 16/100 (16%)")

### Progress Reporting

- Real-time progress bars for time-intensive operations:
  - Photo file copying: Show current/total count and percentage
  - Album sync: Show current/total count and percentage
  - Database operations: Show progress for batch inserts/updates
- Progress updates written to stdout (or suppressed with `--quiet`)
- Use stderr for logs to keep progress output clean
