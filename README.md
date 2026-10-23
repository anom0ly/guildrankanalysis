# Guild pull analytics

Compares Mythic raid progression between higher and lower ranked guilds:
pulls to kill, raid nights to kill, time on boss and item level on kill, as
bracket medians for Top 100 / 101-500 / 501-1000 / 1001-5000, under All, US
and EU. The rules follow the metric spec
(https://claude.ai/artifact/F8BfVJ7vtZjbpkbsnmZpX6).

This repo holds the data pipeline. The dashboard reads its snapshot files.

## Running

```sh
pip install -e '.[dev]'
export WCL_CLIENT_ID=...  WCL_CLIENT_SECRET=...   # Warcraft Logs API client

python -m guildpulls run                 # daily refresh of the current tier
python -m guildpulls run --limit 50      # first 50 guilds only
python -m guildpulls status              # progress of today's run
python -m guildpulls snapshot            # recompute medians from stored pulls
python -m guildpulls --tier mn-tier-1 run   # backfill the previous tier
pytest
```

Data goes to `data/guildpulls.sqlite`, snapshots to
`data/snapshots/<tier>/<YYYY-MM-DD>.json` (plus `latest.json`, and a
`-guilds.json` file with each guild's per-boss numbers for spot checks).

## How a run works

1. **Ranks.** Raider.IO `raiding/raid-rankings` (Mythic, world) down to rank
   5000: guild, realm, region, world rank, region rank, first kill date and
   Raider.IO's pull count per boss.
2. **Match.** Each guild is looked up on WCL with
   `guildData.guild(name, serverSlug, serverRegion)`. Matches are cached; a
   miss is retried after 7 days. CN guilds are skipped (no WCL API coverage).
3. **Reports.** `reportData.reports(guildID, zoneID, startTime, endTime)` from
   the tier start. Once Raider.IO shows every boss killed, the window ends a
   day after the last first kill, so farm logs are never fetched.
4. **Pulls.** `report.fights(difficulty: 5, killType: Encounters)` for new
   reports only, 20 reports per aliased query. Raw pulls are stored as logged.
   A report fetched within 12 hours of its end is fetched once more next run
   in case it was still growing.
5. **Metrics** (`guildpulls/metrics.py`). Per guild: collapse duplicate logs
   (same boss, absolute start within 5 s), drop pulls under 10 s, stop at the
   first kill, then count pulls, nights (new night after a gap over 6 h), sum
   combat time, and take the kill pull's average item level.
6. **Brackets** (`guildpulls/aggregate.py`). Pulls to kill comes from WCL when
   the logs have the kill, and from Raider.IO's own pull count when they
   don't (or when WCL is under 75% of Raider.IO's count, which means the logs
   are missing nights; those guilds also drop out of nights and combat time).
   Nights, combat time and item level are WCL only. Guilds under a quarter of
   the bracket median are left out as incomplete. One-shot kills count; the spec's "first logged pull was the kill"
   rule is available as `EXCLUDE_FIRST_PULL_KILLS` but off. A median needs 10 guilds. Lower
   brackets get a multiple of Top 100 (item level: a difference). Each cell
   also carries the counts behind it and the weekly kill share (from Raider.IO
   first kill dates, so guilds without logs count too).

## WCL budget

Every query also asks for `rateLimitData`, so the client always knows the
points left this hour (18,000/hour). Below 500 left it sleeps until the reset.
Guilds go in rank order and each is marked done as soon as its pulls are
saved, so a run that stops can be restarted with the same `--run-id` (default:
today's UTC date) and continues where it left off. 429s and 5xx are retried.

Measured on the first 60 guilds: about 19 points per guild (many top guilds
keep logs private during the race). A typical mid-ranked guild has 20-70
reports, roughly 1 point per report, so the first full load of 5000 guilds is
estimated at 100k-250k points, or 6-14 hours. Daily runs after that only fetch
new reports.

## Adding a tier

Add a `Tier` to `guildpulls/config.py` with the Raider.IO raid slug, WCL zone
id, US start time and the boss list mapped by Raider.IO slug to WCL encounter
id. The zone ids come from `worldData.expansions { zones { id encounters } }`.

## Known limits

- Region views use region rank among the world top 5000, so the US and EU
  1001-5000 brackets are only partly filled.
- Guilds whose logs are private, or missing the kill, are counted in
  `kill_not_logged`. Their pulls to kill can come from Raider.IO, but they are
  left out of nights, combat time and item level. Each cell's `n` gives the
  sample per metric and `pulls_source` how many pull counts came from where.
- Raider.IO's counting method isn't documented; on the top 60 it matched WCL
  within 10% for about two thirds of kills where both had a number.
