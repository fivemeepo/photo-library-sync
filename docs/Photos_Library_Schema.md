# Apple Photos Library SQLite Schema

Database location: `<library>.photoslibrary/database/Photos.sqlite`

All timestamps use **Apple's Core Data epoch** (2001-01-01 00:00:00 UTC).
To convert to Unix time: `TIMESTAMP + 978307200`.

---

## Database Overview

The Photos.sqlite database contains **89 tables** managed by Core Data. When a photo is imported, the Photos app creates/updates records across multiple tables.

### Table Categories

| Category | Tables | Description |
|----------|--------|-------------|
| Core Asset | 7 | Main photo/video data and metadata |
| Albums | 3 | Album definitions and memberships |
| ML Analysis | 10+ | Machine learning analysis results |
| Face Recognition | 6 | Face detection and people |
| Cloud Sync | 8 | iCloud sync state |
| System | 5 | Core Data infrastructure |

### Records Per Photo (Typical)

Based on analysis of a library with 466 photos:

| Table | Records | Ratio |
|-------|---------|-------|
| `ZASSET` | 466 | 1:1 |
| `ZADDITIONALASSETATTRIBUTES` | 466 | 1:1 |
| `ZEXTENDEDATTRIBUTES` | 466 | 1:1 |
| `ZINTERNALRESOURCE` | 1,048 | ~2.2:1 |
| `ZPHOTOANALYSISASSETATTRIBUTES` | 466 | 1:1 |
| `ZMEDIAANALYSISASSETATTRIBUTES` | 477 | ~1:1 |
| `ZCOMPUTEDASSETATTRIBUTES` | 465 | ~1:1 |
| `ZSCENECLASSIFICATION` | 19,423 | **~42:1** |
| `ZCHARACTERRECOGNITIONATTRIBUTES` | 476 | ~1:1 |
| `ZDETECTEDFACE` | 383 | varies |
| `ZMOMENT` | 79 | shared |

---

## Core Entity: ZASSET (Photos & Videos)

The central table. Each row is one photo or video in the library.

### Primary Columns

| Column | Type | Description |
|--------|------|-------------|
| `Z_PK` | INTEGER | Primary key |
| `Z_ENT` | INTEGER | Core Data entity type |
| `Z_OPT` | INTEGER | Core Data optimistic locking |
| `ZUUID` | VARCHAR | Unique identifier (UUID) |
| `ZFILENAME` | VARCHAR | On-disk filename, e.g. `B1245EFF-4352-41AB-96F4-9268624904E8.jpeg` |
| `ZDIRECTORY` | VARCHAR | Subdirectory under `originals/`, e.g. `B`, `3`, `A` |
| `ZKIND` | INTEGER | Media type: `0` = photo, `1` = video |
| `ZKINDSUBTYPE` | INTEGER | Subtype (screenshots, panoramas, etc.) |
| `ZWIDTH` / `ZHEIGHT` | INTEGER | Pixel dimensions |
| `ZORIENTATION` | INTEGER | EXIF orientation value |
| `ZDATECREATED` | TIMESTAMP | When the photo was originally taken/created |
| `ZADDEDDATE` | TIMESTAMP | When imported into the library |
| `ZMODIFICATIONDATE` | TIMESTAMP | Last edit timestamp |
| `ZADJUSTMENTTIMESTAMP` | TIMESTAMP | Last adjustment/edit timestamp |

### State Flags

| Column | Type | Description |
|--------|------|-------------|
| `ZTRASHEDSTATE` | INTEGER | `0` = active, `1` = in Recently Deleted |
| `ZTRASHEDDATE` | TIMESTAMP | When moved to trash |
| `ZTRASHEDREASON` | INTEGER | Reason for trashing |
| `ZFAVORITE` | INTEGER | `1` = marked as favorite |
| `ZHIDDEN` | INTEGER | `1` = hidden from main view |
| `ZVISIBILITYSTATE` | INTEGER | Visibility state |
| `ZCOMPLETE` | INTEGER | Whether asset is fully imported |

### Location Data

| Column | Type | Description |
|--------|------|-------------|
| `ZLATITUDE` | FLOAT | GPS latitude |
| `ZLONGITUDE` | FLOAT | GPS longitude |
| `ZLOCATIONDATA` | BLOB | Serialized location data |

### Media Properties

| Column | Type | Description |
|--------|------|-------------|
| `ZDURATION` | FLOAT | Video duration in seconds |
| `ZPLAYBACKSTYLE` | INTEGER | `4` = video |
| `ZHDRTYPE` | INTEGER | HDR type |
| `ZDEPTHTYPE` | INTEGER | Portrait mode depth type (non-zero = portrait) |
| `ZSPATIALTYPE` | INTEGER | Spatial/3D type |
| `ZAVALANCHEKIND` | INTEGER | Burst photo grouping |
| `ZAVALANCHEPICKTYPE` | INTEGER | Burst pick type |
| `ZAVALANCHEUUID` | VARCHAR | Burst group UUID |

### Foreign Keys

