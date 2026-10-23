"""Command line entry point.

    python -m guildpulls run                # daily refresh of the current tier
    python -m guildpulls run --limit 50     # first 50 guilds only (smoke test)
    python -m guildpulls run --max-minutes 285   # stop cleanly in time for a CI job limit
    python -m guildpulls backfill --max-minutes 200   # load past tiers with the time left
    python -m guildpulls snapshot           # recompute medians from stored pulls
    python -m guildpulls status
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timedelta, timezone

from guildpulls import config
from guildpulls.collect import collect, refresh_rankings
from guildpulls.snapshot import write_index, write_snapshot
from guildpulls.store import Store


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="guildpulls")
    p.add_argument("--db", default="data/guildpulls.sqlite")
    p.add_argument("--out", default="data/snapshots")
    p.add_argument("--tier", default=config.CURRENT_TIER, choices=sorted(config.TIERS))
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="refresh ranks, fetch new pulls, write a snapshot")
    run.add_argument("--max-rank", type=int, default=config.MAX_RANK)
    run.add_argument("--limit", type=int, help="process at most this many guilds")
    run.add_argument("--run-id", help="resume this run (default: today's date, UTC)")
    run.add_argument("--max-minutes", type=float,
                     help="stop between guilds after this long; resume later with the same run id")
    run.add_argument("--skip-rankings", action="store_true", help="reuse the stored ranking list")

    bf = sub.add_parser("backfill", help="load past tiers once, oldest unfinished first, until the stop hour")
    bf.add_argument("--max-minutes", type=float, help="stop between guilds after this long")

    sub.add_parser("snapshot", help="recompute medians from stored pulls")
    st = sub.add_parser("status", help="show progress of a run")
    st.add_argument("--run-id")

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    # Keep request URLs (which carry nothing secret, but are noisy) out of the log.
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    tier = config.TIERS[args.tier]
    store = Store(args.db)
    now = datetime.now(timezone.utc)
    run_id = getattr(args, "run_id", None) or now.date().isoformat()

    if args.cmd == "run":
        from guildpulls.wcl import WCLClient
        deadline = now + timedelta(minutes=args.max_minutes) if args.max_minutes else None
        run_tier(store, WCLClient(), tier, run_id, now, deadline, args.out, args.max_rank, args.limit,
                 skip_rankings=args.skip_rankings)
        write_index(store, list(config.TIERS.values()), args.out, tier.key)
    elif args.cmd == "backfill":
        pending = backfill(store, now, args.max_minutes, args.out)
        write_index(store, list(config.TIERS.values()), args.out, config.CURRENT_TIER)
        # Read by the workflow to decide whether to start another chunk.
        print(f"backfill_pending={'true' if pending else 'false'}")
    elif args.cmd == "snapshot":
        print(write_snapshot(store, tier, args.out, now))
        write_index(store, list(config.TIERS.values()), args.out, tier.key)
    elif args.cmd == "status":
        total = len(store.guilds(tier.key))
        print(f"tier {tier.key}, run {run_id}: {store.run_status_counts(tier.key, run_id)} of {total} guilds")
        row = store.get_run(tier.key, run_id)
        print("complete" if row and row["completed_at"] else "not complete")
    store.close()


def run_tier(store: Store, wcl, tier: config.Tier, run_id: str, now: datetime, deadline: datetime | None,
             out: str, max_rank: int = config.MAX_RANK, limit: int | None = None,
             skip_rankings: bool = False) -> bool:
    """Refresh ranks, fetch new pulls and write a snapshot once every guild is
    reached. Returns whether the run is complete."""
    row = store.get_run(tier.key, run_id)
    if row and row["completed_at"]:
        logging.info("run %s of %s already complete", run_id, tier.key)
        return True
    if not skip_rankings and not store.done_in_run(tier.key, run_id):
        refresh_rankings(store, tier, max_rank, now)
    store.start_run(tier.key, run_id, now.isoformat())
    finished = collect(store, wcl, tier, run_id, max_rank, limit, now, deadline)
    logging.info("%s run %s: %s; WCL points used: %.0f", tier.key, run_id,
                 store.run_status_counts(tier.key, run_id), wcl.points_used)
    if not finished:
        logging.info("run %s not finished; no snapshot written", run_id)
        return False
    store.complete_run(tier.key, run_id, datetime.now(timezone.utc).isoformat())
    path = write_snapshot(store, tier, out, now)
    logging.info("snapshot written to %s", path)
    return True


def backfill_deadline(now: datetime, max_minutes: float | None) -> datetime | None:
    """When the backfill must stop starting guilds: the next BACKFILL_STOP_HOUR
    (UTC), or sooner with max_minutes. None between the stop hour and the daily
    run, when there's no time to use."""
    stop = now.replace(hour=config.BACKFILL_STOP_HOUR, minute=0, second=0, microsecond=0)
    if stop <= now:
        stop += timedelta(days=1)
    if stop - now > timedelta(hours=23):
        return None
    if max_minutes is not None:
        stop = min(stop, now + timedelta(minutes=max_minutes))
    return stop


def pending_backfill(store: Store) -> list[config.Tier]:
    out = []
    for key in config.BACKFILL_TIERS:
        row = store.get_run(key, config.BACKFILL_RUN_ID)
        if not (row and row["completed_at"]):
            out.append(config.TIERS[key])
    return out


def backfill(store: Store, now: datetime, max_minutes: float | None, out: str, wcl=None) -> bool:
    """Load past tiers in BACKFILL_TIERS order with the time left. Waits while
    the current tier's latest run is unfinished. Returns whether any remain."""
    todo = pending_backfill(store)
    if not todo:
        return False
    current = store.latest_run(config.CURRENT_TIER)
    if current and not current["completed_at"]:
        logging.info("current tier run %s not finished; backfill waits", current["run_id"])
        return True
    deadline = backfill_deadline(now, max_minutes)
    if deadline is None or deadline - now < timedelta(minutes=10):
        logging.info("no backfill time left before %02d:00 UTC", config.BACKFILL_STOP_HOUR)
        return True
    if wcl is None:
        from guildpulls.wcl import WCLClient
        wcl = WCLClient()
    for tier in todo:
        if datetime.now(timezone.utc) >= deadline:
            break
        if not run_tier(store, wcl, tier, config.BACKFILL_RUN_ID, datetime.now(timezone.utc), deadline, out):
            break
    return bool(pending_backfill(store))
