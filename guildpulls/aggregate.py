"""Bracket roll-up: per guild results -> bracket medians, multiples, kill share."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from statistics import median

from guildpulls import config
from guildpulls.config import Tier
from guildpulls.metrics import BossResult, Schedule

METRICS = ("pulls_to_kill", "nights_to_kill", "combat_hours", "item_level",
           "pulls_to_sub10", "closeout_pulls", "late_wipe_share", "longest_plateau",
           "pulls_per_hour", "first_pull_ilvl", "ilvl_gained")
# Compared with the baseline as a difference rather than a multiple.
DIFF_METRICS = {"item_level", "first_pull_ilvl", "ilvl_gained", "late_wipe_share"}
TIER_METRICS = ("hours_per_week", "nights_per_week")
HEALTH_BANDS = ("75-100", "50-75", "25-50", "0-25")


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
    schedule: Schedule | None = None  # progression raid nights from the logs
    realm: str = ""  # Raider.IO realm slug; names alone aren't unique


def bracket_of(rank: int | None, brackets=None) -> str | None:
    if rank is None:
        return None
    for label, lo, hi in brackets or config.BRACKETS:
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
    result: BossResult | None = None  # the logged progression, when the numbers come from WCL

    def value(self, metric: str) -> float | None:
        base = {"pulls_to_kill": self.pulls, "nights_to_kill": self.nights,
                "combat_hours": self.combat_hours, "item_level": self.item_level}
        if metric in base:
            return base[metric]
        return log_metric(self.result, metric) if self.result is not None else None


def late_wipe_share(r: BossResult) -> float | None:
    """Percent of wipes that were late: in the phase the guild killed the boss
    in. Where that is the first phase (or the boss has no phases in the logs),
    phases don't show progress, so late means 30% boss health or lower."""
    if not r.wipes:
        return None
    if r.kill_phase is not None and r.kill_phase > 1:
        late = dict(r.wipes_by_phase).get(r.kill_phase, 0)
    else:
        late = r.low_wipes
    return round(100 * late / r.wipes, 1)


def log_metric(r: BossResult, metric: str) -> float | None:
    """The new per boss metrics, all from the logged pulls up to the kill."""
    if metric == "pulls_to_sub10":
        return r.pulls_to_sub10
    if metric == "closeout_pulls":
        return r.pulls - r.pulls_to_sub10 if r.pulls_to_sub10 is not None else None
    if metric == "late_wipe_share":
        return late_wipe_share(r)
    if metric == "longest_plateau":
        return r.longest_plateau
    if metric == "pulls_per_hour":
        return round(r.pulls / r.boss_hours, 2) if r.boss_hours > 0 else None
    if metric == "first_pull_ilvl":
        return r.first_pull_ilvl
    if metric == "ilvl_gained":
        if r.item_level is None or r.first_pull_ilvl is None:
            return None
        return round(r.item_level - r.first_pull_ilvl, 2)
    raise KeyError(metric)


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
        return Entry(r.pulls, "wcl", r.nights, r.combat_hours, r.item_level, r)
    if rio_n:
        return Entry(rio_n, "rio_fill", None, None, None)
    return "no_pull_data" if boss.rio_slug in g.rio_first_defeated else "not_killed"


def curve_points(longest: int) -> list[int]:
    """Pull numbers the learning curve is sampled at: every pull early on,
    then sparser, so a 400-pull boss stays small in the snapshot."""
    pts = list(range(1, min(longest, 30) + 1))
    pts += list(range(32, min(longest, 100) + 1, 2))
    pts += list(range(105, longest + 1, 5))
    if longest and pts[-1] != longest:
        pts.append(longest)
    return pts


def bracket_curve(entries: list[Entry]) -> list[list[float]] | None:
    """Median of the guilds' best-health-so-far curves, as [pull, health].
    A guild sits at 0 after its kill, so the line reaches 0 at the median kill."""
    curves = [e.result.best_curve for e in entries if e.result is not None and e.result.best_curve]
    if len(curves) < config.MIN_BRACKET_SAMPLE:
        return None
    out = []
    for n in curve_points(max(len(c) for c in curves)):
        v = median(c[n - 1] if n <= len(c) else 0.0 for c in curves)
        out.append([n, round(v, 1)])
        if v == 0:
            break
    return out