| Column | Type | Description |
|--------|------|-------------|
| `ZADDITIONALATTRIBUTES` | INTEGER | FK → `ZADDITIONALASSETATTRIBUTES.Z_PK` |
| `ZMOMENT` | INTEGER | FK → `ZMOMENT.Z_PK` |
| `ZIMPORTSESSION` | INTEGER | FK → import session |
| `ZCOMPUTEDATTRIBUTES` | INTEGER | FK → `ZCOMPUTEDASSETATTRIBUTES.Z_PK` |
| `ZEXTENDEDATTRIBUTES` | INTEGER | FK → `ZEXTENDEDATTRIBUTES.Z_PK` |
| `ZMEDIAANALYSISATTRIBUTES` | INTEGER | FK → `ZMEDIAANALYSISASSETATTRIBUTES.Z_PK` |
| `ZPHOTOANALYSISATTRIBUTES` | INTEGER | FK → `ZPHOTOANALYSISASSETATTRIBUTES.Z_PK` |

### Cloud Sync

| Column | Type | Description |
|--------|------|-------------|
| `ZCLOUDLOCALSTATE` | INTEGER | Local sync state |
| `ZCLOUDDELETESTATE` | INTEGER | Cloud delete state |
| `ZCLOUDASSETGUID` | VARCHAR | Cloud asset GUID |
| `ZCLOUDSERVERPUBLISHDATE` | TIMESTAMP | When published to cloud |
| `ZCLOUDBATCHPUBLISHDATE` | TIMESTAMP | Batch publish date |

### ML/Analysis Scores

| Column | Type | Description |
|--------|------|-------------|
| `ZCURATIONSCORE` | FLOAT | Curation score |
| `ZICONICSCORE` | FLOAT | How "iconic" the photo is |
| `ZOVERALLAESTHETICSCORE` | FLOAT | Overall aesthetic score |
| `ZPROMOTIONSCORE` | FLOAT | Promotion score |
| `ZHIGHLIGHTVISIBILITYSCORE` | FLOAT | Highlight visibility |
| `ZSTICKERCONFIDENCESCORE` | FLOAT | Sticker detection confidence |

**File on disk:** `originals/<ZDIRECTORY>/<ZFILENAME>`

---

## Additional Metadata: ZADDITIONALASSETATTRIBUTES

One-to-one with `ZASSET` (linked via `ZASSET` column → `ZASSET.Z_PK`).

### Primary Columns

| Column | Type | Description |
|--------|------|-------------|
| `Z_PK` | INTEGER | Primary key |
| `ZASSET` | INTEGER | FK → `ZASSET.Z_PK` |
| `ZORIGINALFILENAME` | VARCHAR | The file's name before import (e.g. `IMG_1234.JPG`) |
| `ZORIGINALFILESIZE` | INTEGER | Original file size in bytes |
| `ZORIGINALWIDTH` / `ZORIGINALHEIGHT` | INTEGER | Original dimensions |
| `ZORIGINALORIENTATION` | INTEGER | Original EXIF orientation |

### Import Information

| Column | Type | Description |
|--------|------|-------------|
| `ZIMPORTEDBYBUNDLEIDENTIFIER` | VARCHAR | App that imported it (e.g. `com.apple.mobileslideshow`) |
| `ZIMPORTEDBYDISPLAYNAME` | VARCHAR | Human-readable importer name |
| `ZIMPORTEDBY` | INTEGER | Import source type |
| `ZIMPORTSESSIONID` | VARCHAR | Import session identifier |

### Time & Location

| Column | Type | Description |
|--------|------|-------------|
| `ZTIMEZONENAME` | VARCHAR | Timezone of capture (e.g. `America/New_York`) |
| `ZTIMEZONEOFFSET` | INTEGER | UTC offset in seconds |
| `ZINFERREDTIMEZONEOFFSET` | INTEGER | Inferred timezone offset |
| `ZREVERSELOCATIONDATA` | BLOB | Serialized reverse geocode data |
| `ZREVERSELOCATIONDATAISVALID` | INTEGER | Whether location data is valid |
| `ZSHIFTEDLOCATIONDATA` | BLOB | Shifted location (privacy) |
| `ZSHIFTEDLOCATIONISVALID` | INTEGER | Whether shifted location is valid |
| `ZLOCATIONHASH` | INTEGER | Location hash for grouping |
| `ZPLACEANNOTATIONDATA` | BLOB | Place annotation data |

### Hashes & Fingerprints

| Column | Type | Description |
|--------|------|-------------|
| `ZORIGINALHASH` | BLOB | File content hash |
| `ZORIGINALSTABLEHASH` | VARCHAR | Stable perceptual hash (original) |
| `ZADJUSTEDSTABLEHASH` | VARCHAR | Stable perceptual hash (after edits) |

### Editing

| Column | Type | Description |
|--------|------|-------------|
| `ZEDITORBUNDLEID` | VARCHAR | App used for edits |
| `ZTITLE` | VARCHAR | User-assigned title |
| `ZACCESSIBILITYDESCRIPTION` | VARCHAR | Accessibility description |

### Analysis State

| Column | Type | Description |
|--------|------|-------------|
| `ZALLOWEDFORANALYSIS` | INTEGER | Whether ML analysis is allowed |
| `ZFACEANALYSISVERSION` | INTEGER | Face analysis version |
| `ZSCENEANALYSISVERSION` | INTEGER | Scene analysis version |
| `ZSCENEANALYSISTIMESTAMP` | TIMESTAMP | When scene analysis ran |
| `ZFACEREGIONS` | BLOB | Serialized face region data |

