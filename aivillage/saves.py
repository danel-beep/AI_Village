"""Save a running village and continue it later from the same moment.

A save is a sidecar next to the run's log, `<log>.save.json`, taken between two ticks (the run loop's
`checkpoint`): the whole world (`World.to_dict`, hash-checked on load), every villager's brain (LLM memory:
notes, last actions, people, diaries, today's turns, token use; bots: their own fields and RNG state), god
events still waiting for their tick, the run options and how long the log was at that moment.

Loading cuts the log back to that length (ticks played after the save are dropped, they will be played again)
and the run goes on appending to the same log, so the log stays one replayable story from tick 0 and a
saved-and-continued run ends with exactly the hash of an uninterrupted one (tests/test_saves.py).
The engine never reads a save; `run.replay()` checks the whole log as before.
"""

from __future__ import annotations

import json
import os
import random
import time
from dataclasses import asdict
from pathlib import Path

from .bots import BOT_TYPES
from .state import World

SAVE_VERSION = 1


def path_for(log: str | Path) -> Path:
    p = Path(log)
    return p.with_name(p.stem + ".save.json")


# --- villagers' brains ---

def _plain(v):
    """JSON-safe copy: random.Random -> its state, sets (BuilderBot's places, nested in dicts too) -> sorted lists."""
    if isinstance(v, random.Random):
        return {"__rng__": list(v.getstate())}
    if isinstance(v, (set, frozenset)):
        return {"__set__": sorted(v, key=str)}
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    return v


def _unplain(v):
    if isinstance(v, dict):
        if "__rng__" in v:
            version, internal, gauss = v["__rng__"]
            rng = random.Random()
            rng.setstate((version, tuple(internal), gauss))
            return rng
        if "__set__" in v:
            return set(v["__set__"])
        return {k: _unplain(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_unplain(x) for x in v]
    return v


def _bot_state(bot) -> dict:
    """A bot's own fields; random.Random objects become their state so decisions continue identically."""
    return {k: _plain(v) for k, v in vars(bot).items()}


def _set_bot_state(bot, state: dict) -> None:
    for k, v in state.items():
        setattr(bot, k, _unplain(v))


def _agent_state(ag) -> dict:
    out = {"model": getattr(ag.client, "model", "stub"), "notes": ag.notes, "usage": asdict(ag.usage),
           "recent": list(ag.recent), "people": dict(ag.people), "diary": list(ag.diary),
           "day_log": list(ag.day_log), "turns": list(ag.turns), "shown": dict(ag.shown),
           "villagers": sorted(ag.villagers),
           "goals": {"about_me": ag.about_me, "wants": ag.wants, "plan": ag.plan, "introduced": ag.introduced},
           "kept": list(ag.kept), "record": ag.record, "record_day": ag.record_day}
    if hasattr(ag.client, "bot"):  # StubClient answers with a bot: keep its state too
        out["stub_bot"] = _bot_state(ag.client.bot)
    return out


def brains(decide) -> dict:
    kinds = {cls: k for k, cls in BOT_TYPES.items()}
    return {"agents": {n: _agent_state(ag) for n, ag in (getattr(decide, "agents", None) or {}).items()},
            "bots": {n: {"kind": kinds.get(type(b), type(b).__name__), "state": _bot_state(b)}
                     for n, b in (getattr(decide, "bots", None) or {}).items()}}


def decider(world: World, snap: dict):
    """Rebuild `decide` (with `.agents` / `.bots`, like run.main builds it) and `on_night` from a save."""
    from .llm import Usage
    from .run import llm_agents, night_reflection
    saved = snap["brains"]
    agents = llm_agents(world, {n: a["model"] for n, a in saved["agents"].items()})
    for name, ag in agents.items():
        a = saved["agents"][name]
        ag.notes, ag.recent, ag.people = a["notes"], list(a["recent"]), dict(a["people"])
        ag.diary, ag.day_log, ag.villagers = list(a["diary"]), list(a["day_log"]), set(a["villagers"])
        ag.turns = list(a.get("turns") or [])  # saves before the day conversation: start a fresh one
        ag.shown = dict(a.get("shown") or {})  # what those turns showed of the world ("llm_obs: changes")
        ag.usage = Usage(**a["usage"])
        g = a.get("goals") or {}  # saves made before own goals: no intro mid-game, the first night asks instead
        ag.about_me, ag.wants, ag.plan = g.get("about_me", ""), g.get("wants", ""), g.get("plan", "")
        ag.introduced = bool(g.get("introduced", True))
        # book of deeds (reputation.record): saves before it have none
        ag.kept, ag.record, ag.record_day = list(a.get("kept") or []), a.get("record"), a.get("record_day")
        if "stub_bot" in a and hasattr(ag.client, "bot"):
            _set_bot_state(ag.client.bot, a["stub_bot"])
    bots = {}
    for name, b in saved["bots"].items():
        bots[name] = BOT_TYPES[b["kind"]](name)
        _set_bot_state(bots[name], b["state"])

    def decide(name: str, obs: dict) -> dict:
        return agents[name].decide(obs) if name in agents else bots[name].decide(obs)
    decide.agents, decide.bots = agents, bots
    on_night = (lambda w, day: night_reflection(w, agents, day)) if agents else None
    return decide, on_night


# --- save files ---

def snapshot(world: World, decide, *, log_path: str | Path | None, end_day: int, run: dict | None = None,
             god_pending: list | None = None) -> dict:
    """Everything needed to continue. Take it only between ticks (run's `checkpoint`) or after the run ended."""
    log_bytes = Path(log_path).stat().st_size if log_path and Path(log_path).is_file() else 0
    return {"type": "save", "version": SAVE_VERSION, "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "tick": world.tick, "day": world.day, "hour": world.hour, "minute": world.minute,
            "end_day": end_day, "log_bytes": log_bytes, "hash": world.hash(), "world": world.to_dict(),
            "brains": brains(decide), "god_pending": god_pending or [], "run": run or {}}


def write(log_path: str | Path, snap: dict) -> Path:
    """Atomic: a crash mid-write leaves the previous save intact."""
    out = path_for(log_path)
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, out)
    return out


