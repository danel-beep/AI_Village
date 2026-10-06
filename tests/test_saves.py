"""Save a village between ticks, load it, continue: same story as a run that never stopped."""

import json
from pathlib import Path

import pytest

from aivillage import clock, engine, saves
from aivillage.run import bots_decider, llm_agents, read_log, replay, run

KINDS = ["worker", "thief", "random", "trader", "homestead"]


class _Halt(Exception):
    pass


def _uninterrupted(tmp_path, days):
    world = engine.new_world({"seed": 7})
    run(world, bots_decider(world, KINDS, 7), days, log_path=tmp_path / "full.jsonl")
    return world


def _save_at(world, decide, log, end_day, tick):
    """A checkpoint that saves at `tick` and stops the run there (the app's "save, then close")."""
    def checkpoint(w):
        if w.tick == tick:
            saves.write(log, saves.snapshot(w, decide, log_path=log, end_day=end_day))
            raise _Halt
    return checkpoint


def test_save_load_continue_matches_an_uninterrupted_run(tmp_path):
    full = _uninterrupted(tmp_path, 2)
    log = tmp_path / "run.jsonl"
    world = engine.new_world({"seed": 7})
    decide = bots_decider(world, KINDS, 7)
    with pytest.raises(_Halt):
        run(world, decide, 2, log_path=log, checkpoint=_save_at(world, decide, log, world.day + 2, 23))

    snap = saves.read(saves.path_for(log))
    assert snap["tick"] == 23 and json.loads(json.dumps(snap)) == snap  # plain JSON, nothing pickled
    recs = saves.rewind_log(log, snap)
    w2 = saves.world_of(snap)
    decide2, _ = saves.decider(w2, snap)
    assert w2.hash() == snap["hash"]
    run(w2, decide2, snap["end_day"] - w2.day, log_path=log, resume_header=recs[0])

    assert w2.hash() == full.hash()  # bots kept their RNG and plans: the same village
    headers = [r for r in read_log(log) if r["type"] == "header"]
    assert len(headers) == 1
    ticks = [r["tick"] for r in read_log(log) if r["type"] == "tick"]
    assert ticks == list(range(len(ticks)))  # one continuous story, no gap, no duplicate
    assert replay(log).hash() == full.hash()


def test_ticks_after_the_save_are_cut_and_played_again(tmp_path):
    full = _uninterrupted(tmp_path, 1)
    log = tmp_path / "run.jsonl"
    world = engine.new_world({"seed": 7})
    decide = bots_decider(world, KINDS, 7)
    end_day = world.day + 1

    def checkpoint(w):  # save at tick 20, keep playing (a crash later loses only what came after)
        if w.tick == 10:
            saves.write(log, saves.snapshot(w, decide, log_path=log, end_day=end_day))
    run(world, decide, 1, log_path=log, checkpoint=checkpoint)
    snap = saves.read(saves.path_for(log))
    recs = saves.rewind_log(log, snap)
    assert max(r["tick"] for r in recs if r["type"] == "tick") == 9
    w2 = saves.world_of(snap)
    run(w2, saves.decider(w2, snap)[0], snap["end_day"] - w2.day, log_path=log, resume_header=recs[0])
    assert w2.hash() == full.hash() and replay(log).hash() == full.hash()


def test_llm_memory_survives_a_save(tmp_path):
    log = tmp_path / "llm.jsonl"
    world = engine.new_world({"seed": 2, "population": {"size": 3}})
    agents = llm_agents(world, ["stub"])
    decide = lambda n, o: agents[n].decide(o)
    decide.agents = agents
    from aivillage.run import night_reflection
    end_day = world.day + 2
    stop_at = clock.tick_of(world.config, 2, 9)  # day 2 morning: after the first night
    with pytest.raises(_Halt):
        run(world, decide, 2, log_path=log, on_night=lambda w, d: night_reflection(w, agents, d),
            checkpoint=_save_at(world, decide, log, end_day, stop_at))
    name = sorted(agents)[0]
    before = agents[name]
    assert before.diary and before.usage.calls
    snap = saves.read(saves.path_for(log))
    w2 = saves.world_of(snap)
    decide2, on_night = saves.decider(w2, snap)
    after = decide2.agents[name]
    assert (after.diary, after.people, after.notes, after.recent, after.day_log, after.villagers) == \
        (before.diary, before.people, before.notes, before.recent, before.day_log, before.villagers)
    assert after.usage == before.usage and after.client.model == "stub" and on_night
    assert saves.listing(tmp_path)[0]["llm"] is True