### Usage Stats

| Column | Type | Description |
|--------|------|-------------|
| `ZPLAYCOUNT` | INTEGER | Play count (videos) |
| `ZSHARECOUNT` | INTEGER | Share count |
| `ZVIEWCOUNT` | INTEGER | View count |
| `ZLASTVIEWEDDATE` | TIMESTAMP | Last viewed date |

---

## Albums: ZGENERICALBUM

All albums, folders, smart albums, and system collections live in this single table, differentiated by `ZKIND`.

### Primary Columns

| Column | Type | Description |
|--------|------|-------------|
| `Z_PK` | INTEGER | Primary key |
| `ZUUID` | VARCHAR | Unique identifier |
| `ZTITLE` | VARCHAR | Album display name |
| `ZKIND` | INTEGER | Type of album (see below) |
| `ZPARENTFOLDER` | INTEGER | FK → `ZGENERICALBUM.Z_PK` (for nesting albums in folders) |
| `ZCREATIONDATE` | TIMESTAMP | When album was created |
| `ZSTARTDATE` / `ZENDDATE` | TIMESTAMP | Date range of contents |
| `ZTRASHEDSTATE` | INTEGER | `0` = active |
| `ZTRASHEDDATE` | TIMESTAMP | When trashed |

### Counts

| Column | Type | Description |
|--------|------|-------------|
| `ZCACHEDCOUNT` | INTEGER | Total item count |
| `ZCACHEDPHOTOSCOUNT` | INTEGER | Photo count |
| `ZCACHEDVIDEOSCOUNT` | INTEGER | Video count |
| `ZPENDINGITEMSCOUNT` | INTEGER | Pending items |

### Sorting

| Column | Type | Description |
|--------|------|-------------|
| `ZCUSTOMSORTKEY` | INTEGER | Sort field for custom ordering |
| `ZCUSTOMSORTASCENDING` | INTEGER | Sort direction |
| `ZCUSTOMKEYASSET` | INTEGER | FK → key asset for album cover |

### Cloud Sync

| Column | Type | Description |
|--------|------|-------------|
| `ZCLOUDLOCALSTATE` | INTEGER | Local sync state |
| `ZCLOUDDELETESTATE` | INTEGER | Cloud delete state |
| `ZCLOUDGUID` | VARCHAR | Cloud GUID |
| `ZCLOUDCREATIONDATE` | TIMESTAMP | Cloud creation date |
| `ZCLOUDLASTCONTRIBUTIONDATE` | TIMESTAMP | Last cloud contribution |

### Shared Albums

| Column | Type | Description |
|--------|------|-------------|
| `ZCLOUDOWNERFIRSTNAME` | VARCHAR | Owner first name |
| `ZCLOUDOWNERLASTNAME` | VARCHAR | Owner last name |
| `ZCLOUDOWNERFULLNAME` | VARCHAR | Owner full name |
| `ZCLOUDOWNERHASHEDPERSONID` | VARCHAR | Owner hashed ID |
| `ZCLOUDPERSONID` | VARCHAR | Cloud person ID |
| `ZPUBLICURL` | VARCHAR | Public URL (if enabled) |
| `ZISOWNED` | INTEGER | Whether current user owns it |

### ZKIND Values

| Kind | Meaning |
|------|---------|
| `2` | **Regular user album** (the main ones with photos) |
| `4000` | **Folder** (groups albums, has no photos directly) |
| `1506` | System smart album (various types) |
| `1509` | Date-based smart album |
| `1552` | People album |
| `1600` | Selfies |
| `1601` | Recently Added |
| `1602` | Screenshots |
| `1605` | Live Photos |
| `1606` | Recently Deleted |
| `1607` | Videos |
| `1608` | Slo-mo |
| `1609` | Time-lapse |
| `1610` | Bursts |
| `1611` | Panoramas |
| `1612` | Portrait |
| `3571` | Sync progress |
| `3572` | OTA restore progress |
| `3573` | File-system import progress |
| `3998` | Root folder |
| `3999` | Top-level user folder |

### Folder Hierarchy

Albums can be nested inside folders via `ZPARENTFOLDER`:

```
ZGENERICALBUM (kind=3999, Root Folder)
  └── ZGENERICALBUM (kind=4000, Folder: "Travel")
        └── ZGENERICALBUM (kind=2, Album: "Paris 2024")  ← contains actual photos
```

---

## Album ↔ Asset Join: Z_33ASSETS

Many-to-many relationship between albums and assets.

| Column | Type | Description |
|--------|------|-------------|
| `Z_33ALBUMS` | INTEGER | FK → `ZGENERICALBUM.Z_PK` |
| `Z_3ASSETS` | INTEGER | FK → `ZASSET.Z_PK` |
| `Z_FOK_3ASSETS` | INTEGER | Foreign key optimization |

**Primary Key:** (`Z_33ALBUMS`, `Z_3ASSETS`)

### Example: Get all photos in album "2025 CNY"

```sql
SELECT A.ZFILENAME, A.ZDIRECTORY,
       datetime(A.ZDATECREATED + 978307200, 'unixepoch', 'localtime') as created
FROM ZASSET A
JOIN Z_33ASSETS J ON J.Z_3ASSETS = A.Z_PK
JOIN ZGENERICALBUM G ON G.Z_PK = J.Z_33ALBUMS
WHERE G.ZTITLE = '2025 CNY' AND G.ZKIND = 2 AND A.ZTRASHEDSTATE = 0
ORDER BY A.ZDATECREATED DESC;
```

