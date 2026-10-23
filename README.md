# Guild pull analytics

Compares Mythic raid progression between higher and lower ranked guilds:
pulls to kill, raid nights to kill, time on boss, learning curve, wipe depth,
raid schedule, item level (on the first pull and on the kill), deaths,
roster stability and raid comp and throughput on the first kill, as
bracket medians for 1-200 (Hall of Fame, also split into 1-20 and 21-200) /
201-400 / 401-600 / 601-1000 / 1001-1200 / 1201-1500 / 1501-2000 / 2001-3000 /
3001-5000, under All, US and EU. The rules follow the metric spec
(https://claude.ai/artifact/F8BfVJ7vtZjbpkbsnmZpX6).

This repo holds the data pipeline, the dashboard (`site/`), and the GitHub
Actions workflow that refreshes the data daily and publishes the dashboard to
GitHub Pages.

## Running

```sh
pip install -e '.[dev]'
export WCL_CLIENT_ID=...  WCL_CLIENT_SECRET=...   # Warcraft Logs API client

python -m guildpulls run                 # daily refresh of the current tier
python -m guildpulls run --limit 50      # first 50 guilds only
python -m guildpulls run --max-minutes 270   # stop between guilds after 4.5 h
python -m guildpulls status              # progress of today's run
python -m guildpulls snapshot            # recompute medians from stored pulls
python -m guildpulls --tier mn-tier-1 run   # load one past tier by hand
python -m guildpulls enrich --max-minutes 200     # second read: roster, deaths, comp
python -m guildpulls backfill --max-minutes 200   # load past tiers with the time left
pytest
```

Data goes to `data/guildpulls.sqlite`, snapshots to
`data/snapshots/<tier>/<YYYY-MM-DD>.json` (plus `latest.json`, and
`guilds.json` with each guild's per-boss numbers for spot checks), and
`data/snapshots/index.json` lists the tiers with data and the latest run's
progress. A snapshot is only written once a run has reached every guild.

To preview the dashboard locally, copy the snapshots into `site/data/` and
serve the folder:

```sh
cp -r data/snapshots site/data && python -m http.server -d site 8000
```

## How a run works

1. **Ranks.** Raider.IO `raiding/raid-rankings` (Mythic, world), the whole
   list: every guild in the world top 5000 or in its region's top 5000, with
   realm, region, world rank, region rank, first kill dates and Raider.IO's
   pull count per boss. Raider.IO's region lists are short (in week 10 of The
   Venomous Abyss about 1,660 US and 2,380 EU guilds, 5,584 worldwide), so
   reading the world list to its end covers each region's top 5000.
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
   combat time, and take the kill pull's average item level. From the same
   pulls: the learning curve (best share of the fight left so far, pulls to
   the first sub-10% pull, close-out pulls, longest plateau without a 1-point
   improvement), wipe depth (wipes by stage and by fight left), pulls per hour
   on the boss, and item level on the first pull. Fight left is WCL's
   `fightPercentage`, stored from 23 Oct 2026; older pulls estimate it from
   `lastPhase` (which counts stages, not intermissions) and boss health. The
   raid schedule is per guild across all bosses: nights and hours of
   progression pulls per logged week.
6. **Brackets** (`guildpulls/aggregate.py`). Pulls to kill comes from WCL when
   the logs have the kill, and from Raider.IO's own pull count when they
   don't (or when WCL is under 75% of Raider.IO's count, which means the logs
   are missing nights; those guilds also drop out of nights and combat time).
   Nights, combat time and item level are WCL only. Guilds under a quarter of
   the bracket median are left out as incomplete. One-shot kills count; the spec's "first logged pull was the kill"
   rule is available as `EXCLUDE_FIRST_PULL_KILLS` but off. A median needs 10 guilds. Lower
   brackets and the 1-20 and 21-200 slices get a multiple of 1-200 (item level:
   a difference). Each cell
   also carries the counts behind it and the weekly kill share (from Raider.IO
   first kill dates, so guilds without logs count too), plus the bracket's
   median learning curve and wipe mix for the latest week. Late wipes and
   gained item level compare with 1-200 as a difference. Each bracket also
   gets a tier summary of hours and nights per week, from guilds whose logs
   cover at least 75% of the weeks their Raider.IO kills span. Stage names
   come from one `report.phases` lookup per boss.

## Second read: roster, deaths and comp

`enrich` (`guildpulls/enrich.py`) reads every stored report of the current
tier (`config.ENRICH_TIERS`) once more, best-ranked guild first, and stores
per pull: the players in it, its deaths, early deaths (first 60 s), the time
of the third death and deaths per killing ability, plus WCL's exact
`fightPercentage` for pulls stored before it was fetched. It then fetches
WCL rankings for each guild's first kill of each boss (every player's class,
spec and DPS, and the healers' HPS). Per boss that gives deaths, early deaths
and avoidable deaths per pull (the hand-picked list in
`config.AVOIDABLE_ABILITIES`), the share of wipes that collapsed within 90 s
of the third death, players used, raid DPS and HPS on the kill, and how close
the kill's spec mix is to 1-200's average (cosine similarity). Per tier:
regular players (3+ progression pulls), the share of pulls with 16 of the
guild's 20 most-used players, and new regulars per week. A guild counts in
these only once all its counted pulls on the boss have been read, so a half
read guild never reads low.

