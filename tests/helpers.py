from guildpulls.metrics import Pull

H = 3_600_000
S = 1_000
T0 = 1_787_100_000_000  # an evening in the tier


def pull(start_s: float, dur_s: float = 300, kill: bool = False, boss: int = 3470, ilvl: float | None = 700.0,
         code: str = "A", fid: int = 0, base: int = T0) -> Pull:
    start = base + int(start_s * S)
    return Pull(boss, start, start + int(dur_s * S), kill, ilvl, None, None, code, fid)
