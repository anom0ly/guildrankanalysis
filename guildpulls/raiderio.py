"""Raider.IO raid rankings: the guild list, world rank, region rank, kill dates."""
from __future__ import annotations

import logging
import time
from typing import Callable

import requests

from guildpulls.config import Tier

BASE = "https://raider.io/api/v1/raiding/raid-rankings"
PAGE_SIZE = 50
log = logging.getLogger(__name__)
USER_AGENT = "guildrankanalysis/0.1 (+https://github.com/anom0ly/guildrankanalysis)"


def parse_entry(entry: dict) -> dict:
    g = entry["guild"]
    pulls_public = entry.get("guildPrivacy", {}).get("raidPulls", True)
    return {
        "rio_guild_id": g["id"],
        "name": g["name"],
        "realm": g["realm"]["slug"],
        "region": g["region"]["slug"],
        "world_rank": entry["rank"],
        "region_rank": entry.get("regionRank"),
        "first_defeated": {
            e["slug"]: e["firstDefeated"]
            for e in entry.get("encountersDefeated", [])
            if e.get("firstDefeated")
        },
        # Pulls to kill per boss, only for kills and only when the guild shares pulls.
        "rio_pulls": {
            e["slug"]: e["numPulls"]
            for e in entry.get("encountersPulled", [])
            if pulls_public and e.get("isDefeated") and e.get("numPulls")
        },
    }


def in_scope(world_rank: int, region_rank: int | None, max_rank: int) -> bool:
    return world_rank <= max_rank or (region_rank is not None and region_rank <= max_rank)


def fetch_rankings(tier: Tier, max_rank: int, session: requests.Session | None = None,
                   sleep: Callable[[float], None] = time.sleep, delay: float = 0.25) -> list[dict]:
    """Mythic world rankings for the tier: every guild in the world top max_rank,
    plus every guild in its own region's top max_rank.

    Raider.IO's region lists are short (about 1,700 US and 2,400 EU guilds in
    week 10 of The Venomous Abyss), so the whole world list is read: it has
    every guild with a region rank, and both ranks on each entry.
    """
    s = session or requests.Session()
    s.headers.setdefault("User-Agent", USER_AGENT)
    out: list[dict] = []
    page = 0
    while True:
        resp = _get(s, {"raid": tier.rio_raid, "difficulty": "mythic", "region": "world", "page": page}, sleep)
        entries = resp.get("raidRankings", [])
        log.debug("Raider.IO page %d: %d entries", page, len(entries))
        if not entries:
            break
        for e in entries:
            if in_scope(e["rank"], e.get("regionRank"), max_rank):
                out.append(parse_entry(e))
        if len(entries) < PAGE_SIZE:
            break
        page += 1
        sleep(delay)
    return out


def _get(s: requests.Session, params: dict, sleep: Callable[[float], None], attempts: int = 5) -> dict:
    for i in range(attempts):
        try:
            r = s.get(BASE, params=params, timeout=60)
        except (requests.ConnectionError, requests.Timeout):
            if i == attempts - 1:
                raise
            sleep(2 ** (i + 1))
            continue
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 500, 502, 503, 504) and i < attempts - 1:
            sleep(2 ** (i + 1))
            continue
        r.raise_for_status()
    raise RuntimeError("unreachable")