---

## Keywords: ZKEYWORD + Z_1KEYWORDS

### ZKEYWORD

| Column | Type | Description |
|--------|------|-------------|
| `Z_PK` | INTEGER | Primary key |
| `ZTITLE` | VARCHAR | Keyword text (unique) |
| `ZUUID` | VARCHAR | Unique identifier |
| `ZSHORTCUT` | VARCHAR | Keyboard shortcut |

### Z_1KEYWORDS (Join Table)

| Column | Type | Description |
|--------|------|-------------|
| `Z_1ASSETATTRIBUTES` | INTEGER | FK → `ZADDITIONALASSETATTRIBUTES.Z_PK` |
| `Z_52KEYWORDS` | INTEGER | FK → `ZKEYWORD.Z_PK` |

---

## Moments: ZMOMENT

Auto-generated time+location groupings (the clusters you see in the Photos "Library" view).

| Column | Type | Description |
|--------|------|-------------|
| `Z_PK` | INTEGER | Primary key |
| `ZUUID` | VARCHAR | Unique identifier |
| `ZTITLE` | VARCHAR | Auto-generated title |
| `ZSUBTITLE` | VARCHAR | Auto-generated subtitle |
| `ZSTARTDATE` | TIMESTAMP | Start of time range |
| `ZENDDATE` | TIMESTAMP | End of time range |
| `ZREPRESENTATIVEDATE` | TIMESTAMP | Representative date |
| `ZAPPROXIMATELATITUDE` | FLOAT | Center latitude |
| `ZAPPROXIMATELONGITUDE` | FLOAT | Center longitude |
| `ZGPSHORIZONTALACCURACY` | FLOAT | GPS accuracy |
| `ZCACHEDCOUNT` | INTEGER | Number of items |
| `ZCACHEDPHOTOSCOUNT` | INTEGER | Number of photos |
| `ZCACHEDVIDEOSCOUNT` | INTEGER | Number of videos |
| `ZTRASHEDSTATE` | INTEGER | Trashed state |
| `ZPROCESSEDLOCATION` | INTEGER | Whether location was processed |
| `ZTIMEZONEOFFSET` | INTEGER | Timezone offset |
| `ZLOCALIZEDLOCATIONNAMES` | BLOB | Serialized location names |
| `ZHIGHLIGHT` | INTEGER | FK → highlight |

Assets link to moments via `ZASSET.ZMOMENT` → `ZMOMENT.Z_PK`.

---

## Faces & People: ZPERSON + ZDETECTEDFACE

### ZPERSON (Named People)

| Column | Type | Description |
|--------|------|-------------|
| `Z_PK` | INTEGER | Primary key |
| `ZPERSONUUID` | VARCHAR | Unique identifier |
| `ZDISPLAYNAME` | VARCHAR | User-assigned display name |
| `ZFULLNAME` | VARCHAR | Full name |
| `ZFACECOUNT` | INTEGER | Number of detected faces |
| `ZKEYFACE` | INTEGER | FK → `ZDETECTEDFACE.Z_PK` (representative face) |
| `ZDETECTIONTYPE` | INTEGER | How detected |
| `ZVERIFIEDTYPE` | INTEGER | Whether user-confirmed |
| `ZTYPE` | INTEGER | Person type |
| `ZAGETYPE` | INTEGER | Age type (child, adult, etc.) |
| `ZGENDERTYPE` | INTEGER | Gender type |
| `ZMANUALORDER` | INTEGER | Manual sort order |
| `ZINPERSONNAMINGMODEL` | INTEGER | In naming model |
| `ZMERGETARGETPERSON` | INTEGER | FK → merge target |
| `ZMERGECANDIDATECONFIDENCE` | FLOAT | Merge confidence |
| `ZASSOCIATEDFACEGROUP` | INTEGER | FK → face group |
| `ZPERSONURI` | VARCHAR | Person URI |
| `ZCONTACTMATCHINGDICTIONARY` | BLOB | Contact matching data |
| `ZISMECONFIDENCE` | FLOAT | Confidence this is "me" |

### ZDETECTEDFACE (Individual Face Occurrences)

| Column | Type | Description |
|--------|------|-------------|
| `Z_PK` | INTEGER | Primary key |
| `ZUUID` | VARCHAR | Unique identifier |
| `ZASSETFORFACE` | INTEGER | FK → `ZASSET.Z_PK` (which photo) |
| `ZPERSONFORFACE` | INTEGER | FK → `ZPERSON.Z_PK` (which person) |
| `ZFACEGROUP` | INTEGER | FK → `ZDETECTEDFACEGROUP.Z_PK` |
| `ZFACECROP` | INTEGER | FK → `ZFACECROP.Z_PK` |
| `ZFACEPRINT` | INTEGER | FK → `ZDETECTEDFACEPRINT.Z_PK` |

### Face Position & Quality

