"""Pure delta-vs-full decision functions for incremental sync.

Each plan_* function reads ONLY cheap aggregates + rows past a watermark, and
decides whether the delta fully explains the change (apply just the delta) or
whether to escalate to the existing full comparison this run.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from photo_sync.db.queries import (
    asset_invariant,
    fetch_assets_added_since,
    fetch_assets_trashed_since,
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
