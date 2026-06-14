# Feature Specification: Library Sync

**Feature**: `20260208-library-sync-append`
**Created**: 2026-02-08
**Status**: Draft
**Input**: User description: "I want to synchronize photos and albums between two photo libraries. The source path is /Users/you/Pictures/Photos\ Library.photoslibrary, while the target path is /Users/you/Pictures/Photos\ Library\ copy.photoslibrary. The target library is copied from the source library, so you can use UUID to sync the files. The way I usually use the library is that I keep adding new photos to source library. So the target library often falls behind. You just need to append the new photos to the target library. I may delete photos in the old library, but it's not required to sync the deleted photos as it's not important. The must-have information to sync is the photo files and albums."

## Overview

Synchronize photos and albums from a source Apple Photos library to a target library. The target library is a copy of the source, enabling UUID-based matching to identify changes.

### Configuration

- **Source Library**: `/Users/you/Pictures/Photos Library.photoslibrary`
- **Target Library**: `/Users/you/Pictures/Photos Library copy.photoslibrary`
- **Sync Direction**: One-way (source → target)
- **Sync Mode**: Full sync (additions, deletions, and album changes)
- **Matching Strategy**: UUID-based (target is a copy of source)

### Scope

**In Scope (Must-Have)**:
- Photo files synchronization (new photos)
- Photo deletion synchronization (remove photos deleted in source)
- Album synchronization (new albums)
- Album membership changes (photos added to/removed from albums)

**In Scope (Nice-to-Have)**:
- Favourites synchronization (sync favourite status from source to target)

**Out of Scope**:
- Metadata beyond album membership and favourites
- Bi-directional sync

## Clarifications

### Session 2026-02-08

- Q: Should deleted photos be synced? → A: Yes, sync deleted photos from source to target
- Q: Should album membership changes be synced? → A: Yes, if photo's album changes in source, sync to target
- Q: How many tables need to be synced per photo? → A: Photos.sqlite has 89 tables. A photo touches 7+ core tables plus 10+ ML analysis tables. See Key Entities section for full breakdown. Recommended: Sync core tables only, let Photos app regenerate ML data.
- Q: Should progress be shown during time-intensive operations? → A: Yes, display progress percentage when handling many files or batch operations
- Q: How should favourites sync behave? → A: One-way sync (source → target), matching existing sync direction
- Q: What priority for favourites sync? → A: P5 (nice-to-have, lower than existing features)

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Sync New Photos (Priority: P1)

As a user who regularly adds photos to my source library, I want to append all new photos to my target library so that my backup stays current without manual copying.

The source library continuously receives new photos ("I keep adding new photos to source library"). The target library is a previous copy that falls behind over time ("the target library often falls behind"). The sync identifies photos in source that don't exist in target (by UUID) and copies them to the target library ("you can use UUID to sync the files").

**Why this priority**: This is the core functionality - without syncing photo files, the feature has no value. Photos are explicitly listed as must-have: "The must-have information to sync is the photo files and albums."

**Technical Implementation**:

1. **Database Access**:
   - Open source `Photos.sqlite` in read-only mode
   - Open target `Photos.sqlite` in read-write mode (required for inserting new records)

2. **Identify New Photos**:
   ```sql
   -- Get all photo UUIDs from source
   SELECT ZUUID, Z_PK, ZFILENAME, ZDIRECTORY, ZKIND, ZDATECREATED,
          ZADDEDDATE, ZWIDTH, ZHEIGHT, ZORIENTATION, ZDURATION
   FROM ZASSET
   WHERE ZTRASHEDSTATE = 0

   -- Compare against target UUIDs to find missing
   SELECT ZUUID FROM ZASSET WHERE ZTRASHEDSTATE = 0
   ```

3. **Copy Photo Files**:
   - Source path: `<source>/originals/<ZDIRECTORY>/<ZFILENAME>`
   - Target path: `<target>/originals/<ZDIRECTORY>/<ZFILENAME>`
   - Preserve directory structure