| Column | Type | Description |
|--------|------|-------------|
| `ZCENTERX` / `ZCENTERY` | FLOAT | Face center (normalized 0-1) |
| `ZSIZE` | FLOAT | Relative face size in frame |
| `ZQUALITY` | FLOAT | Face quality score |
| `ZQUALITYMEASURE` | INTEGER | Quality measure |
| `ZBLURSCORE` | FLOAT | Blur score |
| `ZROLL` | FLOAT | Face roll angle |
| `ZPOSEYAW` | FLOAT | Face yaw angle |

### Body Detection

| Column | Type | Description |
|--------|------|-------------|
| `ZBODYCENTERX` / `ZBODYCENTERY` | FLOAT | Body center |
| `ZBODYWIDTH` / `ZBODYHEIGHT` | FLOAT | Body dimensions |

### Face Attributes

| Column | Type | Description |
|--------|------|-------------|
| `ZAGETYPE` | INTEGER | Age type |
| `ZGENDERTYPE` | INTEGER | Gender type |
| `ZETHNICITYTYPE` | INTEGER | Ethnicity type |
| `ZEYESSTATE` | INTEGER | Eyes state (open/closed) |
| `ZHASSMILE` | INTEGER | Has smile |
| `ZSMILETYPE` | INTEGER | Smile type |
| `ZGLASSESTYPE` | INTEGER | Glasses type |
| `ZHAIRTYPE` | INTEGER | Hair type |
| `ZHAIRCOLORTYPE` | INTEGER | Hair color type |
| `ZFACIALHAIRTYPE` | INTEGER | Facial hair type |
| `ZHEADGEARTYPE` | INTEGER | Headgear type |
| `ZEYEMAKEUPTYPE` | INTEGER | Eye makeup type |
| `ZLIPMAKEUPTYPE` | INTEGER | Lip makeup type |
| `ZGAZETYPE` | INTEGER | Gaze type |
| `ZHASFACEMASK` | INTEGER | Has face mask |

### State Flags

| Column | Type | Description |
|--------|------|-------------|
| `ZHIDDEN` | INTEGER | Hidden flag |
| `ZMANUAL` | INTEGER | Manually identified |
| `ZASSETVISIBLE` | INTEGER | Asset visibility (computed) |
| `ZCLOUDLOCALSTATE` | INTEGER | Cloud sync state |
| `ZDETECTIONTYPE` | INTEGER | Detection type |
| `ZTRAININGTYPE` | INTEGER | Training type |
| `ZNAMESOURCE` | INTEGER | Name source |

---

## Internal Resources: ZINTERNALRESOURCE

Tracks all file variants (originals, thumbnails, edits) on disk.

| Column | Type | Description |
|--------|------|-------------|
| `Z_PK` | INTEGER | Primary key |
| `ZASSET` | INTEGER | FK → `ZASSET.Z_PK` |
| `ZRESOURCETYPE` | INTEGER | `0` = original, `1` = edit, `3` = other derivative |
| `ZDATALENGTH` | INTEGER | File size |
| `ZFINGERPRINT` | VARCHAR | Content fingerprint |
| `ZFILESYSTEMVOLUME` | INTEGER | FK → `ZFILESYSTEMVOLUME` |
| `ZFILESYSTEMBOOKMARK` | INTEGER | FK → `ZFILESYSTEMBOOKMARK` |

---

## Entity-Relationship Overview

### Core Relationships

```
ZGENERICALBUM (Albums/Folders)
    │
    │ Z_33ASSETS (join table)
    │   Z_33ALBUMS → ZGENERICALBUM.Z_PK
    │   Z_3ASSETS  → ZASSET.Z_PK
    ▼
ZASSET (Photos/Videos) ──────────────── File: originals/<dir>/<filename>
    │
    ├──→ ZADDITIONALASSETATTRIBUTES    (1:1, via ZASSET.ZADDITIONALATTRIBUTES)
    │        │
    │        └──→ Z_1KEYWORDS          (join → ZKEYWORD, tags/keywords)
    │        └──→ ZSCENECLASSIFICATION (1:N, ~42 per photo, ML scene tags)
    │
    ├──→ ZEXTENDEDATTRIBUTES           (1:1, via ZASSET.ZEXTENDEDATTRIBUTES)
    │
    ├──→ ZPHOTOANALYSISASSETATTRIBUTES (1:1, via ZASSET.ZPHOTOANALYSISATTRIBUTES)
    │
    ├──→ ZMEDIAANALYSISASSETATTRIBUTES (1:1, via ZASSET.ZMEDIAANALYSISATTRIBUTES)
    │
    ├──→ ZCOMPUTEDASSETATTRIBUTES      (1:1, via ZASSET.ZCOMPUTEDATTRIBUTES)
    │
    ├──→ ZDETECTEDFACE                 (1:N, face regions in this photo)
    │        │
    │        ├──→ ZPERSON              (N:1, the named person)
    │        ├──→ ZDETECTEDFACEPRINT   (1:1, face embedding)
    │        └──→ ZFACECROP            (1:1, cropped face image)
    │
    ├──→ ZMOMENT                       (N:1, time+location cluster)
    │
    └──→ ZINTERNALRESOURCE             (1:N, ~2 per photo: original + derivative)
             │
             ├──→ ZFILESYSTEMVOLUME    (N:1, volume info)
             └──→ ZFILESYSTEMBOOKMARK  (N:1, file bookmark)

ZGENERICALBUM self-referencing:
    ZPARENTFOLDER → ZGENERICALBUM.Z_PK  (folder hierarchy)
```

