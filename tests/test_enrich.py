import json

import pytest
from datetime import timedelta

from guildpulls import config
from guildpulls.aggregate import GuildRow, boss_cell, similarity, tier_cell
from guildpulls.collect import collect
from guildpulls.enrich import enrich, fight_enrichment, summarize_kill
from guildpulls.metrics import Pull, boss_result, first_kills, roster
from guildpulls.snapshot import load_guild_rows, write_snapshot
from guildpulls.store import Store
from tests.helpers import S, T0, pull
from tests.test_collect import NOW, TIER, FakeWCL, seed

BOSS = TIER.bosses[0]
EID = BOSS.wcl_encounter_id
VENOM = 1284209


@pytest.fixture(autouse=True)
def avoidable(monkeypatch):
    # The test pulls are on a boss with no avoidable ability; give it one.
    monkeypatch.setitem(config.AVOIDABLE_ABILITIES, EID, frozenset({VENOM}))


def enriched(p: Pull, players=(1, 2), deaths=0, early=0, third=None, killers=()) -> Pull:
    from dataclasses import replace
    return replace(p, players=tuple(players), deaths=deaths, early_deaths=early, third_death_ms=third,
                   killers=tuple(killers))


def test_fight_enrichment_counts_deaths_from_the_pull_start():
    fight = {"id": 3, "startTime": 10_000, "endTime": 200_000, "fightPercentage": 41.5, "friendlyPlayers": [5, 6, 7]}
    actors = {5: ("Ann", "illidan"), 6: ("Bo", "illidan"), 7: ("Cy", "area-52")}
    ids = {("Ann", "illidan"): 1, ("Bo", "illidan"): 2, ("Cy", "area-52"): 3}
    deaths = [{"fight": 3, "timestamp": 10_000 + t * S, "killingAbilityGameID": a}
              for t, a in [(30, VENOM), (61, 77), (120, 77), (59, None)]]
    row = fight_enrichment(fight, actors, deaths, ids)
    assert row == {"fight_percentage": 41.5, "players": [1, 2, 3], "deaths": 4, "early_deaths": 2,
                   "third_death_ms": 61_000, "killers": {VENOM: 1, 77: 2, 0: 1}}


def test_kill_summary_adds_dps_and_healer_hps():
    roles = {"dps": {"tanks": {"characters": [{"class": "Warrior", "spec": "Protection", "amount": 100}]},
                     "healers": {"characters": [{"class": "Priest", "spec": "Holy", "amount": 10}]},
                     "dps": {"characters": [{"class": "Mage", "spec": "Fire", "amount": 1000},
                                            {"class": "Mage", "spec": "Fire", "amount": 900}]}},
             "hps": {"healers": {"characters": [{"class": "Priest", "spec": "Holy", "amount": 5000}]}}}
    assert summarize_kill(roles) == (2010.0, 5000.0, {"Warrior-Protection": 1, "Priest-Holy": 1, "Mage-Fire": 2})
    assert summarize_kill({}) == (None, None, {})


def test_death_numbers_only_when_every_pull_is_enriched():
    ps = [enriched(pull(0, 120, boss=EID), deaths=5, early=2, third=40_000, killers=[(VENOM, 3), (77, 2)]),
          enriched(pull(600, 300, boss=EID), players=(1, 3), deaths=2, third=None, killers=[(77, 2)]),
          enriched(pull(1200, 300, kill=True, boss=EID), deaths=1, killers=[(77, 1)])]
    r = boss_result(EID, ps)
    assert (r.deaths, r.early_deaths, r.avoidable_deaths, r.fast_losses, r.players_used) == (8, 2, 3, 1, 3)
    assert dict(r.killers) == {VENOM: 3, 77: 5}
    half = boss_result(EID, ps[:2] + [pull(1200, 300, kill=True, boss=EID)])
    assert half.deaths is None and half.players_used is None