4. **Insert Database Records** (multiple tables required):
   - Insert into `ZASSET` table with matching UUID
   - Insert into `ZADDITIONALASSETATTRIBUTES` (1:1, linked via ZASSET.ZADDITIONALATTRIBUTES)
   - Insert into `ZEXTENDEDATTRIBUTES` (1:1, linked via ZASSET.ZEXTENDEDATTRIBUTES)
   - Insert into `ZINTERNALRESOURCE` (~2 records per photo for file variants)
   - Create or link to `ZMOMENT` (time cluster)
   - Update `Z_PRIMARYKEY` table for each entity type to track next available PK
   - Preserve Core Data entity/opt fields (Z_ENT, Z_OPT) appropriately
   - **Note**: ML analysis tables (ZPHOTOANALYSISASSETATTRIBUTES, ZSCENECLASSIFICATION, etc.) can be skipped - Photos app will regenerate

**Independent Test**: Can be fully tested by adding a new photo to source library, running sync, and verifying the photo appears in target library's originals folder and database.

**Acceptance Scenarios**:

1. **Given** source library has 100 photos and target has 90 photos (same first 90 by UUID), **When** sync runs, **Then** 10 new photos are copied to target and target database has 100 photo records
2. **Given** source and target have identical photos, **When** sync runs, **Then** no files are copied and sync completes successfully with "0 new photos" message
3. **Given** source has a new photo added today, **When** sync runs, **Then** that specific photo file exists in target's originals folder with correct directory structure

---

### User Story 2 - Sync Deleted Photos (Priority: P2)

As a user who deletes photos from my source library, I want those deletions to be reflected in my target library so that both libraries stay consistent.

When photos are deleted (or moved to Recently Deleted) in the source library, the sync should remove them from the target library as well.

**Why this priority**: User explicitly requested deletion sync: "I also want you to sync deleted photos."

**Technical Implementation**:

1. **Identify Deleted Photos**:
   ```sql
   -- Find photos in target that no longer exist (or are trashed) in source
   -- Photos in target with UUIDs not found in source active photos
   SELECT t.ZUUID, t.Z_PK, t.ZFILENAME, t.ZDIRECTORY
   FROM target.ZASSET t
   WHERE t.ZTRASHEDSTATE = 0
     AND t.ZUUID NOT IN (
       SELECT s.ZUUID FROM source.ZASSET s WHERE s.ZTRASHEDSTATE = 0
     )
   ```

2. **Delete from Target**:
   - Option A: Set `ZTRASHEDSTATE = 1` and `ZTRASHEDDATE` (soft delete - move to Recently Deleted)
   - Option B: Delete database records and files (hard delete)
   - **Recommended**: Soft delete to match Photos app behavior and allow recovery

3. **Clean Up Related Records** (multiple tables):
   - Remove from `Z_33ASSETS` (album memberships)
   - Update `ZCACHEDCOUNT` for affected albums
   - For soft delete: Just set ZTRASHEDSTATE=1, keep related records
   - For hard delete, also remove from:
     - `ZADDITIONALASSETATTRIBUTES`
     - `ZEXTENDEDATTRIBUTES`
     - `ZINTERNALRESOURCE`
     - `ZDETECTEDFACE` (and related ZFACECROP, ZDETECTEDFACEPRINT)
     - ML analysis tables (ZPHOTOANALYSISASSETATTRIBUTES, ZSCENECLASSIFICATION, etc.)

4. **Delete Photo Files** (if hard delete):
   - Remove from `<target>/originals/<ZDIRECTORY>/<ZFILENAME>`

**Independent Test**: Can be tested by deleting a photo from source library, running sync, and verifying the photo is removed (or trashed) in target.

**Acceptance Scenarios**:

1. **Given** source has 100 photos and target has 100 photos, **When** user deletes 5 photos from source and sync runs, **Then** target has 95 active photos (5 are trashed or deleted)
2. **Given** a photo is moved to Recently Deleted in source, **When** sync runs, **Then** the same photo is moved to Recently Deleted in target
3. **Given** a photo exists only in target (was deleted from source before), **When** sync runs, **Then** that photo is removed from target

---

### User Story 3 - Sync Album Membership (Priority: P3)

As a user who organizes photos into albums, I want album membership changes to be synced so that my organizational structure is preserved.

When photos are added to or removed from albums in the source library, those changes should be reflected in the target library. This includes:
- New photos added to existing albums
- Existing photos added to albums
- Photos removed from albums

