"""Compute metrics from stored pulls and write the dated snapshot files."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from guildpulls.aggregate import GuildRow, build_snapshot
from guildpulls import config
from guildpulls.collect import WCL_REGIONS
from guildpulls.config import Tier
from guildpulls.metrics import guild_results
from guildpulls.store import Store


def load_guild_rows(store: Store, tier: Tier) -> list[GuildRow]:
    matches = store.matches()
    kills = store.rio_kills(tier.key)
    # Raider.IO pull counts aren't trusted for every tier; without them pulls
    # to kill come from the logs only.
    rio_pulls = store.rio_pulls(tier.key) if tier.rio_pulls else {}
    pulls = store.pulls_by_guild(tier.key)
    encounter_ids = [b.wcl_encounter_id for b in tier.bosses]
    results_cache: dict[int, dict] = {}
    rows = []
    for g in store.guilds(tier.key):
        rid = g["rio_guild_id"]
        wcl_id = matches.get(rid)
        if wcl_id is not None:
            status = "matched"
            if wcl_id not in results_cache:
                results_cache[wcl_id] = guild_results(pulls.get(wcl_id, []), encounter_ids)
            results = results_cache[wcl_id]
        else:
            status = "pending" if rid not in matches and g["region"] in WCL_REGIONS else "unmatched"
            results = {}
        rows.append(GuildRow(rid, g["name"], g["region"], g["world_rank"], g["region_rank"], status,
                             results, kills.get(rid, {}), rio_pulls.get(rid, {})))
    return rows


def guild_detail(tier: Tier, rows: list[GuildRow]) -> list[dict]:
    """Per guild, per boss numbers, for checking the medians by hand."""
    out = []
    for g in rows:
        bosses = {}
        for b in tier.bosses:
            r = g.results.get(b.wcl_encounter_id)
            if r:
                bosses[b.rio_slug] = {"killed": r.killed, "pulls": r.pulls, "nights": r.nights,
                                      "combat_hours": round(r.combat_hours, 3), "item_level": r.item_level,
                                      "first_pull_is_kill": r.first_pull_is_kill}
        out.append({"name": g.name, "region": g.region, "world_rank": g.world_rank,
                    "region_rank": g.region_rank, "status": g.status, "bosses": bosses,
                    "rio_pulls": g.rio_pulls})
    return out


def write_snapshot(store: Store, tier: Tier, out_dir: str | Path, now: datetime | None = None) -> Path:
    now = now or datetime.now(timezone.utc)
    rows = load_guild_rows(store, tier)
    snap = build_snapshot(tier, rows, now)
    day = now.date().isoformat()
    d = Path(out_dir) / tier.key
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{day}.json"
    path.write_text(json.dumps(snap, separators=(",", ":"), ensure_ascii=False))
    # Per guild detail is a few MB, so only the latest copy is kept.
    (d / "guilds.json").write_text(json.dumps(guild_detail(tier, rows), ensure_ascii=False))
    (d / "latest.json").write_text(json.dumps(snap, separators=(",", ":"), ensure_ascii=False))
    store.record_snapshot(tier.key, day, str(path), now.isoformat())
    return path


def write_index(store: Store, tiers: list[Tier], out_dir: str | Path, run_tier: str,
                now: datetime | None = None) -> Path:
    """The file the dashboard reads first: which tiers have data, how far each
    past tier's backfill has got, and the progress of the latest run of `run_tier`."""
    now = now or datetime.now(timezone.utc)
    out = {"schema": 1, "generated_at": now.isoformat(), "tiers": [], "run": None}
    for tier in tiers:
        snap = store.latest_snapshot(tier.key)
        out["tiers"].append({
            "key": tier.key, "name": tier.name, "expansion": tier.expansion,
            "starts": tier.starts.isoformat(), "ends": tier.ends.isoformat() if tier.ends else None,
            "current": tier.ends is None,
            "snapshot": f"{tier.key}/latest.json" if snap else None,
            "guilds": f"{tier.key}/guilds.json" if snap else None,
            "updated_at": snap["created_at"] if snap else None,
            "backfill": backfill_progress(store, tier),
        })
    row = store.latest_run(run_tier)
    if row:
        counts = store.run_status_counts(run_tier, row["run_id"])
        out["run"] = {
            "tier": run_tier, "run_id": row["run_id"], "started_at": row["started_at"],
            "completed_at": row["completed_at"], "complete": row["completed_at"] is not None,
            "done": sum(counts.values()), "total": len(store.guilds(run_tier)),
        }
    path = Path(out_dir) / "index.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    return path


def backfill_progress(store: Store, tier: Tier) -> dict | None:
    """Progress of a past tier's one-time load, or None when it isn't loading."""
    if tier.key not in config.BACKFILL_TIERS:
        return None
    row = store.get_run(tier.key, config.BACKFILL_RUN_ID)
    if row is None:
        return {"state": "queued", "done": 0, "total": 0}
    if row["completed_at"]:
        return {"state": "complete", "done": len(store.guilds(tier.key)), "total": len(store.guilds(tier.key))}
    counts = store.run_status_counts(tier.key, config.BACKFILL_RUN_ID)
    return {"state": "loading", "done": sum(counts.values()), "total": len(store.guilds(tier.key))}
