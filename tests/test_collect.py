from datetime import datetime, timedelta, timezone

from guildpulls import config
from guildpulls.collect import collect, report_window, reports_to_fetch
from guildpulls.store import Store
from guildpulls.wcl import ReportRef
from tests.helpers import pull

TIER = config.TIERS["venomous-abyss"]
NOW = datetime(2026, 10, 23, tzinfo=timezone.utc)
H = 3_600_000


def test_window_ends_after_last_first_kill():
    kills = {b.rio_slug: "2026-09-01T03:00:00Z" for b in TIER.bosses}
    start, end = report_window(TIER, kills, NOW)
    assert start == int(TIER.starts.timestamp() * 1000)
    assert end == int(datetime(2026, 9, 2, 3, tzinfo=timezone.utc).timestamp() * 1000)


def test_window_runs_to_now_while_progressing():
    kills = {TIER.bosses[0].rio_slug: "2026-09-01T03:00:00Z"}
    assert report_window(TIER, kills, NOW)[1] == int(NOW.timestamp() * 1000)


def test_only_new_or_still_growing_reports_are_refetched():
    known = {"old": {"end_ms": 100 * H, "fetched_at_ms": 200 * H},
             "live": {"end_ms": 100 * H, "fetched_at_ms": 101 * H},
             "grew": {"end_ms": 100 * H, "fetched_at_ms": 200 * H}}
    listed = [ReportRef("old", 0, 100 * H), ReportRef("live", 0, 100 * H), ReportRef("grew", 0, 103 * H),
              ReportRef("new", 0, 5 * H)]
    assert [r.code for r in reports_to_fetch(listed, known, 300 * H)] == ["live", "grew", "new"]


class FakeWCL:
    def __init__(self):
        self.rate = type("R", (), {"remaining": 18000})()
        self.lookups = 0

    def find_guild(self, name, realm, region):
        self.lookups += 1
        return None if name == "missing" else 900 + self.lookups

    def list_reports(self, gid, zone, start, end):
        return [ReportRef("R%d" % gid, 0, 1)]

    def encounter_phases(self, code):
        self.phase_lookups = getattr(self, "phase_lookups", 0) + 1
        return {TIER.bosses[0].wcl_encounter_id: [{"id": 1, "name": "Stage One", "intermission": False}]}

    def report_pulls(self, refs):
        return {r.code: [pull(0, code=r.code), pull(600, kill=True, code=r.code, fid=1),
                         pull(0, boss=99999, code=r.code, fid=2)] for r in refs}


def seed(store):
    guilds = [{"rio_guild_id": i, "name": n, "realm": "illidan", "region": reg, "world_rank": i,
               "region_rank": i, "first_defeated": {}}
              for i, n, reg in [(1, "a", "us"), (2, "missing", "eu"), (3, "c", "cn"), (4, "d", "us")]]
    store.replace_rankings(TIER.key, guilds, NOW.isoformat())


def test_collect_is_resumable_and_skips_other_bosses():
    store = Store(":memory:")
    seed(store)
    wcl = FakeWCL()
    assert collect(store, wcl, TIER, "run1", limit=2, now=NOW)
    assert store.run_status_counts(TIER.key, "run1") == {"ok": 1, "unmatched": 1}
    assert collect(store, wcl, TIER, "run1", now=NOW)
    assert store.run_status_counts(TIER.key, "run1") == {"ok": 2, "unmatched": 2}
    assert wcl.lookups == 3  # CN guild never looked up; nothing looked up twice
    pulls = store.pulls_by_guild(TIER.key)
    assert all(p.encounter_id == 3470 for ps in pulls.values() for p in ps)
    assert sum(len(ps) for ps in pulls.values()) == 4