def test_roster_regulars_core_and_new_players():
    week = 7 * 86_400_000
    start = T0 - week
    core = tuple(range(1, 21))
    ps = [enriched(pull(i * 600, boss=EID, base=T0 + (i // 3) * week), players=core) for i in range(9)]
    ps[0] = enriched(ps[0], players=core[:15] + (99,))  # 15 of the core: not a full core pull
    ps[8] = enriched(ps[8], players=core[1:] + (50,))
    ps += [enriched(pull(9000, boss=EID, base=T0 + 2 * week), players=core[1:] + (50,)) for _ in range(2)]
    r = roster(ps, start)
    assert r.regulars == 21 and r.fill_ins == 1
    assert r.core_coverage == round(10 / 11, 4)
    assert r.new_per_week == 1.0  # player 50 first seen in the third logged week


def test_comp_similarity():
    assert similarity({"a": 2, "b": 1}, {"a": 2, "b": 1}) == 100.0
    assert similarity({"a": 1}, {"b": 1}) == 0.0


def run_collect(store):
    seed(store)
    collect(store, FakeWCL(), TIER, "run1", now=NOW)
    store.complete_run(TIER.key, "run1", NOW.isoformat())


class EnrichWCL:
    def __init__(self, store):
        self.store, self.calls, self.points_used = store, [], 0
        self.rate = type("R", (), {"remaining": 18000})()

    def enrich_reports(self, items):
        self.calls.append([c for c, _ in items])
        out = {}
        for code, fids in items:
            fights = [{"id": f, "startTime": 0, "endTime": 300_000, "fightPercentage": 0.0 if f == 1 else 52.0,
                       "friendlyPlayers": [1, 2]} for f in fids]
            deaths = [{"fight": 0, "timestamp": 20_000, "killingAbilityGameID": VENOM,
                       "killingAbilityName": "Living Venom"}]
            out[code] = {"fights": fights, "actors": {1: ("Ann", "x"), 2: (code, "x")}, "deaths": deaths}
        return out

    def kill_rankings(self, items):
        return {c: {f: {"dps": {"dps": {"characters": [{"class": "Mage", "spec": "Fire", "amount": 10}]}}}
                    for f in fids} for c, fids in items}


def test_enrich_reads_each_report_once_and_resumes(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "ENRICH_REPORTS_PER_QUERY", 1)
    monkeypatch.setattr(config, "ENRICH_WORKERS", 1)
    store = Store(":memory:")
    run_collect(store)
    assert store.enrich_counts(TIER.key) == (0, 2)
    wcl = EnrichWCL(store)
    ticks = iter([NOW, NOW + timedelta(minutes=20)])
    assert enrich(store, wcl, TIER, NOW + timedelta(minutes=10), clock=lambda: next(ticks, NOW + timedelta(hours=1)))
    assert store.enrich_counts(TIER.key) == (1, 2)
    assert not enrich(store, wcl, TIER, clock=lambda: NOW)
    assert wcl.calls == [["R901"], ["R903"]]  # best-ranked guild first, nothing read twice
    assert not enrich(store, wcl, TIER, clock=lambda: NOW) and len(wcl.calls) == 2

    pulls = store.pulls_by_guild(TIER.key)
    ps = sorted(pulls[901], key=lambda p: p.fight_id)
    assert [p.fight_percentage for p in ps] == [52.0, 0.0]
    assert ps[0].deaths == 1 and ps[0].killers == ((VENOM, 1),) and ps[1].deaths == 0
    assert len(set(ps[0].players)) == 2
    assert store.ability_names() == {VENOM: "Living Venom"}
    assert [(p.report_code, p.fight_id) for p in first_kills(pulls[901], [EID])] == [("R901", 1)]
    assert store.kill_summaries(TIER.key)[("R901", 1)] == {"raid_dps": 10.0, "raid_hps": None,
                                                         "specs": {"Mage-Fire": 1}}

    rows = {g.rio_guild_id: g for g in load_guild_rows(store, TIER)}
    assert rows[1].results[EID].deaths == 1 and rows[1].kill_summaries[EID]["raid_dps"] == 10.0
    assert rows[1].roster is not None

    write_snapshot(store, TIER, tmp_path, NOW)
    detail = json.loads((tmp_path / TIER.key / "guilds.json").read_text())
    assert detail[0]["bosses"][BOSS.rio_slug]["avoidable_deaths"] == 1


def test_refetched_report_is_read_again():
    store = Store(":memory:")
    run_collect(store)
    enrich(store, EnrichWCL(store), TIER, clock=lambda: NOW)
    store.save_report(TIER.key, 901, "R901", 0, 1, 2, [pull(0, code="R901", boss=EID)])
    assert [r["code"] for r in store.reports_to_enrich(TIER.key)] == ["R901"]


def test_cells_and_tier_summary_use_enriched_numbers(monkeypatch):
    monkeypatch.setattr(config, "MIN_BRACKET_SAMPLE", 2)
    ps = [enriched(pull(0, 120, boss=EID), deaths=4, early=1, third=50_000, killers=[(VENOM, 2), (77, 2)]),
          enriched(pull(600, 300, kill=True, boss=EID), deaths=0)]
    r = boss_result(EID, ps)
    kill = {"raid_dps": 1e6, "raid_hps": 2e5, "specs": {"Mage-Fire": 2}}
    gs = [GuildRow(i, f"g{i}", "us", i, i, "matched", {EID: r}, {BOSS.rio_slug: "2026-09-01T00:00:00Z"},
                   {}, None, roster=roster(ps, T0), kill_summaries={EID: kill}) for i in (1, 2)]
    cell = boss_cell(gs, BOSS, detail=True, base_specs={"Mage-Fire": 1.0}, killer_ids=[77, VENOM])
    m = cell["median"]
    assert (m["deaths_per_pull"], m["early_deaths_per_pull"], m["avoidable_deaths_per_pull"]) == (2.0, 0.5, 1.0)
    assert m["fast_loss_share"] == 100.0 and m["players_used"] == 2
    assert (m["raid_dps_on_kill"], m["raid_hps_on_kill"], m["comp_similarity"]) == (1e6, 2e5, 100.0)
    assert cell["killers"]["per_pull"] == {"77": 1.0, str(VENOM): 1.0}
    assert cell["specs"] == {"mean": {"Mage-Fire": 2.0}, "n": 2}
    t = tier_cell(TIER, gs)
    assert t["median"]["regulars"] == 0 and t["n"]["regulars"] == 2  # two pulls: nobody reaches 3


def test_waves_keep_order_and_skip_failed_queries(monkeypatch):
    from guildpulls.enrich import waves
    from guildpulls.wcl import WCLError
    monkeypatch.setattr(config, "ENRICH_WORKERS", 3)

    def call(batch):
        if batch[0][0] == "b":
            raise WCLError("boom")
        return batch[0][0]
    batches = [[(c, [])] for c in "abcde"]
    assert [(b[0][0], r) for b, r in waves(batches, call, lambda: False)] == \
        [("a", "a"), ("b", None), ("c", "c"), ("d", "d"), ("e", "e")]
    stops = iter([False, True])
    assert len(list(waves(batches, call, lambda: next(stops)))) == 3  # one wave, then the deadline
