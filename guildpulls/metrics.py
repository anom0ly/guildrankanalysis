"""Per guild, per boss metric math. Pure functions, no I/O.

Rules (from the metric spec):
- Duplicate logs: same boss and absolute start within 5 s are one pull.
- Pulls shorter than 10 s are resets and are ignored for every metric.
- Only pulls up to and including the first kill count.
- A new raid night starts after a gap of more than 6 hours between pulls.

Learning curve, wipe depth and gear at first pull come from the same counted
pulls. The raid schedule is per guild across every boss (see `schedule`).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from guildpulls import config


@dataclass(frozen=True)
class Pull:
    encounter_id: int
    start_ms: int  # absolute: report start + fight start
    end_ms: int
    kill: bool
    item_level: float | None = None
    boss_percentage: float | None = None
    last_phase: int | None = None
    report_code: str = ""
    fight_id: int = 0
    # WCL's fightPercentage: progress through the whole fight, across phases.
    # Stored from 23 Oct 2026; older pulls estimate it (see fight_left).
    fight_percentage: float | None = None
    # From the enrich step (None until the report is enriched): the players in
    # the pull, as stored player ids, and its deaths.
    players: tuple[int, ...] | None = None
    deaths: int | None = None
    early_deaths: int | None = None  # deaths in the first EARLY_DEATH_SECONDS
    third_death_ms: int | None = None  # time into the pull of the third death
    killers: tuple[tuple[int, int], ...] | None = None  # (killing ability id, deaths)

    @property
    def enriched(self) -> bool:
        return self.deaths is not None

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


@dataclass(frozen=True)
class BossResult:
    encounter_id: int
    killed: bool
    pulls: int  # pulls to kill, or pulls so far when not killed
    nights: int
    combat_ms: int
    item_level: float | None  # average item level on the kill pull
    first_kill_ms: int | None
    first_pull_is_kill: bool  # spec's "incomplete" signal: progression wasn't logged
    # Learning curve: best boss health % reached so far, after each counted pull.
    best_curve: tuple[float, ...] = ()
    pulls_to_sub10: int | None = None  # pull number of the first pull under 10% (a kill counts)
    longest_plateau: int = 0  # most pulls in a row without a new best (by at least 1 point)
    # Wipe depth: wipes by the phase they ended in, and wipes at 30% boss health or lower.
    wipes_by_phase: tuple[tuple[int, int], ...] = ()
    wipe_bands: tuple[int, int, int, int] = (0, 0, 0, 0)  # wipes at 75-100, 50-75, 25-50, 0-25% health
    wipes: int = 0
    low_wipes: int = 0
    kill_phase: int | None = None
    first_pull_ilvl: float | None = None
    boss_hours: float = 0.0  # raid time spent on this boss: first to last pull of it, per night
    # Deaths, when every counted pull is enriched; else None.
    deaths: int | None = None
    early_deaths: int | None = None
    avoidable_deaths: int | None = None
    fast_losses: int | None = None  # wipes that ended soon after the third death
    killers: tuple[tuple[int, int], ...] = ()
    players_used: int | None = None  # distinct players across the counted pulls
    kill_key: tuple[str, int] | None = None  # (report code, fight id) of the kill pull

    @property
    def combat_hours(self) -> float:
        return self.combat_ms / 3_600_000


def _better(a: Pull, b: Pull) -> Pull:
    """Pick which copy of a duplicated pull to keep."""
    def score(p: Pull) -> tuple:
        return (p.kill, p.item_level is not None, p.enriched, p.duration_ms)
    return a if score(a) >= score(b) else b


def dedupe(pulls: Iterable[Pull], window_ms: int = config.DUPLICATE_WINDOW_MS) -> list[Pull]:
    """Collapse copies of the same pull logged in more than one report.

    Pulls are grouped per boss and walked in start order. A pull within
    window_ms of the first pull of the current group joins that group. Each
    group keeps one pull; if any copy was a kill, the kept pull is a kill.
    """
    by_boss: dict[int, list[Pull]] = {}
    for p in pulls:
        by_boss.setdefault(p.encounter_id, []).append(p)

    out: list[Pull] = []
    for boss_pulls in by_boss.values():
        boss_pulls.sort(key=lambda p: (p.start_ms, p.report_code, p.fight_id))
        group_start: int | None = None
        kept: Pull | None = None
        for p in boss_pulls:
            if kept is not None and group_start is not None and p.start_ms - group_start <= window_ms:
                kept = _better(kept, p)
                continue
            if kept is not None:
                out.append(kept)
            group_start, kept = p.start_ms, p
        if kept is not None:
            out.append(kept)
    out.sort(key=lambda p: (p.start_ms, p.encounter_id))
    return out


def count_nights(start_times_ms: list[int], gap_hours: float = config.NIGHT_GAP_HOURS) -> int:
    if not start_times_ms:
        return 0
    gap_ms = gap_hours * 3_600_000
    times = sorted(start_times_ms)
    return 1 + sum(1 for a, b in zip(times, times[1:]) if b - a > gap_ms)


def progression_pulls(pulls: Iterable[Pull], min_seconds: int = config.MIN_PULL_SECONDS) -> list[Pull]:
    """Pulls for one boss that count: no resets, nothing after the first kill.

    Expects pulls already deduped. Kills are never dropped as resets.
    """
    ordered = sorted(pulls, key=lambda p: p.start_ms)
    out: list[Pull] = []
    for p in ordered:
        if not p.kill and p.duration_ms < min_seconds * 1000:
            continue
        out.append(p)
        if p.kill:
            break
    return out


def split_nights(pulls: list[Pull], gap_hours: float = config.NIGHT_GAP_HOURS) -> list[list[Pull]]:
    """Pulls in start order, grouped into raid nights."""
    gap_ms = gap_hours * 3_600_000
    nights: list[list[Pull]] = []
    for p in sorted(pulls, key=lambda p: p.start_ms):
        if nights and p.start_ms - nights[-1][-1].start_ms <= gap_ms:
            nights[-1].append(p)
        else:
            nights.append([p])
    return nights


def night_hours(night: list[Pull]) -> float:
    return (max(p.end_ms for p in night) - night[0].start_ms) / 3_600_000


def _clamp(v: float) -> float:
    return min(100.0, max(0.0, v))


def fight_left(p: Pull, stages: int) -> float:
    """How much of the fight was left when the pull ended, 0 on a kill.

    WCL's fightPercentage when stored. Otherwise an estimate from the stage
    (lastPhase counts stages, not intermissions) and boss health, giving each
    of the `stages` stages an equal share. Boss health resets between stages
    on many bosses, so health alone would call a stage-one wipe at 15% close.
    WCL can report health over 100 on multi-boss encounters, so it is capped.
    """
    if p.kill:
        return 0.0
    if p.fight_percentage is not None:
        return _clamp(p.fight_percentage)
    health = _clamp(p.boss_percentage if p.boss_percentage is not None else 100.0)
    stage = p.last_phase or 0
    if stages <= 1 or stage < 1 or stage > stages:
        return health
    return _clamp(((stages - stage) * 100 + health) / stages)


def boss_stages(counted: list[Pull]) -> int:
    """Stages the guild has to get through: the stage of its kill, or the
    furthest stage reached. Bosses that cycle back to stage one (kill in
    stage 1) come out as 1, which leaves boss health as the measure."""
    kill = counted[-1] if counted and counted[-1].kill else None
    if kill is not None:
        return kill.last_phase or 0
    return max((p.last_phase or 0) for p in counted) if counted else 0


def learning_curve(counted: list[Pull], step: float = config.PLATEAU_STEP) -> tuple[tuple[float, ...], int | None, int]:
    """Best fight progress so far after each pull (% of the fight left), the
    first sub-10% pull, and the longest run of pulls that didn't beat the
    best by at least `step` points."""
    stages = boss_stages(counted)
    best, curve, sub10 = 100.0, [], None
    run = longest = 0
    for i, p in enumerate(counted, 1):
        h = fight_left(p, stages)
        if h <= best - step or (p.kill and best > 0):
            best, run = h, 0
        else:
            best = min(best, h)
            run += 1
            longest = max(longest, run)
        curve.append(round(best, 1))
        if sub10 is None and h < config.SUB10_HEALTH:
            sub10 = i
    return tuple(curve), sub10, longest


def boss_result(encounter_id: int, pulls: Iterable[Pull]) -> BossResult | None:
    """Metrics for one guild on one boss from that guild's deduped pulls."""
    counted = progression_pulls(p for p in pulls if p.encounter_id == encounter_id)
    if not counted:
        return None
    kill = counted[-1] if counted[-1].kill else None
    curve, sub10, plateau = learning_curve(counted)
    wipes = [p for p in counted if not p.kill]
    by_phase: dict[int, int] = {}
    for p in wipes:
        ph = p.last_phase or 0
        by_phase[ph] = by_phase.get(ph, 0) + 1
    return BossResult(
        encounter_id=encounter_id,
        killed=kill is not None,
        pulls=len(counted),
        nights=count_nights([p.start_ms for p in counted]),
        combat_ms=sum(p.duration_ms for p in counted),
        item_level=kill.item_level if kill else None,
        first_kill_ms=kill.start_ms if kill else None,
        first_pull_is_kill=kill is not None and len(counted) == 1,
        best_curve=curve,
        pulls_to_sub10=sub10,
        longest_plateau=plateau,
        wipes_by_phase=tuple(sorted(by_phase.items())),
        wipe_bands=_bands(wipes, boss_stages(counted)),
        wipes=len(wipes),
        low_wipes=sum(1 for p in wipes if fight_left(p, 1) <= config.LOW_WIPE_HEALTH),
        kill_phase=(kill.last_phase or 0) if kill else None,
        first_pull_ilvl=counted[0].item_level,
        boss_hours=sum(night_hours(n) for n in split_nights(counted)),
        kill_key=(kill.report_code, kill.fight_id) if kill else None,
        **death_numbers(encounter_id, counted),
    )


