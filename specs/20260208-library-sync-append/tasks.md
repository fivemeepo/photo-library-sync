# Tasks: Library Sync

**Feature**: `20260208-library-sync-append`
**Input**: Design documents from `/specs/20260208-library-sync-append/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/cli.md

**Tests**: Tests are NOT explicitly requested in the spec, so test tasks are OMITTED. The spec mentions pytest for testing infrastructure, but no TDD approach was specified.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`
- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3, US4)
- Include exact file paths in descriptions

## Path Conventions
- **Single project**: `src/`, `tests/` at repository root
- All paths are relative to `/Users/you/work/photo_library/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure

- [x] T001 Create project directory structure: `src/photo_sync/`, `src/photo_sync/db/`, `src/photo_sync/models/`, `src/photo_sync/operations/`, `src/lib/`, `tests/fixtures/`, `tests/unit/`, `tests/integration/`
- [x] T002 [P] Create `setup.py` with project metadata, dependencies (Python 3.10+), and entry point for `photo-sync` CLI command
- [x] T003 [P] Create `pyproject.toml` with pytest configuration and ruff linting rules
- [x] T004 [P] Create `src/photo_sync/__init__.py` with package version and exports
- [x] T005 [P] Create `src/lib/__init__.py` for shared utilities

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T006 [P] Implement Core Data helpers in `src/lib/core_data.py`: timestamp conversion functions (Core Data epoch ↔ Unix), Z_ENT constants (Asset=3, AdditionalAssetAttributes=1, ExtendedAttributes=28, InternalResource=51, GenericAlbum=32, Moment=58)
- [x] T007 [P] Create data models in `src/photo_sync/models/__init__.py`: Asset, AdditionalAssetAttributes, ExtendedAttributes, InternalResource, Album, AlbumAsset, Moment dataclasses matching data-model.md structure
- [x] T008 [P] Create result models in `src/photo_sync/models/sync_result.py`: SyncResult and SyncPlan dataclasses with to_dict() methods
- [x] T009 Implement database connection manager in `src/photo_sync/db/connection.py`: connect_with_retry() function with exponential backoff (max 3 retries), support for read-only (`?mode=ro`) and read-write modes, handle SQLITE_BUSY errors
- [x] T010 Implement Z_PRIMARYKEY manager in `src/photo_sync/db/pk_manager.py`: get_next_pk(conn, entity_name) function that reads Z_MAX from Z_PRIMARYKEY, increments it, updates the table, and returns the new PK
- [x] T011 [P] Implement base query functions in `src/photo_sync/db/queries.py`: get_all_asset_uuids(conn), get_asset_by_uuid(conn, uuid), get_all_albums(conn), get_album_memberships(conn)
- [x] T012 [P] Implement base mutation functions in `src/photo_sync/db/mutations.py`: insert_asset(conn, asset), update_asset_trashed_state(conn, uuid, state), insert_album(conn, album), insert_album_membership(conn, album_pk, asset_pk), delete_album_membership(conn, album_pk, asset_pk)

**Checkpoint**: Foundation ready - user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - Sync New Photos (Priority: P1) 🎯 MVP

**Goal**: Append all new photos from source library to target library, copying files and inserting database records

**Independent Test**: Add a new photo to source library, run sync, verify photo appears in target library's originals folder and database

### Implementation for User Story 1

- [x] T013 [P] [US1] Implement photo identification logic in `src/photo_sync/operations/photo_sync.py`: identify_new_photos(source_conn, target_conn) function that queries UUIDs from both libraries and returns list of Asset objects for photos in source but not in target (ZTRASHEDSTATE=0)
- [x] T014 [P] [US1] Implement file copy operation in `src/photo_sync/operations/file_copy.py`: copy_photo_file(source_lib_path, target_lib_path, asset) function using shutil.copy2() to preserve metadata, create directories as needed, return bytes copied
- [x] T015 [US1] Implement photo insertion in `src/photo_sync/operations/photo_sync.py`: insert_photo_with_relations(target_conn, asset, source_conn) function that uses transactions to insert ZASSET, ZADDITIONALASSETATTRIBUTES, ZEXTENDEDATTRIBUTES, ZINTERNALRESOURCE (1-2 records per photo), link to or create ZMOMENT, update Z_PRIMARYKEY for each entity type
- [x] T016 [US1] Implement moment management in `src/photo_sync/operations/photo_sync.py`: find_or_create_moment(conn, date_created) function that finds existing moment by date range or creates new moment with photo's date
- [x] T017 [US1] Implement main sync orchestration for photos in `src/photo_sync/sync.py`: sync_photos(source_lib, target_lib) function that opens connections, identifies new photos, copies files, inserts records, handles errors, returns SyncResult

**Checkpoint**: At this point, User Story 1 should be fully functional - new photos can be synced from source to target

---

## Phase 4: User Story 2 - Sync Deleted Photos (Priority: P2)

**Goal**: Remove photos from target library that were deleted from source library

**Independent Test**: Delete a photo from source library, run sync, verify photo is trashed in target

### Implementation for User Story 2

- [x] T018 [P] [US2] Implement deletion identification in `src/photo_sync/operations/photo_sync.py`: identify_deleted_photos(source_conn, target_conn) function that finds photos in target (ZTRASHEDSTATE=0) with UUIDs not in source active photos, returns list of UUIDs to delete
- [x] T019 [US2] Implement soft delete operation in `src/photo_sync/operations/photo_sync.py`: soft_delete_photo(target_conn, uuid) function that sets ZTRASHEDSTATE=1 and ZTRASHEDDATE=now (Core Data epoch), removes from Z_33ASSETS (album memberships), updates affected albums' ZCACHEDCOUNT
- [x] T020 [US2] Integrate deletion sync into main orchestration in `src/photo_sync/sync.py`: Add deletion logic to sync_photos() function after photo additions, update SyncResult with photos_deleted count

**Checkpoint**: At this point, User Stories 1 AND 2 should both work - photos can be added and deletions can be synced

---

## Phase 5: User Story 3 - Sync Album Membership (Priority: P3)

**Goal**: Synchronize album definitions and photo-album memberships from source to target

**Independent Test**: Add/remove a photo from an album in source, run sync, verify album membership matches in target

### Implementation for User Story 3

- [x] T021 [P] [US3] Implement album identification in `src/photo_sync/operations/album_sync.py`: identify_new_albums(source_conn, target_conn) function that finds user albums (ZKIND=2, ZTRASHEDSTATE=0) in source not in target by UUID, returns list of Album objects
- [x] T022 [P] [US3] Implement album membership diff in `src/photo_sync/operations/album_sync.py`: diff_album_memberships(source_conn, target_conn) function that compares Z_33ASSETS join table between libraries, returns (memberships_to_add, memberships_to_remove) as lists of (album_uuid, asset_uuid) tuples
- [x] T023 [US3] Implement album insertion in `src/photo_sync/operations/album_sync.py`: insert_album_with_hierarchy(target_conn, album, source_conn) function that inserts ZGENERICALBUM, handles ZPARENTFOLDER by UUID lookup, updates Z_PRIMARYKEY
- [x] T024 [US3] Implement membership sync in `src/photo_sync/operations/album_sync.py`: sync_album_memberships(target_conn, memberships_to_add, memberships_to_remove) function that inserts/deletes Z_33ASSETS rows, updates ZCACHEDCOUNT/ZCACHEDPHOTOSCOUNT/ZCACHEDVIDEOSCOUNT for affected albums
- [x] T025 [US3] Implement album folder sync in `src/photo_sync/operations/album_sync.py`: sync_album_folders(source_conn, target_conn) function that syncs folders (ZKIND=4000) before albums to establish parent references
- [x] T026 [US3] Integrate album sync into main orchestration in `src/photo_sync/sync.py`: Add sync_albums(source_lib, target_lib) function that syncs folders, albums, and memberships, returns counts in SyncResult

**Checkpoint**: All core user stories should now be independently functional - photos, deletions, and albums sync correctly

---

## Phase 6: User Story 4 - Sync Preview/Report Mode (Priority: P4)

**Goal**: Preview sync changes without executing them (dry-run mode)

**Independent Test**: Run with `--dry-run`, verify output shows expected changes and no files were actually copied

### Implementation for User Story 4

- [x] T027 [P] [US4] Implement dry-run analysis in `src/photo_sync/sync.py`: create_sync_plan(source_lib, target_lib) function that identifies all changes (photos to add/delete, albums to add, memberships to add/remove) without executing them, returns SyncPlan object
- [x] T028 [P] [US4] Implement plan output formatting in `src/photo_sync/sync.py`: format_sync_plan(plan, json_output) function that generates human-readable or JSON output showing counts and details of planned changes, includes total data size to copy
- [x] T029 [US4] Integrate dry-run mode into CLI in `src/photo_sync/cli.py`: Add `--dry-run` flag that calls create_sync_plan() instead of actual sync, outputs plan and exits with code 0

**Checkpoint**: Dry-run mode allows users to preview changes before executing sync

---

## Phase 6.5: User Story 5 - Sync Favourites (Priority: P5)

**Goal**: Synchronize favourite status from source to target library (one-way sync)

**Independent Test**: Mark/unmark a photo as favourite in source, run sync, verify favourite status matches in target

### Implementation for User Story 5

- [x] T027.5 [P] [US5] Implement favourite identification in `src/photo_sync/operations/favourite_sync.py`: identify_favourite_changes(source_conn, target_conn) function that compares ZASSET.ZFAVORITE between libraries for matching UUIDs, returns list of (uuid, source_fav, target_fav) tuples where values differ
- [x] T027.6 [US5] Implement favourite update in `src/photo_sync/operations/favourite_sync.py`: sync_favourites(target_conn, favourite_changes) function that updates ZFAVORITE in target to match source, returns count of updates
- [x] T027.7 [US5] Integrate favourite sync into main orchestration in `src/photo_sync/sync.py`: Add sync_favourites() call after album sync, update SyncResult with favourites_synced count

**Checkpoint**: Favourite status is now synced from source to target

---

## Phase 7: CLI Interface & Polish

**Purpose**: Complete CLI implementation and cross-cutting concerns

- [x] T030 Implement CLI argument parsing in `src/photo_sync/cli.py`: main() function with argparse for SOURCE and TARGET positional args, options: --dry-run, --json, --verbose, --quiet, --no-delete, --no-albums, --verify, --help, --version
- [x] T031 Implement CLI output formatting in `src/photo_sync/cli.py`: format_output(result, json_output) function that generates human-readable progress bars and summary, or JSON output matching contracts/cli.md format
- [x] T032 Implement CLI error handling in `src/photo_sync/cli.py`: Validate library paths exist, handle exceptions with appropriate exit codes (0=success, 1=error, 2=invalid args, 3=source not found, 4=target not found, 5=db locked, 6=disk full, 7=permission denied)
- [x] T033 [P] Implement logging configuration in `src/photo_sync/cli.py`: Setup stderr logging with levels (ERROR, WARNING, INFO, DEBUG), respect --verbose and --quiet flags, support PHOTO_SYNC_LOG_LEVEL environment variable
- [x] T034 [P] Add file verification option in `src/photo_sync/operations/file_copy.py`: Implement verify_file_copy(source_path, target_path) function with SHA256 checksum comparison, only run if --verify flag is set
- [x] T035 [P] Implement --no-delete flag handling in `src/photo_sync/sync.py`: Skip deletion sync when flag is set (add-only mode)
- [x] T036 [P] Implement --no-albums flag handling in `src/photo_sync/sync.py`: Skip album sync when flag is set (photos only mode)
- [x] T037 Add edge case handling in `src/photo_sync/operations/photo_sync.py`: Handle missing files (skip with warning), handle database locks (retry with timeout), handle disk full errors (report space required vs available)
- [x] T038 [P] Implement progress reporting in `src/photo_sync/cli.py`: Create progress_bar(current, total, prefix) function that displays real-time progress with percentage (e.g., "[====] 16/100 (16%)"), update during file copy and batch operations, respect --quiet flag
- [x] T039 [P] Create README.md in repository root: Installation instructions, basic usage examples, link to quickstart.md
- [x] T040 [P] Update CLAUDE.md with sync command: Add `photo-sync` to commands section
- [x] T041 Run quickstart.md validation: Execute all commands from quickstart.md to verify they work correctly

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Stories (Phase 3-6)**: All depend on Foundational phase completion
  - User stories can then proceed in parallel (if staffed)
  - Or sequentially in priority order (P1 → P2 → P3 → P4)
- **CLI & Polish (Phase 7)**: Depends on User Story 1 (MVP) at minimum, ideally all user stories

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational (Phase 2) - No dependencies on other stories
- **User Story 2 (P2)**: Can start after Foundational (Phase 2) - Independent of US1 but naturally builds on photo sync infrastructure
- **User Story 3 (P3)**: Can start after Foundational (Phase 2) - Independent of US1/US2, requires album-specific queries
- **User Story 4 (P4)**: Depends on US1, US2, US3 completion - needs to analyze all sync operations
- **User Story 5 (P5)**: Can start after Foundational (Phase 2) - Independent, only modifies ZASSET.ZFAVORITE

### Within Each User Story

- Models before services (Phase 2 completes all models)
- Query/mutation functions before operations
- Individual operations before orchestration
- Core implementation before integration

### Parallel Opportunities

**Phase 1 - Setup**: All tasks marked [P] can run in parallel (T002, T003, T004, T005)

**Phase 2 - Foundational**: Tasks T006, T007, T008 can run in parallel (models and helpers), then T011 and T012 can run in parallel (queries and mutations), T009 and T010 are sequential dependencies for database operations

**Phase 3 - User Story 1**: T013 and T014 can run in parallel (different files), then T015 uses T013 output, T016 is independent, T017 orchestrates all

**Phase 4 - User Story 2**: T018 and T019 can run in parallel (different concerns), T020 integrates both

**Phase 5 - User Story 3**: T021 and T022 can run in parallel (different analysis functions), T023 and T024 can run in parallel (different operations), T025 is independent, T026 orchestrates all

**Phase 6 - User Story 4**: T027 and T028 can run in parallel (analysis vs formatting), T029 integrates both

**Phase 7 - CLI & Polish**: T033, T034, T035, T036, T037, T038, T039, T040 can all run in parallel (different files/concerns), T030-T032 are sequential for CLI core, T041 runs last

---

## Parallel Example: Phase 2 - Foundational

```bash
# Launch all model and helper tasks together:
Task: "Implement Core Data helpers in src/lib/core_data.py"
Task: "Create data models in src/photo_sync/models/__init__.py"
Task: "Create result models in src/photo_sync/models/sync_result.py"