### ZASSET Foreign Key Columns

The `ZASSET` table has these foreign key columns pointing to related tables:

| Column | Points To | Relationship |
|--------|-----------|--------------|
| `ZADDITIONALATTRIBUTES` | `ZADDITIONALASSETATTRIBUTES.Z_PK` | 1:1 |
| `ZEXTENDEDATTRIBUTES` | `ZEXTENDEDATTRIBUTES.Z_PK` | 1:1 |
| `ZCOMPUTEDATTRIBUTES` | `ZCOMPUTEDASSETATTRIBUTES.Z_PK` | 1:1 (nullable) |
| `ZMEDIAANALYSISATTRIBUTES` | `ZMEDIAANALYSISASSETATTRIBUTES.Z_PK` | 1:1 |
| `ZPHOTOANALYSISATTRIBUTES` | `ZPHOTOANALYSISASSETATTRIBUTES.Z_PK` | 1:1 |
| `ZMOMENT` | `ZMOMENT.Z_PK` | N:1 |
| `ZIMPORTSESSION` | Import session | N:1 |
| `ZMASTER` | `ZCLOUDMASTER.Z_PK` | N:1 (cloud) |

### Tables That Reference ZASSET

These tables have a column pointing back to `ZASSET.Z_PK`:

| Table | FK Column | Relationship |
|-------|-----------|--------------|
| `ZADDITIONALASSETATTRIBUTES` | `ZASSET` | 1:1 |
| `ZEXTENDEDATTRIBUTES` | `ZASSET` | 1:1 |
| `ZINTERNALRESOURCE` | `ZASSET` | 1:N |
| `ZDETECTEDFACE` | `ZASSETFORFACE` | 1:N |
| `ZCLOUDRESOURCE` | `ZASSET` | 1:N |
| `ZCOMPUTEDASSETATTRIBUTES` | `ZASSET` | 1:1 |
| `ZCOMPUTESYNCATTRIBUTES` | `ZASSET` | 1:1 |
| `ZASSETANALYSISSTATE` | `ZASSET` | 1:1 |
| `ZASSETDESCRIPTION` | `ZASSET` | 1:1 |
| `ZMEDIAANALYSISASSETATTRIBUTES` | `ZASSET` | 1:1 |
| `ZPHOTOANALYSISASSETATTRIBUTES` | `ZASSET` | 1:1 |
| `ZSCENECLASSIFICATION` | `ZASSETATTRIBUTES` | 1:N (via attributes) |
| `ZCHARACTERRECOGNITIONATTRIBUTES` | `ZASSET` | 1:1 |
| `ZVISUALSEARCHATTRIBUTES` | `ZASSET` | 1:1 |
| `ZUNMANAGEDADJUSTMENT` | `ZASSET` | 1:N |
| `ZEDITEDIPTCATTRIBUTES` | `ZASSET` | 1:1 |

---

## Complete Table Reference

### Core Asset Tables

These tables are essential for basic photo storage and must be populated for each photo.

| Table | Relationship | Description |
|-------|--------------|-------------|
| `ZASSET` | Primary | Core photo/video entity |
| `ZADDITIONALASSETATTRIBUTES` | 1:1 via `ZASSET.ZADDITIONALATTRIBUTES` | Original filename, import info, location |
| `ZEXTENDEDATTRIBUTES` | 1:1 via `ZASSET.ZEXTENDEDATTRIBUTES` | Extended photo attributes |
| `ZINTERNALRESOURCE` | 1:N via `ZINTERNALRESOURCE.ZASSET` | File variants (~2 per photo) |
| `ZMOMENT` | N:1 via `ZASSET.ZMOMENT` | Time+location clusters |
| `ZFILESYSTEMVOLUME` | Referenced by ZINTERNALRESOURCE | Volume information |
| `ZFILESYSTEMBOOKMARK` | Referenced by ZINTERNALRESOURCE | File bookmarks |

### Album Tables

| Table | Relationship | Description |
|-------|--------------|-------------|
| `ZGENERICALBUM` | Independent | Albums, folders, smart albums |
| `Z_33ASSETS` | Join table | Album ↔ Asset membership |
| `ZALBUMLIST` | Independent | Album lists |
| `Z_32ALBUMLISTS` | Join table | Album list memberships |
| `Z_32KEYASSETS` | Join table | Key assets for albums |

### ML Analysis Tables

These tables store machine learning analysis results. They can be regenerated by Photos app.

| Table | Relationship | Records/Photo | Description |
|-------|--------------|---------------|-------------|
| `ZPHOTOANALYSISASSETATTRIBUTES` | 1:1 via `ZASSET.ZPHOTOANALYSISATTRIBUTES` | 1 | Photo analysis |
| `ZMEDIAANALYSISASSETATTRIBUTES` | 1:1 via `ZASSET.ZMEDIAANALYSISATTRIBUTES` | 1 | Media analysis |
| `ZCOMPUTEDASSETATTRIBUTES` | 1:1 via `ZASSET.ZCOMPUTEDATTRIBUTES` | 1 | Computed scores |
| `ZSCENECLASSIFICATION` | 1:N via `ZASSETATTRIBUTES` | **~42** | Scene tags (ML) |
| `ZCHARACTERRECOGNITIONATTRIBUTES` | 1:1 | 1 | OCR/text recognition |
| `ZVISUALSEARCHATTRIBUTES` | 1:1 | 1 | Visual search data |
| `ZSCENEPRINT` | 1:1 | 1 | Scene fingerprints |
| `ZASSETANALYSISSTATE` | 1:1 | 0-1 | Analysis state tracking |
| `ZASSETDESCRIPTION` | 1:1 | 0-1 | AI-generated descriptions |
| `ZDETECTIONTRAIT` | 1:N | varies | Detection traits |