**Why this priority**: User explicitly requested: "If I change the photo's album in the source library, you also need to sync the change to the target."

**Technical Implementation**:

1. **Sync Album Definitions**:
   ```sql
   -- Get user albums from source (ZKIND = 2)
   SELECT Z_PK, ZUUID, ZTITLE, ZKIND, ZPARENTFOLDER, ZCREATIONDATE
   FROM ZGENERICALBUM
   WHERE ZKIND = 2 AND ZTRASHEDSTATE = 0 AND ZTITLE IS NOT NULL
   ```

2. **Identify Album Membership Changes**:
   ```sql
   -- Get all album memberships from source
   SELECT G.ZUUID as album_uuid, A.ZUUID as asset_uuid
   FROM Z_33ASSETS J
   JOIN ZGENERICALBUM G ON G.Z_PK = J.Z_33ALBUMS
   JOIN ZASSET A ON A.Z_PK = J.Z_3ASSETS
   WHERE G.ZKIND = 2 AND G.ZTRASHEDSTATE = 0 AND A.ZTRASHEDSTATE = 0

   -- Compare with target to find:
   -- 1. New memberships (in source, not in target) → INSERT
   -- 2. Removed memberships (in target, not in source) → DELETE
   ```

3. **Sync Album Membership**:
   - **Add**: Insert new rows into `Z_33ASSETS` for photos added to albums
   - **Remove**: Delete rows from `Z_33ASSETS` for photos removed from albums
   - Update `ZCACHEDCOUNT`, `ZCACHEDPHOTOSCOUNT`, `ZCACHEDVIDEOSCOUNT` for affected albums

4. **Insert New Albums in Target**:
   - Insert new albums into `ZGENERICALBUM`
   - Preserve folder hierarchy via `ZPARENTFOLDER`

**Independent Test**: Can be tested by adding/removing a photo from an album in source, running sync, and verifying the album membership matches in target.

**Acceptance Scenarios**:

1. **Given** source has album "Vacation 2026" with 20 photos, **When** sync runs on a target without this album, **Then** target has album "Vacation 2026" with the same 20 photos
2. **Given** source album "Family" has 5 new photos added since last sync, **When** sync runs, **Then** target album "Family" contains those 5 additional photos
3. **Given** a photo is removed from album "Work" in source, **When** sync runs, **Then** the photo is also removed from album "Work" in target
4. **Given** a photo is moved from album "A" to album "B" in source, **When** sync runs, **Then** target reflects the same change (photo in B, not in A)

---

### User Story 4 - Sync Preview/Report Mode (Priority: P4)

As a user, I want to preview what will be synced before actually syncing so that I can verify the operation and avoid unexpected changes.

A dry-run mode that shows what would be synced without making changes.

**Why this priority**: This is a safety feature that improves user confidence but isn't strictly required for the core sync functionality.

**Technical Implementation**:

1. **Dry-Run Flag**: `--dry-run` or `--preview` CLI option
2. **Output Report**:
   - Number of new photos to sync
   - Number of photos to delete
   - List of photo filenames affected
   - Number of new albums to create
   - Number of album membership additions
   - Number of album membership removals
   - Total data size to copy

**Independent Test**: Can be tested by running with `--dry-run`, verifying output shows expected changes, and confirming no files were actually copied or deleted.

**Acceptance Scenarios**:

1. **Given** 10 new photos need syncing and 3 need deleting, **When** running with `--dry-run`, **Then** output shows "10 photos to add, 3 photos to delete" and no changes are made
2. **Given** sync would create 2 new albums, **When** running with `--dry-run`, **Then** output lists the 2 album names

---

### User Story 5 - Sync Favourites (Priority: P5)

As a user who marks photos as favourites, I want my favourite status to be synced to the target library so that my favourite photos are consistent across both libraries.

When photos are added to or removed from favourites in the source library, those changes should be reflected in the target library.

**Why this priority**: This is a nice-to-have feature. Core sync functionality (photos, deletions, albums) takes precedence.

**Technical Implementation**:

