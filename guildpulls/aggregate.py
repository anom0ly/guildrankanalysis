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
    rio_pulls: dict[str, int] = field(default_factory=dict)  # Raider.IO pulls to kill, by boss slug


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


@dataclass(frozen=True)
class Entry:
    """One guild's numbers on one boss, after choosing the pull count's source."""
    pulls: int
    source: str  # "wcl", "rio_fill" (no logged kill) or "rio_corrected" (logs missing nights)
    nights: int | None
    combat_hours: float | None
    item_level: float | None

    def value(self, metric: str) -> float | None:
        return {"pulls_to_kill": self.pulls, "nights_to_kill": self.nights,
                "combat_hours": self.combat_hours, "item_level": self.item_level}[metric]


def boss_entry(g: GuildRow, boss, exclude_first_pull_kills: bool) -> Entry | str:
    """Pick the guild's numbers for a boss, or say why it has none.

    WCL is used when the logs have the kill. Raider.IO's pull count fills in
    when they don't, and replaces the WCL count when WCL is under 75% of it
    (the logs are missing nights, so nights and combat time are dropped too).
    """
    rio_n = g.rio_pulls.get(boss.rio_slug)
    r = g.results.get(boss.wcl_encounter_id) if g.status == "matched" else None
    if r is not None and r.killed:
        if rio_n and r.pulls < config.RIO_UNDERCOUNT_FRACTION * rio_n:
            return Entry(rio_n, "rio_corrected", None, None, r.item_level)
        if r.first_pull_is_kill and exclude_first_pull_kills:
            return "incomplete"
        return Entry(r.pulls, "wcl", r.nights, r.combat_hours, r.item_level)
    if rio_n:
        return Entry(rio_n, "rio_fill", None, None, None)
    return "no_pull_data" if boss.rio_slug in g.rio_first_defeated else "not_killed"


def boss_cell(members: list[GuildRow], boss,
              exclude_first_pull_kills: bool | None = None) -> dict:
    """One bracket x boss cell: medians plus the counts the page shows."""
    if exclude_first_pull_kills is None:
        exclude_first_pull_kills = config.EXCLUDE_FIRST_PULL_KILLS
    counts = {"guilds": len(members), "killed": 0, "unmatched": 0, "pending": 0,
              "kill_not_logged": 0, "no_pull_data": 0, "incomplete": 0, "used": 0}
    entries: list[Entry] = []
    for g in members:
        killed = boss.rio_slug in g.rio_first_defeated
        counts["killed"] += killed
        # WCL coverage, shown whether or not Raider.IO fills the gap.
        if g.status != "matched":
            counts[g.status] += 1
        else:
            r = g.results.get(boss.wcl_encounter_id)
            if killed and (r is None or not r.killed):
                counts["kill_not_logged"] += 1
        e = boss_entry(g, boss, exclude_first_pull_kills)
        if isinstance(e, Entry):
            entries.append(e)
        elif e != "not_killed":
            counts[e] += 1

    # Missing nights: pull count under a quarter of the bracket's median.
    if entries:
        floor = config.LOW_PULL_FRACTION * median(e.pulls for e in entries)
        kept = [e for e in entries if e.pulls >= floor]
        counts["incomplete"] += len(entries) - len(kept)
        entries = kept
    counts["used"] = len(entries)
    counts["pulls_source"] = {src: sum(1 for e in entries if e.source == src)
                              for src in ("wcl", "rio_fill", "rio_corrected")}

    medians: dict[str, float | None] = {}
    n: dict[str, int] = {}
    for m in METRICS:
        vals = [v for v in (e.value(m) for e in entries) if v is not None]
        n[m] = len(vals)
        medians[m] = round(median(vals), 3) if len(vals) >= config.MIN_BRACKET_SAMPLE else None
    counts["n"] = n
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


def kill_time(g: GuildRow, boss) -> datetime | None:
    """When the guild first killed the boss: Raider.IO's date, else the logged kill."""
    rio = g.rio_first_defeated.get(boss.rio_slug)
    if rio:
        return datetime.fromisoformat(rio.replace("Z", "+00:00"))
    r = g.results.get(boss.wcl_encounter_id)
    if r is not None and r.killed and r.first_kill_ms is not None:
        return datetime.fromtimestamp(r.first_kill_ms / 1000, timezone.utc)
    return None


def as_of(g: GuildRow, boss, week_end: datetime) -> GuildRow:
    """The guild as it stood on one boss at the end of a week.

    A kill's numbers never change once it happens, so a past week is the
    current data with the kills that came later taken out.
    """
    k = kill_time(g, boss)
    if k is not None and k <= week_end:
        return g
    return GuildRow(g.rio_guild_id, g.name, g.region, g.world_rank, g.region_rank, g.status,
                    {}, {}, {})


WEEKLY_KEYS = ("median", "vs_top", "n", "used", "killed", "guilds", "pulls_source")


def weekly_cells(by_bracket: dict[str, list[GuildRow]], boss, weeks: list[datetime]) -> dict[str, list[dict]]:
    """Each bracket's cell at the end of every tier week, cumulative."""
    out: dict[str, list[dict]] = {label: [] for label in by_bracket}
    for w in weeks:
        cells = {label: boss_cell([as_of(g, boss, w) for g in members], boss)
                 for label, members in by_bracket.items()}
        add_comparisons(cells)
        for label, cell in cells.items():
            out[label].append({k: cell[k] for k in WEEKLY_KEYS})
    return out


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
            weekly = weekly_cells(by_bracket, boss, weeks)
            for label, members in by_bracket.items():
                cells[label]["kill_share_weekly"] = weekly_kill_share(members, boss, weeks)
                cells[label]["weekly"] = weekly[label]
            bosses[boss.rio_slug] = cells
        views[view] = {
            "bracket_sizes": {label: len(m) for label, m in by_bracket.items()},
            "bosses": bosses,
        }
    return {
        "schema": 3,
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
                  "exclude_first_pull_kills": config.EXCLUDE_FIRST_PULL_KILLS,
                  "rio_undercount_fraction": config.RIO_UNDERCOUNT_FRACTION},
        "views": views,
    }
