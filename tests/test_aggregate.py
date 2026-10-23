from datetime import datetime, timezone

from guildpulls import config
from guildpulls.aggregate import Entry, GuildRow, boss_cell, boss_entry, bracket_of, build_snapshot, tier_weeks, view_rank
from guildpulls.metrics import BossResult

TIER = config.TIERS["venomous-abyss"]
BOSS = TIER.bosses[0]
NOW = datetime(2026, 10, 23, tzinfo=timezone.utc)


def result(pulls, nights=2, hours=1.0, ilvl=700.0, killed=True, first_pull_is_kill=False):
    return BossResult(BOSS.wcl_encounter_id, killed, pulls, nights, int(hours * 3_600_000),
                      ilvl if killed else None, 0 if killed else None, first_pull_is_kill)


def guild(rank, r=None, region="us", region_rank=None, status="matched", killed_at="2026-09-01T00:00:00Z",
          rio=None):
    return GuildRow(rank, f"g{rank}", region, rank, region_rank or rank, status,
                    {BOSS.wcl_encounter_id: r} if r else {},
                    {BOSS.rio_slug: killed_at} if killed_at else {},
                    {BOSS.rio_slug: rio} if rio else {})


def test_brackets():
    assert bracket_of(1) == "Top 100" and bracket_of(100) == "Top 100"
    assert bracket_of(101) == "101-500" and bracket_of(500) == "101-500"
    assert bracket_of(1000) == "501-1000" and bracket_of(5000) == "1001-5000"
    assert bracket_of(5001) is None and bracket_of(None) is None


def test_region_view_uses_region_rank():
    g = guild(250, region="eu", region_rank=80)
    assert view_rank(g, "all") == 250 and view_rank(g, "eu") == 80 and view_rank(g, "us") is None


def test_median_needs_ten_guilds():
    members = [guild(i, result(10 + i)) for i in range(1, 10)]
    assert boss_cell(members, BOSS)["median"]["pulls_to_kill"] is None
    members.append(guild(10, result(20)))
    cell = boss_cell(members, BOSS)
    assert cell["used"] == 10
    assert cell["median"]["pulls_to_kill"] == 15.5


def test_medians_of_each_metric():
    members = [guild(i, result(100 + i, nights=i, hours=i / 2, ilvl=690 + i)) for i in range(1, 12)]
    m = boss_cell(members, BOSS)["median"]
    assert m == {"pulls_to_kill": 106, "nights_to_kill": 6, "combat_hours": 3.0, "item_level": 696}


def test_exclusions_are_counted():
    members = [guild(i, result(40)) for i in range(1, 11)]
    members += [
        guild(11, result(1, first_pull_is_kill=True)),     # incomplete: under 1/4 of median
        guild(12, result(9)),                             # incomplete: under 1/4 of median (40)
        guild(13, result(10)),                            # exactly 1/4: kept
        guild(14, None, status="unmatched"),
        guild(15, None, status="pending"),
        guild(16, None),                                  # Raider.IO kill, nothing in logs
        guild(17, result(30, killed=False), killed_at=None),  # still progressing
    ]
    c = boss_cell(members, BOSS)
    assert (c["guilds"], c["killed"], c["used"]) == (17, 16, 11)
    assert (c["incomplete"], c["unmatched"], c["pending"], c["kill_not_logged"]) == (2, 1, 1, 1)
    assert c["kill_share"] == round(16 / 17, 4)


def test_snapshot_multiples_and_item_level_difference():
    guilds = [guild(i, result(10, nights=2, hours=1, ilvl=710)) for i in range(1, 101)]
    guilds += [guild(100 + i, result(23, nights=5, hours=3, ilvl=706.2)) for i in range(1, 21)]
    snap = build_snapshot(TIER, guilds, NOW)
    cells = snap["views"]["all"]["bosses"][BOSS.rio_slug]
    assert cells["Top 100"]["vs_top"]["pulls_to_kill"] is None
    vs = cells["101-500"]["vs_top"]
    assert vs["pulls_to_kill"] == 2.3 and vs["nights_to_kill"] == 2.5 and vs["combat_hours"] == 3.0
    assert vs["item_level"] == -3.8
    assert cells["501-1000"]["median"]["pulls_to_kill"] is None
    assert snap["views"]["us"]["bracket_sizes"]["Top 100"] == 100
    assert snap["views"]["eu"]["bracket_sizes"]["Top 100"] == 0


def test_tier_weeks_and_weekly_kill_share():
    weeks = tier_weeks(TIER, NOW)
    assert weeks[0] == datetime(2026, 8, 25, 15, tzinfo=timezone.utc)
    assert weeks[-1] == NOW and len(weeks) == 10
    guilds = [guild(1, killed_at="2026-08-20T00:00:00Z"), guild(2, killed_at="2026-09-03T00:00:00Z"),
              guild(3, killed_at=None), guild(4, killed_at=None)]
    share = build_snapshot(TIER, guilds, NOW)["views"]["all"]["bosses"][BOSS.rio_slug]["Top 100"]["kill_share_weekly"]
    assert share[:3] == [0.25, 0.25, 0.5] and share[-1] == 0.5


