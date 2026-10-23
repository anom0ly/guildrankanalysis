"""Learning curve, wipe depth, gear at first pull and raid schedule."""
from datetime import datetime, timedelta, timezone

from guildpulls import config
from guildpulls.aggregate import (GuildRow, boss_cell, bracket_curve, curve_points, guild_schedule_numbers,
                                  late_wipe_share, log_metric, boss_entry, wipe_mix)
from guildpulls.collect import fetch_phase_names
from guildpulls.metrics import Pull, boss_result, fight_left, guild_schedule
from guildpulls.store import Store
from tests.helpers import H, S, T0

TIER = config.TIERS["venomous-abyss"]
BOSS = TIER.bosses[0]
EID = BOSS.wcl_encounter_id


def p(start_s, health=None, phase=None, kill=False, dur_s=300, ilvl=700.0, eid=EID, base=T0):
    start = base + int(start_s * S)
    return Pull(eid, start, start + int(dur_s * S), kill, ilvl, health, phase)


def test_learning_curve_tracks_best_health_and_first_sub10_pull():
    r = boss_result(EID, [p(0, 80), p(600, 85), p(1200, 40), p(1800, 9.5), p(2400, 30), p(3000, kill=True)])
    assert r.best_curve == (80, 80, 40, 9.5, 9.5, 0)
    assert r.pulls_to_sub10 == 4
    assert log_metric(r, "closeout_pulls") == 2


def test_plateau_needs_a_one_point_improvement():
    # 50, then 49.5 (not a full point better), 49.8, 60: three pulls with no real progress.
    r = boss_result(EID, [p(0, 50), p(600, 49.5), p(1200, 49.8), p(1800, 60), p(2400, 30), p(3000, kill=True)])
    assert r.longest_plateau == 3
    assert r.best_curve[:4] == (50, 49.5, 49.5, 49.5)


def test_health_over_100_is_capped_and_missing_health_counts_as_full():
    r = boss_result(EID, [p(0, 114.9), p(600, None), p(1200, kill=True)])
    assert r.best_curve == (100, 100, 0)
    assert r.wipe_bands == (2, 0, 0, 0)


def test_late_wipes_use_kill_phase_when_it_shows_progress():
    pulls = [p(0, 60, 1), p(600, 40, 2), p(1200, 30, 3), p(1800, 20, 3), p(2400, 5, 3, kill=True)]
    r = boss_result(EID, pulls)
    assert r.kill_phase == 3 and r.wipes == 4
    assert late_wipe_share(r) == 50.0


def test_late_wipes_fall_back_to_low_health_without_phases():
    r = boss_result(EID, [p(0, 80, 0), p(600, 25, 0), p(1200, 31, 0), p(1800, kill=True)])
    assert late_wipe_share(r) == round(100 / 3, 1)
    assert r.wipe_bands == (1, 0, 1, 1)  # 80 -> 75-100, 31 -> 25-50, 25 -> 0-25


def test_first_pull_ilvl_and_gain():
    r = boss_result(EID, [p(0, 50, ilvl=310.2), p(600, 20, ilvl=311), p(1200, kill=True, ilvl=314.0)])
    assert r.first_pull_ilvl == 310.2
    assert log_metric(r, "ilvl_gained") == 3.8


def test_pulls_per_hour_uses_time_on_the_boss_each_night():
    # Two nights: 3 pulls over 1h (0..3600s incl. last pull's 5 min) then 2 pulls next day.
    pulls = [p(0, 50), p(1650, 40), p(3300, 30), p(86400, 20), p(86400 + 1500, kill=True)]
    r = boss_result(EID, pulls)
    assert abs(r.boss_hours - (1.0 + (1500 + 300) / 3600)) < 1e-9
    assert log_metric(r, "pulls_per_hour") == round(5 / r.boss_hours, 2)


def guild_with(rank, curve_pulls):
    r = boss_result(EID, curve_pulls)
    return GuildRow(rank, f"g{rank}", "us", rank, rank, "matched", {EID: r},
                    {BOSS.rio_slug: "2026-09-01T00:00:00Z"}, {})


def test_bracket_curve_reaches_zero_at_median_kill():
    members = [guild_with(i, [p(0, 60), p(600, 30)] + [p(1200 + 600 * k, 20) for k in range(i % 3)]
                          + [p(9000, kill=True)]) for i in range(1, 12)]
    cell = boss_cell(members, BOSS, detail=True)
    curve = cell["curve"]
    assert curve[0] == [1, 60] and curve[1] == [2, 30]
    assert curve[-1][1] == 0
    assert cell["wipe_mix"]["by"] == "health" and abs(sum(cell["wipe_mix"]["shares"].values()) - 1) < 1e-3
    assert boss_cell(members[:9], BOSS, detail=True)["curve"] is None


def test_curve_points_thin_out_after_thirty_pulls():
    pts = curve_points(212)
    assert pts[:3] == [1, 2, 3] and 30 in pts and 31 not in pts and 32 in pts and pts[-1] == 212


