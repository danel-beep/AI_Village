"""Model comparison series: the same village, the models swap seats, one report at the end.

    python scripts/compare_models.py --config configs/compare.yaml               # every rotation of its roster
    python scripts/compare_models.py --config configs/compare.yaml --seeds 7,8 --rotations 2
    python scripts/compare_models.py --logs runs/compare/*.jsonl --judge default  # only the report

For each seed and rotation k it writes runs/compare/s<seed>-r<k>.yaml (the exact run config, `models` resolved)
and .jsonl (the log), then aivillage/compare.py adds them up per model into report.md / report.json.
Before any model is called it estimates the cost from OpenRouter's prices and checks every model with one tiny
call; it stops when the estimate is above --budget (USD) unless --yes.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aivillage import compare, engine, mapgen, roster, run, runconfig  # noqa: E402


def seating(rc: runconfig.RunConfig, models: list[str]) -> dict[str, str]:
    w = engine.new_world(mapgen.for_run(rc.world_override(), False, None))
    return {n: (m if k == "model" else f"bot:{m}") for n, (k, m) in rc.brains(sorted(w.agents), models).items()}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--config", help="run config with a `models:` roster (see configs/compare.yaml)")
    p.add_argument("--seeds", default=None, help="comma-separated seeds (default: the config's seed)")
    p.add_argument("--rotations", type=int, default=None, help="rotations per seed (default: one per model)")
    p.add_argument("--out", default="runs/compare", help="folder for configs, logs and the report")
    p.add_argument("--budget", type=float, default=roster.BUDGET_PER_DAY, help="stop above this estimate, USD")
    p.add_argument("--yes", action="store_true", help="run even above the budget / without a price list")
    p.add_argument("--judge", default=None, help="model that marks lies in the report ('default' = GPT-6 Luna)")
    p.add_argument("--logs", nargs="*", default=None, help="skip running: report on these logs")
    a = p.parse_args(argv)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    logs = a.logs
    if logs is None:
        if not a.config:
            p.error("--config or --logs is required")
        base = yaml.safe_load(Path(a.config).read_text(encoding="utf-8")) or {}
        rc = runconfig.parse(base, a.config)
        if not rc.models:
            p.error(f"{a.config} has no `models:` roster")
        try:
            models = run.resolve_roster(rc, rc.villagers or len(rc.agents or []) or 5)
        except RuntimeError as e:
            print(e, file=sys.stderr)
            return 2
        seeds = [int(s) for s in a.seeds.split(",")] if a.seeds else [rc.seed]
        rotations = a.rotations or len(models)
        plan = []
        for seed in seeds:
            for k in range(rotations):
                spec = {**base, "seed": seed, "models": models, "rotate": k, "log": str(out / f"s{seed}-r{k}.jsonl")}
                plan.append((spec, seating(runconfig.parse(spec), models)))
        llm_models = sorted({m for _, s in plan for m in s.values() if not roster.is_bot(m) and m != "stub"})
        if llm_models:
            try:
                prices = roster.catalog_prices(roster.fetch_catalog())
            except OSError as e:
                prices = {}
                print(f"price list unavailable ({e})")
            est = [roster.estimate(s, spec.get("days", 3), prices) for spec, s in plan]
            total = sum(e["total"] for e in est)
            unknown = sorted({u for e in est for u in e["unknown"]})
            print(f"{len(plan)} runs, models: {', '.join(models)}; estimate ${total:.2f}"
                  + (f" (no price for {', '.join(unknown)})" if unknown else ""))
            if (total > a.budget or unknown) and not a.yes:
                print(f"stopping: above the ${a.budget:.2f} budget or prices unknown; pass --yes to run anyway")
                return 3
            from aivillage.llm import check
            bad = {m: r.get("error") for m in llm_models if not (r := check(m)).get("ok")}
            if bad:
                print("models that do not answer: " + "; ".join(f"{m}: {e}" for m, e in bad.items()), file=sys.stderr)
                return 2
        logs = []
        for spec, seats in plan:
            cfg = Path(spec["log"]).with_suffix(".yaml")
            cfg.write_text(yaml.safe_dump(spec, allow_unicode=True, sort_keys=False), encoding="utf-8")
            print(f"seed {spec['seed']} rotation {spec['rotate']}: " + ", ".join(f"{n}={m}" for n, m in seats.items()))
            with contextlib.redirect_stdout(io.StringIO()):
                code = run.main(["--config", str(cfg)])
            if code:
                return code
            logs.append(spec["log"])
    judge = None
    if a.judge:
        from aivillage.llm import make_client
        judge = make_client(a.judge)
    rep = compare.compute(logs, judge)
    (out / "report.json").write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    md = compare.to_markdown(rep)
    (out / "report.md").write_text(md, encoding="utf-8")
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
