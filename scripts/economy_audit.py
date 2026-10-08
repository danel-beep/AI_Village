"""Where the coins come from and who ends up with them: bot villages with every coin tagged by its source.

    python scripts/economy_audit.py --mode crafts --bots trader --villagers 10 --days 14 --seeds 1,2,3,4,5
    python scripts/economy_audit.py --mode survival --bots builder --villagers 6 --days 24 --set progress.start_stage=camp

Every ops.mint_coins / burn_coins / move_coins call is counted under the function that made it (actions.sell,
market.buy_sale, governance.pay_tax, taxes.deliver ...). Prints a Russian markdown summary: money flows per run,
coins per start profession (start, end, main sources), inequality (Gini) and who sat in hospital.
Report: docs/runs/economy-audit.md. Bots are the measuring stick, so their limits (fixed prices at the middle of
the trader's, no haggling) are the report's limits too.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aivillage import engine, modes, ops  # noqa: E402
from aivillage.run import bots_decider, run  # noqa: E402
from aivillage.state import Agent  # noqa: E402

FLOW: Counter = Counter()  # "mint|actions.sell" -> coins
PER: dict = defaultdict(Counter)  # villager -> "+actions.sell" / "-governance.pay_tax" -> coins


def _source() -> str:
    f = sys._getframe(2)
    while f is not None:
        mod = f.f_globals.get("__name__", "")
        if mod.startswith("aivillage") and not mod.endswith(".ops"):
            return f"{mod.split('.')[-1]}.{f.f_code.co_name}"
        f = f.f_back
    return "?"


def _tag(holder, sign: str, s: str, n: int) -> None:
    if isinstance(holder, Agent):
        PER[holder.name][sign + s] += n


def _install() -> None:
    mint, burn, move = ops.mint_coins, ops.burn_coins, ops.move_coins

    def mint_coins(world, holder, n):
        s = _source()
        FLOW["mint|" + s] += n
        _tag(holder, "+", s, n)
        return mint(world, holder, n)

    def burn_coins(world, holder, n):
        s = _source()
        FLOW["burn|" + s] += n
        _tag(holder, "-", s, n)
        return burn(world, holder, n)

    def move_coins(src, dst, n):
        s = _source()
        kind = lambda h: "villager" if isinstance(h, Agent) else type(h).__name__  # noqa: E731
        if n:
            FLOW[f"move {kind(src)}->{kind(dst)}|{s}"] += n
        _tag(src, "-", s, n)
        _tag(dst, "+", s, n)
        return move(src, dst, n)

    ops.mint_coins, ops.burn_coins, ops.move_coins = mint_coins, burn_coins, move_coins


def _wealth(world, name: str) -> int:
    a = world.agents[name]
    chest = world.chests.get(f"chest_{name}")
    return a.coins + (chest.coins if chest else 0)


def gini(xs) -> float:
    xs = sorted(max(0, x) for x in xs)
    total = sum(xs)
    return sum((2 * i - len(xs) + 1) * x for i, x in enumerate(xs)) / (len(xs) * total) if total else 0.0


def play(preset: str, bots: list[str], n: int, days: int, seed: int, extra: dict) -> dict:
    FLOW.clear()
    PER.clear()
    over = {"seed": seed, "population": {"size": n}, "map": {"procedural": True}, "tick_minutes": 15}
    for key, value in extra.items():
        d = over
        *path, last = key.split(".")
        for k in path:
            d = d.setdefault(k, {})
        d[last] = value
    w = engine.new_world(modes.world_override(preset, over))
    names = sorted(w.agents)
    start = {x: _wealth(w, x) for x in names}
    prof = {a["name"]: a.get("profession") for a in w.config["agents"]}  # at the start (places.py may change it)
    sick = Counter()

    def night(world, day):
        sick.update(prof[x] for x in names if world.agents[x].status != "active")
        return {}
    run(w, bots_decider(w, bots, seed), days, None, None, check_every_tick=False, on_night=night)
    return {"flow": dict(FLOW), "per": {k: dict(v) for k, v in PER.items()}, "prof": prof, "start": start,
            "end": {x: _wealth(w, x) for x in names}, "treasury": w.governance.coins, "sick_days": dict(sick)}


def report(runs: list[dict], args) -> str:
    k = len(runs)
    flow = Counter()
    for r in runs:
        flow.update(r["flow"])
    out = [f"## {args.preset}, боты {args.bots}, {args.villagers} жителей × {args.days} дней, сиды {args.seeds}", "",
           "Потоки монет за прогон (в среднем):", "", "| монет | что | откуда |", "|---:|---|---|"]
    out += [f"| {v / k:.0f} | {key.split('|')[0]} | `{key.split('|')[1]}` |" for key, v in flow.most_common(12)]
    by = defaultdict(lambda: {"start": [], "end": [], "src": Counter()})
    sick = Counter()
    for r in runs:
        sick.update(r["sick_days"])
        for name, p in r["prof"].items():
            by[p]["start"].append(r["start"][name])
            by[p]["end"].append(r["end"][name])
            by[p]["src"].update(r["per"].get(name, {}))
    out += ["", "| профессия на старте | жителей | монет на старте | в конце | ×  | мин–макс | дней в больнице | главное |",
            "|---|---:|---:|---:|---:|---|---:|---|"]
    for p, d in sorted(by.items(), key=lambda x: -statistics.mean(x[1]["end"])):
        s, e, cnt = statistics.mean(d["start"]), statistics.mean(d["end"]), len(d["end"])
        top = ", ".join(f"{key[0]}{key[1:]} {v / cnt:.0f}" for key, v in d["src"].most_common(3))
        out.append(f"| {p} | {cnt} | {s:.0f} | {e:.0f} | {e / max(s, 1):.1f} | {min(d['end'])}–{max(d['end'])} "
                   f"| {sick.get(p, 0)} | {top} |")
    g = [f"{gini(r['start'].values()):.2f}→{gini(r['end'].values()):.2f}" for r in runs]
    out += ["", f"Неравенство (Джини, старт→конец): {', '.join(g)}. "
                f"Казна в конце: {', '.join(str(r['treasury']) for r in runs)}."]
    return "\n".join(out)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--preset", default="village")
    p.add_argument("--bots", default="trader")
    p.add_argument("--villagers", type=int, default=10)
    p.add_argument("--days", type=int, default=14)
    p.add_argument("--seeds", default="1,2,3,4,5")
    p.add_argument("--set", action="append", default=[], help="world key=JSON value, e.g. labor.work_hours_per_day=4")
    p.add_argument("--json", default=None, help="also save the raw numbers here")
    args = p.parse_args(argv)
    extra = {}
    for item in args.set:
        key, value = item.split("=", 1)
        try:
            extra[key] = json.loads(value)
        except json.JSONDecodeError:
            extra[key] = value
    _install()
    runs = [play(args.preset, args.bots.split(","), args.villagers, args.days, int(s), extra)
            for s in args.seeds.split(",")]
    if args.json:
        Path(args.json).write_text(json.dumps(runs, ensure_ascii=False))
    print(report(runs, args))
    return 0


if __name__ == "__main__":
    sys.exit(main())
