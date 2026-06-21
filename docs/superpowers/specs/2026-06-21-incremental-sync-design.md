# Incremental Sync via Per-Phase Fingerprint Gates

Date: 2026-06-21

## Problem

Every sync run re-reads the whole library to decide what to do, regardless of
whether anything changed:

- `identify_new_photos` / `identify_deleted_photos` read the full active-asset
  UUID set from **both** source and target (`get_all_asset_uuids`) and diff them.
- `identify_favourite_changes` reads the full `(ZUUID, ZFAVORITE)` map from both
  sides.
- `diff_album_memberships` reads the full `Z_33ASSETS` membership set from both
  sides.

This is correct but wasteful: a run where nothing (or only one dimension)
changed still pays for full-library scans of every dimension. The goal is to
**skip the redundant scans for unchanged dimensions** — on principle/efficiency,
not because the tool is currently too slow.

## Guiding principle

> Cheap check first. If the check says anything moved, fall back to today's
> proven full comparison.

A per-phase **fingerprint** is a small, cheap-to-compute summary of the relevant
state. Each run compares the current fingerprint against the one stored from the
last successful sync:

- **Unchanged** → skip the phase entirely (no-op).
- **Changed** → run the existing full comparison, then store the new fingerprint.

The fingerprint only needs to be a **sound over-approximation**: it must move on
*every* real change. A fingerprint that is *too* sensitive merely triggers an
unnecessary full scan — wasted work, never a missed change. This is what makes
the design satisfy the hard requirement: **never silently miss a change.**

## Non-goals

- Propagating edits to existing photos. The sync is insert-only by design;
  re-syncing changed originals/metadata is out of scope.
- Repairing derivatives for photos already present in the target. The current
  one-time backfill (Phase 1b) is **removed** (see "Derivatives").
- Per-row incremental processing or `ZMODIFICATIONDATE` watermarks. Considered
  and rejected: a watermark cannot see deletions or album-membership changes
  (the join table has no timestamps and does not touch `ZASSET`), and edits are
  not propagated anyway.

## Architecture

New module `src/photo_sync/operations/sync_state.py`, the single owner of the
state file `.photo_sync_meta/sync_state.json` inside the **target** bundle. This
mirrors the existing per-target marker convention already used by the (now
removed) derivative backfill.

Public surface:

- `load_sync_state(target_lib) -> dict` — parse the state file; return an empty
  state (all phases absent) on missing / unreadable / `version`-mismatch.
- `save_sync_state(target_lib, state) -> None` — atomic write (temp file +
  `os.replace`).
- One fingerprint function per phase, e.g. `assets_fingerprint(conn) -> dict`,
  computed from a live connection.

`sync_photos` wraps each phase with a gate: compute current fingerprint →
compare to stored → skip, or run the existing full comparison and mark the phase
for fingerprint refresh.

### State file shape

```json
{
  "version": 1,
  "phases": {
    "assets":     {"source": {...}, "target": {...}},
    "favourites": {"source": {...}, "target": {...}},
    "albums":     {"source": {...}, "target": {...}},
    "membership": {"source": {...}, "target": {...}}
  }
}
```

Each phase stores the fingerprint of **both** sides, because new/deleted/
membership are `source − target` diffs — a change on *either* side must
re-trigger the comparison. (A user editing the target library outside the tool
is therefore also caught.)

## Fingerprints

All components are read with cheap SQL (index-backed `COUNT`/`MAX`/`SUM` or a
single-row lookup) — no full-column reads. `Z_MAX(...)` is read via the existing
`pk_manager.get_current_max_pk(conn, entity)`, the Core Data per-entity
monotonic counter (only ever increases; one insert bumps it; deletes never lower
it).

| Phase | Components (per side) | Why it cannot miss a change |
|---|---|---|
| **assets** (new + deleted + derivatives) | `asset_zmax = Z_MAX("Asset")`, `active_count = COUNT(* WHERE ZTRASHEDSTATE=0)` | Add → `asset_zmax`↑ even if a simultaneous delete nets the count to zero. Trash/un-trash → `active_count` moves. |
| **favourites** | `count`, `pk_sum = SUM(Z_PK)`, `pk_sqsum = SUM(Z_PK*Z_PK)` over `ZFAVORITE=1 AND ZTRASHEDSTATE=0` | Toggle on/off → `count` moves. Swap (off A, on B; count unchanged) → `pk_sum`/`pk_sqsum` move; both colliding simultaneously is ruled out by the squared term for any realistic swap. |
| **albums** (definitions) | `album_zmax = Z_MAX("GenericAlbum")`, `active_count = COUNT(active)`, `mod_max = MAX(ZMODIFICATIONDATE)` | New album → `album_zmax`↑. Rename/trash → `mod_max`/`active_count` move. |
| **membership** | `count = COUNT(Z_33ASSETS)`, `album_sum = SUM(Z_33ALBUMS)`, `asset_sum = SUM(Z_3ASSETS)`, `prod_sum = SUM(Z_33ALBUMS*Z_3ASSETS)` | Add/remove → `count` moves. Move (remove `(A,p)`, add `(B,p)`) → `album_sum` moves. Cross-swaps that preserve both linear sums are broken by `prod_sum`. |

