"""Fetch step: ranking list, WCL guild matching, reports and Mythic pulls.

Guilds are processed in rank order so the top brackets fill first. Each guild
is marked done for the current run as soon as its pulls are stored, so a run
that is interrupted (or paused for the WCL budget and killed) picks up where it
stopped when started again with the same run id.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable

from guildpulls import config, raiderio
from guildpulls.config import Tier
from guildpulls.store import Store
from guildpulls.wcl import ReportRef, WCLClient, WCLError

log = logging.getLogger(__name__)

# WCL has no public API coverage for the CN region.
WCL_REGIONS = {"us", "eu", "kr", "tw"}


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def _parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def report_window(tier: Tier, first_defeated: dict[str, str], now: datetime) -> tuple[int, int]:
    """Time range of logs worth reading for one guild.

    Once Raider.IO shows every boss killed, logs after the last first kill
    are farm and are skipped, which saves most of the WCL budget for guilds
    that finished early.
    """
    end = min(now, tier.ends) if tier.ends else now
    kills = [first_defeated.get(b.rio_slug) for b in tier.bosses]
    if all(kills):
        last = max(_parse_iso(k) for k in kills)
        end = min(end, last + timedelta(hours=config.KILL_WINDOW_PADDING_HOURS))
    return _ms(tier.starts), _ms(end)


def reports_to_fetch(listed: list[ReportRef], known: dict, now_ms: int) -> list[ReportRef]:
    """New reports, plus ones fetched while they might still have been growing."""
    live_ms = config.LIVE_REPORT_HOURS * 3_600_000
    out = []
    for ref in listed:
        k = known.get(ref.code)
        if k is None:
            out.append(ref)
        elif k["end_ms"] != ref.end_ms or k["fetched_at_ms"] - k["end_ms"] < live_ms:
            out.append(ref)
    return out


def resolve_guild(store: Store, wcl: WCLClient, g, now: datetime) -> int | None:
    if g["region"] not in WCL_REGIONS:
        return None
    cached = store.get_match(g["rio_guild_id"])
    if cached is not None:
        if cached["wcl_guild_id"] is not None:
            return cached["wcl_guild_id"]
        if now - _parse_iso(cached["checked_at"]) < timedelta(days=config.UNMATCHED_RETRY_DAYS):
            return None
    wcl_id = wcl.find_guild(g["name"], g["realm"], g["region"])
    store.set_match(g["rio_guild_id"], wcl_id, now.isoformat())
    return wcl_id


def refresh_rankings(store: Store, tier: Tier, max_rank: int, now: datetime, **kw) -> int:
    guilds = raiderio.fetch_rankings(tier, max_rank, **kw)
    store.replace_rankings(tier.key, guilds, now.isoformat())
    log.info("stored %d ranked guilds for %s", len(guilds), tier.key)
    return len(guilds)


def collect(store: Store, wcl: WCLClient, tier: Tier, run_id: str, max_rank: int = config.MAX_RANK,
            limit: int | None = None, now: datetime | None = None, deadline: datetime | None = None,
            clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> bool:
    """Fetch new Mythic pulls for every ranked guild not yet done in this run.

    Returns False when the deadline stopped it early, else True (a --limit
    smoke run counts as finished). Stopping between guilds keeps the run
    resumable with the same run id.
    """
    now = now or datetime.now(timezone.utc)
    done = store.done_in_run(tier.key, run_id)
    kills = store.rio_kills(tier.key)
    todo = [g for g in store.guilds(tier.key)
            if raiderio.in_scope(g["world_rank"], g["region_rank"], max_rank) and g["rio_guild_id"] not in done]
    if limit is not None:
        todo = todo[:limit]
    log.info("%d guilds to process (%d already done in run %s)", len(todo), len(done), run_id)

    for n, g in enumerate(todo, 1):
        if deadline is not None and clock() >= deadline:
            log.info("deadline reached after %d of %d guilds; resume with run id %s", n - 1, len(todo), run_id)
            return False
        try:
            status = _collect_guild(store, wcl, tier, g, kills.get(g["rio_guild_id"], {}), now)
        except WCLError as e:
            log.error("rank %d %s: %s", g["world_rank"], g["name"], e)
            status = "error"
        if status != "error":
            store.mark_done(tier.key, g["rio_guild_id"], run_id, status)
        if n % 25 == 0:
            log.info("%d/%d guilds, WCL points left this hour: %.0f", n, len(todo), wcl.rate.remaining)
    return True


def _collect_guild(store: Store, wcl: WCLClient, tier: Tier, g, first_defeated: dict, now: datetime) -> str:
    wcl_id = resolve_guild(store, wcl, g, now)
    if wcl_id is None:
        return "unmatched"
    start_ms, end_ms = report_window(tier, first_defeated, now)
    listed = wcl.list_reports(wcl_id, tier.wcl_zone_id, start_ms, end_ms)
    todo = reports_to_fetch(listed, store.known_reports(tier.key, wcl_id), _ms(now))
    keep = {b.wcl_encounter_id for b in tier.bosses}
    step = config.WCL_REPORTS_PER_QUERY
    for i in range(0, len(todo), step):
        batch = todo[i:i + step]
        fetched = wcl.report_pulls(batch)
        for ref in batch:
            pulls = [p for p in fetched.get(ref.code, []) if p.encounter_id in keep]
            store.save_report(tier.key, wcl_id, ref.code, ref.start_ms, ref.end_ms, _ms(now), pulls)
    return "ok" if listed else "no_logs"
