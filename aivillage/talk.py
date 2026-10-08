"""Turn-taking talk: villagers at one place think one after another and hear what was said before them.

Config "talk" (missing in old logs and saves = everything off, the engine works as before):
- `turn_taking`: villagers asked in the same tick at the same place decide in a seeded order (its own rng
  stream, so no other draw shifts). Each later one sees `just_said`: the words said out loud and what the
  earlier ones set out to do there this tick. Their decisions then run in that order, so an answer comes
  right after the question. The order is logged in the tick record ("talk") and replay reads it back.
- `waves`: at most this many turns in a row at one place; a bigger crowd is split into this many waves
  (each wave thinks at the same time and hears every earlier wave), so a full camp does not wait for
  twenty model calls in a row.
- `interrupt_pause`: a busy villager spoken to by someone at the same place (a whisper, an offer, its name
  said out loud) is asked on the next tick; the rest of its hour is not lost but owed (`Agent.time_debt`)
  and served after the answer, so the time spent on the job stays the same.

The engine only reorders decisions it already has and moves `busy_until`; `just_said` is built in run.py
outside engine.observe and is not world state.
"""

from __future__ import annotations

import random

from . import ops
from .ops import Event
from .state import World

# Acts done in the open: everyone at the place sees them (their events go to the whole location).
SEEN = frozenset({
    "move", "work", "eat", "sleep", "craft", "plant", "collect", "pick_up", "hunt", "catch_animal",
    "give", "lend", "accept", "buy", "sell", "attack", "defend", "care", "dice", "hang_out", "teach", "learn",
    "extinguish", "pay_respects", "help_stranger", "build", "construct", "bring_materials",
    "buy_animal", "take_animal", "leave_animal", "lend_animal", "return_animal", "give_animal", "feed_animal",
})
# Acts only the person they are aimed at learns about.
TO_YOU = frozenset({"offer", "offer_job", "propose", "praise", "gossip"})
TARGET_KEYS = ("to", "person", "target", "teacher")
TEXT_MAX = 300


def _cfg(world: World) -> dict:
    return world.config.get("talk") or {}


def enabled(world: World) -> bool:
    return bool(_cfg(world).get("turn_taking"))


def groups(world: World, asked: list[str]) -> list[list[str]]:
    """The villagers asked this tick who share a place with another asked villager, each place's group in the
    order its members take turns. [] when turn-taking is off or everybody is alone."""
    if not enabled(world):
        return []
    by_place: dict[str, list[str]] = {}
    for n in asked:
        by_place.setdefault(world.agents[n].location, []).append(n)
    rng = random.Random(f"{world.config['seed']}:{world.tick}:order")
    out = []
    for place in sorted(by_place):
        g = sorted(by_place[place])
        if len(g) > 1:
            rng.shuffle(g)
            out.append(g)
    return out


def waves(world: World, group: list[str]) -> list[list[str]]:
    """Split a place's turn order into at most `talk.waves` consecutive waves (0 = one by one)."""
    k = int(_cfg(world).get("waves") or 0)
    if k <= 0 or len(group) <= k:
        return [[n] for n in group]
    size = -(-len(group) // k)
    return [group[i:i + size] for i in range(0, len(group), size)]


def _target(args: dict) -> str | None:
    for k in TARGET_KEYS:
        if isinstance(args.get(k), str):
            return args[k]
    return None


def just_said(name: str, earlier: list[tuple[str, dict]]) -> list[dict]:
    """What `name` saw of the earlier turns at its place this tick: who spoke and what they said out loud,
    a whisper only if it was to `name`, and what each set out to do in the open (or aimed at `name`).
    Secret acts (stealing, setting fires, taking from the treasury...) never show."""
    out = []
    for who, dec in earlier:
        if not isinstance(dec, dict):
            continue
        act = dec.get("action") if isinstance(dec.get("action"), dict) else {}
        args = act.get("args") if isinstance(act.get("args"), dict) else {}
        verb = str(act.get("name") or "wait")
        target = _target(args)
        line: dict = {"who": who}
        words = dec.get("say") or (args.get("text") if verb == "say" else None)
        if words:
            line["say"] = str(words)[:TEXT_MAX]
        if verb == "whisper":
            if target == name and args.get("text"):
                line["whispers_to_you"] = str(args["text"])[:TEXT_MAX]
        elif verb in SEEN or (verb in TO_YOU and target == name):
            line["does"] = verb
            if target:
                line["to"] = target
        if len(line) > 1:
            out.append(line)
    return out


def in_turn_order(order: list[str], talk: list[list[str]] | None) -> list[str]:
    """The engine's shuffled order with each talking group put into its own turn order. The group keeps the
    same seats in the order (only who sits where among them changes), so nobody else moves."""
    if not talk:
        return order
    out = list(order)
    for g in talk:
        members = [n for n in g if n in out]
        seats = sorted(out.index(n) for n in members)
        for i, n in zip(seats, members):
            out[i] = n
    return out


def pause_for(world: World, ev: Event, name: str, mode: str | None) -> None:
    """`interrupt_pause`: someone at the same place spoke to busy `name`. It answers on the next tick and owes
    the rest of what it was doing."""
    if not _cfg(world).get("interrupt_pause") or mode not in ("direct", "mention"):
        return
    a, by = world.agents.get(name), world.agents.get(ev.actor or "")
    if a is None or by is None or not ops.can_act(a) or a.location != by.location:
        return
    nxt = world.tick + 1
    if a.busy_until > nxt:
        a.time_debt += a.busy_until - nxt
        a.busy_until = nxt


def facts(cfg: dict) -> str | None:
    """The handbook line, only when turn-taking is on."""
    if not (cfg.get("talk") or {}).get("turn_taking"):
        return None
    return ("- \"just_said\": what people here said or set out to do a moment ago, earlier in this same turn, "
            "before you. Their actions happen right before yours.")
