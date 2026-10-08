"""Game time. One tick is `tick_minutes` game minutes (15 in real runs, 60 = the old hourly mode).

Ticks only cover the waking day (day_start_hour..day_end_hour); the night is not ticked, it runs
inside the last tick of the day. So tick -> (day, hour, minute) is plain arithmetic.
"""

from __future__ import annotations

ALLOWED = (15, 20, 30, 60)
RUN_DEFAULT = 15  # what the CLI and the live server use; engine tests keep config's 60


def tick_minutes(cfg: dict) -> int:
    return int(cfg.get("tick_minutes", 60))


def per_hour(cfg: dict) -> int:
    return 60 // tick_minutes(cfg)


def per_day(cfg: dict) -> int:
    return (cfg["day_end_hour"] - cfg["day_start_hour"]) * per_hour(cfg)


def hours(cfg: dict, n: int) -> int:
    """n game hours in ticks."""
    return n * per_hour(cfg)


def time_of(cfg: dict, tick: int) -> tuple[int, int, int]:
    """(day, hour, minute) at the start of `tick`."""
    day, rest = divmod(tick, per_day(cfg))
    h, q = divmod(rest, per_hour(cfg))
    return day + 1, cfg["day_start_hour"] + h, q * tick_minutes(cfg)


def tick_of(cfg: dict, day: int, hour: int, minute: int = 0) -> int:
    return (day - 1) * per_day(cfg) + (hour - cfg["day_start_hour"]) * per_hour(cfg) + minute // tick_minutes(cfg)


def label(cfg: dict, tick: int) -> str:
    d, h, m = time_of(cfg, tick)
    return f"day {d} {h:02d}:{m:02d}"


def action_ticks(cfg: dict, name: str) -> int:
    """How many ticks an action keeps the agent busy (`action_minutes` in config, default one hour)."""
    mins = (cfg.get("action_minutes") or {}).get(name, 60)
    return max(1, -(-int(mins) // tick_minutes(cfg)))


def quick_actions(cfg: dict) -> list[str]:
    """Actions shorter than an hour (for the prompt)."""
    return sorted(n for n, m in (cfg.get("action_minutes") or {}).items() if m < 60)
