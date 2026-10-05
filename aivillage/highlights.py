"""Highlights of the day: the 3-5 most dramatic moments of each game day, each tied to a tick so the
viewer can rewind to it ("⭐ Хайлайты").

    python -m aivillage.highlights runs/x.jsonl                # -> runs/x.highlights.json
    python -m aivillage.highlights runs/x.jsonl --model stub   # offline: picked by rules, no key

Reads only log records, like summary.py (whose digest gives the model context and whose client it reuses).
Candidates are scored log events (theft, fire, debts, deals...); the model picks among them by number and
writes a Russian title and a line for each. If the model is off or answers nonsense, the rules pick.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .llm import DEFAULT_MODEL, Client, parse_json_object
from .summary import StubSummaryClient, by_day, digest, make_client, ticks_of, when

MAX_PICKS, MIN_PICKS = 5, 3
MAX_CANDIDATES = 60
CONTEXT_LINES = 120

# How dramatic an event kind is; 0 / missing = never a highlight.
DRAMA = {
    "death": 10, "house_burned": 10, "steal": 10, "robbed": 9, "fire": 9, "default": 8, "evicted": 8,
    "steal_attempt": 7, "hospital": 7, "extinguish": 6, "witness": 6, "whisper_seen": 5, "fire_out": 5,
    "starving": 5, "drought": 5, "god_treasure": 5, "project_done": 5, "lend": 4, "give": 4, "sick": 4,
    "take_shared": 4, "trade": 3, "decline": 3, "repay": 3, "gift": 3, "tax": 3, "unshare": 3, "discharged": 3,
    "whisper": 2, "letter": 2, "share": 2, "lock": 2, "tool_broke": 2, "offer": 1,
    # families, elections, rumors (PRs #17, #19, #21)
    "wedding": 9, "divorce": 9, "elected": 8, "theft_report": 7, "inheritance": 6, "law_passed": 6,
    "proposal": 6, "proposal_refused": 6, "exile_over": 5, "gossip": 4, "gossip_heard": 4, "law_failed": 4,
    "election": 4, "law_proposed": 3, "candidate": 3, "fire_grows": 3, "hang_out": 1,
}
TITLES = {
    "death": "Смерть в деревне", "house_burned": "Сгорел дом", "steal": "Кража", "robbed": "Кража",
    "fire": "Пожар", "default": "Долг не вернули", "evicted": "Выселение", "steal_attempt": "Попытка кражи",
    "hospital": "В больнице", "extinguish": "Тушат пожар", "witness": "Свидетель кражи",
    "whisper_seen": "Подслушанный шёпот", "fire_out": "Пожар потушен", "starving": "Голод",
    "drought": "Засуха", "god_treasure": "Клад", "project_done": "Общая стройка готова", "lend": "Заём",
    "give": "Подарок", "sick": "Болезнь", "take_shared": "Взял из общего", "trade": "Сделка",
    "decline": "Отказ", "repay": "Долг вернули", "gift": "Дар богов", "tax": "Налог",
    "unshare": "Забрал своё", "discharged": "Выписка", "whisper": "Шёпот", "letter": "Письмо",
    "share": "Вклад в общее", "lock": "Замок", "tool_broke": "Сломался инструмент", "offer": "Предложение",
    "wedding": "Свадьба", "divorce": "Развод", "elected": "Новый староста", "theft_report": "Донос о краже",
    "inheritance": "Наследство", "law_passed": "Принят закон", "proposal": "Предложение руки и сердца",
    "proposal_refused": "Отказ жениться", "exile_over": "Изгнание окончено", "gossip": "Слух",
    "gossip_heard": "Слух", "law_failed": "Закон провалился", "election": "Выборы", "law_proposed": "Новый закон",
    "candidate": "Кандидат в старосты", "fire_grows": "Пожар разгорается", "hang_out": "Провели время вместе",
}

PROMPT = """You pick the highlights of one day in a village life simulation where every villager is an AI.
Input: numbered candidate moments ("#3 D2 09:00 [steal] ...") and, for context, a digest of the day with
villagers' private thoughts, actions and speech. Choose the 3-5 most dramatic, surprising or story-worthy
moments for a human spectator: betrayal, theft, lies (thought differs from what was said), fires, debts,
alliances, quarrels, generosity, someone in trouble. Prefer different stories over repeats of one.
For each write in Russian a title (at most 6 words) and one or two sentences with concrete names.
Answer ONLY a JSON object: {"highlights": [{"id": 3, "title": "...", "text": "..."}]}"""


def candidates(ticks: list[dict], cfg: dict | None = None) -> list[dict]:
    """Scored dramatic events of these ticks, chronological, at most MAX_CANDIDATES (best kept).
    The same event repeated (a thief failing every hour) is one candidate with `times`."""
    names = {n for rec in ticks for n in (rec.get("decisions") or {})}
    out, first = [], {}
    for rec in ticks:
        day, hour = when(rec, cfg)
        for e in rec.get("events") or []:
            score = DRAMA.get(e.get("kind"), 0)
            if not score or not e.get("text"):
                continue
            text = " ".join(str(e["text"]).split())
            key = (e["kind"], e.get("actor"), text)
            if key in first:
                first[key]["times"] += 1
                continue
            who = [n for n in [e.get("actor"), *(e.get("to") or [])] if n]
            who += sorted(n for n in names if n in text and n not in who)  # "Anna's house is on fire"
            first[key] = {"tick": rec["tick"], "day": day, "hour": hour, "kind": e["kind"], "score": score,
                          "who": list(dict.fromkeys(who)), "event": text, "times": 1}
            out.append(first[key])
    if len(out) > MAX_CANDIDATES:
        keep = sorted(range(len(out)), key=lambda k: -out[k]["score"])[:MAX_CANDIDATES]
        out = [out[k] for k in sorted(keep)]
    return out


def by_rules(cands: list[dict], n: int = MAX_PICKS) -> list[int]:
    """Indexes of the best candidates: by score, skipping the same incident seen twice
    (theft + robbed + witness in one tick) and more than two of one kind."""
    picked: list[int] = []
    kinds: dict[str, int] = {}
    for k in sorted(range(len(cands)), key=lambda k: (-cands[k]["score"], cands[k]["tick"])):
        c = cands[k]
        if c["score"] < 3 or kinds.get(c["kind"], 0) >= 2:
            continue
        if any(cands[p]["tick"] == c["tick"] and set(cands[p]["who"]) & set(c["who"]) for p in picked):
            continue
        picked.append(k)
        kinds[c["kind"]] = kinds.get(c["kind"], 0) + 1
        if len(picked) >= n:
            break
    return sorted(picked, key=lambda k: cands[k]["tick"])


def _item(c: dict, title: str | None = None, text: str | None = None) -> dict:
    return {"tick": c["tick"], "day": c["day"], "hour": c["hour"], "time": f"день {c['day']}, {c['hour']:02d}:00",
            "kind": c["kind"], "who": c["who"], "title": title or TITLES.get(c["kind"], c["kind"]),
            "text": text or c["event"] + (f" (×{c['times']} за день)" if c["times"] > 1 else ""),
            "event": c["event"], "times": c["times"]}


class Highlighter:
    def __init__(self, client: Client | None, cfg: dict | None = None):
        """`client=None` or a stub: rules only, no model call."""
        self.client = None if client is None or isinstance(client, StubSummaryClient) else client
        self.cfg = cfg
        self.cost_usd = 0.0

    def pick(self, ticks: list[dict]) -> dict | None:
        """Highlights of these ticks (normally one game day), or None if nothing dramatic happened."""
        cands = candidates(ticks, self.cfg)
        if not ticks or not cands:
            return None
        items, cost, source = self._ask(ticks, cands) if self.client else ([], 0.0, "rules")
        if len(items) < min(MIN_PICKS, len(by_rules(cands))):
            items, source = [_item(cands[k]) for k in by_rules(cands)], "rules"
        if not items:
            return None
        day = when(ticks[0], self.cfg)[0]
        return {"day": day, "from_tick": ticks[0]["tick"], "to_tick": ticks[-1]["tick"], "source": source,
                "items": items, "cost_usd": cost}

    def _ask(self, ticks: list[dict], cands: list[dict]) -> tuple[list[dict], float, str]:
        listing = "\n".join(f"#{k} D{c['day']} {c['hour']:02d}:00 [{c['kind']}] {c['event'][:200]}"
                            + (f" (x{c['times']} that day)" if c["times"] > 1 else "")
                            for k, c in enumerate(cands))
        text = f"Candidates:\n{listing}\n\nDigest:\n{digest(ticks, CONTEXT_LINES, self.cfg)}"
        try:
            reply, usage = self.client.complete([{"role": "system", "content": PROMPT},
                                                 {"role": "user", "content": text}])
        except Exception:  # a failed call falls back to the rules; highlights never stop the village
            return [], 0.0, "rules"
        cost = float(usage.get("cost") or 0)
        self.cost_usd += cost
        obj = parse_json_object(reply, "highlights") or {}
        items, used = [], set()
        for h in obj.get("highlights") or []:
            if not isinstance(h, dict):
                continue
            try:
                k = int(str(h.get("id")).lstrip("#"))
            except ValueError:
                continue
            if k in used or not 0 <= k < len(cands):
                continue
            used.add(k)
            title, line = str(h.get("title") or "").strip()[:80], str(h.get("text") or "").strip()[:400]
            items.append(_item(cands[k], title or None, line or None))
            if len(items) >= MAX_PICKS:
                break
        return sorted(items, key=lambda it: it["tick"]), cost, "model"


def sidecar_path(log: str | Path) -> Path:
    p = Path(log)
    return p.with_name(p.stem + ".highlights.json")


def write_sidecar(log: str | Path, days: list[dict]) -> Path:
    out = sidecar_path(log)
    out.write_text(json.dumps(days, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Highlights (3-5 dramatic moments) per game day of a finished log.")
    p.add_argument("log")
    p.add_argument("--model", default=DEFAULT_MODEL, help="OpenRouter id, 'default' or 'stub' (rules only)")
    a = p.parse_args(argv)
    from .run import read_log
    recs = list(read_log(a.log))
    cfg = recs[0].get("config") if recs and recs[0].get("type") == "header" else None
    h = Highlighter(make_client(a.model), cfg)
    days = [r for day in by_day(ticks_of(recs), cfg) if (r := h.pick(day))]
    out = write_sidecar(a.log, days)
    for d in days:
        print(f"День {d['day']} ({d['source']}):")
        for it in d["items"]:
            print(f"  [{it['time']}, ход {it['tick']}] {it['title']}: {it['text']}")
    print(f"{len(days)} days -> {out}, cost ${h.cost_usd:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