def test_damaged_save_is_refused(tmp_path):
    log = tmp_path / "run.jsonl"
    world = engine.new_world({"seed": 7})
    decide = bots_decider(world, ["worker"], 7)
    with pytest.raises(_Halt):
        run(world, decide, 1, log_path=log, checkpoint=_save_at(world, decide, log, 2, 5))
    snap = saves.read(saves.path_for(log))
    snap["world"]["agents"][sorted(world.agents)[0]]["coins"] += 100
    with pytest.raises(ValueError):
        saves.world_of(snap)
    log.write_text("")  # a log shorter than at save time
    with pytest.raises(ValueError):
        saves.rewind_log(log, snap)


def _wait(cond, timeout=20.0):
    import time
    end = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < end, "timed out"
        time.sleep(0.01)


def test_app_save_close_and_continue(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from aivillage.server import Host, create_app
    monkeypatch.setenv("AIVILLAGE_HOME", str(tmp_path))
    for k in ("OPENAI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    host = Host(None, str(tmp_path / "runs"), str(tmp_path / "reports"), setup=True)
    c = TestClient(create_app(host=host))
    opts = {"brains": "bots", "villagers": 4, "days": 2, "pace": 0, "seed": 9}
    assert c.get("/api/saves").json()["saves"] == []

    assert c.post("/api/start", json=opts).status_code == 200  # the reference: never stopped
    _wait(lambda: host.sim.finished)
    full = host.sim.world.hash()
    assert c.get("/api/saves").json()["saves"][0]["finished"]  # an ended village is saved too

    assert c.post("/api/start", json={**opts, "pace": 0.5}).status_code == 200
    sim = host.sim
    _wait(lambda: len(sim.ticks) >= 10)
    c.post("/api/control", json={"cmd": "pause"})
    saved = c.post("/api/save").json()
    assert saved["ok"] and not saved["pending"] and saved["tick"] == sim.world.tick
    assert c.post("/api/stop").json()["ok"] and host.sim is None
    listed = c.get("/api/saves").json()["saves"]
    name = Path(sim.log_path).stem
    row = next(s for s in listed if s["name"] == name)
    assert not row["finished"] and row["villagers"] == 4 and not row["llm"]

    assert c.post("/api/load", json={"name": "../etc"}).status_code == 400
    r = c.post("/api/load", json={"name": name})
    assert r.status_code == 200, r.text
    sim2 = host.sim
    assert sim2.ticks[0]["tick"] == 0 and len(sim2.ticks) >= saved["tick"]  # the story so far, for the viewer
    c.post("/api/control", json={"cmd": "pace", "seconds": 0})
    _wait(lambda: sim2.finished)
    assert sim2.error is None and sim2.world.hash() == full
    assert replay(sim2.log_path).hash() == full
    with c.websocket_connect("/ws") as ws:  # a fresh page gets the whole village from tick 0
        assert json.loads(ws.receive_text())["type"] == "header"
        assert json.loads(ws.receive_text())["tick"] == 0

    day = sim2.world.day  # an ended village goes on for more days
    assert c.post("/api/load", json={"name": name, "days": 1}).status_code == 200
    _wait(lambda: host.sim.finished)
    assert host.sim.world.day == day + 1 and replay(host.sim.log_path).hash() == host.sim.world.hash()
