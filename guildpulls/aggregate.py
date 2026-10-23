"""Bracket roll-up: per guild results -> bracket medians, multiples, kill share."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from statistics import median

from guildpulls import config
from guildpulls.config import Tier
from guildpulls.metrics import BossResult

METRICS = ("pulls_to_kill", "nights_to_kill", "combat_hours", "item_level")


@dataclass
class GuildRow:
    rio_guild_id: int
    name: str
    region: str
    world_rank: int
    region_rank: int | None
    status: str  # "matched", "unmatched" or "pending" (not looked up yet)
    results: dict[int, BossResult] = field(default_factory=dict)  # by WCL encounter id
    rio_first_defeated: dict[str, str] = field(default_factory=dict)  # by Raider.IO boss slug


def bracket_of(rank: int | None) -> str | None:
    if rank is None:
        return None
    for label, lo, hi in config.BRACKETS:
        if lo <= rank <= hi:
            return label
    return None


def view_rank(g: GuildRow, view: str) -> int | None:
    """World rank under All; rank within the region under US or EU."""
    if view == "all":
        return g.world_rank
    return g.region_rank if g.region == view else None


def _metric_values(r: BossResult) -> dict[str, float | None]:
    return {
        "pulls_to_kill": r.pulls,
        "nights_to_kill": r.nights,
        "combat_hours": r.combat_hours,
        "item_level": r.item_level,
    }


def boss_cell(members: list[GuildRow], boss,
              exclude_first_pull_kills: bool | None = None) -> dict:
    """One bracket x boss cell: medians plus the counts the page shows."""
    counts = {"guilds": len(members), "killed": 0, "unmatched": 0, "pending": 0,
              "kill_not_logged": 0, "incomplete": 0, "used": 0}
    if exclude_first_pull_kills is None:
        exclude_first_pull_kills = config.EXCLUDE_FIRST_PULL_KILLS
    candidates: list[BossResult] = []
    for g in members:
        if boss.rio_slug in g.rio_first_defeated:
            counts["killed"] += 1
        if g.status != "matched":
            counts[g.status] += 1
            continue
        r = g.results.get(boss.wcl_encounter_id)
        if r is None or not r.killed:
            if boss.rio_slug in g.rio_first_defeated:
                counts["kill_not_logged"] += 1
            continue
        if r.first_pull_is_kill and exclude_first_pull_kills:
            counts["incomplete"] += 1
            continue
        candidates.append(r)

    # Missing nights: pull count under a quarter of the bracket's median.
    if candidates:
        floor = config.LOW_PULL_FRACTION * median(r.pulls for r in candidates)
        kept = [r for r in candidates if r.pulls >= floor]
        counts["incomplete"] += len(candidates) - len(kept)
        candidates = kept
    counts["used"] = len(candidates)

    medians: dict[str, float | None] = {m: None for m in METRICS}
    if len(candidates) >= config.MIN_BRACKET_SAMPLE:
        for m in METRICS:
            vals = [v for v in (_metric_values(r)[m] for r in candidates) if v is not None]
            medians[m] = round(median(vals), 3) if len(vals) >= config.MIN_BRACKET_SAMPLE else None
    counts["kill_share"] = round(counts["killed"] / counts["guilds"], 4) if counts["guilds"] else None
    return {"median": medians, **counts}


def add_comparisons(cells: dict[str, dict]) -> None:
    """Multiples of the top bracket; item level as a difference."""
    base_label = config.BRACKETS[0][0]
    base = cells.get(base_label, {}).get("median", {})
    for label, cell in cells.items():
        comp: dict[str, float | None] = {}
        for m in METRICS:
            v, b = cell["median"][m], base.get(m)
            if label == base_label or v is None or b is None:
                comp[m] = None
            elif m == "item_level":
                comp[m] = round(v - b, 2)
            else:
                comp[m] = round(v / b, 3) if b else None
        cell["vs_top"] = comp


def tier_weeks(tier: Tier, now: datetime) -> list[datetime]:
    """End of each tier week (reset to reset) from week 1 up to now."""
    end = min(now, tier.ends) if tier.ends else now
    weeks, t = [], tier.starts
    while t < end:
        t = t + timedelta(days=7)
        weeks.append(min(t, end))
    return weeks


def weekly_kill_share(members: list[GuildRow], boss, weeks: list[datetime]) -> list[float | None]:
    if not members:
        return [None] * len(weeks)
    kill_times = [datetime.fromisoformat(g.rio_first_defeated[boss.rio_slug].replace("Z", "+00:00"))
                  for g in members if boss.rio_slug in g.rio_first_defeated]
    return [round(sum(1 for k in kill_times if k <= w) / len(members), 4) for w in weeks]


def build_snapshot(tier: Tier, guilds: list[GuildRow], now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    weeks = tier_weeks(tier, now)
    views = {}
    for view in config.REGIONS:
        by_bracket: dict[str, list[GuildRow]] = {label: [] for label, _, _ in config.BRACKETS}
        for g in guilds:
            b = bracket_of(view_rank(g, view))
            if b:
                by_bracket[b].append(g)
        bosses = {}
        for boss in tier.bosses:
            cells = {label: boss_cell(members, boss) for label, members in by_bracket.items()}
            add_comparisons(cells)
            for label, members in by_bracket.items():
                cells[label]["kill_share_weekly"] = weekly_kill_share(members, boss, weeks)
            bosses[boss.rio_slug] = cells
        views[view] = {
            "bracket_sizes": {label: len(m) for label, m in by_bracket.items()},
            "bosses": bosses,
        }
    return {
        "schema": 1,
        "tier": {"key": tier.key, "name": tier.name, "wcl_zone_id": tier.wcl_zone_id,
                 "starts": tier.starts.isoformat()},
        "generated_at": now.isoformat(),
        "bosses": [{"slug": b.rio_slug, "name": b.name, "wcl_encounter_id": b.wcl_encounter_id}
                   for b in tier.bosses],
        "brackets": [{"label": l, "from": lo, "to": hi} for l, lo, hi in config.BRACKETS],
        "metrics": list(METRICS),
        "weeks": [w.isoformat() for w in weeks],
        "rules": {"min_sample": config.MIN_BRACKET_SAMPLE, "min_pull_seconds": config.MIN_PULL_SECONDS,
                  "night_gap_hours": config.NIGHT_GAP_HOURS, "low_pull_fraction": config.LOW_PULL_FRACTION,
                  "exclude_first_pull_kills": config.EXCLUDE_FIRST_PULL_KILLS},
        "views": views,
    }
