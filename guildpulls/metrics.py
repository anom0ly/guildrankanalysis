"""Per guild, per boss metric math. Pure functions, no I/O.

Rules (from the metric spec):
- Duplicate logs: same boss and absolute start within 5 s are one pull.
- Pulls shorter than 10 s are resets and are ignored for every metric.
- Only pulls up to and including the first kill count.
- A new raid night starts after a gap of more than 6 hours between pulls.
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

    @property
    def combat_hours(self) -> float:
        return self.combat_ms / 3_600_000


def _better(a: Pull, b: Pull) -> Pull:
    """Pick which copy of a duplicated pull to keep."""
    def score(p: Pull) -> tuple:
        return (p.kill, p.item_level is not None, p.duration_ms)
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


def boss_result(encounter_id: int, pulls: Iterable[Pull]) -> BossResult | None:
    """Metrics for one guild on one boss from that guild's deduped pulls."""
    counted = progression_pulls(p for p in pulls if p.encounter_id == encounter_id)
    if not counted:
        return None
    kill = counted[-1] if counted[-1].kill else None
    return BossResult(
        encounter_id=encounter_id,
        killed=kill is not None,
        pulls=len(counted),
        nights=count_nights([p.start_ms for p in counted]),
        combat_ms=sum(p.duration_ms for p in counted),
        item_level=kill.item_level if kill else None,
        first_kill_ms=kill.start_ms if kill else None,
        first_pull_is_kill=kill is not None and len(counted) == 1,
    )


def guild_results(pulls: Iterable[Pull], encounter_ids: Iterable[int]) -> dict[int, BossResult]:
    """Dedupe a guild's pulls across all its reports, then compute every boss."""
    deduped = dedupe(pulls)
    results = {}
    for eid in encounter_ids:
        r = boss_result(eid, deduped)
        if r is not None:
            results[eid] = r
    return results