1. **Identify Favourite Changes**:
   ```sql
   -- Find photos where favourite status differs between source and target
   SELECT s.ZUUID, s.ZFAVORITE as source_fav, t.ZFAVORITE as target_fav
   FROM source.ZASSET s
   JOIN target.ZASSET t ON s.ZUUID = t.ZUUID
   WHERE s.ZTRASHEDSTATE = 0 AND t.ZTRASHEDSTATE = 0
     AND s.ZFAVORITE != t.ZFAVORITE
   ```

2. **Update Target Favourites**:
   ```sql
   -- Update favourite status in target to match source
   UPDATE ZASSET SET ZFAVORITE = ? WHERE ZUUID = ?
   ```

3. **Note**: New photos synced via User Story 1 will automatically have their favourite status copied as part of the full record copy.

**Independent Test**: Can be tested by marking/unmarking a photo as favourite in source, running sync, and verifying the favourite status matches in target.

**Acceptance Scenarios**:

1. **Given** a photo is marked as favourite in source but not in target, **When** sync runs, **Then** the photo is marked as favourite in target
2. **Given** a photo is unmarked as favourite in source but still favourite in target, **When** sync runs, **Then** the photo is unmarked as favourite in target
3. **Given** 5 photos have favourite status changes, **When** sync runs, **Then** all 5 photos have matching favourite status in target

---

### Edge Cases

- What happens when source library is locked by Photos app? → Retry with delay or report error
- What happens when target disk is full? → Report error with space required vs available
- What happens when a photo file exists in source DB but file is missing on disk? → Skip and log warning
- What happens when target already has a file with same path but different content? → Skip (UUID match means same photo)
- How to handle photos in "Recently Deleted" (ZTRASHEDSTATE=1)? → Treat as deleted; if in source Recently Deleted, delete from target
- What happens when a photo is deleted from source? → Delete (or trash) the photo in target
- What happens when album membership changes? → Sync the change (add or remove from album in target)

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST read source library database in read-only mode
- **FR-002**: System MUST identify new photos by comparing UUIDs between source and target
- **FR-003**: System MUST copy photo files preserving the `originals/<ZDIRECTORY>/<ZFILENAME>` structure
- **FR-004**: System MUST insert corresponding database records for synced photos
- **FR-005**: System MUST sync user album definitions (ZKIND=2) from source to target
- **FR-006**: System MUST sync album-photo membership relationships (additions and removals)
- **FR-007**: System MUST sync photo deletions from source to target
- **FR-008**: System MUST report number of photos added, deleted, and album changes upon completion
- **FR-009**: System MUST handle database locks gracefully with appropriate error messages
- **FR-010**: System MUST update album cached counts after membership changes
- **FR-011**: System MUST display progress percentage during time-intensive operations (file copying, batch processing) to provide user feedback
- **FR-012**: System SHOULD sync favourite status from source to target (one-way sync)

### Key Entities

**WARNING**: The Photos.sqlite database has 89 tables. A single photo import touches many related tables. The following is a comprehensive list of tables that need to be synced for each photo.

#### Core Tables (Required for basic sync)

| Table | Relationship | Description |
|-------|--------------|-------------|
| `ZASSET` | Primary | Core photo/video entity. UUID, filename, directory, timestamps, dimensions |
| `ZADDITIONALASSETATTRIBUTES` | 1:1 with ZASSET | Original filename, file size, import source, timezone, location data |
| `ZEXTENDEDATTRIBUTES` | 1:1 with ZASSET | Extended photo attributes |
| `ZINTERNALRESOURCE` | 1:N with ZASSET | File variants (original ~2 per photo: original + derivative) |
| `ZGENERICALBUM` | Independent | Album definitions (ZKIND=2 for user albums) |
| `Z_33ASSETS` | Join table | Album-photo membership relationships |
| `ZMOMENT` | N:1 from ZASSET | Time+location clusters (may need to create/update) |

#### Analysis Tables (ML-generated, may be regenerated by Photos app)

