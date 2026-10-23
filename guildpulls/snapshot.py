"""Compute metrics from stored pulls and write the dated snapshot files."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from guildpulls.aggregate import GuildRow, build_snapshot
from guildpulls.collect import WCL_REGIONS
from guildpulls.config import Tier
from guildpulls.metrics import guild_results
from guildpulls.store import Store


def load_guild_rows(store: Store, tier: Tier) -> list[GuildRow]:
    matches = store.matches()
    kills = store.rio_kills(tier.key)
    rio_pulls = store.rio_pulls(tier.key)
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
    path.write_text(json.dumps(snap, indent=1, ensure_ascii=False))
    (d / f"{day}-guilds.json").write_text(json.dumps(guild_detail(tier, rows), ensure_ascii=False))
    (d / "latest.json").write_text(json.dumps(snap, indent=1, ensure_ascii=False))
    store.record_snapshot(tier.key, day, str(path), now.isoformat())
    return path
