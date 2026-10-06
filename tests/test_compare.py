"""Model comparison: seating by seed, rotation, brains + usage in the log, the per-model report, lie judge."""

import json
from collections import Counter

import pytest
import yaml

from aivillage import compare, engine, mapgen, roster, run, runconfig

NAMES = ["Anna", "Boris", "Clara", "Dmitri", "Elena", "Fedor", "Galina"]


def test_same_seed_same_seating_and_balanced():
    a = roster.assign(NAMES, ["m1", "m2", "m3"], seed=7)
    assert a == roster.assign(list(reversed(NAMES)), ["m1", "m2", "m3"], seed=7)  # input order does not matter
    assert sorted(Counter(a.values()).values()) == [2, 2, 3]
    assert any(roster.assign(NAMES, ["m1", "m2", "m3"], seed=s) != a for s in range(1, 6))


def test_rotations_put_every_model_in_every_seat():
    models = ["m1", "m2", "m3"]
    seen = {n: set() for n in NAMES}
    for k in range(len(models)):
        for n, m in roster.assign(NAMES, models, seed=3, rotate=k).items():
            seen[n].add(m)
    assert all(s == set(models) for s in seen.values())


def test_rotation_keeps_the_village():
    hashes = set()
    for k in range(3):
        rc = runconfig.parse({"seed": 5, "villagers": 6, "models": ["bot:worker", "bot:thief", "stub"], "rotate": k})
        hashes.add(engine.new_world(mapgen.for_run(rc.world_override())).hash())
    assert len(hashes) == 1


def test_runconfig_roster_and_own_brains():
    rc = runconfig.parse({"seed": 2, "models": ["stub", "bot:thief"],
                          "agents": [{"name": "Anna", "profession": "farmer", "bot": "worker"},
                                     {"name": "Boris", "profession": "fisher"}, {"name": "Clara", "profession": "smith"}]})
    b = rc.brains(["Anna", "Boris", "Clara"])
    assert b["Anna"] == ("bot", "worker")  # own brain wins over the roster
    assert {b["Boris"], b["Clara"]} == {("model", "stub"), ("bot", "thief")}
    with pytest.raises(runconfig.ConfigError, match="unknown bot"):
        runconfig.parse({"models": ["bot:nope"]})
    with pytest.raises(runconfig.ConfigError):
        runconfig.parse({"models": []})
    assert runconfig.parse({"models": "auto"}).models == "auto"


def _run(tmp_path, k, models=("stub", "bot:thief", "bot:worker")):
    spec = {"days": 2, "seed": 4, "villagers": 6, "models": list(models), "rotate": k,
            "log": str(tmp_path / f"r{k}.jsonl")}
    cfg = tmp_path / f"r{k}.yaml"
    cfg.write_text(yaml.safe_dump(spec))
    assert run.main(["--config", str(cfg)]) == 0
    return spec["log"]


def test_log_names_brains_and_usage(tmp_path):
    log = _run(tmp_path, 0)
    recs = [json.loads(line) for line in open(log)]
    header = recs[0]
    assert header["roster"] == ["stub", "bot:thief", "bot:worker"] and header["rotate"] == 0
    assert sorted(Counter(header["brains"].values()).values()) == [2, 2, 2]
    usage = [r for r in recs if r["type"] == "usage"]
    assert len(usage) >= 2  # after the night and at the end
    stubs = {n for n, b in header["brains"].items() if b == "stub"}
    assert set(usage[-1]["agents"]) == stubs and all(u["calls"] > 0 for u in usage[-1]["agents"].values())
    run.replay(log)  # extra records never break replay


def test_report_over_rotations(tmp_path):
    logs = [_run(tmp_path, k) for k in range(3)]
    rep = compare.compute(logs)
    assert set(rep["models"]) == {"stub", "bot:thief", "bot:worker"}
    assert rep["seeds"] == [4] and rep["wealth_exact"]
    for m in rep["models"].values():
        assert m["villagers"] == 6 and m["villager_days"] == 12
        assert 0 <= m["survival"] <= 1 and m["turns"] > 0
    thief = rep["models"]["bot:thief"]
    assert thief["actions"].get("steal", 0) > 0 and thief["thefts_tried"] == thief["actions"]["steal"]
    assert rep["models"]["bot:worker"]["thefts_tried"] == 0
    md = compare.to_markdown(rep)
    assert "## По моделям" in md and "bot:thief" in md and "не измерялась" in md


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
    rep = compare.compute([log], judge)
    rows = {v["name"]: v for v in rep["villagers"]}
    assert rows[names[0]]["lies"] > 0 and rows[names[1]]["lies"] == 0
    assert rows[names[1]]["judged"] > 0 and judge.calls >= 1
    assert "из" in compare.to_markdown(rep)


def test_auto_roster_picks_newest_cheap_per_company():
    now = 2_000_000_000
    day = 86400
    cat = [
        {"id": "google/old-cheap", "created": now - 30 * day, "pricing": {"prompt": "1e-7", "completion": "4e-7"}},
        {"id": "google/new-cheap", "created": now - 5 * day, "pricing": {"prompt": "2e-7", "completion": "8e-7"}},
        {"id": "google/new-pricey", "created": now - 1 * day, "pricing": {"prompt": "3e-6", "completion": "1e-5"}},
        {"id": "google/new-cheap:free", "created": now, "pricing": {"prompt": "0", "completion": "0"}},
        {"id": "anthropic/small", "created": now - 60 * day, "pricing": {"prompt": "1e-6", "completion": "5e-6"}},
        {"id": "anthropic/big", "created": now - 2 * day, "pricing": {"prompt": "3e-6", "completion": "1.5e-5"}},
        {"id": "deepseek/ancient", "created": now - 900 * day, "pricing": {"prompt": "1e-7", "completion": "2e-7"}},
        {"id": "qwen/embed-small", "created": now, "pricing": {"prompt": "1e-8", "completion": "1e-8"}},
    ]
    got = roster.pick(cat, now=now)
    assert got["google"]["id"] == "google/new-cheap"
    assert got["anthropic"]["id"] == "anthropic/small"  # no ultra-cheap Claude: its cheapest recent one
    assert "deepseek" not in got and "qwen" not in got
    r = roster.auto(catalog=cat, now=now)
    assert r[0] == "openai/gpt-6-luna" and r[1:] == ["anthropic/small", "google/new-cheap"]
    est = roster.estimate({"A": "google/new-cheap", "B": "bot:worker", "C": "x/unknown"}, 3,
                          roster.catalog_prices(cat))
    assert est["unknown"] == ["x/unknown"] and est["total"] == pytest.approx(3 * (25_000 * 0.2 + 1_000 * 0.8) / 1e6, rel=0.01)
