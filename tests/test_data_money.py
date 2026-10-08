"""Nothing the app records is lost: a failed "continue" leaves the log as it was, what came after a save is
kept, every model cent reaches the daily count, and the history kept in memory is the one in the log."""

import hashlib
import json
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from aivillage import budget, engine, saves
from aivillage.run import bots_decider, read_log, run

KINDS = ["worker", "thief", "random", "trader", "homestead"]


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _village_with_tail(runs: Path) -> Path:
    """Two days played, saved at tick 23: the log goes on for hours after the save."""
    log = runs / "v.jsonl"
    world = engine.new_world({"seed": 7})
    decide = bots_decider(world, KINDS, 7)

    def checkpoint(w):
        if w.tick == 23:
            saves.write(log, saves.snapshot(w, decide, log_path=log, end_day=w.day + 2))
    run(world, decide, 2, log_path=log, checkpoint=checkpoint)
    return log


def test_a_bad_save_or_log_changes_nothing(tmp_path):
    log = _village_with_tail(tmp_path)
    snap = saves.read(saves.path_for(log))
    before = _sha(log)
    assert log.stat().st_size > snap["log_bytes"]
    for bad in ({**snap, "log_bytes": snap["log_bytes"] - 1},  # not on a record boundary
                {**snap, "log_bytes": log.stat().st_size + 1}):  # longer than the log
        with pytest.raises(ValueError):
            saves.rewind_log(log, bad)
        assert _sha(log) == before
    damaged = log.read_bytes().replace(b'"type": "header"', b'"type": "headex"', 1)
    log.write_bytes(damaged)
    with pytest.raises(ValueError, match="no header"):
        saves.rewind_log(log, snap)
    assert log.read_bytes() == damaged


def test_continuing_keeps_what_came_after_the_save(tmp_path):
    log = _village_with_tail(tmp_path)
    snap = saves.read(saves.path_for(log))
    data = log.read_bytes()
    recs = saves.rewind_log(log, snap)
    assert recs[0]["type"] == "header" and log.read_bytes() == data[: snap["log_bytes"]]
    kept = list(tmp_path.glob("v.jsonl.after-save-*"))
    assert len(kept) == 1 and kept[0].read_bytes() == data[snap["log_bytes"]:]
    assert saves.cut_log(log, snap) is None  # nothing after the save any more: nothing to keep


def test_load_with_a_wrong_answer_does_not_cut_the_log(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from aivillage.server import Host
    monkeypatch.setenv("AIVILLAGE_HOME", str(tmp_path))
    for k in ("OPENAI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    log = _village_with_tail(tmp_path / "runs")
    before = _sha(log)
    host = Host(None, str(tmp_path / "runs"), str(tmp_path / "reports"), setup=True)
    for days in (366, -1, "x"):
        with pytest.raises(ValueError):
            host.load("v", days)
        assert _sha(log) == before
    assert not list(log.parent.glob("*.after-save-*"))
    sim = host.load("v", 1)
    try:
        assert sim.ticks[-1]["tick"] == 22 and list(log.parent.glob("v.jsonl.after-save-*"))
    finally:
        host.stop()


class _Usage:
    calls = failures = prompt_tokens = cached_tokens = completion_tokens = 0
    by_model: dict = {}

    def __init__(self):
        self.cost_usd = 0.0


def test_the_last_tick_and_recaps_reach_the_daily_count(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from aivillage.server import LiveSim
    monkeypatch.setenv("AIVILLAGE_HOME", str(tmp_path))
    world = engine.new_world({"seed": 1})
    names = list(world.agents)[:5]
    agents = {n: SimpleNamespace(client=SimpleNamespace(model="fake"), usage=_Usage()) for n in names}
    lock = threading.Lock()

    def decide(name, obs):
        if name in agents:
            with lock:
                agents[name].usage.cost_usd += 0.10
        return {"action": {"name": "wait"}}
    decide.agents = agents
    sim = LiveSim(world, decide, 1, pace=0)  # no cap: spending is counted all the same
    sim.start()
    deadline = time.monotonic() + 60
    while not sim.finished and time.monotonic() < deadline:
        time.sleep(0.05)
    assert sim.finished and sim.error is None
    assert sim.spent() > 0 and budget.spent_today() == pytest.approx(sim.spent())

    sim.summarizer = SimpleNamespace(cost_usd=0.0, summarize=None)

    def recap(ticks):
        sim.summarizer.cost_usd += 0.25
        return {"error": "no model"}
    sim.summarizer.summarize = recap
    sim.summarize(list(sim.ticks)[-4:])  # "Что произошло?" after the end: counted at once
    assert budget.spent_today() == pytest.approx(sim.spent())


def test_spend_file_is_replaced_whole(tmp_path, monkeypatch):
    monkeypatch.setenv("AIVILLAGE_HOME", str(tmp_path))
    budget.add(0.5)
    budget.add(0.25)
    assert budget.spent_today() == pytest.approx(0.75) and not list(tmp_path.glob("*.tmp"))


def test_a_failed_lab_run_still_counts(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    from aivillage.server import LabJob
    monkeypatch.setenv("AIVILLAGE_HOME", str(tmp_path))
    job = LabJob("x", tmp_path, llm=True, save=None, daily_budget=5.0)
    job._progress({"index": 1, "of": 1, "arm": "a", "replicate": 1, "state": "failed", "cost": 0.3, "spent": 0.3})
    assert budget.spent_today() == pytest.approx(0.3)


def test_history_in_memory_is_the_log(tmp_path):
    """`view` holds the world's own dicts; records handed on are copies, so later ticks cannot rewrite them."""
    world = engine.new_world({"seed": 3})
    seen = []
    log = tmp_path / "r.jsonl"
    run(world, bots_decider(world, KINDS, 3), 1, log_path=log, on_record=seen.append)
    assert seen == list(read_log(log))
