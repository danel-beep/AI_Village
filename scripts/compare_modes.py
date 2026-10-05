"""Run every economy mode on the same seeds and compare behaviour (Russian markdown table).

    python scripts/compare_modes.py --days 3 --seeds 1,2,3 --out docs/runs/modes-bots.md
    python scripts/compare_modes.py --days 3 --seeds 7 --models default --out docs/runs/modes-luna.md
    python scripts/compare_modes.py --logs runs/modes/*.jsonl          # only compare existing logs

Logs go to runs/modes/<brain>-<mode>-s<seed>.jsonl. Numbers are summed over seeds, except
the Gini coefficient and wealth, which are averaged.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aivillage import metrics, run  # noqa: E402
from aivillage.modes import MODES  # noqa: E402

BOTS = "trader,worker,thief,trader,random"
PARTNER_KINDS = {"trade", "give", "lend", "share_chest"}

COLUMNS = [
    ("thefts", "Попыток краж"),
    ("thefts_ok", "Удачных краж"),
    ("thefts_unseen", "Удачных и незамеченных"),
    ("betrayals", "Краж у партнёров"),
    ("trades", "Сделок"),
    ("gifts", "Подарков"),
    ("loans", "Займов"),
    ("defaults", "Невозвратов"),
    ("evictions", "Выселений"),
    ("hospital", "В больницу"),
    ("orders", "Заказов выполнено"),
    ("gini", "Неравенство (Джини)"),
    ("wealth", "Монет у всех"),
    ("conflicts", "Конфликтов"),
]


def log_stats(records: list[dict]) -> dict:
    m = metrics.compute(records)
    counts: dict[str, int] = defaultdict(int)
    partners: set[tuple[str, str]] = set()
    betrayals = 0
    for rec in records:
        if rec.get("type") != "tick":
            continue
        for ev in rec["events"]:
            kind, actor = ev["kind"], ev.get("actor")
            counts[kind] += 1
            if kind in PARTNER_KINDS and actor:
                for other in ev.get("to") or []:
                    partners.add(tuple(sorted((actor, other))))
            if kind == "steal" and actor:
                victim = (ev.get("data") or {}).get("victim")
                if victim and tuple(sorted((actor, victim))) in partners:
                    betrayals += 1
    last = m["gini_by_day"][max(m["gini_by_day"])] if m["gini_by_day"] else {"gini_coins": 0, "total_coins": 0}
    t, d = m["thefts"], m["debts"]
    return {
        "thefts": t["attempts"], "thefts_ok": t["successful"], "thefts_unseen": t["successful_unseen"],
        "betrayals": betrayals, "trades": m["trades"]["count"], "gifts": counts["give"],
        "loans": d["count"], "defaults": d["defaulted"], "evictions": counts["evicted"],
        "hospital": counts["hospital"] + counts["death"], "orders": counts["order_done"],
        "gini": last["gini_coins"], "wealth": last["total_coins"],
        # Open hostility: theft attempts, broken loans, people thrown out or collapsing.
        "conflicts": t["attempts"] + d["defaulted"] + counts["evicted"],
    }


def mode_of(records: list[dict]) -> str:
    return records[0]["config"].get("economy_mode", "standard")


def table(stats_by_mode: dict[str, list[dict]]) -> str:
    head = "| Режим | " + " | ".join(t for _k, t in COLUMNS) + " |"
    out = [head, "|" + "---|" * (len(COLUMNS) + 1)]
    for mode in [m for m in MODES if m in stats_by_mode]:
        runs = stats_by_mode[mode]
        cells = []
        for key, _t in COLUMNS:
            vals = [r[key] for r in runs]
            if key in ("gini", "wealth"):
                v = sum(vals) / len(vals)
                cells.append(f"{v:.2f}" if key == "gini" else f"{v:.0f}")
            else:
                cells.append(str(sum(vals)))
        out.append(f"| {MODES[mode]['title']} | " + " | ".join(cells) + " |")
    return "\n".join(out)


def run_all(days: int, seeds: list[int], models: str | None, agents: int) -> list[Path]:
    brain = "llm" if models else "bots"
    logs = []
    for mode in MODES:
        for seed in seeds:
            log = ROOT / "runs" / "modes" / f"{brain}-{mode}-s{seed}.jsonl"
            log.parent.mkdir(parents=True, exist_ok=True)
            argv = ["--mode", mode, "--days", str(days), "--seed", str(seed), "--log", str(log)]
            argv += ["--models", models] if models else ["--bots", BOTS]
            if agents:
                argv += ["--agents", str(agents)]
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = run.main(argv)
            if rc:
                raise SystemExit(f"run failed: {mode} seed {seed}")
            cost = sum(float(line.split("cost=$")[1]) for line in buf.getvalue().splitlines() if "cost=$" in line)
            print(f"{mode:10} seed {seed}: ok" + (f", ${cost:.4f}" if models else ""), file=sys.stderr)
            logs.append(log)
    return logs


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Compare economy modes.")
    p.add_argument("--days", type=int, default=3)
    p.add_argument("--seeds", default="1,2,3")
    p.add_argument("--models", default=None, help="LLM model ids (as in run.py --models); default: bots " + BOTS)
    p.add_argument("--agents", type=int, default=5)
    p.add_argument("--logs", nargs="*", help="compare these logs instead of running")
    p.add_argument("--out", default=None, help="write the markdown table here")
    p.add_argument("--json", default=None, help="write per-log stats here")
    a = p.parse_args(argv)
    logs = [Path(x) for x in a.logs] if a.logs else run_all(a.days, [int(s) for s in a.seeds.split(",")],
                                                             a.models, a.agents)
    by_mode: dict[str, list[dict]] = defaultdict(list)
    per_log = {}
    for log in logs:
        recs = metrics.read_log(log)
        s = log_stats(recs)
        by_mode[mode_of(recs)].append(s)
        per_log[log.name] = s
    md = table(by_mode)
    print(md)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(md + "\n", encoding="utf-8")
    if a.json:
        Path(a.json).write_text(json.dumps(per_log, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