def wipe_mix(entries: list[Entry]) -> dict | None:
    """Where wipes ended, averaged over guilds so each guild counts once: by
    stage when the logs show more than one, else by how much of the fight was left."""
    rs = [e.result for e in entries if e.result is not None and e.result.wipes]
    if len(rs) < config.MIN_BRACKET_SAMPLE:
        return None
    phased = any(ph > 1 for r in rs for ph, _ in r.wipes_by_phase)
    totals: dict[str, float] = {}
    for r in rs:
        parts = ({str(ph): n for ph, n in r.wipes_by_phase} if phased
                 else dict(zip(HEALTH_BANDS, r.wipe_bands)))
        for k, n in parts.items():
            totals[k] = totals.get(k, 0.0) + n / r.wipes
    keys = sorted(totals, key=int) if phased else list(HEALTH_BANDS)
    return {"by": "phase" if phased else "health",
            "shares": {k: round(totals.get(k, 0.0) / len(rs), 4) for k in keys}, "n": len(rs)}


def boss_cell(members: list[GuildRow], boss,
              exclude_first_pull_kills: bool | None = None, detail: bool = False) -> dict:
    """One bracket x boss cell: medians plus the counts the page shows.
    `detail` adds the learning curve and wipe mix (latest week only)."""
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
    out = {"median": medians, **counts}
    if detail:
        out["curve"] = bracket_curve(entries)
        out["wipe_mix"] = wipe_mix(entries)
    return out


def add_comparisons(cells: dict[str, dict], base_cell: dict | None = None) -> None:
    """Multiples of the top bracket; item level as a difference.

    `base_cell` is the baseline when it isn't among `cells` (the slices of the
    top bracket are compared with the whole bracket).
    """
    base_label = config.BRACKETS[0][0]
    base_cell = base_cell or cells.get(base_label, {})
    base = base_cell.get("median", {})
    for label, cell in cells.items():
        cell["vs_top"] = compare(cell["median"], base, cell is base_cell)


def compare(medians: dict, base: dict, is_base: bool) -> dict[str, float | None]:
    comp: dict[str, float | None] = {}
    for m, v in medians.items():
        b = base.get(m)
        if is_base or v is None or b is None:
            comp[m] = None
        elif m in DIFF_METRICS:
            comp[m] = round(v - b, 2)
        else:
            comp[m] = round(v / b, 3) if b else None
    return comp


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


def boss_cells(by_bracket: dict[str, list[GuildRow]], by_slice: dict[str, list[GuildRow]], boss,
               week_end: datetime | None = None) -> dict[str, dict]:
    """Every bracket and slice cell for one boss, with multiples of the top bracket."""
    def members_at(members):
        return members if week_end is None else [as_of(g, boss, week_end) for g in members]
    detail = week_end is None
    cells = {label: boss_cell(members_at(m), boss, detail=detail) for label, m in by_bracket.items()}
    add_comparisons(cells)
    slices = {label: boss_cell(members_at(m), boss, detail=detail) for label, m in by_slice.items()}
    add_comparisons(slices, cells[config.BRACKETS[0][0]])
    return {**cells, **slices}


def weekly_cells(by_bracket: dict[str, list[GuildRow]], by_slice: dict[str, list[GuildRow]], boss,
                 weeks: list[datetime]) -> dict[str, list[dict]]:
    """Each bracket's and slice's cell at the end of every tier week, cumulative."""
    out: dict[str, list[dict]] = {label: [] for label in [*by_bracket, *by_slice]}
    for w in weeks:
        for label, cell in boss_cells(by_bracket, by_slice, boss, w).items():
            out[label].append({k: cell[k] for k in WEEKLY_KEYS})
    return out


