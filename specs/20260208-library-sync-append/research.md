# Research: Library Sync

**Feature**: `20260208-library-sync-append`
**Date**: 2026-02-08

## Research Questions

### 1. Core Data Z_ENT and Z_OPT Values

**Question**: What are the correct Z_ENT values for each entity type?

**Decision**: Use values from Z_PRIMARYKEY table

**Research Findings**:
```sql
SELECT Z_ENT, Z_NAME, Z_MAX FROM Z_PRIMARYKEY ORDER BY Z_ENT;
```

Key entity types:
| Z_ENT | Z_NAME | Description |
|-------|--------|-------------|
| 1 | AdditionalAssetAttributes | ZADDITIONALASSETATTRIBUTES |
| 3 | Asset | ZASSET |
| 28 | ExtendedAttributes | ZEXTENDEDATTRIBUTES |
| 32 | GenericAlbum | ZGENERICALBUM |
| 51 | InternalResource | ZINTERNALRESOURCE |
| 58 | Moment | ZMOMENT |

**Z_OPT**: Optimistic locking counter. Start at 1 for new records, increment on updates.

**Rationale**: Z_ENT values are fixed per entity type and must match exactly for Core Data to recognize records.

---

### 2. ZINTERNALRESOURCE Structure

**Question**: How many ZINTERNALRESOURCE records per photo and what are the required fields?

**Decision**: Create 1-2 records per photo (original + optional derivative)

**Research Findings**:
```sql
SELECT ZRESOURCETYPE, COUNT(*) FROM ZINTERNALRESOURCE GROUP BY ZRESOURCETYPE;
```

| ZRESOURCETYPE | Meaning | Required |
|---------------|---------|----------|
| 0 | Original file | Yes |
| 1 | Edited version | No (only if edited) |
| 3 | Derivative | Sometimes |

**Required Fields**:
- `ZASSET` - FK to ZASSET.Z_PK
- `ZRESOURCETYPE` - 0 for original
- `ZDATALENGTH` - File size in bytes
- `ZLOCALAVAILABILITY` - 1 for local, -1 for cloud-only
- `ZFINGERPRINT` - Content hash (can be NULL)

**Rationale**: Minimal viable sync only needs the original file resource (type 0).

---

### 3. ZMOMENT Handling

**Question**: Should we create new moments or reuse existing ones?

**Decision**: Link to existing moments by date range, or create new if needed

**Research Findings**:
Moments are time+location clusters. Photos within the same time range share a moment.

```sql
SELECT Z_PK, ZSTARTDATE, ZENDDATE, ZCACHEDCOUNT
FROM ZMOMENT
ORDER BY ZSTARTDATE DESC LIMIT 5;
```

**Strategy**:
1. Find moment that contains photo's ZDATECREATED
2. If found, link to existing moment
3. If not found, create new moment with photo's date as start/end
4. Update moment's ZCACHEDCOUNT

**Rationale**: Reusing moments maintains library organization. Creating new moments is safe if no match.

---

### 4. Album Folder Hierarchy

**Question**: How to handle album folders (ZKIND=4000)?

**Decision**: Sync folders along with albums, preserve ZPARENTFOLDER relationships

**Research Findings**:
```sql
SELECT Z_PK, ZTITLE, ZKIND, ZPARENTFOLDER
FROM ZGENERICALBUM
WHERE ZKIND IN (2, 4000) AND ZTRASHEDSTATE = 0;
```

Folder hierarchy:
- ZKIND=3999: Root folder (system)
- ZKIND=4000: User folder
- ZKIND=2: User album

**Strategy**:
1. Sync folders (ZKIND=4000) first
2. Then sync albums (ZKIND=2)
3. Preserve ZPARENTFOLDER by UUID lookup

**Rationale**: Albums may be nested in folders; must sync folders first to establish parent references.

---

### 5. Database Locking Strategy

**Question**: How to handle Photos app holding locks on the database?

**Decision**: Retry with exponential backoff, max 3 attempts

**Research Findings**:
SQLite error when locked: `SQLITE_BUSY` (error code 5)

**Strategy**:
```python
def connect_with_retry(path, mode='ro', max_retries=3):
    for attempt in range(max_retries):
        try:
            return sqlite3.connect(f"file:{path}?mode={mode}", uri=True)
        except sqlite3.OperationalError as e:
            if "database is locked" in str(e):
                time.sleep(2 ** attempt)  # 1s, 2s, 4s
            else:
                raise
    raise Exception("Database locked after max retries")
```

**Rationale**: Photos app may briefly lock DB during operations. Short retry usually succeeds.

---

### 6. File Copy Verification

**Question**: Should we verify file integrity after copy?

**Decision**: Optional checksum verification, disabled by default for performance

**Research Findings**:
- `shutil.copy2()` preserves metadata and is reliable
- Checksum adds ~10% overhead for large files
- Disk errors are rare on modern systems

**Strategy**:
- Default: Trust `shutil.copy2()` success
- Optional `--verify` flag: Compare SHA256 checksums
- Log warning if source file missing (DB record exists but file doesn't)

**Rationale**: Performance over paranoia for typical use. Verification available for critical syncs.

---

### 7. Transaction Strategy

**Question**: How to ensure atomicity of multi-table inserts?

**Decision**: Use SQLite transactions, rollback on any failure

**Research Findings**:
Core Data uses transactions internally. We should too:

```python
conn.execute("BEGIN TRANSACTION")
try:
    # Insert ZASSET
    # Insert ZADDITIONALASSETATTRIBUTES
    # Insert ZEXTENDEDATTRIBUTES
    # Insert ZINTERNALRESOURCE
    # Update Z_PRIMARYKEY
    conn.execute("COMMIT")
except:
    conn.execute("ROLLBACK")
    raise
```

**Rationale**: Partial inserts would corrupt the database. All-or-nothing is essential.

---

## Alternatives Considered

### Full Table Sync (Rejected)

**What**: Sync all 17+ tables per photo including ML analysis

**Why Rejected**:
- 42x more ZSCENECLASSIFICATION records to sync
- ML data may conflict with Photos app analysis
- Higher risk of corruption
- Photos app regenerates ML data anyway

### Hard Delete (Rejected)

**What**: DELETE records and files for removed photos

**Why Rejected**:
- More complex (must delete from many tables)
- No recovery option
- Soft delete matches Photos app behavior
- Photos app handles hard delete during "Empty Recently Deleted"

### Z_PK-Based Matching (Rejected)

**What**: Match records by Z_PK instead of UUID

**Why Rejected**:
- Z_PK may differ between libraries
- UUID is guaranteed unique and stable
- UUID matching is how Photos app works internally