def test_wipe_mix_by_phase_weights_each_guild_once():
    a = guild_with(1, [p(0, 50, 1), p(600, 40, 2), p(1200, kill=True, phase=2)])
    b = guild_with(2, [p(0, 50, 1)] * 1 + [p(600 * k, 50, 1) for k in range(1, 4)] + [p(9000, kill=True, phase=2)])
    entries = [boss_entry(g, BOSS, False) for g in [a, b] * 5]
    mix = wipe_mix(entries)
    assert mix["by"] == "phase"
    assert mix["shares"] == {"1": 0.75, "2": 0.25}


def sched_guild(nights_at_days, kills):
    pulls = []
    for d in nights_at_days:
        base = int(TIER.starts.timestamp() * 1000) + int(d * 86400 * 1000) + 4 * H
        pulls += [p(0, 50, base=base), p(3300, 40, base=base)]  # one hour per night
    g = GuildRow(1, "g", "us", 1, 1, "matched", {}, kills, {}, guild_schedule(pulls, [EID]))
    return g


def test_schedule_hours_and_nights_per_week():
    kills = {BOSS.rio_slug: (TIER.starts + timedelta(days=20)).isoformat()}
    g = sched_guild([0, 1, 7, 8, 9, 14], {**kills, "x": (TIER.starts + timedelta(days=1)).isoformat()})
    v = guild_schedule_numbers(TIER, g)
    assert v == {"hours_per_week": 2.0, "nights_per_week": 2.0}


def test_schedule_dropped_when_logs_miss_weeks():
    kills = {BOSS.rio_slug: (TIER.starts + timedelta(days=30)).isoformat(),
             "x": (TIER.starts + timedelta(days=1)).isoformat()}
    assert guild_schedule_numbers(TIER, sched_guild([0, 1, 29], kills)) is None  # 2 of 5 weeks logged


class PhaseWCL:
    calls = 0

    def encounter_phases(self, code):
        self.calls += 1
        return {EID: [{"id": 1, "name": "Stage One", "intermission": False},
                      {"id": 2, "name": "Intermission", "intermission": True}]}


def test_phase_names_fetched_once_per_boss():
    store = Store(":memory:")
    store.save_report(TIER.key, 9, "ABC", 0, 1, 0, [p(0, 50, 1)])
    wcl = PhaseWCL()
    assert fetch_phase_names(store, wcl, TIER) == 1
    assert fetch_phase_names(store, wcl, TIER) == 0
    assert wcl.calls == 1
    assert store.phases()[EID][1] == {"id": 2, "name": "Intermission", "intermission": True}


def test_fight_left_prefers_wcl_fight_percentage():
    q = Pull(EID, T0, T0 + 300 * S, False, 700.0, 14.7, 1, fight_percentage=82.9)
    assert fight_left(q, 3) == 82.9


def test_fight_left_estimate_gives_each_stage_an_equal_share():
    # Stage 1 at 15% health on a three-stage boss is far from a kill, not close.
    assert round(fight_left(p(0, 15, 1), 3), 1) == 71.7
    assert round(fight_left(p(0, 30, 3), 3), 1) == 10.0
    assert fight_left(p(0, 40, 1), 1) == 40  # cycles back to stage 1: health only
    assert fight_left(p(0, kill=True), 3) == 0


def test_stage_resets_do_not_count_as_close_wipes():
    pulls = [p(0, 10, 1), p(600, 5, 1), p(1200, 50, 2), p(1800, 50, 3), p(2400, 25, 3), p(3000, kill=True, phase=3)]
    r = boss_result(EID, pulls)
    assert r.pulls_to_sub10 == 5  # stage 3 at 25% health (8% of the fight), not the stage-1 pulls


def test_store_adds_fight_percentage_to_an_older_database(tmp_path):
    import sqlite3
    path = tmp_path / "old.sqlite"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE pulls (tier TEXT NOT NULL, report_code TEXT NOT NULL, fight_id INTEGER NOT NULL, "
               "wcl_guild_id INTEGER NOT NULL, encounter_id INTEGER NOT NULL, start_ms INTEGER NOT NULL, "
               "end_ms INTEGER NOT NULL, kill INTEGER NOT NULL, item_level REAL, boss_percentage REAL, "
               "last_phase INTEGER, PRIMARY KEY (tier, report_code, fight_id))")
    db.execute("INSERT INTO pulls VALUES ('venomous-abyss', 'A', 1, 9, ?, 0, 1, 0, 700, 50, 1)", (EID,))
    db.commit()
    db.close()
    store = Store(path)
    old = store.pulls_by_guild(TIER.key)[9][0]
    assert old.fight_percentage is None
    store.save_report(TIER.key, 9, "B", 0, 1, 0, [Pull(EID, 5, 6, False, 700.0, 40, 2, "B", 1, 61.5)])
    assert {q.fight_percentage for q in store.pulls_by_guild(TIER.key)[9]} == {None, 61.5}


def test_stage_names_skip_intermissions():
    from guildpulls.aggregate import stage_names
    phases = [{"id": 1, "name": "Stage One", "intermission": False},
              {"id": 2, "name": "Intermission", "intermission": True},
              {"id": 3, "name": "Stage Two", "intermission": False}]
    assert stage_names(phases) == {"1": "Stage One", "2": "Stage Two"}
