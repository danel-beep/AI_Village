"""Behaviour metrics from a run log (JSONL written by run.py). Reads only the log, never the engine.

    python -m aivillage.metrics runs/demo.jsonl              # markdown to stdout
    python -m aivillage.metrics runs/demo.jsonl --json out.json --md out.md
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

from . import logio

# Event kinds that are a direct interaction between the actor and the people in `to`.
DIRECT_KINDS = {"whisper", "letter", "give", "lend", "offer", "trade", "decline", "share", "unshare"}

_LEND_RE = re.compile(r"must repay (\d+) by day (\d+)")
_REPAY_RE = re.compile(r"repaid (\d+) coins to (.+?) \((\S+), (\d+) left\)")
_DEFAULT_RE = re.compile(r"^(.+?) failed to repay (.+?) on time \((\d+) coins, (\S+)\)\.$")
_TRADE_RE = re.compile(r"traded: (.*) for (.*)\.$")


def gini(values: Iterable[float]) -> float:
    xs = sorted(max(0.0, float(v)) for v in values)
    n, total = len(xs), sum(xs)
    if n == 0 or total == 0:
        return 0.0
    weighted = sum((i + 1) * x for i, x in enumerate(xs))
    return round((2 * weighted) / (n * total) - (n + 1) / n, 4)


def read_log(path: str | Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return list(logio.parse(f))


def _counterparts(ev: dict) -> list[str]:
    return [n for n in ev.get("to") or [] if n != ev.get("actor")]


def compute(records: list[dict]) -> dict:
    ticks = [r for r in records if r.get("type") == "tick"]
    edges: Counter = Counter()          # (a, b, kind) -> n, directed a -> b
    trades: list[dict] = []
    trade_pairs: Counter = Counter()
    debts: dict[str, dict] = {}
    thefts: list[dict] = []
    fires: list[dict] = []
    open_fires: dict[str, dict] = {}    # home location -> fire record
    last_view_by_day: dict[int, dict] = {}
    agents: set[str] = set()

    def edge(a: str | None, b: str | None, kind: str) -> None:
        if a and b and a != b:
            edges[(a, b, kind)] += 1

    for rec in ticks:
        view = rec.get("view") or {}
        positions = {n: s.get("location") for n, s in (view.get("agents") or {}).items()}
        agents.update(positions)
        if view:
            last_view_by_day[view["day"]] = view
        attempts = {(e.get("actor"), tuple(e.get("to") or [])) for e in rec["events"] if e["kind"] == "steal_attempt"}
        for ev in rec["events"]:
            kind, actor, data = ev["kind"], ev.get("actor"), ev.get("data") or {}
            if kind in DIRECT_KINDS:
                for other in _counterparts(ev):
                    edge(actor, other, kind)
            if kind == "trade":
                partner = (_counterparts(ev) or [None])[0]
                m = _TRADE_RE.search(ev["text"])
                trades.append({"tick": ev["tick"], "day": ev["day"], "offerer": partner, "accepter": actor,
                               "offerer_gave": m.group(1) if m else None, "accepter_gave": m.group(2) if m else None})
                trade_pairs[tuple(sorted((partner or "?", actor or "?")))] += 1
            elif kind == "lend":
                m = _LEND_RE.search(ev["text"])
                debts[data["debt"]] = {"id": data["debt"], "lender": actor, "borrower": _counterparts(ev)[0],
                                       "day": ev["day"], "owed": int(m.group(1)) if m else None,
                                       "due_day": int(m.group(2)) if m else None, "repaid": 0,
                                       "status": "open", "defaulted_day": None}
            elif kind == "promise":  # an IOU (debts.py): the actor owes data["lender"]
                debts[data["debt"]] = {"id": data["debt"], "lender": data.get("lender"), "borrower": actor,
                                       "day": ev["day"], "owed": data.get("coins"), "due_day": data.get("due_day"),
                                       "repaid": 0, "status": "open", "defaulted_day": None, "kind": "iou"}
            elif kind == "pledge_forfeited" and data.get("debt") in debts:
                debts[data["debt"]].update(status="defaulted", defaulted_day=ev["day"])
            elif kind in ("debt_collected", "debt_seized", "debt_garnished") and data.get("debt") in debts:
                d = debts[data["debt"]]
                d["repaid"] += int(data.get("coins") or 0) + int(data.get("goods_value") or 0)
                if "the debt is closed" in ev["text"]:
                    d["status"] = "repaid_late"
            elif kind == "repay":
                m = _REPAY_RE.search(ev["text"])
                d = debts.get(data.get("debt"))
                if m and d is not None:
                    edge(actor, d["lender"], "repay")
                    d["repaid"] += int(m.group(1))
                    if int(m.group(4)) == 0:
                        d["status"] = "repaid_late" if d["defaulted_day"] is not None else "repaid"
            elif kind == "default":
                m = _DEFAULT_RE.search(ev["text"])
                if m and m.group(4) in debts:
                    debts[m.group(4)]["status"] = "defaulted"
                    debts[m.group(4)]["defaulted_day"] = ev["day"]
            elif kind == "steal":
                victim = data.get("victim")
                witnesses = data.get("witnesses") or []
                victim_noticed = (actor, (victim,)) in attempts
                edge(actor, victim, "steal")
                thefts.append({"tick": ev["tick"], "day": ev["day"], "thief": actor, "victim": victim,
                               "success": bool(data.get("success")), "item": data.get("item"),
                               "qty": data.get("qty", 0), "witnesses": witnesses,
                               "victim_noticed": victim_noticed, "seen": bool(witnesses) or victim_noticed})
            elif kind == "fire":
                victim = data.get("victim")
                f = {"victim": victim, "start_tick": ev["tick"], "day": ev["day"], "end_tick": None,
                     "outcome": "burning", "put_out_by": None, "responders": {}}
                fires.append(f)
                open_fires[f"home_{victim}"] = f
            elif kind in ("extinguish", "pour_water", "fire_out"):  # "extinguish": logs before pour_water
                loc = ev.get("location") or positions.get(actor)
                f = open_fires.get(loc)
                if f is not None:
                    f["responders"][actor] = f["responders"].get(actor, 0) + 1
                    edge(actor, f["victim"], "extinguish")
                    if kind == "fire_out":
                        f.update(outcome="put_out", put_out_by=actor, end_tick=ev["tick"])
                        del open_fires[loc]
            elif kind == "house_burned":
                f = open_fires.pop(data.get("home"), None)
                if f is not None:
                    f.update(outcome="burned", end_tick=ev["tick"])

    graph: dict[str, dict[str, dict[str, int]]] = defaultdict(lambda: defaultdict(dict))
    for (a, b, kind), n in sorted(edges.items()):
        graph[a][b][kind] = n
    pair_totals: Counter = Counter()
    for (a, b, _kind), n in edges.items():
        pair_totals[tuple(sorted((a, b)))] += n

    debt_list = sorted(debts.values(), key=lambda d: d["id"])
    debt_status = Counter(d["status"] for d in debt_list)
    gini_by_day = {}
    for day, view in sorted(last_view_by_day.items()):
        alive = [s["coins"] for s in view["agents"].values() if s.get("status") != "dead"]
        gini_by_day[day] = {"gini_coins": gini(alive), "total_coins": sum(alive), "alive": len(alive)}
    successful = [t for t in thefts if t["success"]]
    responders_total: Counter = Counter()
    for f in fires:
        responders_total.update(f["responders"].keys())

    return {
        "ticks": len(ticks),
        "days": sorted(last_view_by_day),
        "agents": sorted(agents),
        "interactions": {
            "graph": {a: dict(bs) for a, bs in graph.items()},
            "pairs": [{"a": a, "b": b, "count": n} for (a, b), n in pair_totals.most_common()],
            "by_kind": dict(Counter(k for (_a, _b, k) in edges.elements())),
        },
        "trades": {"count": len(trades), "pairs": [{"a": a, "b": b, "count": n}
                                                   for (a, b), n in trade_pairs.most_common()], "list": trades},
        "debts": {"count": len(debt_list), "repaid": debt_status["repaid"],
                  "repaid_late": debt_status["repaid_late"], "defaulted": debt_status["defaulted"],
                  "open": debt_status["open"], "list": debt_list},
        "thefts": {"attempts": len(thefts), "successful": len(successful),
                   "seen": sum(t["seen"] for t in thefts), "unseen": sum(not t["seen"] for t in thefts),
                   "successful_unseen": sum(not t["seen"] for t in successful),
                   "by_thief": dict(Counter(t["thief"] for t in thefts)), "list": thefts},
        "gini_by_day": gini_by_day,
        "fires": {"count": len(fires), "put_out": sum(f["outcome"] == "put_out" for f in fires),
                  "burned": sum(f["outcome"] == "burned" for f in fires),
                  "responders_total": dict(responders_total), "list": fires},
    }


def to_markdown(m: dict) -> str:
    out = [f"# Метрики прогона", "",
           f"Тиков: {m['ticks']}, дней: {len(m['days'])}, агентов: {len(m['agents'])}.", ""]
    out += ["## Взаимодействия (пары)", "", "| Пара | Контактов |", "| --- | --- |"]
    out += [f"| {p['a']} — {p['b']} | {p['count']} |" for p in m["interactions"]["pairs"]] or ["| — | 0 |"]
    kinds = ", ".join(f"{k}: {n}" for k, n in sorted(m["interactions"]["by_kind"].items()))
    out += ["", f"По типам: {kinds or 'нет'}.", ""]
    t = m["trades"]
    out += ["## Сделки", "", f"Всего: {t['count']}."]
    out += [f"- {p['a']} — {p['b']}: {p['count']}" for p in t["pairs"]]
    d = m["debts"]
    out += ["", "## Долги", "",
            f"Выдано: {d['count']}; вернули вовремя: {d['repaid']}; вернули после просрочки: {d['repaid_late']}; "
            f"не вернули: {d['defaulted']}; ещё открыты: {d['open']}."]
    out += [f"- {x['id']}: {x['lender']} → {x['borrower']}, долг {x['owed']} до дня {x['due_day']}, "
            f"вернул {x['repaid']}, статус {x['status']}" for x in d["list"]]
    th = m["thefts"]
    out += ["", "## Кражи", "",
            f"Попыток: {th['attempts']}; удачных: {th['successful']}; замечены: {th['seen']}; "
            f"не замечены: {th['unseen']} (из удачных незамеченных: {th['successful_unseen']})."]
    out += [f"- {k}: {n}" for k, n in sorted(th["by_thief"].items())]
    out += ["", "## Неравенство (Джини по монетам, конец дня)", "", "| День | Джини | Монет всего | Живых |",
            "| --- | --- | --- | --- |"]
    out += [f"| {day} | {g['gini_coins']} | {g['total_coins']} | {g['alive']} |"
            for day, g in m["gini_by_day"].items()]
    fi = m["fires"]
    out += ["", "## Пожары", "", f"Всего: {fi['count']}; потушены: {fi['put_out']}; сгорели: {fi['burned']}."]
    for f in fi["list"]:
        who = ", ".join(f"{n} ({k})" for n, k in sorted(f["responders"].items())) or "никто"
        out.append(f"- дом {f['victim']}, день {f['day']}: {f['outcome']}; тушили: {who}")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("log", help="JSONL log written by aivillage.run")
    p.add_argument("--json", help="write metrics JSON here")
    p.add_argument("--md", help="write markdown report here (default: stdout)")
    args = p.parse_args(argv)
    m = compute(read_log(args.log))
    if args.json:
        Path(args.json).write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    md = to_markdown(m)
    if args.md:
        Path(args.md).write_text(md, encoding="utf-8")
    else:
        sys.stdout.write(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
