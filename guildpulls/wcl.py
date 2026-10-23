"""Warcraft Logs v2 GraphQL client with rate-limit safeguards.

Every query asks for rateLimitData alongside its real fields, so the client
always knows how many of the hourly points are left. When fewer than the
reserve remain, it sleeps until the hour resets instead of running dry.
Credentials come from WCL_CLIENT_ID / WCL_CLIENT_SECRET and are never logged.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Callable

import requests

from guildpulls import config
from guildpulls.metrics import Pull

TOKEN_URL = "https://www.warcraftlogs.com/oauth/token"
API_URL = "https://www.warcraftlogs.com/api/v2/client"
RATE_FIELDS = "rateLimitData { limitPerHour pointsSpentThisHour pointsResetIn }"
FIGHT_FIELDS = (
    "fights(difficulty: %d, killType: Encounters) "
    "{ id encounterID startTime endTime kill averageItemLevel bossPercentage fightPercentage lastPhase }" % config.MYTHIC
)

log = logging.getLogger(__name__)


class WCLError(RuntimeError):
    pass


@dataclass
class RateLimit:
    limit_per_hour: float = 18_000
    spent: float = 0
    reset_in: float = 3600

    @property
    def remaining(self) -> float:
        return self.limit_per_hour - self.spent


@dataclass(frozen=True)
class ReportRef:
    code: str
    start_ms: int
    end_ms: int


class WCLClient:
    def __init__(self, client_id: str | None = None, client_secret: str | None = None,
                 session: requests.Session | None = None,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.time,
                 reserve: float = config.WCL_RESERVE_POINTS):
        self._id = client_id or os.environ.get("WCL_CLIENT_ID")
        self._secret = client_secret or os.environ.get("WCL_CLIENT_SECRET")
        if not self._id or not self._secret:
            raise WCLError("WCL_CLIENT_ID and WCL_CLIENT_SECRET must be set")
        self.session = session or requests.Session()
        self.sleep = sleep
        self.clock = clock
        self.reserve = reserve
        self.rate = RateLimit()
        self._token: str | None = None
        self._token_expires = 0.0
        self.points_used = 0.0

    # Auth
    def _auth(self) -> str:
        if self._token and self.clock() < self._token_expires - 60:
            return self._token
        r = self.session.post(TOKEN_URL, data={"grant_type": "client_credentials"},
                              auth=(self._id, self._secret), timeout=30)
        if r.status_code != 200:
            raise WCLError(f"token request failed with HTTP {r.status_code}")
        body = r.json()
        self._token = body["access_token"]
        self._token_expires = self.clock() + float(body.get("expires_in", 3600))
        return self._token

    # Rate limiting
    def wait_for_budget(self) -> None:
        if self.rate.remaining >= self.reserve:
            return
        wait = self.rate.reset_in + 5
        log.warning("WCL points low (%.0f left), pausing %.0fs until the hourly reset",
                    self.rate.remaining, wait)
        self.sleep(wait)
        self.rate = RateLimit(limit_per_hour=self.rate.limit_per_hour, spent=0, reset_in=3600)

    def _update_rate(self, data: dict) -> None:
        rl = data.get("rateLimitData")
        if not rl:
            return
        before = self.rate.spent
        self.rate = RateLimit(rl["limitPerHour"], rl["pointsSpentThisHour"], rl["pointsResetIn"])
        if self.rate.spent >= before:
            self.points_used += self.rate.spent - before

    def query(self, body: str, variables: dict | None = None, attempts: int = 5) -> dict:
        """Run `{ body rateLimitData {...} }` and return the data dict."""
        decl, values = _split_vars(variables)
        query = "query%s { %s %s }" % (decl, body, RATE_FIELDS)
        for i in range(attempts):
            self.wait_for_budget()
            try:
                r = self.session.post(API_URL, json={"query": query, "variables": values},
                                      headers={"Authorization": f"Bearer {self._auth()}"}, timeout=90)
            except (requests.ConnectionError, requests.Timeout) as e:
                if i == attempts - 1:
                    raise WCLError(f"WCL request failed: {type(e).__name__}") from None
                self.sleep(2 ** (i + 1))
                continue
            if r.status_code == 429:
                wait = float(r.headers.get("Retry-After", 60))
                log.warning("WCL returned 429, waiting %.0fs", wait)
                self.sleep(wait)
                continue
            if r.status_code == 401:
                self._token = None
                continue
            if r.status_code >= 500 and i < attempts - 1:
                self.sleep(2 ** (i + 1))
                continue
            if r.status_code != 200:
                raise WCLError(f"WCL HTTP {r.status_code}: {r.text[:200]}")
            payload = r.json()
            if payload.get("data"):
                self._update_rate(payload["data"])
            if payload.get("errors"):
                raise WCLError("; ".join(e.get("message", "?") for e in payload["errors"]))
            return payload["data"]
        raise WCLError(f"WCL query failed after {attempts} attempts")

    # Queries used by the pipeline
    def find_guild(self, name: str, realm: str, region: str) -> int | None:
        data = self.query(
            "guildData { guild(name: $name, serverSlug: $realm, serverRegion: $region) { id } }",
            {"name": ("String", name), "realm": ("String", realm), "region": ("String", region)},
        )
        g = data["guildData"]["guild"]
        return g["id"] if g else None

    def list_reports(self, guild_id: int, zone_id: int, start_ms: int, end_ms: int) -> list[ReportRef]:
        out: list[ReportRef] = []
        page = 1
        while True:
            data = self.query(
                "reportData { reports(guildID: $guild, zoneID: $zone, startTime: $start, endTime: $end, "
                "limit: 100, page: $page) { has_more_pages data { code startTime endTime } } }",
                {"guild": ("Int", guild_id), "zone": ("Int", zone_id), "start": ("Float", start_ms),
                 "end": ("Float", end_ms), "page": ("Int", page)},
            )
            reps = data["reportData"]["reports"]
            out.extend(ReportRef(r["code"], int(r["startTime"]), int(r["endTime"])) for r in reps["data"])
            if not reps["has_more_pages"]:
                return out
            page += 1

    def report_pulls(self, refs: list[ReportRef]) -> dict[str, list[Pull]]:
        """Mythic boss fights for several reports in one aliased query."""
        if not refs:
            return {}
        parts = " ".join(f'r{i}: report(code: "{_safe_code(ref.code)}") {{ startTime {FIGHT_FIELDS} }}'
                         for i, ref in enumerate(refs))
        data = self.query(f"reportData {{ {parts} }}")["reportData"]
        out: dict[str, list[Pull]] = {}
        for i, ref in enumerate(refs):
            rep = data.get(f"r{i}")
            out[ref.code] = parse_fights(ref.code, rep) if rep else []
        return out


    def encounter_phases(self, code: str) -> dict[int, list[dict]]:
        """Phase names of every encounter in a report (about 1 point)."""
        data = self.query(f'reportData {{ report(code: "{_safe_code(code)}") '
                          "{ phases { encounterID phases { id name isIntermission } } } }")
        rep = data["reportData"]["report"] or {}
        return {e["encounterID"]: [{"id": p["id"], "name": p["name"], "intermission": bool(p.get("isIntermission"))}
                                   for p in e.get("phases") or []]
                for e in rep.get("phases") or []}


    def enrich_reports(self, items: list[tuple[str, list[int]]]) -> dict[str, dict]:
        """For each (report code, stored fight ids): the fights again (for
        fightPercentage and the players in each), the report's players and
        ability names, and every player death in those fights.

        Deaths come from events, about 10 points a report. The Deaths table
        is cheaper but stops at 200 deaths a report, which a progression night
        passes. The first read of a report's events is slow on WCL's side
        (2-20 s), so callers run several of these at once."""
        if not items:
            return {}

        def events(code, fids, start=None):
            since = f", startTime: {float(start)}" if start is not None else ""
            return (f"events(dataType: Deaths, hostilityType: Friendlies, fightIDs: {sorted(fids)}, "
                    f"limit: 10000{since}) {{ data nextPageTimestamp }}")
        parts = " ".join(
            f'r{i}: report(code: "{_safe_code(code)}") {{ fights(fightIDs: {sorted(fids)}) '
            "{ id startTime endTime fightPercentage friendlyPlayers } "
            'masterData { actors(type: "Player") { id name server } abilities { gameID name } } '
            f"{events(code, fids)} }}"
            for i, (code, fids) in enumerate(items))
        data = self.query(f"reportData {{ {parts} }}")["reportData"]
        out = {}
        for i, (code, fids) in enumerate(items):
            rep = data.get(f"r{i}")
            if not rep:
                continue
            page = rep["events"]
            found = list(page["data"] or [])
            while page.get("nextPageTimestamp"):
                page = self.query(f'reportData {{ report(code: "{_safe_code(code)}") '
                                  f'{{ {events(code, fids, page["nextPageTimestamp"])} }} }}')["reportData"]["report"]["events"]
                found += page["data"] or []
            master = rep.get("masterData") or {}
            names = {a["gameID"]: a["name"] for a in master.get("abilities") or []}
            out[code] = {
                "fights": rep.get("fights") or [],
                "actors": {a["id"]: (a["name"], a["server"] or "") for a in master.get("actors") or []},
                "deaths": [{"fight": e.get("fight"), "timestamp": e.get("timestamp"),
                            "killingAbilityGameID": e.get("killingAbilityGameID"),
                            "killingAbilityName": names.get(e.get("killingAbilityGameID"))}
                           for e in found if e.get("type") == "death"],
            }
        return out

    def kill_rankings(self, items: list[tuple[str, list[int]]]) -> dict[str, dict[int, dict]]:
        """Rankings for kill fights, by report and fight id: each player's
        class, spec and DPS, and the healers' HPS."""
        if not items:
            return {}
        parts = " ".join(
            f'r{i}: report(code: "{_safe_code(code)}") {{ '
            f"dps: rankings(fightIDs: {sorted(fids)}, playerMetric: dps) "
            f"hps: rankings(fightIDs: {sorted(fids)}, playerMetric: hps) }}"
            for i, (code, fids) in enumerate(items))
        data = self.query(f"reportData {{ {parts} }}")["reportData"]
        out: dict[str, dict[int, dict]] = {}
        for i, (code, _) in enumerate(items):
            rep = data.get(f"r{i}") or {}
            fights: dict[int, dict] = {}
            for metric in ("dps", "hps"):
                for entry in ((rep.get(metric) or {}).get("data") or []):
                    fights.setdefault(entry["fightID"], {})[metric] = entry.get("roles") or {}
            out[code] = fights
        return out


def parse_fights(code: str, report: dict) -> list[Pull]:
    base = int(report["startTime"])
    return [
        Pull(
            encounter_id=f["encounterID"],
            start_ms=base + int(f["startTime"]),
            end_ms=base + int(f["endTime"]),
            kill=bool(f.get("kill")),
            item_level=f.get("averageItemLevel") or None,
            boss_percentage=f.get("bossPercentage"),
            last_phase=f.get("lastPhase"),
            fight_percentage=f.get("fightPercentage"),
            report_code=code,
            fight_id=f["id"],
        )
        for f in report.get("fights") or []
        if f.get("encounterID")
    ]


def _split_vars(variables: dict | None) -> tuple[str, dict]:
    """Turn {"name": ("String", v)} into ("($name: String)", {"name": v})."""
    if not variables:
        return "", {}
    decl = ", ".join(f"${k}: {t}" for k, (t, _) in variables.items())
    return f"({decl})", {k: v for k, (_, v) in variables.items()}


def _safe_code(code: str) -> str:
    if not code.isalnum():
        raise WCLError(f"unexpected report code {code!r}")
    return code
