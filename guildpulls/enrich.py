"""Enrich step: a second read of each stored report for roster, deaths and
kill comp, plus WCL's exact fightPercentage for pulls stored before it was
fetched.

Reports are read once, best-ranked guild first, so the top brackets fill
first. A report fetched again by the daily run (it was still growing) is
read again. Then the first kill of each boss per guild gets its rankings
(class, spec, DPS and HPS of every player). Queries run several at once,
since WCL is slow to first open a report. Everything stops cleanly at the
deadline and resumes on the next run.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Callable, Iterator

from guildpulls import config
from guildpulls.config import Tier
from guildpulls.metrics import first_kills
from guildpulls.store import Store
from guildpulls.wcl import WCLClient, WCLError

log = logging.getLogger(__name__)


def fight_enrichment(fight: dict, actors: dict[int, tuple[str, str]], deaths: list[dict],
                     player_ids: dict[tuple[str, str], int]) -> dict:
    """One fight's row for Store.save_enrichment from the enrich query."""
    start = int(fight["startTime"])
    times = sorted(int(d["timestamp"]) - start for d in deaths)
    killers: dict[int, int] = {}
    for d in deaths:
        aid = d.get("killingAbilityGameID") or 0  # 0: WCL doesn't say
        killers[aid] = killers.get(aid, 0) + 1
    early = config.EARLY_DEATH_SECONDS * 1000
    players = [player_ids[actors[a]] for a in fight.get("friendlyPlayers") or [] if a in actors]
    return {
        "fight_percentage": fight.get("fightPercentage"),
        "players": sorted(set(players)),
        "deaths": len(times),
        "early_deaths": sum(1 for t in times if t <= early),
        "third_death_ms": times[2] if len(times) >= 3 else None,
        "killers": killers,
    }


def save_report_enrichment(store: Store, tier: Tier, code: str, rep: dict, now_ms: int) -> None:
    player_ids = store.player_ids(rep["actors"].values())
    by_fight: dict[int, list[dict]] = {}
    for d in rep["deaths"]:
        by_fight.setdefault(d.get("fight"), []).append(d)
    fights = {f["id"]: fight_enrichment(f, rep["actors"], by_fight.get(f["id"], []), player_ids)
              for f in rep["fights"]}
    store.save_enrichment(tier.key, code, now_ms, fights)
    names = {d["killingAbilityGameID"]: d["killingAbilityName"] for d in rep["deaths"]
             if d.get("killingAbilityGameID") and d.get("killingAbilityName")}
    if names:
        store.save_ability_names(names)


def summarize_kill(roles: dict[str, dict]) -> tuple[float | None, float | None, dict[str, int]]:
    """Raid DPS (everyone), raid HPS (healers) and spec counts from rankings."""
    def chars(metric):
        return [c for role in (roles.get(metric) or {}).values() for c in role.get("characters") or []]
    dps_chars, hps_roles = chars("dps"), roles.get("hps") or {}
    raid_dps = round(sum(c.get("amount") or 0 for c in dps_chars), 1) if dps_chars else None
    healers = (hps_roles.get("healers") or {}).get("characters") or []
    raid_hps = round(sum(c.get("amount") or 0 for c in healers), 1) if healers else None
    specs: dict[str, int] = {}
    for c in dps_chars:
        if c.get("class") and c.get("spec"):
            k = f'{c["class"]}-{c["spec"]}'
            specs[k] = specs.get(k, 0) + 1
    return raid_dps, raid_hps, specs


def missing_first_kills(store: Store, tier: Tier) -> dict[str, list[int]]:
    """First-kill fights without a stored summary, by report."""
    have = store.kill_summaries(tier.key)
    eids = [b.wcl_encounter_id for b in tier.bosses]
    out: dict[str, list[int]] = {}
    for pulls in store.pulls_by_guild(tier.key).values():
        for p in first_kills(pulls, eids):
            if (p.report_code, p.fight_id) not in have:
                out.setdefault(p.report_code, []).append(p.fight_id)
    return out


def waves(batches: list, call: Callable, out_of_time: Callable[[], bool]) -> Iterator[tuple]:
    """Run `call` on the batches ENRICH_WORKERS at a time, yielding
    (batch, result) in order; result is None when the query failed. Stops
    starting new waves at the deadline (the caller then sees fewer results)."""
    n = config.ENRICH_WORKERS
    with ThreadPoolExecutor(n) as ex:
        for i in range(0, len(batches), n):
            if out_of_time():
                return
            wave = batches[i:i + n]
            futures = [ex.submit(call, b) for b in wave]
            for b, f in zip(wave, futures):
                try:
                    yield b, f.result()
                except WCLError as e:
                    log.error("query at %s: %s", b[0][0], e)
                    yield b, None
                except Exception:
                    # Anything unexpected in one batch skips that batch, not the whole pass.
                    log.exception("query at %s failed", b[0][0])
                    yield b, None


def enrich(store: Store, wcl: WCLClient, tier: Tier, deadline: datetime | None = None,
           clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> bool:
    """Run the enrich step until done or the deadline. Returns whether work remains."""
    def out_of_time():
        return deadline is not None and clock() >= deadline

    todo = store.reports_to_enrich(tier.key)
    done, total = store.enrich_counts(tier.key)
    log.info("enrich %s: %d of %d reports done, %d to read", tier.key, done, total, len(todo))
    step = config.ENRICH_REPORTS_PER_QUERY
    batches = [[(r["code"], store.fight_ids(tier.key, r["code"])) for r in todo[i:i + step]]
               for i in range(0, len(todo), step)]
    read = skipped = 0
    for batch, got in waves(batches, wcl.enrich_reports, out_of_time):
        if got is None:
            continue
        now_ms = int(clock().timestamp() * 1000)
        for code, _ in batch:
            if code not in got:
                continue
            if got[code].get("unreadable"):
                # Marked done with nothing stored, so it isn't asked for again;
                # its pulls stay unread and leave the guild out of the second
                # read's numbers on those bosses.
                store.mark_enriched(tier.key, code, now_ms)
                skipped += 1
                log.warning("report %s has no event data (private or deleted); skipped", code)
            else:
                save_report_enrichment(store, tier, code, got[code], now_ms)
            read += 1
        if read % 1000 < step:
            log.info("enrich: %d/%d reports read, WCL points left this hour: %.0f", read, len(todo),
                     wcl.rate.remaining)
    if skipped:
        log.info("enrich: %d unreadable reports skipped", skipped)
    if out_of_time():
        log.info("enrich stopped at the deadline after %d of %d reports", read, len(todo))
        return True

    kills = missing_first_kills(store, tier)
    log.info("first kills without rankings: %d in %d reports", sum(map(len, kills.values())), len(kills))
    codes = list(kills)
    step = config.RANKINGS_REPORTS_PER_QUERY
    batches = [[(c, kills[c]) for c in codes[i:i + step]] for i in range(0, len(codes), step)]
    for batch, got in waves(batches, wcl.kill_rankings, out_of_time):
        if got is None:
            continue
        for code, fids in batch:
            for fid in fids:
                store.save_kill_summary(tier.key, code, fid, *summarize_kill(got.get(code, {}).get(fid, {})))
    return out_of_time() or bool(store.reports_to_enrich(tier.key))
