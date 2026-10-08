"""World overrides for tests now that «С нуля» is the only way to play (aivillage/modes.py)."""
from aivillage import modes
from aivillage.config import _merge


def override(kind: str = "plain", world: dict | None = None) -> dict:
    """"plain": the engine's own config with the runs' rules (modes.RUN_DEFAULTS); "trades": the ready village with
    professions, places and taxes (modes.TRADES); a preset name: «С нуля» with that preset. `world` on top."""
    if kind == "plain":
        return _merge(modes.RUN_DEFAULTS, world or {})
    if kind == "trades":
        return modes.trades_override(world)
    return modes.world_override(kind, world)