### Face Recognition Tables

| Table | Relationship | Description |
|-------|--------------|-------------|
| `ZDETECTEDFACE` | 1:N via `ZASSETFORFACE` | Detected faces in photos |
| `ZDETECTEDFACEGROUP` | Groups faces | Face clustering groups |
| `ZDETECTEDFACEPRINT` | 1:1 with ZDETECTEDFACE | Face embeddings |
| `ZFACECROP` | 1:1 with ZDETECTEDFACE | Cropped face images |
| `ZPERSON` | Independent | Named people |
| `ZPERSONREFERENCE` | References ZPERSON | Person references |
| `ZLEGACYFACE` | Legacy | Legacy face data |
| `ZDEFERREDREBUILDFACE` | Queue | Faces pending rebuild |

### Cloud & Sharing Tables

| Table | Description |
|-------|-------------|
| `ZCLOUDMASTER` | Cloud master records |
| `ZCLOUDMASTERMEDIAMETADATA` | Cloud media metadata |
| `ZCLOUDRESOURCE` | Cloud resources |
| `ZCLOUDFEEDENTRY` | Cloud feed entries |
| `ZCLOUDSHAREDALBUMINVITATIONRECORD` | Shared album invitations |
| `ZCLOUDSHAREDCOMMENT` | Shared album comments |
| `ZSHARE` | Shared albums |
| `ZSHAREPARTICIPANT` | Share participants |
| `ZASSETCONTRIBUTOR` | Asset contributors |

### Memories & Highlights Tables

| Table | Description |
|-------|-------------|
| `ZMEMORY` | Memories feature |
| `ZPHOTOSHIGHLIGHT` | Photo highlights |
| `ZSUGGESTION` | Suggestions |
| `Z_3MEMORIESBEINGCURATEDASSETS` | Memory curation join |
| `Z_3MEMORIESBEINGREPRESENTATIVEASSETS` | Memory representative assets |
| `Z_3SUGGESTIONSBEINGKEYASSETS` | Suggestion key assets |

### Graph Tables (Knowledge Graph)

| Table | Description |
|-------|-------------|
| `ZGRAPHNODE` | Graph nodes |
| `ZGRAPHNODEVALUE` | Node values |
| `ZGRAPHNODEADDITIONALLABELASSIGNMENT` | Node labels |
| `ZGRAPHEDGE` | Graph edges |
| `ZGRAPHEDGEVALUE` | Edge values |
| `ZGRAPHEDGEADDITIONALLABELASSIGNMENT` | Edge labels |
| `ZGRAPHLABEL` | Graph labels |

### System Tables (Core Data Infrastructure)

| Table | Description |
|-------|-------------|
| `Z_PRIMARYKEY` | Next available PK for each entity type - **MUST update when inserting** |
| `Z_METADATA` | Core Data metadata and model version |
| `Z_MODELCACHE` | Model cache |
| `ZMIGRATIONHISTORY` | Schema migration history |
| `ZGLOBALKEYVALUE` | Global key-value store |

### Other Tables

| Table | Description |
|-------|-------------|
| `ZKEYWORD` | Keywords/tags |
| `Z_1KEYWORDS` | Keyword ↔ Asset join |
| `ZQUESTION` | User questions |
| `ZUSERFEEDBACK` | User feedback |
| `ZUNMANAGEDADJUSTMENT` | Unmanaged adjustments |
| `ZEDITEDIPTCATTRIBUTES` | Edited IPTC metadata |
| `ZCOMPUTESYNCATTRIBUTES` | Compute sync attributes |
| `ZTRANSIENTINTERNALRESOURCE` | Transient resources |
| `ZBACKGROUNDJOBWORKITEM` | Background job queue |
| `ZLIMITEDLIBRARYFETCHFILTER` | Limited library filters |

### R-Tree Spatial Index Tables

| Table | Description |
|-------|-------------|
| `Z_RT_Asset_boundedByRect` | Spatial index for assets |
| `Z_RT_Asset_boundedByRect_node` | R-tree nodes |
| `Z_RT_Asset_boundedByRect_parent` | R-tree parent refs |
| `Z_RT_Asset_boundedByRect_rowid` | R-tree row IDs |

---

## Useful Queries

### List all user albums with photo counts
```sql
SELECT ZTITLE, ZCACHEDCOUNT, ZCACHEDPHOTOSCOUNT, ZCACHEDVIDEOSCOUNT
FROM ZGENERICALBUM
WHERE ZKIND = 2 AND ZTRASHEDSTATE = 0 AND ZTITLE IS NOT NULL
ORDER BY ZCACHEDCOUNT DESC;
```

