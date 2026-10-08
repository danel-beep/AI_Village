"""Experiment lab (aivillage/lab.py): arms, replicates, mirrored seating, forks from a save, counted behaviour."""

import json
import time
from collections import Counter
from pathlib import Path

import pytest

from aivillage import engine, lab, saves, scenario as S, social_metrics as SM
from aivillage.run import bots_decider, llm_agents, read_log, replay, run

LUNA, HAIKU = "openai/gpt-6-luna", "anthropic/claude-haiku-5.5"


def test_seats_split_in_halves_and_mirror_on_the_next_replicate():
    names = ["Anna", "Boris", "Clara", "Dmitri", "Elena", "Emil"]
    first = lab.seats(names, [LUNA, HAIKU], seed=3, replicate=0)
    second = lab.seats(names, [LUNA, HAIKU], seed=3, replicate=1)
    assert Counter(first.values()) == {LUNA: 3, HAIKU: 3}
    assert all(first[n] != second[n] for n in names)  # every seat changed model
    assert lab.seats(names, [LUNA, HAIKU], seed=3, replicate=1, rotate=False) == first
    assert lab.seats(names, [LUNA, HAIKU], seed=4, replicate=0) != first  # another seed, another split


def test_plan_pairs_mirrored_runs_on_one_seed():
    scn = S.load("mirror_luna_haiku")
    runs = lab.plan(scn, replicates=4)
    assert [(r["arm"].name, r["replicate"], r["seed"]) for r in runs] == [("A", 1, 11), ("A", 2, 11), ("A", 3, 12),
                                                                         ("A", 4, 12)]
    with pytest.raises(S.ScenarioError, match="multiple"):
        lab.plan(scn, replicates=3)
    arms = [a.name for a in lab.arms_of(S.load("fork_memory"))]
    assert arms == ["A", "AA", "B"]
    with pytest.raises(S.ScenarioError, match="control"):
        lab.arms_of(S.parse({"title": "t", "arms": [{"name": "AA"}]}))


def test_mirrored_stub_runs_fill_the_model_table(tmp_path):
    rep = lab.run_lab("mirror_luna_haiku", out=tmp_path, model="stub", days=1)
    logs = sorted(tmp_path.glob("mirror_luna_haiku_A_r*.jsonl"))
    assert len(logs) == 2 and (tmp_path / "lab.md").is_file() and (tmp_path / "lab.json").is_file()
    s1, s2 = (next(read_log(p))["fork"]["seats"] for p in logs)
    assert set(s1) == set(s2) and all(s1[n] != s2[n] for n in s1)
    for p in logs:
        ticks = [r for r in read_log(p) if r.get("type") == "tick"]
        assert replay(p).hash() == ticks[-1]["hash"]
    table = rep["models"]["A"]
    assert set(table) == {LUNA, HAIKU} and table[LUNA]["basics"]["villagers"] == 6
    assert "Проверка без ИИ" in (tmp_path / "lab.md").read_text(encoding="utf-8")


def _save(tmp_path) -> Path:
    """A village of 5 (Anna and Boris on the stub model, the rest bots) saved at the start of day 2."""
    world = engine.new_world({"seed": 9})
    agents = llm_agents(world, {"Anna": "stub", "Boris": "stub"})
    bots = {n: b for n, b in bots_decider(world, ["worker"], 9).bots.items() if n not in agents}

    def decide(name, obs):
        return agents[name].decide(obs) if name in agents else bots[name].decide(obs)
    decide.agents, decide.bots = agents, bots
    log = tmp_path / "parent.jsonl"
    run(world, decide, 1, log_path=log)
    agents["Anna"].notes = "Boris owes me 3 fish."
    saves.write(log, saves.snapshot(world, decide, log_path=log, end_day=world.day + 5))
    return saves.path_for(log)


def test_fork_from_a_save(tmp_path):
    save = _save(tmp_path)
    snap = saves.read(save)
    (tmp_path / "fork.yaml").write_text(json.dumps({
        "title": "fork", "from_save": str(save), "play": {"days": 1},
        "arms": [{"name": "B", "villagers": {"Boris": {"character": "Grumpy and stingy."},
                                             "Clara": {"model": "stub"}, "Anna": {"model": "bot:worker"}}}]}),
        encoding="utf-8")
    rep = lab.run_lab(str(tmp_path / "fork.yaml"), out=tmp_path / "lab")
    heads = {p.stem.split("_")[1]: next(read_log(p)) for p in (tmp_path / "lab").glob("*.jsonl")}
    assert set(heads) == {"A", "AA", "B"}
    for arm in ("A", "AA"):  # unedited arms start exactly at the save
        assert heads[arm]["hash"] == snap["hash"] and heads[arm]["fork"]["save_sha"]
        assert heads[arm]["brains"]["Anna"] == "stub" and heads[arm]["brains"]["Clara"].startswith("bot:")
    b = heads["B"]
    assert b["brains"]["Anna"] == "bot:worker" and b["brains"]["Clara"] == "stub" and b["brains"]["Boris"] == "stub"
    assert next(a for a in b["config"]["agents"] if a["name"] == "Boris")["character"] == "Grumpy and stingy."
    assert b["fork"]["edits"]["villagers"]["Boris"] == {"character": "Grumpy and stingy."}
    for p in (tmp_path / "lab").glob("*.jsonl"):
        ticks = [r for r in read_log(p) if r.get("type") == "tick"]
        assert replay(p).hash() == ticks[-1]["hash"]
    assert set(rep["effects"]) == {"B"} and rep["cost"] == 0
    assert save.is_file() and Path(tmp_path / "parent.jsonl").is_file()  # the parent is never cut


