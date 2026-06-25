"""Pure delta-vs-full decision functions for incremental sync.

Each plan_* function reads ONLY cheap aggregates + rows past a watermark, and
decides whether the delta fully explains the change (apply just the delta) or
whether to escalate to the existing full comparison this run.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from photo_sync.db.queries import (
    album_defs_invariant,
    asset_invariant,
    favourite_set_summary,
    favourite_state,
    fetch_assets_added_since,
    fetch_assets_trashed_since,
    fetch_favourite_candidates_since,
    fetch_memberships_added_since,
    membership_invariant,
)


@dataclass
class AssetPlan:
    full: bool
    invariant: dict
    added_uuids: list[str] = field(default_factory=list)
    trashed_uuids: list[str] = field(default_factory=list)


def plan_asset_sync(source_conn: sqlite3.Connection, prev: dict | None) -> AssetPlan:
    cur = asset_invariant(source_conn)
    if not prev:
        return AssetPlan(full=True, invariant=cur)

    added = fetch_assets_added_since(source_conn, prev["asset_zmax"])
    trashed = fetch_assets_trashed_since(source_conn, prev["max_trashed_date"])
    # Only assets that were active at last sync are present in the target.
    prev_active_trashed = [(u, pk) for (u, pk) in trashed if pk <= prev["asset_zmax"]]

    predicted_count = prev["active_count"] + len(added) - len(prev_active_trashed)
    predicted_pk_sum = (
        prev["active_pk_sum"]
        + sum(pk for _, pk in added)
        - sum(pk for _, pk in prev_active_trashed)
    )

    if predicted_count == cur["active_count"] and predicted_pk_sum == cur["active_pk_sum"]:
        return AssetPlan(
            full=False,
            invariant=cur,
            added_uuids=[u for u, _ in added],
            trashed_uuids=[u for u, _ in prev_active_trashed],
        )
    return AssetPlan(full=True, invariant=cur)


@dataclass
class MembershipPlan:
    full: bool
    invariant: dict
    added: list[tuple[int, int]] = field(default_factory=list)


def plan_membership_sync(source_conn: sqlite3.Connection, prev: dict | None) -> MembershipPlan:
    cur = membership_invariant(source_conn)
    if not prev:
        return MembershipPlan(full=True, invariant=cur)

    added = fetch_memberships_added_since(source_conn, prev["max_rowid"])
    predicted = {
        "count": prev["count"] + len(added),
        "album_sum": prev["album_sum"] + sum(a for a, _ in added),
        "asset_sum": prev["asset_sum"] + sum(p for _, p in added),
        "prod_sum": prev["prod_sum"] + sum(a * p for a, p in added),
    }
    if all(predicted[k] == cur[k] for k in predicted):
        return MembershipPlan(full=False, invariant=cur, added=added)
    return MembershipPlan(full=True, invariant=cur)


@dataclass
class FavouritePlan:
    full: bool
    state: dict
    candidate_uuids: list[str] = field(default_factory=list)


def plan_favourite_sync(
    source_conn: sqlite3.Connection,
    target_conn: sqlite3.Connection,
    prev: dict | None,
) -> FavouritePlan:
    state = favourite_state(source_conn)
    if not prev:
        return FavouritePlan(full=True, state=state)

    candidates = fetch_favourite_candidates_since(source_conn, prev["max_mod_date"])
    # The caller applies candidate favourite changes to the target before this
    # verify. If the candidates captured every favourite change, source and
    # target favourite sets now match (by UUID).
    if favourite_set_summary(source_conn) == favourite_set_summary(target_conn):
        return FavouritePlan(
            full=False, state=state, candidate_uuids=[u for u, _ in candidates]
        )
    return FavouritePlan(full=True, state=state)


def plan_album_defs_sync(
    source_conn: sqlite3.Connection, prev: dict | None
) -> tuple[bool, dict]:
    """Skip-or-full decision for album definitions.

    Returns:
        (needs_full, invariant) where needs_full is True if prev is empty or
        any invariant component changed.
    """
    cur = album_defs_invariant(source_conn)
    if not prev:
        return True, cur
    return (cur != prev), cur
