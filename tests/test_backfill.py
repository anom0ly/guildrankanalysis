import json
from dataclasses import replace
from datetime import datetime, timezone

from guildpulls import cli, config
from guildpulls.snapshot import load_guild_rows, write_index
from guildpulls.store import Store
from tests.test_collect import FakeWCL as _FakeWCL


class FakeWCL(_FakeWCL):
    points_used = 0


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


def test_deadline_is_next_stop_hour():
    assert cli.backfill_deadline(utc(2026, 10, 23, 10, 30), None) == utc(2026, 10, 24, 9)
    assert cli.backfill_deadline(utc(2026, 10, 24, 3), None) == utc(2026, 10, 24, 9)
    assert cli.backfill_deadline(utc(2026, 10, 24, 3), 60) == utc(2026, 10, 24, 4)


def test_no_backfill_between_stop_hour_and_daily_run():
    assert cli.backfill_deadline(utc(2026, 10, 24, 9, 30), None) is None


def test_backfill_tiers_are_configured_past_tiers():
    for key in config.BACKFILL_TIERS:
        t = config.TIERS[key]
        assert t.ends is not None and t.starts < t.ends
        assert len({b.wcl_encounter_id for b in t.bosses}) == len(t.bosses)
    assert config.CURRENT_TIER not in config.BACKFILL_TIERS


def fake_rankings(store, tier, max_rank, now, **kw):
    guilds = [{"rio_guild_id": i, "name": f"g{i}", "realm": "illidan", "region": "us", "world_rank": i,
               "region_rank": i, "first_defeated": {}} for i in (1, 2)]
    store.replace_rankings(tier.key, guilds, now.isoformat())


def test_backfill_waits_for_the_current_tier(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "refresh_rankings", fake_rankings)
    store = Store(":memory:")
    store.start_run(config.CURRENT_TIER, "2026-10-23", "2026-10-23T10:00:00+00:00")
    wcl = FakeWCL()
    assert cli.backfill(store, utc(2026, 10, 23, 12), None, str(tmp_path), wcl) is True
    assert wcl.lookups == 0


def test_backfill_loads_past_tiers_in_order(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "refresh_rankings", fake_rankings)
    store = Store(":memory:")
    store.start_run(config.CURRENT_TIER, "2026-10-23", "2026-10-23T10:00:00+00:00")
    store.complete_run(config.CURRENT_TIER, "2026-10-23", "2026-10-23T11:00:00+00:00")
    now = datetime.now(timezone.utc).replace(hour=1, minute=0)  # well before the stop hour
    monkeypatch.setattr(cli, "backfill_deadline", lambda now, m: utc(2100, 1, 1))
    assert cli.backfill(store, now, None, str(tmp_path), FakeWCL()) is False
    for key in config.BACKFILL_TIERS:
        assert store.get_run(key, config.BACKFILL_RUN_ID)["completed_at"]
        assert (tmp_path / key / "latest.json").exists()
    idx = json.loads(write_index(store, list(config.TIERS.values()), tmp_path, config.CURRENT_TIER).read_text())
    by_key = {t["key"]: t for t in idx["tiers"]}
    assert by_key[config.BACKFILL_TIERS[0]]["backfill"]["state"] == "complete"
    assert by_key[config.CURRENT_TIER]["backfill"] is None
    assert by_key["manaforge-omega"]["expansion"] == "The War Within"


def test_backfill_progress_while_loading(tmp_path):
    store = Store(":memory:")
    key = config.BACKFILL_TIERS[0]
    fake_rankings(store, config.TIERS[key], 5000, utc(2026, 10, 23))
    store.start_run(key, config.BACKFILL_RUN_ID, "2026-10-23T12:00:00+00:00")
    store.mark_done(key, 1, config.BACKFILL_RUN_ID, "matched")
    idx = json.loads(write_index(store, list(config.TIERS.values()), tmp_path, config.CURRENT_TIER).read_text())
    by_key = {t["key"]: t for t in idx["tiers"]}
    assert by_key[key]["backfill"] == {"state": "loading", "done": 1, "total": 2}
    assert by_key[config.BACKFILL_TIERS[1]]["backfill"]["state"] == "queued"


def test_tier_without_rio_pulls_counts_from_logs_only():
    store = Store(":memory:")
    tier = config.TIERS["nerubar-palace"]
    store.replace_rankings(tier.key, [{"rio_guild_id": 1, "name": "a", "realm": "r", "region": "us",
                                       "world_rank": 1, "region_rank": 1, "first_defeated": {},
                                       "rio_pulls": {tier.bosses[0].rio_slug: 40}}], "2026-10-23")
    assert load_guild_rows(store, tier)[0].rio_pulls == {tier.bosses[0].rio_slug: 40}
    assert load_guild_rows(store, replace(tier, rio_pulls=False))[0].rio_pulls == {}
