"""Experiment lab: play one scenario as several arms and replicates, and compare them by counted behaviour.

An experiment is a scenario (aivillage/scenario.py, scenarios/*.yaml) with any of:

- `arms`: variants that change one thing (a villager's character, model or memory, the world, a config knob).
  The scenario as written is arm "A"; when there are arms, an unedited copy "AA" is played too, so the report can
  show how far two identical arms drift apart by chance (the A/A spread) next to each real difference;
- `play.replicates`: how many times every arm is played (LLM villagers answer differently every time);
- `play.seating`: models on seats for a fair model comparison. The AI villagers are split into equal groups by a
  seeded order, one model per group; each next replicate moves every group to the next model, so with two models
  replicate 2 has the seats of replicate 1 mirrored (fairness audit: 3 on 3, models swap seats);
- `play.reseed`: every replicate (every mirrored set, with seating) gets the next world seed;
- `from_save`: start every run from a save (the same world, the same shocks on every tick: crises, threats and
  illness come from named random streams of the world's seed), with the villagers' memory as saved.

Each run is its own log `<out>/<name>_<arm>_r<k>.jsonl` (header: the starting world after the edits, `fork`: arm,
edits, replicate, seed, seats, save). Logs replay like any other. `<out>/lab.md` and `lab.json` compare the arms
(aivillage/social_metrics.py: lies about food, promises kept, gifts and votes, grudges, reports of theft,
embezzlement, replies and long talks, trades, gifts) and, with seating, the models within each arm.

    python -m aivillage.lab run mirror_luna_haiku --out runs/lab-1          # needs an OpenRouter key
    python -m aivillage.lab run mirror_luna_haiku --model stub --days 1     # the whole pipeline, offline
    python -m aivillage.lab report runs/lab-1                              # rebuild lab.md from the logs
The app's start screen plays experiments too (the «🧪 Сценарии» block, button «🔬 Опыт»).
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Callable

from . import runconfig, scenario as S, scorecard, social_metrics as SM

CONTROL = "AA"


class LabStopped(Exception):
    """Raised by `on_progress` to stop the experiment between runs."""


def arms_of(scn: S.Scenario) -> list[S.Arm]:
    """A (the scenario as written), AA (its unedited copy, only when there are arms), then the scenario's arms."""
    names = [a.name for a in scn.arms]
    if {"A", CONTROL} & set(names) or len(set(names)) != len(names):
        raise S.ScenarioError(f"arms: names must be unique and not A or {CONTROL} (those are the control arms)")
    base = [S.Arm(name="A", about="как в сценарии")]
    if scn.arms:
        base.append(S.Arm(name=CONTROL, about="копия A без изменений (контроль)"))
    return base + list(scn.arms)


def base_seed(scn: S.Scenario, snap: dict | None) -> int:
    if snap is not None:
        return int(snap["world"]["config"]["seed"])
    try:
        return runconfig.parse({**scn.config, "days": 1}, "config").seed
    except runconfig.ConfigError as e:
        raise S.ScenarioError(str(e)) from None


