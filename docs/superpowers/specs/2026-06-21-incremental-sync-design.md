# Incremental Sync via Delta Queries with Checksum-Verified Escalation

Date: 2026-06-21

## Problem

Every sync run re-reads the whole library to decide what to do, even when little
or nothing changed:

- `identify_new_photos` / `identify_deleted_photos` read the full active-asset
  UUID set from **both** source and target and diff them.
- `identify_favourite_changes` reads the full `(ZUUID, ZFAVORITE)` map from both.
- `diff_album_memberships` reads the full `Z_33ASSETS` membership set from both.

The goal is **not merely to skip work when nothing changed** — it is to avoid the
full-library comparison even when the library *did* change, by examining **only
the delta** (the rows that changed since the last sync). The hard requirement
stays: **never silently miss a change.**

## The fundamental limit (read this first)

Some changes can be found by querying "only what changed since last time";
others cannot.

- **Additions** leave a monotonic, range-queryable trace: a new row always gets
  a higher primary key / rowid than every existing one. You can fetch exactly the
  new rows with `WHERE <key> > <watermark>`.
- **Removals leave no trace.** When a row is deleted from a table, nothing
  records "row X used to be here." To learn what disappeared you must compare the
  *previous* full set against the *current* full set — and computing the current
  set is a full read. There is no app-level delete journal in the Photos DB.

Consequence: a design that is *always* delta-only **and** never misses a change
is **impossible for set-removals** (album-membership removals/moves, and photos
hard-deleted from the DB). This is information-theoretic, not an implementation
shortcut.

This spec resolves the tension with **delta queries plus a cheap checksum that
verifies the delta is complete; only the runs where an untrackable removal
actually happened escalate to a full comparison — and only for the affected
dimension.** Common-case changes (adding photos, adding to albums, trash-based
deletions) are pure delta; the checksum guarantees nothing is ever missed.

## Strategy

For each dimension, per run:

1. **Delta fetch** — query only rows changed since the stored watermark.
2. **Verify** — recompute a cheap invariant (count + sum-checksum, both
   index/aggregate-backed) on the *current* source and check that
   `predicted (old invariant + applied delta) == current`.
   - **Reconciles** → the delta is the complete change set. Apply it. (Pure
     incremental — no full scan.)
   - **Does not reconcile** → something happened the delta query cannot see
     (a removal, a move, a restore, a hard-delete). Run that dimension's existing
     full comparison **this run only**, then resync the invariant.
3. **Advance watermark** — only for dimensions whose work completed without error
   (see "Save discipline").

Verification is what preserves *never-miss*: any change the delta query fails to
capture breaks the invariant and forces the full path.

## State file

New module `src/photo_sync/operations/sync_state.py` owns
`.photo_sync_meta/sync_state.json` inside the **target** bundle (mirroring the
existing per-target marker convention). Public surface:

- `load_sync_state(target_lib) -> dict` — parse; return empty state on missing /
  unreadable / `version` mismatch (→ everything escalates to full = correct first
  run).
- `save_sync_state(target_lib, state) -> None` — atomic write (temp + `os.replace`).

Shape:

```json
{
  "version": 1,
  "assets": {
    "source_asset_zmax": 12345,      // Z_MAX("Asset") at last sync
    "source_max_trashed_date": 0.0,  // MAX(ZTRASHEDDATE) at last sync
    "source_active_count": 9000,
    "source_active_pk_sum": 73910022 // SUM(Z_PK) over active — checksum
  },
  "membership": {
    "source_max_rowid": 55012,       // MAX(rowid) of Z_33ASSETS at last sync
    "source_count": 18000,
    "source_checksum": 99887766      // SUM(Z_33ALBUMS*BIG + Z_3ASSETS)
  },
  "favourites": { "source_count": 120, "source_pk_sum": 8123, "source_pk_sqsum": 661 },
  "albums":     { "source_album_zmax": 220, "source_active_count": 60, "source_mod_max": 0.0 }
}
```

Watermarks/invariants are **source-side**. Source→target identity is by `ZUUID`,
not by primary key (target assigns its own PKs), so source watermarks are only
used to locate changed *source* rows; matching into the target is always by UUID.

## Per-dimension mechanics

`Z_MAX(entity)` is read via the existing `pk_manager.get_current_max_pk` (the
Core Data per-entity monotonic counter — AUTOINCREMENT-like, never reused).

### Assets — additions (covers derivatives too)

- delta_add = `SELECT ... FROM ZASSET WHERE Z_PK > source_asset_zmax AND ZTRASHEDSTATE = 0`.
  These are assets created in source since last sync; their UUIDs cannot already
  be in target (target only holds what was synced through the prior watermark),
  so **no target full-read is needed**. Per UUID, an indexed existence check in
  target keeps the insert idempotent (guards crash-without-save reruns).
- Each inserted photo gets its original **and derivatives** copied inline via the
  existing `copy_asset_derivatives` (new-photo path). Derivatives need no
  separate handling.

### Assets — deletions

- delta_del = `SELECT ZUUID FROM ZASSET WHERE ZTRASHEDSTATE = 1 AND ZTRASHEDDATE > source_max_trashed_date`.
  These are photos sent to "Recently Deleted" in source since last sync →
  soft-delete them in target by UUID (existing `soft_delete_photo`).
- **Assumption:** syncs run more frequently than Photos expunges Recently Deleted
  (~30 days). A photo trashed *and* permanently expunged within one gap leaves no
  row → not in delta_del. The verification below catches it (count won't
  reconcile → escalate).

### Assets — verification