def week_index(tier: Tier, ms: int) -> int:
    return int((ms / 1000 - tier.starts.timestamp()) // (7 * 86400))


def guild_schedule_numbers(tier: Tier, g: GuildRow) -> dict[str, float] | None:
    """Hours and nights per logged week, or None when the logs miss too many
    of the weeks the guild's Raider.IO kills span (it would read low)."""
    s = g.schedule
    if g.status != "matched" or s is None or not s.nights or not g.rio_first_defeated:
        return None
    kill_weeks = [week_index(tier, int(datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp() * 1000))
                  for t in g.rio_first_defeated.values()]
    lo, hi = max(0, min(kill_weeks)), max(kill_weeks)
    logged = {week_index(tier, a) for a, _ in s.nights}
    span = range(lo, hi + 1)
    covered = sum(1 for w in span if w in logged)
    if covered < config.SCHEDULE_MIN_WEEK_COVERAGE * len(span):
        return None
    weeks = len(logged)
    return {"hours_per_week": s.hours / weeks, "nights_per_week": len(s.nights) / weeks}


def tier_cell(tier: Tier, members: list[GuildRow]) -> dict:
    """Whole-tier numbers for one bracket: raid schedule medians."""
    vals = [v for v in (guild_schedule_numbers(tier, g) for g in members) if v is not None]
    medians = {m: (round(median(v[m] for v in vals), 2) if len(vals) >= config.MIN_BRACKET_SAMPLE else None)
               for m in TIER_METRICS}
    return {"median": medians, "n": len(vals)}


def tier_summary(tier: Tier, by_bracket: dict[str, list[GuildRow]],
                 by_slice: dict[str, list[GuildRow]]) -> dict[str, dict]:
    cells = {label: tier_cell(tier, m) for label, m in by_bracket.items()}
    base = cells[config.BRACKETS[0][0]]
    for cell in cells.values():
        cell["vs_top"] = compare(cell["median"], base["median"], cell is base)
    for label, m in by_slice.items():
        cell = tier_cell(tier, m)
        cell["vs_top"] = compare(cell["median"], base["median"], False)
        cells[label] = cell
    return cells


def stage_names(phases: list[dict]) -> dict[str, str]:
    """WCL's lastPhase counts stages and skips intermissions, so stage N is
    the Nth phase that isn't an intermission."""
    stages = [p for p in sorted(phases, key=lambda p: p["id"]) if not p["intermission"]]
    return {str(i): p["name"] for i, p in enumerate(stages, 1)}


def build_snapshot(tier: Tier, guilds: list[GuildRow], now: datetime | None = None,
                   phases: dict[int, list[dict]] | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    weeks = tier_weeks(tier, now)
    views = {}
    for view in config.REGIONS:
        by_bracket: dict[str, list[GuildRow]] = {label: [] for label, _, _ in config.BRACKETS}
        by_slice: dict[str, list[GuildRow]] = {label: [] for label, _, _ in config.SLICES}
        for g in guilds:
            rank = view_rank(g, view)
            b = bracket_of(rank)
            if b:
                by_bracket[b].append(g)
            s = bracket_of(rank, config.SLICES)
            if s:
                by_slice[s].append(g)
        groups = {**by_bracket, **by_slice}
        bosses = {}
        for boss in tier.bosses:
            cells = boss_cells(by_bracket, by_slice, boss)
            weekly = weekly_cells(by_bracket, by_slice, boss, weeks)
            for label, members in groups.items():
                cells[label]["kill_share_weekly"] = weekly_kill_share(members, boss, weeks)
                cells[label]["weekly"] = weekly[label]
            bosses[boss.rio_slug] = cells
        views[view] = {
            "bracket_sizes": {label: len(m) for label, m in groups.items()},
            "bosses": bosses,
            "tier_summary": tier_summary(tier, by_bracket, by_slice),
        }
    phases = phases or {}
    return {
        "schema": 5,
        "tier": {"key": tier.key, "name": tier.name, "wcl_zone_id": tier.wcl_zone_id,
                 "starts": tier.starts.isoformat(), "ends": tier.ends.isoformat() if tier.ends else None,
                 "rio_pulls": tier.rio_pulls},
        "generated_at": now.isoformat(),
        "bosses": [{"slug": b.rio_slug, "name": b.name, "wcl_encounter_id": b.wcl_encounter_id}
                   for b in tier.bosses],
        "brackets": [{"label": l, "from": lo, "to": hi} for l, lo, hi in config.BRACKETS],
        "slices": [{"label": l, "from": lo, "to": hi, "parent": config.BRACKETS[0][0]}
                   for l, lo, hi in config.SLICES],
        "metrics": list(METRICS),
        "tier_metrics": list(TIER_METRICS),
        "stages": {b.rio_slug: stage_names(phases.get(b.wcl_encounter_id, [])) for b in tier.bosses},
        "weeks": [w.isoformat() for w in weeks],
        "rules": {"min_sample": config.MIN_BRACKET_SAMPLE, "min_pull_seconds": config.MIN_PULL_SECONDS,
                  "night_gap_hours": config.NIGHT_GAP_HOURS, "low_pull_fraction": config.LOW_PULL_FRACTION,
                  "exclude_first_pull_kills": config.EXCLUDE_FIRST_PULL_KILLS,
                  "rio_undercount_fraction": config.RIO_UNDERCOUNT_FRACTION,
                  "sub10_health": config.SUB10_HEALTH, "plateau_step": config.PLATEAU_STEP,
                  "low_wipe_health": config.LOW_WIPE_HEALTH,
                  "schedule_min_week_coverage": config.SCHEDULE_MIN_WEEK_COVERAGE},
        "views": views,
    }