def test_first_pull_kills_can_be_kept():
    members = [guild(i, result(1, first_pull_is_kill=True)) for i in range(1, 8)]
    members += [guild(7 + i, result(3)) for i in range(1, 5)]
    assert boss_cell(members, BOSS, exclude_first_pull_kills=True)["median"]["pulls_to_kill"] is None
    cell = boss_cell(members, BOSS)
    assert cell["used"] == 11 and cell["incomplete"] == 0
    assert cell["median"]["pulls_to_kill"] == 1


def test_wcl_used_when_logs_have_the_kill():
    e = boss_entry(guild(1, result(100, nights=4, hours=6, ilvl=705), rio=110), BOSS, False)
    assert e == Entry(100, "wcl", 4, 6.0, 705)


def test_wcl_higher_than_rio_still_uses_wcl():
    assert boss_entry(guild(1, result(400), rio=300), BOSS, False).source == "wcl"


def test_rio_fills_when_logs_have_no_kill():
    for g in (guild(1, None, rio=80),                          # matched, no logs
              guild(2, result(50, killed=False), rio=80),      # logs stop before the kill
              guild(3, None, status="unmatched", rio=80),      # not on WCL (e.g. CN)
              guild(4, None, status="pending", rio=80)):
        assert boss_entry(g, BOSS, False) == Entry(80, "rio_fill", None, None, None)


def test_rio_replaces_wcl_under_75_percent():
    # 74 < 0.75 * 100: logs missing nights; keep the kill's item level only
    e = boss_entry(guild(1, result(74, nights=3, hours=4, ilvl=708), rio=100), BOSS, False)
    assert e == Entry(100, "rio_corrected", None, None, 708)
    # exactly 75%: WCL kept
    assert boss_entry(guild(1, result(75), rio=100), BOSS, False).source == "wcl"


def test_rio_correction_wins_over_first_pull_rule():
    e = boss_entry(guild(1, result(1, first_pull_is_kill=True), rio=200), BOSS, True)
    assert e.source == "rio_corrected"
    assert boss_entry(guild(1, result(1, first_pull_is_kill=True)), BOSS, True) == "incomplete"


def test_no_data_from_either_source():
    assert boss_entry(guild(1, None), BOSS, False) == "no_pull_data"
    assert boss_entry(guild(1, None, killed_at=None), BOSS, False) == "not_killed"


def test_cell_mixes_sources_and_counts_samples_per_metric():
    members = [guild(i, result(100, nights=5, hours=8, ilvl=700)) for i in range(1, 7)]   # 6 from logs
    members += [guild(6 + i, None, status="unmatched", rio=120) for i in range(1, 4)]      # 3 filled
    members += [guild(10, result(50, ilvl=702), rio=140)]                                  # 1 corrected
    members += [guild(11, None, rio=2)]                                                    # odd value
    c = boss_cell(members, BOSS)
    assert c["pulls_source"] == {"wcl": 6, "rio_fill": 3, "rio_corrected": 1}
    assert c["incomplete"] == 1  # 2 pulls is under a quarter of the median
    assert c["n"] == {"pulls_to_kill": 10, "nights_to_kill": 6, "combat_hours": 6, "item_level": 7}
    assert c["median"]["pulls_to_kill"] == 100
    assert c["median"]["nights_to_kill"] is None  # only 6 guilds have nights
    assert (c["unmatched"], c["kill_not_logged"], c["no_pull_data"]) == (3, 1, 0)


def test_weekly_cells_only_count_kills_made_by_that_week():
    early = [guild(i, result(10), killed_at="2026-08-20T00:00:00Z") for i in range(1, 11)]
    late = [guild(i, result(40), killed_at="2026-09-03T00:00:00Z") for i in range(11, 21)]
    # A logged kill with no Raider.IO date falls back to the log's kill time.
    wcl_only = guild(21, BossResult(BOSS.wcl_encounter_id, True, 40, 2, 3_600_000, 700.0,
                                    int(datetime(2026, 9, 3, tzinfo=timezone.utc).timestamp() * 1000), False),
                     killed_at=None)
    cell = build_snapshot(TIER, early + late + [wcl_only], NOW)["views"]["all"]["bosses"][BOSS.rio_slug]["Top 100"]
    w1, w3 = cell["weekly"][0], cell["weekly"][2]
    assert w1["used"] == 10 and w1["median"]["pulls_to_kill"] == 10 and w1["guilds"] == 21
    assert w3["used"] == 21 and w3["median"]["pulls_to_kill"] == 40
    assert cell["weekly"][-1]["median"] == cell["median"]
    assert len(cell["weekly"]) == len(tier_weeks(TIER, NOW))
