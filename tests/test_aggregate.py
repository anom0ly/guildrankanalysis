from datetime import datetime, timezone

from guildpulls import config
from guildpulls.aggregate import GuildRow, boss_cell, bracket_of, build_snapshot, tier_weeks, view_rank
from guildpulls.metrics import BossResult

TIER = config.TIERS["venomous-abyss"]
BOSS = TIER.bosses[0]
NOW = datetime(2026, 10, 23, tzinfo=timezone.utc)


def result(pulls, nights=2, hours=1.0, ilvl=700.0, killed=True, first_pull_is_kill=False):
    return BossResult(BOSS.wcl_encounter_id, killed, pulls, nights, int(hours * 3_600_000),
                      ilvl if killed else None, 0 if killed else None, first_pull_is_kill)


def guild(rank, r=None, region="us", region_rank=None, status="matched", killed_at="2026-09-01T00:00:00Z"):
    return GuildRow(rank, f"g{rank}", region, rank, region_rank or rank, status,
                    {BOSS.wcl_encounter_id: r} if r else {},
                    {BOSS.rio_slug: killed_at} if killed_at else {})


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