The membership checksum carries a *theoretical* (astronomically unlikely)
collision risk. This is the only spot where soundness is statistical rather than
absolute; the `--full` escape hatch (below) is the deterministic insurance.

The fixed join-table name `Z_33ASSETS` (and columns `Z_33ALBUMS`, `Z_3ASSETS`)
matches the rest of the codebase, valid under the schema already enforced by
`assert_schema_compatible`.

## Control flow in `sync_photos`

1. Open connections; `assert_schema_compatible` (unchanged, stays the front-line
   guard).
2. `state = load_sync_state(target)`.
3. For each phase, compute the current fingerprint `{source, target}`:
   - If `state["phases"][phase]` exists and equals the current fingerprint →
     log `"<phase> unchanged, skipping"` and skip the phase's work.
   - Else run the existing full comparison and apply changes; mark the phase for
     refresh.
4. **Save discipline (critical):** a phase's fingerprint is recomputed *after*
   its work and persisted **only if that phase completed without error**. A phase
   that raised must not have its fingerprint saved, or the next run would wrongly
   skip unfinished work. The state file is written once at end of run,
   atomically, merging the successfully-completed phases over the
   previously-stored values; phases that were skipped keep their stored
   fingerprint, phases that errored are left at their *previous* fingerprint
   (forcing a re-run next time).

A per-phase success flag is tracked explicitly rather than inferred from
`result.errors`/`result.warnings`, since today some non-fatal failures are
recorded as warnings.

## Derivatives

Folded into the **assets** phase and gated by the assets fingerprint. Because
derivatives are strictly per-asset and are only ever copied for *new* photos:

- assets fingerprint unchanged → no new/removed photos → nothing to copy
  (derivatives included). Skip.
- assets fingerprint moved → run the assets phase; each new photo's original and
  its derivatives are copied inline via the existing `copy_asset_derivatives`
  call in the new-photo path.

**Removed** (the one-time backfill machinery, per decision to drop legacy
repair):

- `sync.py`: the Phase 1b backfill block.
- `file_copy.py`: `backfill_derivatives`, `is_derivatives_backfilled`,
  `mark_derivatives_backfilled`, `derivatives_backfill_marker_path`,
  `BACKFILL_MARKER_RELPATH`.
- `tests/unit/test_derivative_backfill_marker.py`.

**Kept**: `copy_asset_derivatives` (new-photo path) and
`get_asset_derivative_size` (disk-space estimate).

**Consequence:** there is no longer any path that repairs an already-present
photo's missing derivatives — not even `--full`, since the assets phase only
copies derivatives for `source − target` photos. New photos still always get
their thumbnails. A target that was synced by an older tool version and still
needs backfill must be finished on the *current* version before upgrading to
this one.

## CLI & safety valve

- `--full` (alias `--reconcile`): ignore stored fingerprints, force the full
  comparison of all phases, then refresh state. Covers post-upgrade runs and the
  theoretical membership-checksum collision — this is what keeps the "never
  miss" guarantee deterministic.
- Dry-run (`create_sync_plan`) **ignores the gate** and always runs the full
  comparison. A `--dry-run` is the user explicitly asking "what *would* change?",
  so it must stay truthful rather than report a cached "nothing changed".
- `README.md` updated with the `--full` flag and a short note on incremental
  behavior (per the project rule to keep README in sync with CLI/features).

## Testing

- **Fingerprint unit tests** (in-memory SQLite fixtures), one per change kind,
  each asserting the fingerprint *moves*: add asset; trash; un-trash; favourite
  on / off / **swap**; add album; rename album; membership add / remove /
  **move**. The net-zero cases (add+delete, favourite swap, membership move) are
  the important ones.
- **Lifecycle tests:** missing state → all phases full; corrupt / old-`version`
  JSON → all phases full; a phase that raises → its fingerprint is *not* saved →
  next run re-runs it.
- **Integration:** run twice with no source change → second run is a no-op (0
  photos/albums/favourites touched, every phase logged as skipped); change
  exactly one dimension → only that phase runs.
- **`--full`** overrides all skips.
- Existing suite stays green: `cd src && pytest && ruff check .`.

## Assumptions / risks

- **Z_MAX monotonicity:** Core Data never lowers or reuses `Z_PRIMARYKEY.Z_MAX`.
  Documented assumption, consistent with how the tool already allocates PKs.
- **Membership checksum collision:** statistically negligible with four
  components; `--full` is the deterministic fallback.
- **Single-process:** read/modify/write of the state file assumes no concurrent
  syncs into the same target — the same assumption the existing marker makes.
- **Favourite/album fingerprint sensitivity:** covered by multi-component sums
  (favourites: count + pk_sum + pk_sqsum; membership: count + 3 sums) so that
  count-preserving swaps/moves still move the fingerprint.
