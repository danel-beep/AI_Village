"""What was said to a villager: letters, whispers and words said out loud with its name in them.

A message is seen in the news only once, at the next turn. Here the last few stay in the observation
("said_to_you") until the end of the next day (`said_to_you.keep_days`), or until the two villagers have since
given, lent or traded to each other, whichever comes first. The engine cannot tell a request from small talk,
so every message addressed to the villager is kept the same way. Off when `said_to_you` is missing from the
config (old saves and logs) or `keep_days` is 0.
"""

from __future__ import annotations

import re

from . import ops
from .ops import Ctx, Event
from .state import World

_SETTLE = ("give", "lend", "trade")  # the two have since exchanged something: their messages are answered


def _cfg(world: World) -> dict:
    return world.config.get("said_to_you") or {}


def enabled(world: World) -> bool:
    return bool(_cfg(world).get("keep_days"))


def _keep(world: World, name: str, sender: str, how: str, text: str) -> None:
    box = world.addressed.setdefault(name, [])
    box.append({"from": sender, "how": how, "day": world.day, "time": f"{world.hour:02d}:{world.minute:02d}",
                "text": text})
    keep_days = _cfg(world)["keep_days"]
    box[:] = [m for m in box if m["day"] + keep_days >= world.day][-int(_cfg(world).get("max", 5)):]


def _settle(world: World, name: str, other: str) -> None:
    box = world.addressed.get(name)
    if box:
        box[:] = [m for m in box if m["from"] != other]
        if not box:
            del world.addressed[name]


def _on_event(ctx: Ctx, ev: Event, recipients: list[str]) -> None:
    w = ctx.world
    if not enabled(w) or not ev.actor or ev.actor not in w.agents:
        return
    if ev.kind in ("letter", "whisper"):
        text = str(ev.data.get("text_raw", ev.text))
        for n in ev.to:
            if n != ev.actor and n in w.agents:
                _keep(w, n, ev.actor, ev.kind, text)
    elif ev.kind == "say":
        text = str(ev.data.get("text_raw", ev.text))
        for n in recipients:
            if n != ev.actor and n in w.agents and re.search(rf"\b{re.escape(n)}\b", text, re.IGNORECASE):
                _keep(w, n, ev.actor, "said", text)
    elif ev.kind in _SETTLE:
        other = ev.data.get("partner") if ev.kind == "trade" else (ev.to or [None])[0]
        if other in w.agents:
            _settle(w, ev.actor, other)
            _settle(w, other, ev.actor)


ops.EVENT_HOOKS.append(_on_event)


def observe(world: World, name: str) -> dict:
    """{"said_to_you": [...]} oldest first, or {} when there is nothing (the state is not changed here)."""
    if not enabled(world):
        return {}
    keep_days = _cfg(world)["keep_days"]
    box = [{k: m[k] for k in ("from", "how", "text")} | {"when": f"day {m['day']} {m['time']}"}
           for m in world.addressed.get(name, []) if m["day"] + keep_days >= world.day]
    return {"said_to_you": box} if box else {}


def facts(cfg: dict) -> str | None:
    c = cfg.get("said_to_you") or {}
    days = c.get("keep_days")
    if not days:
        return None
    until = "the next day" if days == 1 else f"day N+{days}, for words said on day N"
    return ("- \"said_to_you\": letters, whispers and words said out loud with your name in them, kept until the end "
            f"of {until} or until you and the sender have given, lent or traded to each other (the last "
            f"{c.get('max', 5)}).")
