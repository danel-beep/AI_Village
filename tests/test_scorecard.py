"""End-of-run scorecard and reproducibility: brains + usage in the log, per-villager rows, per-model grouping,
lie judge, and the same seed giving the same village."""

import json
from pathlib import Path

import yaml

from aivillage import engine, mapgen, run, runconfig, scorecard


def _main(tmp_path, name, spec):
    cfg = tmp_path / f"{name}.yaml"
    cfg.write_text(yaml.safe_dump({"log": str(tmp_path / f"{name}.jsonl"), **spec}))
    assert run.main(["--config", str(cfg)]) == 0
    return tmp_path / f"{name}.jsonl"


def _recs(log):
    return [json.loads(line) for line in open(log)]


def test_same_seed_same_village_and_run(tmp_path):
    def village(seed):
        rc = runconfig.parse({"seed": seed, "villagers": 8, "characters": "random", "world": {"map": {"unfairness": 0.8}}})
        return engine.new_world(mapgen.for_run(rc.world_override()))
    a, b = village(11), village(11)
    assert a.hash() == b.hash() and a.config["map"]["layout"] == b.config["map"]["layout"]
    assert [x.get("character") for x in a.config["agents"]] == [x.get("character") for x in b.config["agents"]]
    assert village(12).hash() != a.hash()
    spec = {"days": 2, "seed": 11, "villagers": 8, "bot": "random"}
    h1 = [r["hash"] for r in _recs(_main(tmp_path, "one", spec)) if r["type"] == "tick"]
    h2 = [r["hash"] for r in _recs(_main(tmp_path, "two", spec)) if r["type"] == "tick"]
    assert h1 == h2


def test_log_names_brains_and_usage(tmp_path):
    log = _main(tmp_path, "mix", {"days": 2, "seed": 4, "model": "stub",
                                  "agents": [{"name": "Anna", "profession": "farmer", "bot": "thief"},
                                             {"name": "Boris", "profession": "fisher"},
                                             {"name": "Clara", "profession": "woodcutter"}]})
    recs = _recs(log)
    assert recs[0]["brains"] == {"Anna": "bot:thief", "Boris": "stub", "Clara": "stub"}
    usage = [r for r in recs if r["type"] == "usage"]
    assert len(usage) >= 2  # after the night and at the end
    assert set(usage[-1]["agents"]) == {"Boris", "Clara"} and usage[-1]["agents"]["Boris"]["calls"] > 0
    run.replay(log)  # extra records never break replay
    assert Path(f"{tmp_path / 'mix'}.scorecard.md").exists()  # written at the end of the run


def test_scorecard_rows_and_grouping(tmp_path):
    logs = [_main(tmp_path, f"s{seed}", {"mode": "crafts", "days": 3, "seed": seed, "villagers": 6, "bot": "thief",
                                         "agents": [{"name": "Anna", "profession": "farmer", "bot": "worker"}]})
            for seed in (2, 3)]
    rep = scorecard.compute(logs)
    assert rep["seeds"] == [2, 3] and rep["wealth_exact"] and len(rep["villagers"]) == 12
    thief = rep["models"]["bot:thief"]
    assert thief["villagers"] == 10 and thief["villager_days"] == 30
    acts = thief["actions"]
    # a theft decision that turned out invalid when it ran (the yard was emptied meanwhile) is not an attempt
    refused = sum(1 for log in logs for r in _recs(log) if r["type"] == "tick" for e in r["events"]
                  if e["kind"] == "error" and e.get("actor") != "Anna"
                  and (e.get("data") or {}).get("action", {}).get("name") in ("steal", "steal_from_plot"))
    assert acts.get("steal", 0) > 0
    assert thief["thefts_tried"] == acts["steal"] + acts.get("steal_from_plot", 0) - refused
    assert rep["models"]["bot:worker"]["thefts_tried"] == 0
    for v in rep["villagers"]:
        assert v["wealth_start"] is not None and v["turns"] > 0 and v["profession"]
    md = scorecard.to_markdown(rep)
    assert "## По жителям" in md and "## По моделям" in md and "bot:thief" in md
    one = scorecard.write(logs[0])
    assert one.name == "s2.scorecard.md" and "# Итоги прогона" in one.read_text()
    assert json.loads(Path(str(one).replace(".md", ".json")).read_text())["runs"][0]["seed"] == 2


class FakeJudge:
    model = "judge"

    def __init__(self):
        self.calls = 0

    def complete(self, messages):
        self.calls += 1
        lies = [i + 1 for i, line in enumerate(l for l in messages[1]["content"].splitlines() if "THOUGHT:" in l)
                if "lie" in line]
        return json.dumps({"lies": lies}), {}


def test_lie_judge(tmp_path):
    log = tmp_path / "talk.jsonl"
    w = engine.new_world({"seed": 1})
    names = sorted(w.agents)[:2]
    decisions = {names[0]: {"thought": "I will lie: I have bread", "action": {"name": "wait"}, "say": "I have no bread"},
                 names[1]: {"thought": "be nice", "action": {"name": "say", "args": {"text": "Hello"}}}}
    run.run(w, lambda n, o: decisions.get(n, {"action": {"name": "wait"}}), days=1, log_path=log)
    judge = FakeJudge()
    rep = scorecard.compute([log], judge)
    rows = {v["name"]: v for v in rep["villagers"]}
    assert rows[names[0]]["lies"] > 0 and rows[names[1]]["lies"] == 0
    assert rows[names[1]]["judged"] > 0 and judge.calls >= 1
    assert " из " in scorecard.to_markdown(rep)


def test_lost_turns_backups_and_fairness_notes(tmp_path):
    """Fairness audit: turns a model never played are not its actions, backup answers and fixed seats are flagged."""
    log = _main(tmp_path, "fair", {"days": 1, "seed": 4, "model": "stub",
                                   "agents": [{"name": "Anna", "profession": "farmer", "model": "stub"},
                                              {"name": "Boris", "profession": "fisher", "bot": "worker"},
                                              {"name": "Clara", "profession": "woodcutter", "model": "stub"}]})
    recs = _recs(log)
    ticks = [r for r in recs if r["type"] == "tick" and "Anna" in r["decisions"]]
    ticks[0]["decisions"]["Anna"] = {"thought": "(model error: boom)", "action": {"name": "wait"}}
    ticks[1]["decisions"]["Anna"] = {"thought": "(unparseable reply)", "action": {"name": "wait"}, "parse_error": "x"}
    usage = [r for r in recs if r["type"] == "usage"][-1]["agents"]
    usage["Clara"]["by_model"] = {"stub": 5, "stub-2026-01-01": 2, "backup/model": 3}
    Path(log).write_text("".join(json.dumps(r) + "\n" for r in recs))
    rows = scorecard.villagers(scorecard.read(log))
    assert rows["Anna"]["lost"] == 2 and rows["Anna"]["turns"] == len(ticks) - 2
    assert sum(rows["Anna"]["actions"].values()) == rows["Anna"]["turns"]
    assert rows["Clara"]["other_model_calls"] == 3  # a dated name of the same model is not a backup
    md = scorecard.to_markdown(scorecard.compute([log]))
    assert "Мало прогонов" in md and "одних и тех же жителей" in md and "ответила запасная модель" in md
