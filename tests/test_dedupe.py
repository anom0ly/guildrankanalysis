from guildpulls.metrics import boss_result, dedupe, guild_results
from tests.helpers import S, T0, pull


def two_loggers(offset_s: float):
    """The same night logged by two raiders whose clocks differ by offset_s."""
    a = [pull(t, code="A", fid=i) for i, t in enumerate([0, 600, 1200])] + [pull(1800, kill=True, code="A", fid=3)]
    b = [pull(t + offset_s, code="B", fid=i) for i, t in enumerate([0, 600, 1200])] + \
        [pull(1800 + offset_s, kill=True, code="B", fid=3)]
    return a + b


def test_same_pull_in_two_reports_counts_once():
    assert boss_result(3470, dedupe(two_loggers(2))).pulls == 4


def test_five_second_window_is_inclusive():
    assert len(dedupe(two_loggers(5))) == 4
    assert len(dedupe(two_loggers(5.001))) == 8


def test_different_bosses_at_same_time_are_not_merged():
    pulls = [pull(0, boss=1), pull(1, boss=2)]
    assert len(dedupe(pulls)) == 2


def test_partial_overlap_between_reports():
    # Logger A logs the whole night, logger B joins for the last two pulls.
    a = [pull(t, code="A", fid=i) for i, t in enumerate([0, 600, 1200, 1800])]
    b = [pull(1201, code="B", fid=0), pull(1799, code="B", fid=1), pull(2400, code="B", fid=2, kill=True)]
    r = boss_result(3470, dedupe(a + b))
    assert r.pulls == 5 and r.killed


def test_kill_survives_when_one_copy_missed_it():
    # One log cut off before the kill was registered; the other has it.
    a = [pull(0, code="A"), pull(600, dur_s=250, kill=False, code="A", fid=1)]
    b = [pull(1, code="B"), pull(601, kill=True, code="B", fid=1, ilvl=711.0)]
    r = boss_result(3470, dedupe(a + b))
    assert r.killed and r.pulls == 2 and r.item_level == 711.0


def test_copy_with_item_level_preferred():
    a = pull(0, kill=True, ilvl=None, code="A")
    b = pull(2, kill=True, ilvl=709.5, code="B")
    assert dedupe([a, b])[0].item_level == 709.5


def test_back_to_back_pulls_are_not_merged():
    # Two genuine pulls 6 s apart (instant wipe and re-pull) stay separate.
    assert len(dedupe([pull(0, dur_s=12), pull(6, dur_s=200)])) == 2


def test_three_loggers():
    pulls = [pull(t + o, code=c, fid=i) for c, o in (("A", 0), ("B", 1.5), ("C", 3))
             for i, t in enumerate([0, 600])]
    assert len(dedupe(pulls)) == 2


def test_guild_results_dedupes_across_reports():
    res = guild_results(two_loggers(1), [3470])
    assert res[3470].pulls == 4
    assert res[3470].combat_ms == (3 * 300 + 300) * S
    assert res[3470].first_kill_ms == T0 + 1800 * S