def test_deadline_stops_between_guilds_and_run_resumes():
    store = Store(":memory:")
    seed(store)
    wcl = FakeWCL()
    ticks = iter([NOW, NOW + timedelta(minutes=5), NOW + timedelta(minutes=10)])
    deadline = NOW + timedelta(minutes=8)
    assert not collect(store, wcl, TIER, "run1", now=NOW, deadline=deadline, clock=lambda: next(ticks))
    assert sum(store.run_status_counts(TIER.key, "run1").values()) == 2
    assert collect(store, wcl, TIER, "run1", now=NOW, deadline=NOW + timedelta(hours=1), clock=lambda: NOW)
    assert sum(store.run_status_counts(TIER.key, "run1").values()) == 4


def test_index_reports_run_progress_and_snapshots(tmp_path):
    import json
    from guildpulls.snapshot import write_index, write_snapshot
    store = Store(":memory:")
    seed(store)
    store.start_run(TIER.key, "run1", NOW.isoformat())
    collect(store, FakeWCL(), TIER, "run1", limit=1, now=NOW)
    idx = json.loads(write_index(store, list(config.TIERS.values()), tmp_path, TIER.key, NOW).read_text())
    assert idx["run"] == {"tier": TIER.key, "run_id": "run1", "started_at": NOW.isoformat(),
                          "completed_at": None, "complete": False, "done": 1, "total": 4}
    assert idx["tiers"][0]["snapshot"] is None
    store.complete_run(TIER.key, "run1", NOW.isoformat())
    write_snapshot(store, TIER, tmp_path, NOW)
    idx = json.loads(write_index(store, list(config.TIERS.values()), tmp_path, TIER.key, NOW).read_text())
    assert idx["run"]["complete"]
    assert idx["tiers"][0]["snapshot"] == f"{TIER.key}/latest.json"
    assert (tmp_path / TIER.key / "guilds.json").exists()


def test_region_top_counts_even_outside_the_world_top():
    from guildpulls.raiderio import in_scope
    assert in_scope(5000, 1800, 5000) and in_scope(7000, 4999, 5000)
    assert not in_scope(7000, 5001, 5000) and not in_scope(5001, None, 5000)
    store = Store(":memory:")
    store.replace_rankings(TIER.key, [
        {"rio_guild_id": 1, "name": "a", "realm": "r", "region": "us", "world_rank": 1, "region_rank": 1,
         "first_defeated": {}},
        {"rio_guild_id": 2, "name": "b", "realm": "r", "region": "eu", "world_rank": 6000, "region_rank": 2500,
         "first_defeated": {}},
        {"rio_guild_id": 3, "name": "c", "realm": "r", "region": "eu", "world_rank": 9000, "region_rank": 9000,
         "first_defeated": {}},
    ], NOW.isoformat())
    collect(store, FakeWCL(), TIER, "run1", max_rank=5000, now=NOW)
    assert store.done_in_run(TIER.key, "run1") == {1, 2}


def test_raiderio_pulls_parsed_and_stored():
    from guildpulls.raiderio import parse_entry
    entry = {"rank": 7, "regionRank": 3,
             "guild": {"id": 5, "name": "x", "realm": {"slug": "r"}, "region": {"slug": "eu"}},
             "encountersDefeated": [{"slug": "sszorak", "firstDefeated": "2026-09-01T00:00:00Z"}],
             "guildPrivacy": {"raidPulls": True},
             "encountersPulled": [{"slug": "sszorak", "numPulls": 42, "isDefeated": True},
                                  {"slug": "ulatek", "numPulls": 90, "isDefeated": False},
                                  {"slug": "the-twin-fangs", "isDefeated": True}]}
    g = parse_entry(entry)
    assert g["rio_pulls"] == {"sszorak": 42}
    entry["guildPrivacy"]["raidPulls"] = False
    assert parse_entry(entry)["rio_pulls"] == {}
    store = Store(":memory:")
    store.replace_rankings(TIER.key, [g], NOW.isoformat())
    assert store.rio_pulls(TIER.key) == {5: {"sszorak": 42}}
