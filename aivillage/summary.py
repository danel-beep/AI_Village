"""Short LLM recaps of what happened in the village, for spectators ("что произошло за последнее время").

    python -m aivillage.summary runs/x.jsonl                 # one recap per game day -> runs/x.summary.json
    python -m aivillage.summary runs/x.jsonl --md recap.md   # also a Russian markdown report
    python -m aivillage.summary runs/x.jsonl --model stub    # offline, no key

Reads only log records (never the engine), like translate.py and metrics.py. The live server
uses `Summarizer` for its "Что произошло?" panel and writes the same sidecar file.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

from .llm import DEFAULT_MODEL, Client, StubClient, parse_json_object

MAX_LINES = 220  # digest lines sent to the model; one game day of 5 agents is ~100-150
MAX_CHARS = 160

PROMPT = """You are the narrator of a village life simulation where every villager is an AI.
Input: a chronological digest of one stretch of time ("D2 09:00" = day 2, 9 o'clock):
villagers' private thoughts (thought), what they did (did), what they said aloud (say) and events.
Write a recap for a human spectator in Russian: 3-6 short sentences, the most interesting things first
(conflicts, deals, theft, lies, help, fires, hunger, who is doing well or badly). Use concrete names.
Thoughts are private: say when someone plans one thing and says another. No intro, no lists.
Answer ONLY a JSON object: {"summary": "..."}"""


def _clip(s: str, n: int = MAX_CHARS) -> str:
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[: n - 1] + "…"


def when(rec: dict, cfg: dict | None = None) -> tuple[int, int]:
    """Game day and hour when the tick was played (its `view` is the time after it)."""
    from .config import DEFAULT_CONFIG
    cfg = cfg or DEFAULT_CONFIG
    start, hours = cfg["day_start_hour"], cfg["day_end_hour"] - cfg["day_start_hour"]
    return rec["tick"] // hours + 1, start + rec["tick"] % hours


def ticks_of(records: Iterable[dict]) -> list[dict]:
    return [r for r in records if r.get("type") == "tick"]


def digest(ticks: list[dict], max_lines: int = MAX_LINES, cfg: dict | None = None) -> str:
    """Compact text of decisions and events. Skips idle `wait`s and repeated thoughts; when too long,
    keeps events plus an even sample of the rest so the whole stretch stays covered."""
    lines: list[tuple[bool, str]] = []  # (is_event, text)
    last_thought: dict[str, str] = {}
    for rec in ticks:
        for e in rec.get("events") or []:
            if e.get("kind") in ("error",) or not e.get("text"):
                continue
            lines.append((True, f"D{e.get('day')} {e.get('hour', 0):02d}:00 event: {_clip(e['text'])}"))
        day, hour = when(rec, cfg)
        for name, d in sorted((rec.get("decisions") or {}).items()):
            if not isinstance(d, dict):
                continue
            act = d.get("action") or {}
            parts = []
            th = (d.get("thought") or "").strip()
            if th and last_thought.get(name) != th:
                parts.append(f"thought: {_clip(th)}")
                last_thought[name] = th
            if act.get("name") and act.get("name") != "wait":
                args = ", ".join(f"{k}={v}" for k, v in (act.get("args") or {}).items())
                parts.append(f"did: {act['name']}({_clip(args, 60)})")
            if (d.get("say") or "").strip():
                parts.append(f"say: {_clip(d['say'])}")
            if parts:
                lines.append((False, f"D{day} {hour:02d}:00 {name} " + " | ".join(parts)))
    if len(lines) > max_lines:
        events = [i for i, (ev, _) in enumerate(lines) if ev]
        rest = [i for i, (ev, _) in enumerate(lines) if not ev]
        keep = set(events[: max_lines // 2])
        room = max_lines - len(keep)
        if rest and room > 0:
            step = len(rest) / room
            keep.update(rest[int(k * step)] for k in range(min(room, len(rest))))
        lines = [ln for i, ln in enumerate(lines) if i in keep]
    return "\n".join(t for _, t in lines)


class Summarizer:
    def __init__(self, client: Client, cfg: dict | None = None):
        self.client, self.cfg = client, cfg
        self.cost_usd = 0.0

    def summarize(self, ticks: list[dict]) -> dict | None:
        """One recap of these tick records, or None if nothing happened in them."""
        text = digest(ticks, cfg=self.cfg)
        if not ticks or not text:
            return None
        msgs = [{"role": "system", "content": PROMPT}, {"role": "user", "content": text}]
        reply, usage = self.client.complete(msgs)
        obj = parse_json_object(reply, "summary")
        out = (obj or {}).get("summary") if obj else None
        if not isinstance(out, str) or not out.strip():
            out = reply.strip()
        self.cost_usd += float(usage.get("cost") or 0)
        (d0, h0), (d1, h1) = when(ticks[0], self.cfg), when(ticks[-1], self.cfg)
        return {"from_tick": ticks[0]["tick"], "to_tick": ticks[-1]["tick"],
                "from": f"день {d0}, {h0:02d}:00", "to": f"день {d1}, {h1:02d}:00",
                "text": out.strip(), "cost_usd": float(usage.get("cost") or 0)}


class StubSummaryClient(StubClient):
    """Offline stand-in: counts lines instead of asking a model."""

    model = "stub"

    def __init__(self) -> None:
        super().__init__("narrator")

    def complete(self, messages: list[dict]) -> tuple[str, dict]:
        n = messages[-1]["content"].count("\n") + 1
        return json.dumps({"summary": f"(заглушка) За это время записано {n} строк событий."}), {}


def make_client(model: str) -> Client:
    if model == "stub":
        return StubSummaryClient()
    from .llm import OpenRouterClient
    return OpenRouterClient(DEFAULT_MODEL if model == "default" else model, max_tokens=600, temperature=0.5)


def by_day(ticks: list[dict], cfg: dict | None = None) -> list[list[dict]]:
    groups: dict[int, list[dict]] = {}
    for t in ticks:
        groups.setdefault(when(t, cfg)[0], []).append(t)
    return [groups[d] for d in sorted(groups)]


def sidecar_path(log: str | Path) -> Path:
    p = Path(log)
    return p.with_name(p.stem + ".summary.json")


def write_sidecar(log: str | Path, summaries: list[dict]) -> Path:
    out = sidecar_path(log)
    out.write_text(json.dumps(summaries, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def to_markdown(summaries: list[dict]) -> str:
    lines = ["# Что произошло в деревне", ""]
    for s in summaries:
        lines += [f"## {s['from']} — {s['to']}", "", s["text"], ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="LLM recap per game day of a finished log.")
    p.add_argument("log")
    p.add_argument("--model", default=DEFAULT_MODEL, help="OpenRouter id, 'default' or 'stub'")
    p.add_argument("--md", default=None, help="also write a Russian markdown report here")
    a = p.parse_args(argv)
    from .run import read_log
    recs = list(read_log(a.log))
    cfg = recs[0].get("config") if recs and recs[0].get("type") == "header" else None
    s = Summarizer(make_client(a.model), cfg)
    summaries = [r for day in by_day(ticks_of(recs), cfg) if (r := s.summarize(day))]
    out = write_sidecar(a.log, summaries)
    if a.md:
        Path(a.md).write_text(to_markdown(summaries), encoding="utf-8")
    for r in summaries:
        print(f"[{r['from']} — {r['to']}] {r['text']}\n")
    print(f"{len(summaries)} recaps -> {out}, cost ${s.cost_usd:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