def seats(names: list[str], models: list[str], seed: int, replicate: int, rotate: bool = True) -> dict[str, str]:
    """{villager: model}: villagers in seeded order split into len(models) equal groups; replicate k shifts every
    group k models on (with two models: odd replicates mirror the even ones)."""
    from .run import seat_order
    order = seat_order(names, seed)
    shift = replicate if rotate else 0
    return {n: models[(i * len(models) // len(order) + shift) % len(models)] for i, n in enumerate(order)}


def plan(scn: S.Scenario, *, replicates: int | None = None, models: list[str] | None = None,
         snap: dict | None = None) -> list[dict]:
    """Every run in playing order: replicate by replicate, all arms of a replicate together, so an experiment
    stopped early (cost cap) still has balanced arms."""
    reps = replicates or scn.play.replicates
    seating = scn.play.seating
    models = models or (seating.models if seating else None)
    if models and len(models) < 2:
        raise S.ScenarioError("seating: at least two models")
    if models and (seating is None or seating.rotate) and reps % len(models):
        raise S.ScenarioError(f"seating: replicates must be a multiple of the number of models ({len(models)}), "
                              "so every model sits on every seat equally often")
    seed0 = base_seed(scn, snap)
    per_seed = len(models) if models and (seating is None or seating.rotate) else 1
    out = []
    for k in range(reps):
        seed = seed0 + k // per_seed if scn.play.reseed else seed0
        for arm in arms_of(scn):
            out.append({"arm": arm, "replicate": k + 1, "seed": seed, "models": models,
                        "rotate": seating.rotate if seating else True})
    return out


def _cost(log: Path) -> float:
    from .run import read_log
    cost = 0.0
    for r in read_log(log):
        if r.get("type") == "usage":
            cost = sum(a.get("cost_usd", 0) for a in r["agents"].values())
    return round(cost, 4)


def run_lab(name: str, *, out: str | Path, model: str | None = None, ai: list[str] | None = None,
            days: int | None = None, max_cost: float | None = None, max_total: float = 0.0,
            replicates: int | None = None, models: list[str] | None = None, from_save: str | None = None,
            folder: str | Path | None = None,
            on_progress: Callable[[dict], None] | None = None) -> dict:
    """Play every arm and replicate, then write the comparison. `model`: one model for every AI villager
    (e.g. "stub"; it replaces the seating models too), `models`: other seating models, `max_cost`: USD per run,
    `max_total`: USD for the whole experiment (0 = none; checked between runs). `on_progress(info)` is told
    before and after every run and may raise LabStopped."""
    from .run import run
    scn = S.load(name, folder)
    if from_save:
        scn = scn.model_copy(update={"from_save": from_save})
    snap = S.read_save(scn.from_save) if scn.from_save else None
    stem = Path(name).stem
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    runs = plan(scn, replicates=replicates, models=models, snap=snap)
    god = {}
    for tick, ev in (snap or {}).get("god_pending") or []:
        god.setdefault(tick, []).append(ev)
    cap = scn.play.max_cost if max_cost is None else max_cost
    done, total, stopped = [], 0.0, None
    for i, r in enumerate(runs):
        arm = r["arm"]
        info = {"index": i + 1, "of": len(runs), "arm": arm.name, "replicate": r["replicate"], "spent": total}
        if max_total and total >= max_total:
            stopped = f"бюджет опыта ${max_total:g} исчерпан"
            break
        try:
            if on_progress:
                on_progress({**info, "state": "start"})
        except LabStopped as e:
            stopped = str(e) or "остановлено"
            break
        world = S.start_world(scn, seed=r["seed"], snap=snap)
        S.edit(world, arm)
        names = S.ai_names(world, scn, ai=ai, snap=snap, arm=arm)
        placed = seats(names, r["models"], r["seed"], r["replicate"] - 1, r["rotate"]) if r["models"] else {}
        decide, on_night = S.brains(world, scn, ai=ai, model=model, snap=snap, arm=arm,
                                    seats={n: model for n in placed} if model else placed)
        log = out / f"{stem}_{arm.name}_r{r['replicate']}.jsonl"
        meta = {**S.header_meta(world, stem, scn),
                "fork": {"arm": arm.name, "about": arm.about, "edits": arm.model_dump(exclude_unset=True),
                         "replicate": r["replicate"], "seed": r["seed"], "seats": placed,
                         **({"model_override": model} if model else {}),
                         "save": (snap or {}).get("source"), "save_sha": (snap or {}).get("sha"),
                         "save_day": (snap or {}).get("day")}}
        run(world, decide, days or scn.play.days, god, log, on_night=on_night, max_cost=cap, meta=meta)
        cost = _cost(log)
        total += cost
        done.append(str(log))
        if on_progress:
            on_progress({**info, "state": "done", "log": str(log), "cost": cost, "spent": total})
    rep = compare(done)
    rep.update(name=stem, title=scn.title, about=scn.about, stopped=stopped, planned=len(runs), cost=round(total, 4))
    write(out, rep)
    return rep


# --- comparing ---

def _stats(xs: list[float | None]) -> dict:
    v = [x for x in xs if x is not None]
    return {"values": xs, "n": len(v), "mean": round(statistics.fmean(v), 3) if v else None,
            "sd": round(statistics.stdev(v), 3) if len(v) > 1 else None}


def _verdict(diff: float | None, noise: float | None) -> str:
    if diff is None:
        return "нет данных"
    if noise is None:
        return "мало повторов"
    if abs(diff) > 2 * noise and abs(diff) > 1e-9:
        return "заметно"
    return "в пределах шума"


def compare(logs: list[str]) -> dict:
    """Arms and models from the logs of one experiment (`fork` in their headers)."""
    from . import knobs, modes
    from .registry import ACTIONS
    from .run import hidden_actions, read_log
    runs, per_arm, use = [], {}, {}
    for p in logs:
        recs = list(read_log(p))
        head = recs[0]
        fork = head.get("fork") or {"arm": "A", "replicate": 1}
        sm = SM.compute(recs)
        last = next((r.get("view") for r in reversed(recs) if r.get("type") == "tick"), None) or {}
        alive = [s.get("status") != "dead" for s in (last.get("agents") or {}).values()]
        vals = {**SM.summary(sm), "survival": round(sum(alive) / len(alive), 3) if alive else None}
        ai = set(fork.get("seats") or {}) or {n for n, b in (head.get("brains") or {}).items()
                                               if not str(b).startswith("bot:")}
        acts, answered = use.setdefault(fork["arm"], {"turns": Counter(), "offered": set()}), Counter()
        acts["offered"] |= set(ACTIONS.specs) - hidden_actions(head.get("config") or {})
        for r in recs:
            for n, d in ((r.get("decisions") or {}).items() if r.get("type") == "tick" else ()):
                if n in ai and isinstance(d, dict):
                    act = d.get("action") if isinstance(d.get("action"), dict) else {}
                    acts["turns"][str(act.get("name") or "none")] += 1
                    if (d.get("call") or {}).get("model"):
                        answered[d["call"]["model"]] += 1
        runs.append({"log": p, "arm": fork["arm"], "replicate": fork.get("replicate"), "seed": fork.get("seed"),
                     "code": head.get("code"), "answered": dict(answered),
                     "override": fork.get("model_override"), "preset": modes.title(head.get("config") or {}),
                     "knobs": knobs.changed(head),
                     "seats": fork.get("seats") or {}, "brains": head.get("brains") or {}, "values": vals,
                     "social": sm})
        per_arm.setdefault(fork["arm"], []).append(runs[-1])
    keys = [k for k, _t, _kind in SM.METRICS] + ["survival"]
    arms = {}
    for arm, rs in per_arm.items():
        arms[arm] = {k: _stats([r["values"][k] for r in rs]) for k in keys}
    control = [r for r in runs if r["arm"] in ("A", CONTROL)]
    noise = {k: _stats([r["values"][k] for r in control])["sd"] for k in keys}
    effects = {}
    for arm in arms:
        if arm in ("A", CONTROL) or "A" not in arms:
            continue
        effects[arm] = {}
        for k in keys:
            a, x = arms["A"][k]["mean"], arms[arm][k]["mean"]
            diff = round(x - a, 3) if a is not None and x is not None else None
            effects[arm][k] = {"diff": diff, "noise": noise[k], "verdict": _verdict(diff, noise[k])}
    aa = {}
    if CONTROL in arms and "A" in arms:
        for k in keys:
            a, b = arms["A"][k]["mean"], arms[CONTROL][k]["mean"]
            aa[k] = round(b - a, 3) if a is not None and b is not None else None
    sensitive = [k for k in keys if noise[k] is not None and (arms.get("A") or {}).get(k, {}).get("mean")
                 and arms["A"][k]["mean"] > 2 * noise[k]]
    models = models_by_arm(runs)
    actions = {arm: {"turns": sum(u["turns"].values()), "used": dict(u["turns"].most_common()),
                     "never": sorted(u["offered"] - set(u["turns"]))} for arm, u in use.items()}
    return {"runs": [{k: v for k, v in r.items() if k not in ("social", "by")} for r in runs], "arms": arms,
            "effects": effects, "aa_diff": aa, "noise": noise, "sensitive": sensitive,
            "models": models, "actions": actions}


def models_by_arm(runs: list[dict]) -> dict:
    """{arm: {model: {metric: pooled value, "range": [min, max] over replicates}, plus scorecard basics}} when
    villagers of one run played on different models. Models are the seats the lab gave (a run with `--model stub`
    keeps them, so the offline check fills the same table), else the brains in the log header."""
    out = {}
    per_arm: dict[str, list[dict]] = {}
    for r in runs:
        per_arm.setdefault(r["arm"], []).append(r)
    kinds = {k: kind for k, _t, kind in SM.METRICS}
    for arm, rs in per_arm.items():
        for r in rs:
            r["by"] = r["seats"] or {n: b for n, b in r["brains"].items() if not str(b).startswith("bot:")}
        models = sorted({m for r in rs for m in r["by"].values()})
        if len(models) < 2:
            continue
        table = {}
        for m in models:
            row = {}
            for k in SM.PER_VILLAGER:
                num = den = 0
                each = []
                for r in rs:
                    who = [n for n, b in r["by"].items() if b == m]
                    cells = [r["social"]["villagers"].get(n, {}).get(k) for n in who]
                    n1 = sum(c["num"] for c in cells if c)
                    d1 = sum(c["den"] for c in cells if c)
                    num, den = num + n1, den + d1
                    if d1:
                        each.append(n1 / d1)
                row[k] = {"value": round(num / den, 3) if den else None, "n": den, "kind": kinds[k],
                          "range": [round(min(each), 3), round(max(each), 3)] if each else None}
            table[m] = row
        by_log = {r["log"]: r["by"] for r in rs}
        rows = [{**v, "model": by_log[v["log"]].get(v["name"], v["model"]), "actions": Counter(v["actions"])}
                for v in scorecard.compute(list(by_log))["villagers"]]
        sc = scorecard.by_model(rows)
        for m in models:
            s = sc.get(m) or {}
            table[m]["basics"] = {k: s.get(k) for k in ("villagers", "survival", "wealth_delta_avg", "invalid_share",
                                                        "cost_per_villager_day")}
        out[arm] = table
    return out


# --- report ---

def _fmt(x, kind: str = "value") -> str:
    if x is None:
        return "—"
    return f"{x * 100:.0f}%" if kind == "share" else f"{x:g}"


def markdown(rep: dict) -> str:
    kinds = {k: kind for k, _t, kind in SM.METRICS} | {"survival": "share"}
    titles = {k: t for k, t, _kind in SM.METRICS} | {"survival": "Выжили"}
    keys = list(titles)
    arms = list(rep["arms"])
    lines = [f"# {rep.get('title') or rep.get('name', '')}", ""]
    if rep.get("about"):
        lines += [rep["about"], ""]
    n = len(rep["runs"])
    lines.append(f"Прогонов: {n}" + (f" из {rep['planned']}" if rep.get("planned") and rep["planned"] != n else "")
                 + f", стоимость ИИ ${rep.get('cost', 0):g}." + (f" Остановлено: {rep['stopped']}." if rep.get("stopped")
                                                                  else ""))
    if any(r.get("override") for r in rep["runs"]):
        lines.append(f"Проверка без ИИ: вместо моделей играла заглушка «{rep['runs'][0]['override']}».")
    lines += ["", "## Ветки (среднее ± разброс по повторам)", "",
              "| Что считаем | " + " | ".join(arms) + " |", "|---|" + "---|" * len(arms)]
    for k in keys:
        cells = []
        for a in arms:
            s = rep["arms"][a][k]
            m = _fmt(s["mean"], kinds[k])
            cells.append(m + (f" ± {_fmt(s['sd'], kinds[k])}" if s["sd"] is not None else ""))
        lines.append(f"| {titles[k]} | " + " | ".join(cells) + " |")
    if rep["effects"]:
        lines += ["", "## Что изменилось против A", "",
                  "Шум = разброс между одинаковыми ветками (A и AA). «Заметно» = разница больше двух шумов.", ""]
        for arm, eff in rep["effects"].items():
            hits = [f"{titles[k]}: {'+' if e['diff'] > 0 else ''}{_fmt(e['diff'], kinds[k])}"
                    for k, e in eff.items() if e["verdict"] == "заметно"]
            lines.append(f"- **{arm}**: " + ("; ".join(hits) if hits else "заметных отличий нет"))
    if rep.get("aa_diff"):
        lines += ["", f"Чувствительность: двукратную разницу видно по {len(rep['sensitive'])} из {len(keys)} "
                      f"показателей ({', '.join(titles[k] for k in rep['sensitive']) or 'ни по одному'})."]
    for arm, table in rep["models"].items():
        ms = list(table)
        lines += ["", f"## Модели в ветке {arm} (все места и повторы вместе; в скобках разброс по повторам)", "",
                  "| | " + " | ".join(ms) + " |", "|---|" + "---|" * len(ms)]
        for k, title in (("survival", "Выжили"), ("wealth_delta_avg", "Прирост богатства на жителя"),
                         ("invalid_share", "Ошибочных ходов"), ("cost_per_villager_day", "$ на жителя в день")):
            kind = "share" if k in ("survival", "invalid_share") else "value"
            lines.append(f"| {title} | " + " | ".join(_fmt(table[m]["basics"].get(k), kind) for m in ms) + " |")
        for k in SM.PER_VILLAGER:
            cells = []
            for m in ms:
                c = table[m][k]
                rng = c["range"]
                cells.append(_fmt(c["value"], c["kind"]) + (f" ({_fmt(rng[0], c['kind'])}–{_fmt(rng[1], c['kind'])})"
                                                             if rng and rng[0] != rng[1] else ""))
            lines.append(f"| {titles[k]} | " + " | ".join(cells) + " |")
    for arm, a in (rep.get("actions") or {}).items():
        if not a["turns"]:
            continue
        lines += ["", f"## Какие действия выбирали ИИ-жители, ветка {arm}", "",
                  f"Ходов: {a['turns']}. Выбрано {len(a['used'])} разных действий"
                  f" из {len(a['used']) + len(a['never'])} доступных.", "", "| Действие | Раз | Доля ходов |", "|---|---|---|"]
        lines += [f"| {k} | {n} | {_fmt(n / a['turns'], 'share')} |" for k, n in a["used"].items()]
        if a["never"]:
            lines += ["", "Ни разу: " + ", ".join(a["never"]) + "."]
    codes = {(r.get("code") or {}).get("source") for r in rep["runs"]}
    if len(codes) > 1:
        lines += ["", f"Внимание: прогоны сыграны разными версиями кода ({len(codes)}), сравнение веток может врать."]
    lines += ["", "## Прогоны", ""]
    for r in rep["runs"]:
        seats = ", ".join(f"{n}: {m.split('/')[-1]}" for n, m in sorted(r["seats"].items()))
        code = (r.get("code") or {})
        ver = (code.get("commit") or "")[:7] or code.get("source") or ""
        answered = ", ".join(f"{m.split('/')[-1]} {n}" for m, n in sorted((r.get("answered") or {}).items()))
        preset = f", пресет «{r['preset']}»" if r.get("preset") else ""
        changed = ", ".join(f"{k}={v}" for k, v in (r.get("knobs") or {}).items())
        lines.append(f"- {r['arm']} r{r['replicate']} (сид {r['seed']}{preset}){': ' + seats if seats else ''}: "
                     f"`{Path(r['log']).name}`" + (f"; код {ver}" if ver else "")
                     + (f"; ручки не как в пресете: {changed}" if changed else "")
                     + (f"; фактически ответили: {answered}" if answered else ""))
    return "\n".join(lines) + "\n"


def write(out: str | Path, rep: dict) -> Path:
    out = Path(out)
    (out / "lab.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    md = out / "lab.md"
    md.write_text(markdown(rep), encoding="utf-8")
    return md


def report(out: str | Path) -> dict:
    """Rebuild the comparison from the logs in a lab folder."""
    out = Path(out)
    logs = sorted(str(p) for p in out.glob("*_r*.jsonl"))
    old = json.loads((out / "lab.json").read_text(encoding="utf-8")) if (out / "lab.json").is_file() else {}
    rep = {**compare(logs), **{k: old[k] for k in ("name", "title", "about", "stopped", "planned", "cost") if k in old}}
    write(out, rep)
    return rep


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Play a scenario's arms and replicates and compare them.")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="play an experiment")
    r.add_argument("name", help="scenario name (scenarios/<name>.yaml) or a path to a .yaml")
    r.add_argument("--out", default=None, help="folder for the logs and lab.md (default runs/lab-<name>)")
    r.add_argument("--model", default=None, help="one model for every AI villager ('stub' = offline)")
    r.add_argument("--models", default=None, help="comma-separated seating models (replace play.seating.models)")
    r.add_argument("--ai", default=None, help="comma-separated AI villagers")
    r.add_argument("--days", type=int, default=None)
    r.add_argument("--replicates", type=int, default=None)
    r.add_argument("--from-save", default=None, help="a .save.json or a zip with one")
    r.add_argument("--max-cost", type=float, default=None, help="USD per run")
    r.add_argument("--max-total", type=float, default=0.0, help="USD for the whole experiment")
    c = sub.add_parser("report", help="rebuild lab.md from a lab folder")
    c.add_argument("out")
    a = p.parse_args(argv)
    try:
        if a.cmd == "report":
            rep = report(a.out)
        else:
            out = a.out or f"runs/lab-{Path(a.name).stem}"
            rep = run_lab(a.name, out=out, model=a.model, ai=a.ai.split(",") if a.ai else None, days=a.days,
                          max_cost=a.max_cost, max_total=a.max_total, replicates=a.replicates,
                          models=a.models.split(",") if a.models else None, from_save=a.from_save,
                          on_progress=lambda i: print(f"[{i['index']}/{i['of']}] {i['arm']} r{i['replicate']} "
                                                      f"{i['state']}" + (f" ${i['cost']}" if "cost" in i else ""),
                                                      flush=True))
            print(f"report: {Path(out) / 'lab.md'}")
    except S.ScenarioError as e:
        print(e, file=sys.stderr)
        return 2
    print(markdown(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
