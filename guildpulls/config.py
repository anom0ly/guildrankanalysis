"""Tier definitions and pipeline constants.

A tier ties a Raider.IO raid slug (for guild ranks) to a Warcraft Logs zone
(for pulls), with the boss list mapped between the two. Adding a past tier is
a new entry here plus a run with --tier.
"""
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class Boss:
    rio_slug: str
    wcl_encounter_id: int
    name: str


@dataclass(frozen=True)
class Tier:
    key: str
    name: str
    rio_raid: str
    wcl_zone_id: int
    starts: datetime  # first Mythic reset (US), start of tier week 1
    ends: datetime | None
    bosses: tuple[Boss, ...]

    def boss_by_encounter(self, encounter_id: int) -> Boss | None:
        for b in self.bosses:
            if b.wcl_encounter_id == encounter_id:
                return b
        return None


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


TIERS: dict[str, Tier] = {
    t.key: t
    for t in (
        Tier(
            key="venomous-abyss",
            name="The Venomous Abyss",
            rio_raid="the-venomous-abyss",
            wcl_zone_id=53,
            starts=_utc(2026, 8, 18, 15),
            ends=None,
            bosses=(
                Boss("nekzali-the-soulcoiler", 3470, "Nek'zali the Soulcoiler"),
                Boss("entombed-sentinels", 3445, "Entombed Sentinels"),
                Boss("the-lost-explorers", 3497, "The Lost Explorers"),
                Boss("vashnik-the-malignant", 3455, "Vashnik the Malignant"),
                Boss("sszorak", 3420, "Sszorak"),
                Boss("the-twin-fangs", 3421, "The Twin Fangs"),
                Boss("the-coiled-altar", 3429, "The Coiled Altar"),
                Boss("ulatek", 3492, "Ula'tek"),
            ),
        ),
        Tier(
            key="mn-tier-1",
            name="VS / DR / MQD",
            rio_raid="tier-mn-1",
            wcl_zone_id=46,
            starts=_utc(2026, 3, 17, 15),
            ends=_utc(2026, 8, 18, 15),
            bosses=(
                Boss("imperator-averzian", 3176, "Imperator Averzian"),
                Boss("vorasius", 3177, "Vorasius"),
                Boss("fallenking-salhadaar", 3179, "Fallen-King Salhadaar"),
                Boss("vaelgor-ezzorak", 3178, "Vaelgor & Ezzorak"),
                Boss("lightblinded-vanguard", 3180, "Lightblinded Vanguard"),
                Boss("crown-of-the-cosmos", 3181, "Crown of the Cosmos"),
                Boss("chimaerus-the-undreamt-god", 3306, "Chimaerus, the Undreamt God"),
                Boss("beloren-child-of-alar", 3182, "Belo'ren, Child of Al'ar"),
                Boss("midnight-falls", 3183, "Midnight Falls"),
            ),
        ),
    )
}
CURRENT_TIER = "venomous-abyss"

MAX_RANK = 5000
MYTHIC = 5

# Metric rules from the spec.
MIN_PULL_SECONDS = 10
DUPLICATE_WINDOW_MS = 5_000
NIGHT_GAP_HOURS = 6
MIN_BRACKET_SAMPLE = 10
LOW_PULL_FRACTION = 0.25
# Original spec rule: a kill on the first logged pull means progression wasn't
# logged. Off (decided 2026-10-23) because it drops genuine one-shots of easy
# bosses; the low-pull rule above catches missing logs on harder bosses.
EXCLUDE_FIRST_PULL_KILLS = False
# Raider.IO pull counts fill pulls to kill where the logs have no kill. When
# both exist and WCL is under this share of Raider.IO's count, the logs are
# treated as missing nights and Raider.IO's count is used instead.
RIO_UNDERCOUNT_FRACTION = 0.75

# (label, first rank, last rank). The first bracket is the baseline for multiples.
BRACKETS: tuple[tuple[str, int, int], ...] = (
    ("Top 100", 1, 100),
    ("101-500", 101, 500),
    ("501-1000", 501, 1000),
    ("1001-5000", 1001, 5000),
)
REGIONS = ("all", "us", "eu")

# WCL budget handling.
WCL_RESERVE_POINTS = 500  # pause when fewer points than this are left in the hour
WCL_REPORTS_PER_QUERY = 20  # reports whose fights are fetched in one aliased query
# Raider.IO firstDefeated can lag or lead the log slightly; widen the window.
KILL_WINDOW_PADDING_HOURS = 24
# A report that was still recent when fetched may have grown; refetch it.
LIVE_REPORT_HOURS = 12
# Retry a guild that wasn't on WCL after this many days.
UNMATCHED_RETRY_DAYS = 7
