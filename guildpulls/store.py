"""SQLite storage. Every row carries its tier key so tiers sit side by side."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

from guildpulls.metrics import Pull

SCHEMA = """
CREATE TABLE IF NOT EXISTS guilds (
    tier TEXT NOT NULL,
    rio_guild_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    realm TEXT NOT NULL,
    region TEXT NOT NULL,
    world_rank INTEGER NOT NULL,
    region_rank INTEGER,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (tier, rio_guild_id)
);
CREATE TABLE IF NOT EXISTS rio_kills (
    tier TEXT NOT NULL,
    rio_guild_id INTEGER NOT NULL,
    boss_slug TEXT NOT NULL,
    first_defeated TEXT NOT NULL,
    PRIMARY KEY (tier, rio_guild_id, boss_slug)
);
-- Raider.IO's own pulls-to-kill count per boss (kills only, public pulls only).
CREATE TABLE IF NOT EXISTS rio_pulls (
    tier TEXT NOT NULL,
    rio_guild_id INTEGER NOT NULL,
    boss_slug TEXT NOT NULL,
    num_pulls INTEGER NOT NULL,
    PRIMARY KEY (tier, rio_guild_id, boss_slug)
);
-- Raider.IO guild -> WCL guild id. NULL wcl_guild_id means looked up, not found.
CREATE TABLE IF NOT EXISTS wcl_match (
    rio_guild_id INTEGER PRIMARY KEY,
    wcl_guild_id INTEGER,
    checked_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reports (
    tier TEXT NOT NULL,
    code TEXT NOT NULL,
    wcl_guild_id INTEGER NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    fetched_at_ms INTEGER NOT NULL,
    PRIMARY KEY (tier, code)
);
CREATE INDEX IF NOT EXISTS reports_guild ON reports (tier, wcl_guild_id);
-- Raw Mythic boss pulls as logged, one row per fight per report. Duplicate
-- logs of the same pull are kept here and collapsed when metrics are computed,
-- so a duplicate that arrives on a later day is still caught.
CREATE TABLE IF NOT EXISTS pulls (
    tier TEXT NOT NULL,
    report_code TEXT NOT NULL,
    fight_id INTEGER NOT NULL,
    wcl_guild_id INTEGER NOT NULL,
    encounter_id INTEGER NOT NULL,
    start_ms INTEGER NOT NULL,
    end_ms INTEGER NOT NULL,
    kill INTEGER NOT NULL,
    item_level REAL,
    boss_percentage REAL,
    last_phase INTEGER,
    fight_percentage REAL,
    PRIMARY KEY (tier, report_code, fight_id)
);
CREATE INDEX IF NOT EXISTS pulls_guild ON pulls (tier, wcl_guild_id);
-- Resumable runs: a guild finished in the current run is skipped on restart.
CREATE TABLE IF NOT EXISTS progress (
    tier TEXT NOT NULL,
    rio_guild_id INTEGER NOT NULL,
    run_id TEXT NOT NULL,
    status TEXT NOT NULL,
    PRIMARY KEY (tier, rio_guild_id)
);
-- One row per run; completed_at is set once every guild has been reached.
CREATE TABLE IF NOT EXISTS runs (
    tier TEXT NOT NULL,
    run_id TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    PRIMARY KEY (tier, run_id)
);
-- Phase names per boss from WCL's encounter metadata (shared by every tier).
CREATE TABLE IF NOT EXISTS encounter_phases (
    encounter_id INTEGER NOT NULL,
    phase_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    is_intermission INTEGER NOT NULL,
    PRIMARY KEY (encounter_id, phase_id)
);
CREATE TABLE IF NOT EXISTS snapshots (
    tier TEXT NOT NULL,
    day TEXT NOT NULL,
    path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (tier, day)
);
"""


class Store:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """Columns added after the first load, for databases created before them."""
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(pulls)")}
        if "fight_percentage" not in cols:
            with self.db:
                self.db.execute("ALTER TABLE pulls ADD COLUMN fight_percentage REAL")

    def close(self) -> None:
        self.db.close()

    # Raider.IO
    def replace_rankings(self, tier: str, guilds: Iterable[dict], now_iso: str) -> None:
        """Replace the tier's ranking list with the latest one."""
        with self.db:
            self.db.execute("DELETE FROM guilds WHERE tier = ?", (tier,))
            self.db.execute("DELETE FROM rio_kills WHERE tier = ?", (tier,))
            self.db.execute("DELETE FROM rio_pulls WHERE tier = ?", (tier,))
            for g in guilds:
                self.db.execute(
                    "INSERT INTO guilds VALUES (?,?,?,?,?,?,?,?)",
                    (tier, g["rio_guild_id"], g["name"], g["realm"], g["region"],
                     g["world_rank"], g["region_rank"], now_iso),
                )
                self.db.executemany(
                    "INSERT INTO rio_kills VALUES (?,?,?,?)",
                    [(tier, g["rio_guild_id"], slug, ts) for slug, ts in g["first_defeated"].items()],
                )
                self.db.executemany(
                    "INSERT INTO rio_pulls VALUES (?,?,?,?)",
                    [(tier, g["rio_guild_id"], slug, n) for slug, n in g.get("rio_pulls", {}).items()],
                )

    def guilds(self, tier: str) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM guilds WHERE tier = ? ORDER BY world_rank", (tier,)
        ).fetchall()

    def rio_kills(self, tier: str) -> dict[int, dict[str, str]]:
        out: dict[int, dict[str, str]] = {}
        for r in self.db.execute("SELECT * FROM rio_kills WHERE tier = ?", (tier,)):
            out.setdefault(r["rio_guild_id"], {})[r["boss_slug"]] = r["first_defeated"]
        return out

    def rio_pulls(self, tier: str) -> dict[int, dict[str, int]]:
        out: dict[int, dict[str, int]] = {}
        for r in self.db.execute("SELECT * FROM rio_pulls WHERE tier = ?", (tier,)):
            out.setdefault(r["rio_guild_id"], {})[r["boss_slug"]] = r["num_pulls"]
        return out

    # WCL guild matching
    def get_match(self, rio_guild_id: int) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT * FROM wcl_match WHERE rio_guild_id = ?", (rio_guild_id,)
        ).fetchone()

    def set_match(self, rio_guild_id: int, wcl_guild_id: int | None, now_iso: str) -> None:
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO wcl_match VALUES (?,?,?)", (rio_guild_id, wcl_guild_id, now_iso)
            )

    def matches(self) -> dict[int, int | None]:
        return {r["rio_guild_id"]: r["wcl_guild_id"] for r in self.db.execute("SELECT * FROM wcl_match")}

    # Reports and pulls
    def known_reports(self, tier: str, wcl_guild_id: int) -> dict[str, sqlite3.Row]:
        rows = self.db.execute(
            "SELECT * FROM reports WHERE tier = ? AND wcl_guild_id = ?", (tier, wcl_guild_id)
        )
        return {r["code"]: r for r in rows}

    def save_report(self, tier: str, wcl_guild_id: int, code: str, start_ms: int, end_ms: int,
                    fetched_at_ms: int, pulls: Iterable[Pull]) -> None:
        with self.db:
            self.db.execute("DELETE FROM pulls WHERE tier = ? AND report_code = ?", (tier, code))
            self.db.executemany(
                "INSERT INTO pulls (tier, report_code, fight_id, wcl_guild_id, encounter_id, start_ms, end_ms, "
                "kill, item_level, boss_percentage, last_phase, fight_percentage) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                [(tier, code, p.fight_id, wcl_guild_id, p.encounter_id, p.start_ms, p.end_ms,
                  int(p.kill), p.item_level, p.boss_percentage, p.last_phase, p.fight_percentage) for p in pulls],
            )
            self.db.execute(
                "INSERT OR REPLACE INTO reports VALUES (?,?,?,?,?,?)",
                (tier, code, wcl_guild_id, start_ms, end_ms, fetched_at_ms),
            )

    def pulls_by_guild(self, tier: str) -> dict[int, list[Pull]]:
        out: dict[int, list[Pull]] = {}
        for r in self.db.execute("SELECT * FROM pulls WHERE tier = ?", (tier,)):
            out.setdefault(r["wcl_guild_id"], []).append(Pull(
                encounter_id=r["encounter_id"], start_ms=r["start_ms"], end_ms=r["end_ms"],
                kill=bool(r["kill"]), item_level=r["item_level"], boss_percentage=r["boss_percentage"],
                last_phase=r["last_phase"], report_code=r["report_code"], fight_id=r["fight_id"],
                fight_percentage=r["fight_percentage"],
            ))
        return out

    def report_with_encounter(self, tier: str, encounter_id: int) -> str | None:
        row = self.db.execute(
            "SELECT report_code FROM pulls WHERE tier = ? AND encounter_id = ? LIMIT 1", (tier, encounter_id)
        ).fetchone()
        return row[0] if row else None

    # Phase names
    def phases(self) -> dict[int, list[dict]]:
        out: dict[int, list[dict]] = {}
        for r in self.db.execute("SELECT * FROM encounter_phases ORDER BY encounter_id, phase_id"):
            out.setdefault(r["encounter_id"], []).append(
                {"id": r["phase_id"], "name": r["name"], "intermission": bool(r["is_intermission"])})
        return out

    def save_phases(self, encounter_id: int, phases: Iterable[dict]) -> None:
        with self.db:
            self.db.execute("DELETE FROM encounter_phases WHERE encounter_id = ?", (encounter_id,))
            self.db.executemany(
                "INSERT INTO encounter_phases VALUES (?,?,?,?)",
                [(encounter_id, p["id"], p["name"], int(p["intermission"])) for p in phases],
            )

    # Resumable progress
    def done_in_run(self, tier: str, run_id: str) -> set[int]:
        rows = self.db.execute(
            "SELECT rio_guild_id FROM progress WHERE tier = ? AND run_id = ?", (tier, run_id)
        )
        return {r[0] for r in rows}

    def mark_done(self, tier: str, rio_guild_id: int, run_id: str, status: str) -> None:
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO progress VALUES (?,?,?,?)", (tier, rio_guild_id, run_id, status)
            )

    def run_status_counts(self, tier: str, run_id: str) -> dict[str, int]:
        rows = self.db.execute(
            "SELECT status, COUNT(*) FROM progress WHERE tier = ? AND run_id = ? GROUP BY status",
            (tier, run_id),
        )
        return {r[0]: r[1] for r in rows}

    def start_run(self, tier: str, run_id: str, now_iso: str) -> None:
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO runs VALUES (?,?,?,NULL)", (tier, run_id, now_iso))

    def complete_run(self, tier: str, run_id: str, now_iso: str) -> None:
        with self.db:
            self.db.execute("UPDATE runs SET completed_at = ? WHERE tier = ? AND run_id = ?",
                            (now_iso, tier, run_id))

    def get_run(self, tier: str, run_id: str) -> sqlite3.Row | None:
        return self.db.execute("SELECT * FROM runs WHERE tier = ? AND run_id = ?", (tier, run_id)).fetchone()

    def latest_run(self, tier: str) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT * FROM runs WHERE tier = ? ORDER BY started_at DESC LIMIT 1", (tier,)
        ).fetchone()

    def latest_snapshot(self, tier: str) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT * FROM snapshots WHERE tier = ? ORDER BY day DESC LIMIT 1", (tier,)
        ).fetchone()

    def record_snapshot(self, tier: str, day: str, path: str, now_iso: str) -> None:
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?)", (tier, day, path, now_iso))