| Table | Relationship | Description |
|-------|--------------|-------------|
| `ZMEDIAANALYSISASSETATTRIBUTES` | 1:1 with ZASSET | Media analysis results |
| `ZPHOTOANALYSISASSETATTRIBUTES` | 1:1 with ZASSET | Photo-specific analysis |
| `ZCOMPUTEDASSETATTRIBUTES` | 1:1 with ZASSET | Computed attributes (aesthetic scores, etc.) |
| `ZSCENECLASSIFICATION` | 1:N (~42 per photo!) | ML scene tags/classifications |
| `ZCHARACTERRECOGNITIONATTRIBUTES` | 1:1 with ZASSET | OCR/text recognition data |
| `ZVISUALSEARCHATTRIBUTES` | 1:1 with ZASSET | Visual search data |
| `ZDETECTEDFACE` | 1:N with ZASSET | Detected faces in photos |
| `ZDETECTEDFACEPRINT` | 1:1 with ZDETECTEDFACE | Face embeddings |
| `ZFACECROP` | 1:1 with ZDETECTEDFACE | Cropped face images |
| `ZPERSON` | Independent | Named people (linked via ZDETECTEDFACE) |

#### System Tables (Core Data infrastructure)

| Table | Description |
|-------|-------------|
| `Z_PRIMARYKEY` | Next available primary key for each entity type - MUST be updated |
| `Z_METADATA` | Core Data metadata and model version |
| `Z_MODELCACHE` | Model cache |

#### Sync Strategy Decision

**Option A: Minimal Sync (Recommended for MVP)**
- Sync only: `ZASSET`, `ZADDITIONALASSETATTRIBUTES`, `ZEXTENDEDATTRIBUTES`, `ZINTERNALRESOURCE`, `ZGENERICALBUM`, `Z_33ASSETS`
- Skip ML/analysis tables - Photos app will regenerate them
- Pros: Simpler, less risk of corruption
- Cons: Target library will need time to rebuild ML data

**Option B: Full Sync**
- Sync all tables including ML analysis data
- Pros: Immediate feature parity
- Cons: Complex, higher risk, may conflict with Photos app analysis

**Option C: Copy-based Sync**
- For new photos: Copy all related records from source
- For deletions: Mark as trashed or delete all related records
- Pros: Preserves all data
- Cons: Need to handle Z_PK remapping if IDs conflict

#### Database Record Counts (Current Library)

Based on analysis of source library with 466 photos:
- `ZASSET`: 466 records
- `ZADDITIONALASSETATTRIBUTES`: 466 records (1:1)
- `ZEXTENDEDATTRIBUTES`: 466 records (1:1)
- `ZINTERNALRESOURCE`: 1,048 records (~2.2 per photo)
- `ZPHOTOANALYSISASSETATTRIBUTES`: 466 records (1:1)
- `ZMEDIAANALYSISASSETATTRIBUTES`: 477 records
- `ZCOMPUTEDASSETATTRIBUTES`: 465 records
- `ZDETECTEDFACE`: 383 records (faces detected)
- `ZSCENECLASSIFICATION`: 19,423 records (~42 per photo!)
- `ZCHARACTERRECOGNITIONATTRIBUTES`: 476 records
- `ZMOMENT`: 79 records (time clusters)
- `ZGENERICALBUM`: 314 records (albums/folders/smart albums)
- `Z_33ASSETS`: 88 records (album memberships)

### Assumptions

- Target library was originally copied from source library (UUIDs match for existing photos) - per user: "The target library is copied from the source library"
- Both libraries use the same Photos.sqlite schema version
- User has read access to source and write access to target
- Photos app is not actively modifying target library during sync
- Core Data entity IDs (Z_ENT) are consistent between libraries
- Z_PK values in target may differ from source (need UUID-based matching, not PK-based)
- ML analysis tables can be regenerated by Photos app if not synced

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Users can sync a library with 1000 changes (adds/deletes/album changes) in under 10 minutes (excluding file copy time based on disk speed)
- **SC-002**: 100% of new photos from source appear in target after sync
- **SC-003**: 100% of deleted photos from source are removed from target after sync
- **SC-004**: 100% of album memberships match between source and target after sync
- **SC-005**: Zero data corruption in target library after sync (library opens normally in Photos app)
- **SC-006**: Sync can be run repeatedly with same result (idempotent) - running twice produces no duplicate entries or errors
- **SC-007**: Users can preview sync changes before execution via dry-run mode