def test_fork_keeps_memory_and_counts_cost_from_zero(tmp_path):
    save = _save(tmp_path)
    snap = saves.read(save)
    scn = S.parse({"title": "f", "from_save": str(save)})
    world = S.start_world(scn, snap=snap)
    decide, _ = S.brains(world, scn, snap=snap, seats={"Anna": "stub", "Boris": "stub"})
    assert decide.agents["Anna"].notes == "Boris owes me 3 fish."
    assert all(ag.usage.calls == 0 for ag in decide.agents.values())


def _tick(t, day, events, decisions=None, agents=None):
    view = {"day": day, "hour": 10, "agents": agents or {}, "chests": {}}
    return {"type": "tick", "tick": t, "asked": [], "decisions": decisions or {}, "god": [], "events": events,
            "hash": "x", "view": view}


def _ev(t, day, kind, actor, to=None, text="", **data):
    return {"tick": t, "day": day, "hour": 10, "kind": kind, "actor": actor, "to": to or [], "text": text,
            "location": "square", "data": data}


def test_social_metrics_on_a_synthetic_log():
    cfg = {"agents": [{"name": n} for n in ("Anna", "Boris", "Clara")],
           "items": {"fish": {"value": 3, "food": 15}, "wood": {"value": 1}}}
    here = {"location": "square", "status": "active", "coins": 0}
    a0 = {"Anna": {**here, "inventory": {"fish": 2}}, "Boris": {**here, "inventory": {}},
          "Clara": {**here, "inventory": {}}}
    recs = [{"type": "header", "config": cfg, "start": {"day": 1, "agents": {n: {"inventory": s["inventory"],
                                                                                 "location": "square"}
                                                                             for n, s in a0.items()}}},
            _tick(1, 1, [_ev(1, 1, "say", "Anna", text='Anna says: "I have no food, Boris"',
                             text_raw="I have no food, Boris"),
                         _ev(1, 1, "say", "Boris", text='Boris says: "No food here either"',
                             text_raw="No food here either")], agents=a0),
            _tick(2, 1, [_ev(2, 1, "whisper", "Boris", ["Anna"], text_raw="Anna, want wood?"),
                         _ev(2, 1, "whisper", "Boris", ["Boris"], text_raw="Anna, want wood?")], agents=a0),
            _tick(3, 1, [_ev(3, 1, "whisper", "Anna", ["Boris"], text_raw="Yes Boris"),
                         _ev(3, 1, "give", "Clara", ["Anna"], text="Clara gave 1 fish to Anna.")],
                  decisions={"Clara": {"action": {"name": "give", "args": {"to": "Anna", "items": {"fish": 1}}}}},
                  agents=a0),
            _tick(4, 2, [_ev(4, 2, "vote", "Anna", ["Anna"], text="You voted for Clara for mayor (secret ballot).")],
                  agents=a0)]
    rep = SM.compute(recs)
    v = SM.summary(rep)
    assert rep["villagers"]["Anna"]["possession_lies"] == {"num": 1, "den": 1}  # had fish, said no food
    assert rep["villagers"]["Boris"]["possession_lies"] == {"num": 0, "den": 1}
    assert v["possession_lies"] == 0.5 and v["gift_vote"] == 1.0 and v["vote_hhi"] == 1.0
    # Anna named Boris aloud (he whispered back the next tick), then whispered to him (no answer); Boris's whisper
    # got Anna's answer the next tick. His "no food here either" named nobody: not addressed.
    assert rep["villagers"]["Anna"]["replies_same_tick"] == {"num": 0, "den": 2}
    assert rep["villagers"]["Anna"]["replies_next_tick"] == {"num": 1, "den": 2}
    assert rep["villagers"]["Boris"]["replies_next_tick"] == {"num": 1, "den": 1}
    assert v["long_talks"] == 1.0  # Anna, Boris, Anna: three alternating turns
    assert v["gifts"] == round(1 / rep["villager_days"], 3)


def test_app_runs_an_experiment_on_bots(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from aivillage.server import Host, create_app
    monkeypatch.setenv("AIVILLAGE_HOME", str(tmp_path))
    for k in ("OPENAI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    host = Host(None, str(tmp_path / "runs"), str(tmp_path / "reports"), setup=True)
    c = TestClient(create_app(host=host))
    listed = {s["name"]: s for s in c.get("/api/scenarios").json()["scenarios"]}
    assert listed["fork_memory"]["lab"] and listed["fork_memory"]["arms"] == ["B"]
    assert not listed["hungry_neighbor"]["lab"]
    assert c.post("/api/lab", json={"name": "fork_memory"}).status_code == 400  # AI without a key
    assert c.post("/api/lab", json={"name": "hungry_neighbor", "brains": "bots"}).status_code == 400
    assert c.post("/api/lab", json={"name": "fork_memory", "brains": "bots", "save": "../x"}).status_code == 400
    r = c.post("/api/lab", json={"name": "fork_memory", "brains": "bots"})
    assert r.status_code == 200, r.text
    end = time.monotonic() + 120
    while c.get("/api/lab").json()["job"]["state"] == "running":
        assert time.monotonic() < end
        time.sleep(0.05)
    job = c.get("/api/lab").json()["job"]
    assert job["state"] == "done", job
    assert job["of"] == 6 and "Что изменилось против A" in job["report"]
    assert (Path(job["out"]) / "lab.md").is_file()