def death_numbers(encounter_id: int, counted: list[Pull]) -> dict:
    """Deaths and roster size over the counted pulls, left out (None) unless
    every one of them has been enriched, so a half-read guild never reads low."""
    out: dict = {}
    if counted and all(p.enriched for p in counted):
        avoid = config.AVOIDABLE_ABILITIES.get(encounter_id)
        killers: dict[int, int] = {}
        for p in counted:
            for aid, n in p.killers or ():
                killers[aid] = killers.get(aid, 0) + n
        fast = config.FAST_LOSS_SECONDS * 1000
        out.update(
            deaths=sum(p.deaths for p in counted),
            early_deaths=sum(p.early_deaths or 0 for p in counted),
            avoidable_deaths=sum(n for aid, n in killers.items() if aid in avoid) if avoid else None,
            fast_losses=sum(1 for p in counted if not p.kill and p.third_death_ms is not None
                            and p.duration_ms - p.third_death_ms <= fast),
            killers=tuple(sorted(killers.items())),
        )
    if counted and all(p.players is not None for p in counted):
        out["players_used"] = len({pid for p in counted for pid in p.players})
    return out


def _bands(wipes: list[Pull], stages: int) -> tuple[int, int, int, int]:
    out = [0, 0, 0, 0]
    for p in wipes:
        out[min(3, int((100 - fight_left(p, stages)) // 25))] += 1
    return tuple(out)


@dataclass(frozen=True)
class Schedule:
    """A guild's progression raid nights across every boss."""
    nights: tuple[tuple[int, int], ...]  # (first pull start, last pull end) in ms

    @property
    def hours(self) -> float:
        return sum(b - a for a, b in self.nights) / 3_600_000


def schedule(counted_by_boss: Iterable[list[Pull]]) -> Schedule:
    """Raid nights from the counted pulls of every boss: all pulls up to each
    boss's first kill. Farm after a kill is outside the logs we read anyway."""
    allp = [p for ps in counted_by_boss for p in ps]
    return Schedule(tuple((n[0].start_ms, max(p.end_ms for p in n)) for n in split_nights(allp)))


def guild_results(pulls: Iterable[Pull], encounter_ids: Iterable[int]) -> dict[int, BossResult]:
    """Dedupe a guild's pulls across all its reports, then compute every boss."""
    deduped = dedupe(pulls)
    results = {}
    for eid in encounter_ids:
        r = boss_result(eid, deduped)
        if r is not None:
            results[eid] = r
    return results


@dataclass(frozen=True)
class Roster:
    """Who a guild brought across its progression pulls on every boss."""
    regulars: int  # players in at least FILL_IN_PULLS progression pulls
    fill_ins: int
    core_coverage: float  # share of pulls with CORE_PRESENT of the CORE_SIZE most-used players
    new_per_week: float | None  # regulars first seen after the guild's first SETTLE_WEEKS logged weeks


def roster(counted: list[Pull], tier_start_ms: int) -> Roster | None:
    if not counted or any(p.players is None for p in counted):
        return None
    uses: dict[int, int] = {}
    first: dict[int, int] = {}
    week = lambda ms: int((ms - tier_start_ms) // (7 * 86_400_000))
    for p in sorted(counted, key=lambda p: p.start_ms):
        for pid in p.players:
            uses[pid] = uses.get(pid, 0) + 1
            first.setdefault(pid, week(p.start_ms))
    regulars = [pid for pid, n in uses.items() if n >= config.FILL_IN_PULLS]
    core = set(sorted(uses, key=lambda pid: -uses[pid])[:config.CORE_SIZE])
    with_core = sum(1 for p in counted if len(core.intersection(p.players)) >= config.CORE_PRESENT)
    weeks = sorted({week(p.start_ms) for p in counted})
    later = weeks[config.SETTLE_WEEKS:]
    new = sum(1 for pid in regulars if first[pid] in later)
    return Roster(len(regulars), len(uses) - len(regulars), round(with_core / len(counted), 4),
                  round(new / len(later), 3) if later else None)


def guild_roster(pulls: Iterable[Pull], encounter_ids: Iterable[int], tier_start_ms: int) -> Roster | None:
    deduped = dedupe(pulls)
    counted = [p for eid in encounter_ids for p in progression_pulls(q for q in deduped if q.encounter_id == eid)]
    return roster(counted, tier_start_ms)


def first_kills(pulls: Iterable[Pull], encounter_ids: Iterable[int]) -> list[Pull]:
    """The pull each boss was first killed on, after dedupe: the fights whose
    rankings (spec, DPS, HPS) the enrich step fetches."""
    deduped = dedupe(pulls)
    out = []
    for eid in encounter_ids:
        counted = progression_pulls(p for p in deduped if p.encounter_id == eid)
        if counted and counted[-1].kill:
            out.append(counted[-1])
    return out


def guild_schedule(pulls: Iterable[Pull], encounter_ids: Iterable[int]) -> Schedule:
    deduped = dedupe(pulls)
    return schedule(progression_pulls(p for p in deduped if p.encounter_id == eid) for eid in encounter_ids)
