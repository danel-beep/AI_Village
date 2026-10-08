"""The honor board: a public board of praise and titles (config block `honors`; on in modes.TRADES and «С нуля»).

The world sets no criteria of merit. Two ways to stand out, both written by the villagers themselves:

- `praise(person, text)`: a villager pins a short note about another villager on the public board (at most
  `per_day` notes a day, never about oneself). Everyone sees the note; the board keeps the last `keep` notes.
- a title law: the village (governance.py, mayor's law `title`) or a polity (polity.py, law `title` for a member)
  gives someone a title in its own words. A person keeps the last `max_titles` titles.

Nothing else follows from a note or a title: no coins, no reputation, no feelings. Rewards in coins are the
existing `grant` laws; whatever else a note or a title means is up to the villagers.

State: `World.honors` = {"notes": [{day, by, about, text}], "titles": {name: [{title, by, day}]},
"posted": {name: [day, n]}}. Log: public `praise`, `title_given`.
"""

from __future__ import annotations

from pydantic import BaseModel

from .actions import _agent, _text
from .ops import Ctx
from .registry import ACTIONS, ActionError
from .state import Agent, World


def enabled(cfg: dict) -> bool:
    return bool(cfg.get("honors", {}).get("enabled"))


def _c(cfg: dict) -> dict:
    return cfg["honors"]


def _board(world: World) -> dict:
    h = world.honors
    if not h:
        h.update({"notes": [], "titles": {}, "posted": {}})
    return h


def _posted_today(world: World, name: str) -> int:
    day, n = world.honors.get("posted", {}).get(name, [0, 0])
    return n if day == world.day else 0


class PraiseArgs(BaseModel):
    person: str
    text: str


@ACTIONS.action("praise", "Pin a short public note about another villager on the honor board (works from "
                "anywhere). Everyone sees it.", PraiseArgs,
                available=lambda c, a: enabled(c.cfg) and _posted_today(c.world, a.name) < _c(c.cfg)["per_day"])
def praise(ctx: Ctx, a: Agent, args: PraiseArgs) -> None:
    if not enabled(ctx.cfg):
        raise ActionError("this village has no honor board")
    w, c = ctx.world, _c(ctx.cfg)
    if _posted_today(w, a.name) >= c["per_day"]:
        raise ActionError(f"at most {c['per_day']} note(s) a day on the honor board")
    about = _agent(ctx, args.person)
    if about.name == a.name:
        raise ActionError("a note on the honor board is about someone else")
    if about.status == "dead":
        raise ActionError(f"{about.name} is dead")
    text = _text(ctx, args.text)[: c["note_len"]]
    b = _board(w)
    b["notes"].append({"day": w.day, "by": a.name, "about": about.name, "text": text})
    del b["notes"][: -c["keep"]]
    b["posted"][a.name] = [w.day, _posted_today(w, a.name) + 1]
    ctx.emit("praise", f"{a.name} pinned a note about {about.name} on the honor board: \"{text}\"", actor=a.name,
             visibility="public", person=about.name, note=text)


# ---------- titles (laws) ----------

def check_title(ctx: Ctx, text: str | None) -> str:
    """For propose_law / polity_propose: the title's words, or an error the villager can act on."""
    if not enabled(ctx.cfg):
        raise ActionError("this village has no honor board")
    if not text or not text.strip():
        raise ActionError("title needs text (the title's words)")
    return _text(ctx, text)[: _c(ctx.cfg)["title_len"]]


def give_title(ctx: Ctx, person: str, title: str, by: str) -> str:
    """A title law passed: `person` holds `title`, given by `by` (the village or a polity). Returns a text."""
    w = ctx.world
    a = w.agents.get(person)
    if a is None or a.status == "dead":
        return f" {person} is not alive; nothing happens."
    held = _board(w)["titles"].setdefault(person, [])
    held.append({"title": title, "by": by, "day": w.day})
    del held[: -_c(ctx.cfg)["max_titles"]]
    ctx.emit("title_given", f"{person} holds the title \"{title}\" from {by}, on the honor board.",
             visibility="public", person=person, honor=title, by=by)
    return ""


# ---------- what villagers and viewers see ----------

def observe(world: World, name: str) -> dict:
    cfg = world.config
    if not enabled(cfg):
        return {}
    h = world.honors
    return {"honor_board": {
        "notes": list(h.get("notes", []))[-_c(cfg)["show"]:],
        "titles": {n: [f"{t['title']} (from {t['by']}, day {t['day']})" for t in ts]
                   for n, ts in sorted(h.get("titles", {}).items()) if ts},
        "your_notes_left_today": max(0, _c(cfg)["per_day"] - _posted_today(world, name)),
    }}


def view(world: World) -> dict:
    """For viewer/honors.js: the whole board (notes kept and titles), empty when nothing was pinned."""
    h = world.honors
    if not (h.get("notes") or h.get("titles")):
        return {}
    return {"honors": {"notes": list(h["notes"]), "titles": {n: list(ts) for n, ts in h["titles"].items() if ts}}}


def facts(cfg: dict) -> str:
    if not enabled(cfg):
        return ""
    c = _c(cfg)
    return (f"- The honor board is public: anyone can praise another villager there (a note of up to {c['note_len']} "
            f"characters, at most {c['per_day']} a day, from anywhere); \"honor_board\" shows the last {c['show']} "
            "notes and everyone's titles. A title is given by a law (title, with the title's words as text) of the "
            "village or of a polity; nothing else comes with a note or a title.")

