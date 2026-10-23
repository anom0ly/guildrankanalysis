import json
from dataclasses import replace

from guildpulls import config
from guildpulls.aggregate import METRICS
from guildpulls.compare import NO_NUMBERS, SOURCES, compare_file
from tests.test_aggregate import BOSS, NOW, TIER, guild, result


def test_compare_file_carries_the_bracket_numbers():
    g = replace(guild(7, result(42, nights=3, hours=2.5, ilvl=701.26)), realm="illidan")
    out = compare_file(TIER, [g], NOW)
    rec = dict(zip(out["fields"], out["guilds"][0]))
    assert (rec["rio_guild_id"], rec["name"], rec["realm"], rec["region"], rec["world_rank"]) == (7, "g7", "illidan", "us", 7)
    assert out["statuses"][rec["status"]] == "matched"
    boss = rec["bosses"][out["bosses"].index(BOSS.rio_slug)]
    assert boss[0] == 1788220800  # Raider.IO kill time, 1 Sep 2026
    assert SOURCES[boss[1]] == "wcl"
    values = dict(zip(METRICS, boss[2:]))
    assert values["pulls_to_kill"] == 42 and values["nights_to_kill"] == 3
    assert values["combat_hours"] == 2.5 and values["item_level"] == 701.3
    assert out["peer_window"] == config.PEER_WINDOW


def test_raider_io_fills_pulls_for_guilds_without_logs():
    out = compare_file(TIER, [guild(9, status="unmatched", rio=55)], NOW)
    boss = out["guilds"][0][7][out["bosses"].index(BOSS.rio_slug)]
    values = dict(zip(METRICS, boss[2:]))
    assert SOURCES[boss[1]] == "rio_fill" and values["pulls_to_kill"] == 55 and values["nights_to_kill"] is None


def test_kill_without_numbers_and_no_kill():
    out = compare_file(TIER, [guild(3, status="unmatched"), guild(4, killed_at=None)], NOW)
    i = out["bosses"].index(BOSS.rio_slug)
    assert out["guilds"][0][7][i] == [1788220800, NO_NUMBERS]
    assert out["guilds"][1][7][i] is None
    json.dumps(out)  # plain JSON