# After models complete, launch query and mutation tasks:
Task: "Implement base query functions in src/photo_sync/db/queries.py"
Task: "Implement base mutation functions in src/photo_sync/db/mutations.py"
```

---

## Parallel Example: User Story 1

```bash
# Launch identification and file copy together:
Task: "Implement photo identification logic in src/photo_sync/operations/photo_sync.py"
Task: "Implement file copy operation in src/photo_sync/operations/file_copy.py"

# After identification completes, implement insertion and moment management:
Task: "Implement photo insertion in src/photo_sync/operations/photo_sync.py"
Task: "Implement moment management in src/photo_sync/operations/photo_sync.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001-T005)
2. Complete Phase 2: Foundational (T006-T012) - CRITICAL
3. Complete Phase 3: User Story 1 (T013-T017)
4. Complete Phase 7 minimal CLI (T030-T032) for testing
5. **STOP and VALIDATE**: Add a new photo to source, run sync, verify it appears in target
6. This is a working MVP that solves the core use case!

### Incremental Delivery

1. Complete Setup + Foundational → Foundation ready
2. Add User Story 1 → Test independently → **MVP deployed!** (Photo additions work)
3. Add User Story 2 → Test independently → **v1.1 deployed** (Photo deletions work)
4. Add User Story 3 → Test independently → **v1.2 deployed** (Album sync works)
5. Add User Story 4 → Test independently → **v1.3 deployed** (Dry-run preview works)
6. Add User Story 5 → Test independently → **v1.4 deployed** (Favourites sync works)
7. Add CLI polish → **v2.0 deployed** (Full feature set with all options)

### Parallel Team Strategy

With multiple developers:

1. Team completes Setup + Foundational together (T001-T012)
2. Once Foundational is done:
   - Developer A: User Story 1 (T013-T017)
   - Developer B: User Story 2 (T018-T020)
   - Developer C: User Story 3 (T021-T026)
3. Developer D: User Story 4 after US1-3 complete (T027-T029)
4. Team: CLI & Polish together (T030-T040)

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- Source database is ALWAYS read-only (`?mode=ro`)
- Target database is read-write (required for sync functionality)
- Use transactions for all multi-table inserts to prevent corruption
- Handle database locks with retry logic (exponential backoff)
- All timestamps use Core Data epoch (2001-01-01 00:00:00 UTC)
- Z_PRIMARYKEY must be updated for every entity insert
- Soft delete (ZTRASHEDSTATE=1) is preferred over hard delete
- UUID-based matching (not Z_PK) since target is a copy of source
