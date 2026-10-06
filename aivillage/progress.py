"""Village progress: stages of the village and what each stage or building opens (the «С нуля» mode).

Off by default (config `progress.enabled`): then everything is open, as in every mode before it.
On, the village starts at `progress.start_stage` and climbs the stages in `progress.stages` by what
it has built; never by the calendar. Each stage lists what must stand in the village (`requires`).

What a stage or a building opens is a table of *unlock keys* (`progress.unlocks`, config wins over
`DEFAULT_UNLOCKS`). A key is "<kind>:<name>": `action:buy`, `recipe:bread`, `building:smithy`,
`law:tax`, `feature:trader`. Its rule is {"stage": id} and/or {"building": kind} (all must hold).
A key with no rule is open. Unlocks are sticky: once open, a key stays open even if the building
burns down, so a run never loses a mechanic it already had.

- Locked actions are refused by a registry guard, left out of `available_actions` and of the
  handbook (`locked_actions` in the observation, read by llm.LLMAgent).
- Other modules ask `unlocked(world, key)` before doing something automatic (the trader coming,
  elections, raids) and `built(world)` / `count(world, kind)` for what stands.
- What stands is counted from private plots (house levels, yard buildings), village works and any
  source a later module appends to `BUILT_SOURCES`. A leveled thing counts as `kind` (any level) and
  `kind@2`, `kind@3` for the levels reached. Starting at a later stage, the buildings its stages
  require count as standing (`prebuilt`), so a "village" start opens what a village has.

State: `world.progress` = {"stage": index, "reached": {stage id: day}, "unlocked": [keys], "prebuilt": {kind: n}}.
Log: a public "village_stage" event with `stage` (id) and `index` when the village reaches a stage.
Spec and the plan this belongs to: docs/specs/survival.md.
"""

from __future__ import annotations

from collections import Counter
from typing import Callable

from .ops import Ctx
from .registry import ACTIONS
from .state import Agent, World

# What a stage or building opens when progress is on. Config `progress.unlocks` adds to / overrides it
# (a key mapped to {} or None there is open from the start). Mechanics added later register their keys here.
DEFAULT_UNLOCKS: dict[str, dict] = {
    # the trader and the market board come with a market square
    "feature:trader": {"building": "market_square"},
    "action:buy": {"building": "market_square"},
    "action:sell": {"building": "market_square"},
    "action:post_sale": {"building": "market_square"},
    "action:buy_sale": {"building": "market_square"},
    "action:cancel_listing": {"building": "market_square"},
    "action:change_trade": {"building": "market_square"},
    # government, treasury, taxes and land sales come with a town hall
    "feature:elections": {"building": "town_hall"},
    "feature:taxes": {"building": "town_hall"},
    "action:run_for_mayor": {"building": "town_hall"},
    "action:vote": {"building": "town_hall"},
    "action:propose_law": {"building": "town_hall"},
    "action:vote_law": {"building": "town_hall"},
    "action:report_theft": {"building": "town_hall"},
    "action:embezzle": {"building": "town_hall"},
    "action:audit_treasury": {"building": "town_hall"},
    "action:treasury_order": {"building": "town_hall"},
    "action:propose_build": {"building": "town_hall"},
    "action:fund_project": {"building": "town_hall"},
    # village projects (works.py): contributing, working on them and the council's suggestions
    "action:contribute": {"building": "town_hall"},
    "action:build_work": {"building": "town_hall"},
    "feature:works": {"building": "town_hall"},
    "action:buy_land": {"building": "town_hall"},
    "action:sell_land": {"building": "town_hall"},
    # locks are smith's work; dice need a tavern
    "action:install_lock": {"building": "smithy"},
    "action:dice": {"building": "tavern"},
    # outside threats find the village once it is a town
    "feature:raids": {"stage": "town"},
}

# fn(world) -> Counter of built kinds; modules that add buildings append theirs.
BUILT_SOURCES: list[Callable[[World], Counter]] = []


# ---------- config and state ----------

def _p(cfg: dict) -> dict:
    return cfg.get("progress", {})


def enabled(cfg: dict) -> bool:
    return bool(_p(cfg).get("enabled"))


def stages(cfg: dict) -> list[dict]:
    return _p(cfg).get("stages", [])


def stage_ids(cfg: dict) -> list[str]:
    return [s["id"] for s in stages(cfg)]


def _state(world: World) -> dict:
    st = world.progress
    st.setdefault("stage", 0)
    st.setdefault("reached", {})
    st.setdefault("unlocked", [])
    return st


def stage_index(world: World) -> int:
    return _state(world)["stage"] if enabled(world.config) else len(stages(world.config)) - 1


def stage(world: World) -> str | None:
    ids = stage_ids(world.config)
    return ids[stage_index(world)] if ids else None


def rules(cfg: dict) -> dict[str, dict]:
    out = dict(DEFAULT_UNLOCKS)
    out.update(_p(cfg).get("unlocks") or {})
    return out


# ---------- what stands ----------

def built(world: World) -> Counter:
    """Everything standing in the village by kind; leveled kinds also as `kind@2`, `kind@3`."""
    c: Counter = Counter()

    def leveled(kind: str, lvl: int) -> None:
        if lvl >= 1:
            c[kind] += 1
        for k in range(2, lvl + 1):
            c[f"{kind}@{k}"] += 1

    for plot in world.plots.values():
        if plot.kind == "home":
            leveled("house", plot.house)
        for b in plot.buildings:
            leveled(b["kind"], int(b.get("level", 1)))
    for structure, lvl in world.works.levels.items():
        leveled(structure, lvl)
    for src in BUILT_SOURCES:
        c.update(src(world))
    for kind, n in world.progress.get("prebuilt", {}).items():  # a later start stage: its buildings stand
        c[kind] = max(c[kind], n)
    return c


