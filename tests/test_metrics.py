from guildpulls.metrics import boss_result, count_nights, guild_results, progression_pulls
from tests.helpers import H, S, T0, pull


def test_pulls_to_kill_counts_through_first_kill():
    pulls = [pull(0), pull(600), pull(1200, kill=True, ilvl=712.4), pull(2000), pull(3000, kill=True)]
    r = boss_result(3470, pulls)
    assert r.killed and r.pulls == 3
    assert r.item_level == 712.4
    assert r.first_kill_ms == T0 + 1200 * S


def test_resets_under_ten_seconds_are_ignored():
    pulls = [pull(0, dur_s=4), pull(60, dur_s=9.9), pull(120, dur_s=10), pull(600, kill=True)]
    r = boss_result(3470, pulls)
    assert r.pulls == 2
    assert r.combat_ms == (10 + 300) * S


def test_short_kill_is_not_dropped():
    assert progression_pulls([pull(0), pull(600, dur_s=8, kill=True)])[-1].kill


def test_combat_time_sums_pull_durations_only():
    pulls = [pull(0, dur_s=120), pull(1000, dur_s=240), pull(5000, dur_s=360, kill=True)]
    assert boss_result(3470, pulls).combat_ms == 720 * S
    assert abs(boss_result(3470, pulls).combat_hours - 0.2) < 1e-9


def test_nights_split_on_gaps_over_six_hours():
    h = 3600
    # night 1 runs past midnight (gaps of 1 h), then a 6 h gap exactly (same night),
    # then a 6 h + 1 s gap (new night), then two days later.
    starts = [0, 1 * h, 2 * h, 8 * h, 14 * h + 1, 62 * h]
    assert count_nights([T0 + s * S for s in starts]) == 3
    assert count_nights([]) == 0
    assert count_nights([T0]) == 1


def test_raid_nights_to_kill():
    h = 3600
    pulls = [pull(0), pull(h), pull(48 * h), pull(49 * h), pull(96 * h, kill=True)]
    assert boss_result(3470, pulls).nights == 3


def test_no_kill_reports_progress_without_item_level():
    r = boss_result(3470, [pull(0), pull(600)])
    assert not r.killed and r.pulls == 2 and r.item_level is None and r.first_kill_ms is None


def test_first_pull_kill_is_flagged():
    assert boss_result(3470, [pull(0, kill=True)]).first_pull_is_kill
    assert not boss_result(3470, [pull(0), pull(600, kill=True)]).first_pull_is_kill
    # a reset before the kill doesn't count as a logged progression pull
    assert boss_result(3470, [pull(0, dur_s=3), pull(600, kill=True)]).first_pull_is_kill


def test_bosses_are_independent():
    pulls = [pull(0, boss=1), pull(600, boss=2), pull(1200, boss=1, kill=True), pull(1800, boss=2)]
    res = guild_results(pulls, [1, 2, 3])
    assert res[1].pulls == 2 and res[1].killed
    assert res[2].pulls == 2 and not res[2].killed
    assert 3 not in res


def test_input_order_does_not_matter():
    pulls = [pull(1200, kill=True), pull(0), pull(600)]
    assert boss_result(3470, pulls).pulls == 3


def test_kill_found_after_unordered_farm():
    pulls = [pull(9 * H // S, kill=True), pull(0), pull(5 * H // S, kill=True)]
    r = boss_result(3470, pulls)
    assert r.pulls == 2 and r.first_kill_ms == T0 + 5 * H