- Recompute current `active_count` and `active_pk_sum = SUM(Z_PK) WHERE ZTRASHEDSTATE=0`.
- previously_active_trashed = delta_del rows with `Z_PK <= source_asset_zmax`
  (existed and were active at last sync). delta_del rows with `Z_PK >` watermark
  were added-and-trashed within the gap and were never in the old active set.
- predicted_count = `source_active_count + |delta_add| − |previously_active_trashed|`
- predicted_pk_sum = `source_active_pk_sum + Σ delta_add.Z_PK − Σ previously_active_trashed.Z_PK`
- predicted == current → apply delta_add + delta_del. Else → run today's full
  `identify_new_photos` + `identify_deleted_photos` for this run.
- Catches restores (untrash: Z_PK ≤ watermark, not in delta_add → count drifts),
  hard-deletes, and any edit the two delta queries miss.

### Album membership

- delta_add = `SELECT Z_33ALBUMS, Z_3ASSETS FROM Z_33ASSETS WHERE rowid > source_max_rowid`.
- predicted_count = `source_count + |delta_add|`;
  predicted_checksum = `source_checksum + Σ (album_pk*BIG + asset_pk)` for delta_add,
  where `BIG` exceeds any asset PK so each pair maps injectively.
- Recompute current `COUNT(Z_33ASSETS)` and the same checksum.
- predicted == current → only additions occurred → sync just delta_add. Else → a
  removal or move happened (no per-row trace) → run today's full
  `diff_album_memberships` this run.
- **rowid reuse caveat:** SQLite may reuse the highest rowid after the
  top row is deleted; a re-inserted membership could land at `rowid ==` watermark
  and be missed by delta_add. The checksum mismatch escalates to full → still
  never missed.

### Favourites & album definitions

Lower volume and no reliable per-row "changed-since" signal (favourite toggles
are not known to bump `ZMODIFICATIONDATE`; verify empirically before relying on
it). Keep these **checksum-gated**: cheap invariant unchanged → skip; changed →
run today's full comparison (both are single-column/low-row and cheap). New
albums may use a `Z_MAX("GenericAlbum")` delta; renames/removals escalate. This
keeps the implementation focused on where delta pays off most (assets,
membership) without sacrificing correctness elsewhere.

## Control flow & save discipline

`sync_photos`:

1. Open connections; `assert_schema_compatible` (unchanged front-line guard).
2. `state = load_sync_state(target)`.
3. For each dimension: delta-fetch → verify → apply-delta **or** escalate-to-full.
4. **Save discipline:** a dimension's watermark/invariant is recomputed *after*
   its work and persisted **only if that dimension completed without error**
   (tracked via an explicit per-dimension success flag, since some non-fatal
   failures are recorded as warnings today). A dimension that raised keeps its
   *previous* watermark → it re-evaluates next run. Whole file written once at end,
   atomically.

## CLI & safety valve

- `--full` (alias `--reconcile`): ignore watermarks/invariants, run the full
  comparison for all dimensions, then resync state. Deterministic insurance for
  the long-gap expunge case, the rowid-reuse caveat, and post-upgrade runs.
- Dry-run (`create_sync_plan`) ignores the gate and always runs the full
  comparison — a `--dry-run` must answer "what *would* change?" truthfully.
- `README.md` updated with `--full` and a note on incremental behavior.

## Removed (derivative backfill)

Per decision to drop legacy repair:

- `sync.py`: the Phase 1b whole-library backfill block.
- `file_copy.py`: `backfill_derivatives`, `is_derivatives_backfilled`,
  `mark_derivatives_backfilled`, `derivatives_backfill_marker_path`,
  `BACKFILL_MARKER_RELPATH`.
- `tests/unit/test_derivative_backfill_marker.py`.

Kept: `copy_asset_derivatives` (new-photo path), `get_asset_derivative_size`
(disk estimate). Consequence: no path repairs an already-present photo's missing
derivatives; new photos always get theirs. A target needing legacy backfill must
finish it on the current version before upgrading.

## Testing

- **Delta + verify unit tests** (in-memory SQLite):
  - additions only → delta path applies exactly the new rows, no escalation;
  - trash-based deletion → delta_del soft-deletes, reconciles;
  - **restore (untrash)** → invariant drifts → escalates to full;
  - **hard-delete** → escalates;
  - membership add-only → delta path; **membership remove / move** → escalates;
  - rowid-reuse synthetic case → escalates (never missed).
- **Verification soundness:** for each "escalate" case, assert the full path runs
  and the change is applied.
- **Lifecycle:** missing/corrupt/old-`version` state → all dimensions full; a
  dimension that raises → watermark not advanced → re-runs next time.
- **Integration:** add N photos → only the N inserted, no full scan touched;
  second no-change run → no-op; remove an album membership → membership escalates
  but assets/favourites stay delta.
- **`--full`** forces full everywhere.
- Existing suite stays green: `cd src && pytest && ruff check .`.

## Assumptions / risks

- **Monotonic keys:** `Z_PRIMARYKEY.Z_MAX` never reused (solid); `Z_33ASSETS`
  rowid may be reused after top-row deletion (handled by checksum escalation).
- **Recently-Deleted window:** trash-based deletion delta is sound only if sync
  interval < expunge window (~30 days); otherwise the count check escalates.
- **One-way / single-process:** assumes no direct edits to the target outside the
  tool and no concurrent syncs into one target (same assumption the existing
  marker and dedup flow already make). Direct target edits that drift the
  invariant simply trigger a full pass.
- **Favourite signal:** no confirmed per-row "changed-since" marker, so favourites
  stay checksum-gated rather than delta-fetched.
- **Checksum collisions:** statistically negligible with the chosen
  count+sum(+product/sq) components; `--full` is the deterministic fallback.