def count(world: World, kind: str) -> int:
    return built(world)[kind]


def _needs(cfg: dict, index: int) -> dict[str, int]:
    return dict((stages(cfg)[index].get("requires") or {}).get("buildings", {}))


def next_needs(world: World) -> dict[str, str] | None:
    """For the next stage: kind -> "have/need" (None at the last stage or with progress off)."""
    cfg = world.config
    i = stage_index(world)
    if not enabled(cfg) or i + 1 >= len(stages(cfg)):
        return None
    have = built(world)
    return {k: f"{min(have[k], n)}/{n}" for k, n in _needs(cfg, i + 1).items()}


# ---------- unlocks ----------

def _holds(world: World, rule: dict | None, have: Counter | None = None) -> bool:
    if not rule:
        return True
    if "stage" in rule:
        ids = stage_ids(world.config)
        if rule["stage"] in ids and stage_index(world) < ids.index(rule["stage"]):
            return False
    if "building" in rule:
        have = built(world) if have is None else have
        if have[rule["building"]] < 1:
            return False
    return True


def unlocked(world: World, key: str) -> bool:
    """Is this mechanic open? Always True with progress off or for a key with no rule."""
    if not enabled(world.config):
        return True
    st = _state(world)
    if key in st["unlocked"]:
        return True
    return _holds(world, rules(world.config).get(key))


def locked_actions(world: World) -> list[str]:
    if not enabled(world.config):
        return []
    have = built(world)
    st = _state(world)
    out = []
    for key, rule in rules(world.config).items():
        if key.startswith("action:") and key not in st["unlocked"] and not _holds(world, rule, have):
            out.append(key.split(":", 1)[1])
    return sorted(out)


def _why(world: World, key: str) -> str:
    rule = rules(world.config).get(key) or {}
    parts = []
    if "building" in rule:
        parts.append(f"a {rule['building']} standing in the village")
    if "stage" in rule:
        parts.append(f"the village being a {rule['stage']}")
    return " and ".join(parts)


def _guard(ctx: Ctx, actor: Agent, name: str) -> str | None:
    key = f"action:{name}"
    if unlocked(ctx.world, key):
        return None
    return f"'{name}' is not possible in this village yet: it needs {_why(ctx.world, key)}"


ACTIONS.guards.append(_guard)


# ---------- start and hourly check ----------

def setup(world: World) -> None:
    """Called by new_world: the start stage (a name or an index) and what it already opens."""
    cfg = world.config
    if not enabled(cfg):
        return
    st = _state(world)
    start = _p(cfg).get("start_stage", 0)
    ids = stage_ids(cfg)
    idx = ids.index(start) if isinstance(start, str) else int(start)
    st["stage"] = max(0, min(idx, len(ids) - 1))
    pre: dict[str, int] = {}
    for i in range(st["stage"] + 1):
        st["reached"].setdefault(ids[i], world.day)
        for kind, n in _needs(cfg, i).items():
            pre[kind] = max(pre.get(kind, 0), n)
    st["prebuilt"] = pre
    _refresh(world)
    if not unlocked(world, "feature:works"):  # no town hall yet: the config's starting village projects wait
        world.projects = {pid: p for pid, p in world.projects.items() if p.proposer != "council"}


def _refresh(world: World) -> list[str]:
    """Record keys that hold now (sticky). Returns the newly opened ones."""
    st = _state(world)
    have = built(world)
    new = [k for k, r in sorted(rules(world.config).items()) if k not in st["unlocked"] and _holds(world, r, have)]
    st["unlocked"].extend(new)
    return new


def end_of_hour(ctx: Ctx) -> None:
    w, cfg = ctx.world, ctx.cfg
    if not enabled(cfg):
        return
    st = _state(w)
    ids = stage_ids(cfg)
    have = built(w)
    while st["stage"] + 1 < len(ids) and all(have[k] >= n for k, n in _needs(cfg, st["stage"] + 1).items()):
        st["stage"] += 1
        sid = ids[st["stage"]]
        st["reached"][sid] = w.day
        ctx.emit("village_stage", f"The village is now a {sid}.", visibility="public", stage=sid, index=st["stage"])
    _refresh(w)


def _need_text(kind: str, n: int) -> str:
    base, _, lvl = kind.partition("@")
    return f"{n} {base}" + (f" (level {lvl}+)" if lvl else "")


def facts(cfg: dict) -> str:
    """The rules line on stages: what each stage needs standing (from the config, the same all run)."""
    if not enabled(cfg) or len(stages(cfg)) < 2:
        return ""
    steps = [f"a {stages(cfg)[0]['id']} at first"]
    for i in range(1, len(stages(cfg))):
        needs = " and ".join(_need_text(k, n) for k, n in _needs(cfg, i).items())
        steps.append(f"a {stages(cfg)[i]['id']} once {needs} stand in it")
    return ("- Village stages: the village is " + ", ".join(steps) + ". Every building in the village counts, "
            "whoever owns it; a stage once reached stays. \"village_stage\" shows the stage and what the next one "
            "still needs. Some buildings and actions open only at a stage or once a building stands; the rules "
            "above and below say which.")


def observe(world: World, name: str) -> dict:
    if not enabled(world.config):
        return {}
    out = {"village_stage": {"stage": stage(world)}}
    nxt = next_needs(world)
    if nxt is not None:
        out["village_stage"]["next_stage"] = stage_ids(world.config)[stage_index(world) + 1]
        out["village_stage"]["next_stage_needs_standing"] = nxt
    out["locked_actions"] = locked_actions(world)
    return out
