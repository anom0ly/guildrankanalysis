"""Per guild numbers for the dashboard's Head to head and Against peers views.

One compact file per tier, loaded by the page only when one of those views is
opened. Each guild's per boss numbers are the same ones the bracket medians
use (see `aggregate.boss_entry`), so the browser can work out peer medians
with the same rules.
"""
from __future__ import annotations

from datetime import datetime

from guildpulls import config
from guildpulls.aggregate import METRICS, SCHEDULE_METRICS, Entry, GuildRow, boss_entry, guild_schedule_numbers, kill_time
from guildpulls.config import Tier

SCHEMA = 1
SOURCES = ("wcl", "rio_fill", "rio_corrected")
STATUSES = ("matched", "unmatched", "pending")
# Where a guild's numbers for a boss come from when it has a kill but no numbers.
NO_NUMBERS = -1


def _round(m: str, v: float | None) -> float | None:
    if v is None:
        return None
    if isinstance(v, int):
        return v
    return round(v, 2 if m in ("combat_hours", "pulls_per_hour") else 1)


def boss_record(g: GuildRow, boss) -> list | None:
    """[kill time (unix seconds) or None, source index, value per metric], or
    None when the guild has neither a kill nor numbers for the boss."""
    k = kill_time(g, boss)
    e = boss_entry(g, boss, config.EXCLUDE_FIRST_PULL_KILLS)
    if not isinstance(e, Entry):
        return None if k is None else [int(k.timestamp()), NO_NUMBERS]
    values = [_round(m, e.value(m)) for m in METRICS]
    return [int(k.timestamp()) if k else None, SOURCES.index(e.source), *values]


def guild_record(tier: Tier, g: GuildRow) -> list:
    sched = guild_schedule_numbers(tier, g)
    return [
        g.rio_guild_id, g.name, g.realm, g.region, g.world_rank, g.region_rank, STATUSES.index(g.status),
        [boss_record(g, b) for b in tier.bosses],
        [round(sched[m], 2) for m in SCHEDULE_METRICS] if sched else None,
    ]


def compare_file(tier: Tier, rows: list[GuildRow], now: datetime) -> dict:
    return {
        "schema": SCHEMA,
        "tier": tier.key,
        "generated_at": now.isoformat(),
        "bosses": [b.rio_slug for b in tier.bosses],
        "metrics": list(METRICS),
        "tier_metrics": list(SCHEDULE_METRICS),
        "sources": list(SOURCES),
        "statuses": list(STATUSES),
        "low_pull_fraction": config.LOW_PULL_FRACTION,
        "min_sample": config.MIN_BRACKET_SAMPLE,
        "peer_window": config.PEER_WINDOW,
        "fields": ["rio_guild_id", "name", "realm", "region", "world_rank", "region_rank", "status",
                   "bosses", "tier"],
        "guilds": [guild_record(tier, g) for g in rows],
    }