def read(path: str | Path) -> dict:
    snap = json.loads(Path(path).read_text(encoding="utf-8"))
    if snap.get("type") != "save" or snap.get("version") != SAVE_VERSION:
        raise ValueError(f"{Path(path).name}: not a village save this version can read")
    return snap


def world_of(snap: dict) -> World:
    world = World.from_dict(snap["world"])
    if world.hash() != snap["hash"]:
        raise ValueError("the save does not match its own hash (file damaged or the engine changed)")
    return world


def check_log(log_path: str | Path, snap: dict) -> list[dict]:
    """The log's records up to the save (header first), read without changing the file; raises if it does not fit."""
    p, n = Path(log_path), snap["log_bytes"]
    if not p.is_file() or p.stat().st_size < n:
        raise ValueError(f"the log {p.name} is missing or shorter than when the village was saved")
    with open(p, "rb") as f:
        head = f.read(n)
    if not head.endswith(b"\n"):
        raise ValueError(f"the save does not end on a record of the log {p.name}")
    try:
        from .logio import parse
        recs = list(parse(head.decode("utf-8").splitlines()))
    except ValueError as e:
        raise ValueError(f"the log {p.name} is damaged before the save: {e}") from None
    if not recs or recs[0].get("type") != "header":
        raise ValueError(f"the log {p.name} has no header")
    return recs


def cut_log(log_path: str | Path, snap: dict) -> Path | None:
    """Cut the log back to the save. What was written after it is kept in `<log>.after-save-<time>` (returned),
    written in full before the log is touched: continuing an older save never loses those hours."""
    p, n = Path(log_path), snap["log_bytes"]
    if p.stat().st_size <= n:
        return None
    keep = p.with_name(f"{p.name}.after-save-{time.strftime('%Y%m%d-%H%M%S')}")
    tmp = keep.with_name(keep.name + ".tmp")
    with open(p, "rb") as src, open(tmp, "wb") as dst:
        src.seek(n)
        while chunk := src.read(1 << 20):
            dst.write(chunk)
        dst.flush()
        os.fsync(dst.fileno())
    os.replace(tmp, keep)
    with open(p, "r+b") as f:
        f.truncate(n)
    return keep


def rewind_log(log_path: str | Path, snap: dict) -> list[dict]:
    """Check the log, then cut it back to the moment of the save; returns its records (header first)."""
    recs = check_log(log_path, snap)
    cut_log(log_path, snap)
    return recs


def listing(runs_dir: str | Path) -> list[dict]:
    """Saved villages in a runs folder, newest first (for the start screen)."""
    out = []
    d = Path(runs_dir)
    for p in d.glob("*.save.json") if d.is_dir() else []:
        try:
            with open(p, encoding="utf-8") as f:
                snap = json.load(f)
        except (OSError, ValueError):
            continue
        if snap.get("type") != "save" or snap.get("version") != SAVE_VERSION:
            continue
        b = snap.get("brains", {})
        out.append({"name": p.name[: -len(".save.json")], "saved_at": snap.get("saved_at"),
                    "day": snap["day"], "hour": snap["hour"], "minute": snap.get("minute", 0),
                    "end_day": snap["end_day"], "finished": snap["day"] >= snap["end_day"],
                    "days": (snap.get("run") or {}).get("days"),
                    "villagers": len(snap["world"]["agents"]),
                    "alive": sum(a.get("status") != "dead" for a in snap["world"]["agents"].values()),
                    "llm": bool(b.get("agents")),
                    "needs_key": any(a.get("model") not in ("stub", "mcp") for a in (b.get("agents") or {}).values()),
                    "mode": snap["world"]["config"].get("preset") or snap["world"]["config"].get("economy_mode"),
                    "mtime": p.stat().st_mtime})
    return sorted(out, key=lambda s: -s["mtime"])