### Find original filename for a library file
```sql
SELECT A.ZORIGINALFILENAME
FROM ZADDITIONALASSETATTRIBUTES A
JOIN ZASSET Z ON A.ZASSET = Z.Z_PK
WHERE Z.ZFILENAME = '<UUID-filename>.jpeg';
```

### Get photos added after a specific date
```sql
SELECT ZDIRECTORY || '/' || ZFILENAME as path,
       datetime(ZDATECREATED + 978307200, 'unixepoch', 'localtime') as created
FROM ZASSET
WHERE ZTRASHEDSTATE = 0
  AND ZADDEDDATE > (strftime('%s', '2025-01-01') - 978307200)
ORDER BY ZADDEDDATE DESC;
```

### Get all photos for a named person
```sql
SELECT Z.ZFILENAME, Z.ZDIRECTORY,
       datetime(Z.ZDATECREATED + 978307200, 'unixepoch', 'localtime') as created
FROM ZASSET Z
JOIN ZDETECTEDFACE F ON F.ZASSETFORFACE = Z.Z_PK
JOIN ZPERSON P ON F.ZPERSONFORFACE = P.Z_PK
WHERE P.ZDISPLAYNAME = 'PersonName'
  AND Z.ZTRASHEDSTATE = 0;
```

### Get photos with GPS coordinates
```sql
SELECT ZFILENAME, ZLATITUDE, ZLONGITUDE,
       datetime(ZDATECREATED + 978307200, 'unixepoch', 'localtime') as created
FROM ZASSET
WHERE ZLATITUDE IS NOT NULL AND ZLONGITUDE IS NOT NULL
  AND ZTRASHEDSTATE = 0
ORDER BY ZDATECREATED DESC;
```

### Get favorite photos
```sql
SELECT ZDIRECTORY || '/' || ZFILENAME as path,
       datetime(ZDATECREATED + 978307200, 'unixepoch', 'localtime') as created
FROM ZASSET
WHERE ZFAVORITE = 1 AND ZTRASHEDSTATE = 0
ORDER BY ZDATECREATED DESC;
```

### Get videos with duration
```sql
SELECT ZFILENAME, ZDURATION,
       datetime(ZDATECREATED + 978307200, 'unixepoch', 'localtime') as created
FROM ZASSET
WHERE ZKIND = 1 AND ZTRASHEDSTATE = 0
ORDER BY ZDURATION DESC;
```

### Get album hierarchy (folders and albums)
```sql
WITH RECURSIVE album_tree AS (
  SELECT Z_PK, ZTITLE, ZKIND, ZPARENTFOLDER, 0 as depth,
         ZTITLE as path
  FROM ZGENERICALBUM
  WHERE ZPARENTFOLDER IS NULL AND ZTRASHEDSTATE = 0

  UNION ALL

  SELECT g.Z_PK, g.ZTITLE, g.ZKIND, g.ZPARENTFOLDER, t.depth + 1,
         t.path || ' > ' || g.ZTITLE
  FROM ZGENERICALBUM g
  JOIN album_tree t ON g.ZPARENTFOLDER = t.Z_PK
  WHERE g.ZTRASHEDSTATE = 0
)
SELECT path, ZKIND, depth FROM album_tree
WHERE ZKIND IN (2, 4000)
ORDER BY path;
```

### Count faces per person
```sql
SELECT P.ZDISPLAYNAME, P.ZFULLNAME, P.ZFACECOUNT,
       COUNT(F.Z_PK) as actual_faces
FROM ZPERSON P
LEFT JOIN ZDETECTEDFACE F ON F.ZPERSONFORFACE = P.Z_PK
WHERE P.ZFACECOUNT > 0
GROUP BY P.Z_PK
ORDER BY P.ZFACECOUNT DESC;
```

---

## Z_PRIMARYKEY Table

This table tracks the next available primary key for each Core Data entity. **Critical for inserts.**

```sql
SELECT * FROM Z_PRIMARYKEY ORDER BY Z_ENT LIMIT 10;
```

| Z_ENT | Z_NAME | Z_SUPER | Z_MAX |
|-------|--------|---------|-------|
| 1 | AdditionalAssetAttributes | 0 | 30739 |
| 3 | Asset | 0 | 30739 |
| 28 | ExtendedAttributes | 0 | 30739 |
| 32 | GenericAlbum | 0 | 1099 |
| 51 | InternalResource | 0 | 68920 |
| 55 | MediaAnalysisAssetAttributes | 0 | 25562 |
| 58 | Moment | 0 | 4722 |
| 61 | PhotoAnalysisAssetAttributes | 0 | 29665 |

When inserting new records:
1. Read current `Z_MAX` for the entity
2. Use `Z_MAX + 1` as the new `Z_PK`
3. Update `Z_MAX` to the new value

---

## Notes

- The database uses Core Data, so `Z_ENT` and `Z_OPT` columns are for Core Data internal use
- Many columns have cloud sync counterparts (prefixed with `ZCLOUD`)
- Face detection stores normalized coordinates (0-1 range)
- The schema may vary slightly between macOS/iOS versions
- Always use read-only access to avoid corrupting the database
- **89 total tables** - a single photo import touches 7+ core tables plus 10+ ML analysis tables
- ML analysis tables (ZSCENECLASSIFICATION, etc.) can be regenerated by Photos app if missing
- The `Z_PRIMARYKEY` table must be updated when inserting new records