Deaths come from death events (about 10 points a report). The Deaths table
is cheaper but stops at 200 deaths a report. WCL takes 2-20 s to first open a
report's events, so 8 queries run at once (`ENRICH_WORKERS`). A report that
the daily run fetches again (it grew) is read again. About 48k reports of
the tier have boss pulls, so the first read is about 500k points (about 28
hours of budget, so a few days); after that only new reports are read. In
the workflow it runs after the daily refresh and before past tiers, stops at
09:00 UTC like the backfill, and prints `enrich_pending=` so the workflow can
chain chunks. `index.json` carries its progress per tier.

## Hosting: GitHub Actions and Pages

`.github/workflows/refresh.yml` runs every day at 10:00 UTC, and on demand from
Actions > Refresh data > Run workflow.

- **State.** The SQLite database is kept between runs, gzipped, as an asset
  on the `pipeline-state` release. Each run downloads it, runs the pipeline,
  and uploads it again (also when the run fails, so progress is kept).
- **Chunks.** A job may run for 6 hours and the first full load takes 6-14.
  Each job stops starting new guilds after 4.5 hours (`CHUNK_MINUTES`),
  saves the database, and if the run isn't finished starts the next chunk of
  the same run id itself, up to `MAX_CHUNKS` (5). Daily runs after the first
  load fit in one chunk.
- **Data.** Snapshots and `index.json` are committed to the `data` branch
  (bot commits stay off `main`).
- **Site.** The deploy job publishes `site/` with the `data` branch's
  snapshots under `site/data/`. Until the first load finishes, the page
  shows its progress instead of numbers.
- **Week filter.** A kill's numbers never change, so each snapshot carries
  every bracket and boss cell as it stood at the end of each tier week
  (`weekly`), computed from kill dates. The dashboard only reads `latest.json`.

### One-time setup

1. Make the repo public (Settings > General > Danger Zone > Change
   visibility). On the free plan Pages needs a public repo, and public repos
   have no Actions minutes cap.
2. Settings > Secrets and variables > Actions > New repository secret:
   `WCL_CLIENT_ID` and `WCL_CLIENT_SECRET`.
3. Settings > Pages > Build and deployment > Source: **GitHub Actions**.
4. Actions > Refresh data > Run workflow, to start the first load now instead
   of at the next 10:00 UTC.

The dashboard is then at `https://anom0ly.github.io/guildrankanalysis/`.

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

## Past tiers

Past tiers are loaded once, by the daily job, with the time it has left. After
the current tier's run is complete, `backfill` works through
`config.BACKFILL_TIERS` in order (VS / DR / MQD, Manaforge Omega, Liberation of
Undermine, Nerub-ar Palace) under the fixed run id `backfill`, so a tier
resumes across days until every guild is reached. It stops starting guilds at
09:00 UTC (`BACKFILL_STOP_HOUR`), and the workflow keeps starting chunks until
then but never between 09:00 and 10:00. That way the next scheduled run never
queues behind a backfill chunk, because GitHub keeps only one waiting run per
concurrency group. Each past tier costs roughly 200k-280k WCL points (11-16
hours of budget), so a tier takes about a day. `index.json` shows each past
tier's state (`queued`, `loading` with counts, `complete`), and the tier
picker shows it too.

WCL archives reports after about two years. Archived reports still return
their fight list (pulls, kill, timings, item level), which is all the v1
metrics need, but not event data.

## Adding a tier

Add a `Tier` to `guildpulls/config.py` with the Raider.IO raid slug, WCL zone
id, US start and end time, expansion name and the boss list mapped by Raider.IO
slug to WCL encounter id. The zone ids come from
`worldData.expansions { zones { id encounters } }`; the dates and boss slugs
from Raider.IO's `raiding/static-data`. For a past tier, add its key to
`BACKFILL_TIERS`. Raider.IO pull counts are unusable for Vault of the
Incarnates and older (every boss shows 1 pull); set `rio_pulls=False` on such
a tier so pulls to kill come from the logs only.

## Known limits

- Region views only fill as far as Raider.IO's region lists go; brackets with
  no guilds in a region are hidden on the dashboard.
- Guilds whose logs are private, or missing the kill, are counted in
  `kill_not_logged`. Their pulls to kill can come from Raider.IO, but they are
  left out of nights, combat time and item level. Each cell's `n` gives the
  sample per metric and `pulls_source` how many pull counts came from where.
- Raider.IO's counting method isn't documented; on the top 60 it matched WCL
  within 10% for about two thirds of kills where both had a number.
