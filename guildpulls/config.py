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
    expansion: str = ""
    # Raider.IO pull counts fill gaps in the logs. They are unusable for some
    # older raids (every boss shows 1 pull); set False there to count pulls
    # from WCL only.
    rio_pulls: bool = True

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
            expansion="Midnight",
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
            expansion="Midnight",
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
        Tier(
            key="manaforge-omega",
            name="Manaforge Omega",
            rio_raid="manaforge-omega",
            wcl_zone_id=44,
            starts=_utc(2025, 8, 12, 15),
            ends=_utc(2026, 3, 2, 22),
            expansion="The War Within",
            bosses=(
                Boss("plexus-sentinel", 3129, "Plexus Sentinel"),
                Boss("loomithar", 3131, "Loom'ithar"),
                Boss("soulbinder-naazindhri", 3130, "Soulbinder Naazindhri"),
                Boss("forgeweaver-araz", 3132, "Forgeweaver Araz"),
                Boss("the-soul-hunters", 3122, "The Soul Hunters"),
                Boss("fractillus", 3133, "Fractillus"),
                Boss("nexus-king-salhadaar", 3134, "Nexus-King Salhadaar"),
                Boss("dimensius", 3135, "Dimensius, the All-Devouring"),
            ),
        ),
        Tier(
            key="liberation-of-undermine",
            name="Liberation of Undermine",
            rio_raid="liberation-of-undermine",
            wcl_zone_id=42,
            starts=_utc(2025, 3, 4, 15),
            ends=_utc(2025, 8, 12, 15),
            expansion="The War Within",
            bosses=(
                Boss("vexie-and-the-geargrinders", 3009, "Vexie and the Geargrinders"),
                Boss("cauldron-of-carnage", 3010, "Cauldron of Carnage"),
                Boss("rik-reverb", 3011, "Rik Reverb"),
                Boss("stix-bunkjunker", 3012, "Stix Bunkjunker"),
                Boss("sprocketmonger-lockenstock", 3013, "Sprocketmonger Lockenstock"),
                Boss("onearmed-bandit", 3014, "One-Armed Bandit"),
                Boss("mugzee-heads-of-security", 3015, "Mug'Zee, Heads of Security"),
                Boss("chrome-king-gallywix", 3016, "Chrome King Gallywix"),
            ),
        ),
        Tier(
            key="nerubar-palace",
            name="Nerub-ar Palace",
            rio_raid="nerubar-palace",
            wcl_zone_id=38,
            starts=_utc(2024, 9, 10, 15),
            ends=_utc(2025, 3, 4, 15),
            expansion="The War Within",
            bosses=(
                Boss("ulgrax-the-devourer", 2902, "Ulgrax the Devourer"),
                Boss("the-bloodbound-horror", 2917, "The Bloodbound Horror"),
                Boss("sikran", 2898, "Sikran"),
                Boss("rashanan", 2918, "Rasha'nan"),
                Boss("broodtwister-ovinax", 2919, "Broodtwister Ovi'nax"),
                Boss("nexus-princess-kyveza", 2920, "Nexus-Princess Ky'veza"),
                Boss("the-silken-court", 2921, "The Silken Court"),
                Boss("queen-ansurek", 2922, "Queen Ansurek"),
            ),
        ),
    )
}
CURRENT_TIER = "venomous-abyss"
# Past tiers the daily job loads once, in this order, with its spare time.
BACKFILL_TIERS = ("mn-tier-1", "manaforge-omega", "liberation-of-undermine", "nerubar-palace")
# The backfill stops starting guilds at this UTC hour and doesn't start another
# chunk after it, so it never blocks the next daily run at 10:00.
BACKFILL_STOP_HOUR = 9
# Fixed run id, so a backfill resumes across days until the tier is complete.
BACKFILL_RUN_ID = "backfill"

MAX_RANK = 5000  # world top 5000, plus each region's top 5000
MYTHIC = 5

# Metric rules from the spec.
MIN_PULL_SECONDS = 10
DUPLICATE_WINDOW_MS = 5_000
NIGHT_GAP_HOURS = 6
MIN_BRACKET_SAMPLE = 10
LOW_PULL_FRACTION = 0.25
# Against peers view: guilds ranked this many places either side (world rank
# under All, region rank under US or EU). Fixed at 100 (decided 2026-10-23).
PEER_WINDOW = 100
# Original spec rule: a kill on the first logged pull means progression wasn't
# logged. Off (decided 2026-10-23) because it drops genuine one-shots of easy
# bosses; the low-pull rule above catches missing logs on harder bosses.
EXCLUDE_FIRST_PULL_KILLS = False
# Raider.IO pull counts fill pulls to kill where the logs have no kill. When
# both exist and WCL is under this share of Raider.IO's count, the logs are
# treated as missing nights and Raider.IO's count is used instead.
RIO_UNDERCOUNT_FRACTION = 0.75

# Learning curve and wipe depth.
SUB10_HEALTH = 10  # "close to a kill": a pull that ended under this boss health %
PLATEAU_STEP = 1.0  # a pull ends a plateau when it beats the best health by this many points
LOW_WIPE_HEALTH = 30  # late wipe on bosses whose phases don't show progress
# Raid schedule: a guild needs logged nights in this share of the weeks its
# Raider.IO kills span, or hours per week would read low.
SCHEDULE_MIN_WEEK_COVERAGE = 0.75

# (label, first rank, last rank). The first bracket (Hall of Fame) is the
# baseline for multiples. Ranks are world rank under All and region rank under
# US or EU.
BRACKETS: tuple[tuple[str, int, int], ...] = (
    ("1-200", 1, 200),
    ("201-400", 201, 400),
    ("401-600", 401, 600),
    ("601-1000", 601, 1000),
    ("1001-1200", 1001, 1200),
    ("1201-1500", 1201, 1500),
    ("1501-2000", 1501, 2000),
    ("2001-3000", 2001, 3000),
    ("3001-5000", 3001, 5000),
)
# Slices of the baseline bracket, shown under it and compared with it.
SLICES: tuple[tuple[str, int, int], ...] = (
    ("1-20", 1, 20),
    ("21-200", 21, 200),
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
