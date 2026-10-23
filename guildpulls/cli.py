"""Command line entry point.

    python -m guildpulls run                # daily refresh of the current tier
    python -m guildpulls run --limit 50     # first 50 guilds only (smoke test)
    python -m guildpulls snapshot           # recompute medians from stored pulls
    python -m guildpulls status
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone

from guildpulls import config
from guildpulls.collect import collect, refresh_rankings
from guildpulls.snapshot import write_snapshot
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
    run.add_argument("--skip-rankings", action="store_true", help="reuse the stored ranking list")

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
        wcl = WCLClient()
        if not args.skip_rankings and not store.done_in_run(tier.key, run_id):
            refresh_rankings(store, tier, args.max_rank, now)
        counts = collect(store, wcl, tier, run_id, args.max_rank, args.limit, now)
        logging.info("run %s: %s; WCL points used: %.0f", run_id, counts, wcl.points_used)
        path = write_snapshot(store, tier, args.out, now)
        logging.info("snapshot written to %s", path)
    elif args.cmd == "snapshot":
        print(write_snapshot(store, tier, args.out, now))
    elif args.cmd == "status":
        total = len(store.guilds(tier.key))
        print(f"tier {tier.key}, run {run_id}: {store.run_status_counts(tier.key, run_id)} of {total} guilds")
    store.close()
