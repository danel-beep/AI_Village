"""Measure how long a game hour takes and what a day costs for N LLM villagers.

    python scripts/scale_bench.py --sizes 10,20 --days 1 [--model default] [--parallel 4] [--fallback m1,m2]

Needs OPENROUTER_API_KEY. Prints a markdown table (paste into docs/runs/).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aivillage import engine, llm  # noqa: E402
from aivillage.run import llm_agents, night_reflection, run  # noqa: E402


def bench(n: int, days: int, model: str, fallbacks: list[str] | None, seed: int) -> dict:
    llm._GATES.clear()
    world = engine.new_world({"seed": seed, "population": {"size": n}})
    agents = llm_agents(world, [model], fallbacks)
    ticks: list[float] = []
    last = [time.monotonic()]

    def on_tick(w, events):
        now = time.monotonic()
        ticks.append(now - last[0])
        last[0] = now

    def on_night(w, day):
        out = night_reflection(w, agents, day)
        last[0] = time.monotonic()  # the diary is timed separately below
        return out

    t0 = time.monotonic()
    stats = run(world, lambda name, obs: agents[name].decide(obs), days, on_tick=on_tick, on_night=on_night,
                check_every_tick=False)
    total = time.monotonic() - t0
    usage = [a.usage for a in agents.values()]
    gates = list(llm._GATES.values())
    cost = sum(u.cost_usd for u in usage)
    return {"n": n, "days": days, "ticks": len(ticks), "tick_avg": sum(ticks) / len(ticks), "tick_max": max(ticks),
            "total": total, "calls": sum(u.calls for u in usage), "failures": sum(u.failures for u in usage),
            "limited": sum(g.rate_limited for g in gates), "waited": sum(g.waited for g in gates),
            "cost": cost, "cost_agent_day": cost / n / days, "asked": stats.get("llm_calls", 0),
            "fallback_calls": sum(c for u in usage for m, c in u.by_model.items() if not m.startswith(model))}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--sizes", default="10,20")
    p.add_argument("--days", type=int, default=1)
    p.add_argument("--model", default="default")
    p.add_argument("--parallel", type=int, default=None, help="max parallel calls per model (env AIVILLAGE_MAX_PARALLEL)")
    p.add_argument("--fallback", default="")
    p.add_argument("--seed", type=int, default=1)
    a = p.parse_args()
    if a.parallel:
        os.environ["AIVILLAGE_MAX_PARALLEL"] = str(a.parallel)
    model = llm.DEFAULT_MODEL if a.model == "default" else a.model
    fallbacks = a.fallback.split(",") if a.fallback else []
    print(f"model {model}, max {os.environ.get('AIVILLAGE_MAX_PARALLEL') or f'{llm.OPENAI_PARALLEL} (OpenAI) / {llm.DEFAULT_PARALLEL} (OpenRouter)'} "
          "parallel, "
          f"fallback {fallbacks or 'none'}\n")
    print("| villagers | days | hour avg, s | hour max, s | whole run, s | model calls | 429s | failed | "
          "cost | per villager-day |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for n in map(int, a.sizes.split(",")):
        r = bench(n, a.days, model, fallbacks, a.seed)
        print(f"| {r['n']} | {r['days']} | {r['tick_avg']:.1f} | {r['tick_max']:.1f} | {r['total']:.0f} | {r['calls']} | "
              f"{r['limited']} | {r['failures']} | ${r['cost']:.4f} | ${r['cost_agent_day']:.4f} |", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
