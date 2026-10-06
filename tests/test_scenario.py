"""Scenarios (aivillage/scenario.py): a village started at a chosen moment, with chosen memory."""

import time
from pathlib import Path

import pytest

from aivillage import saves, scenario as S
from aivillage.invariants import check
from aivillage.run import read_log, replay

NAMES = [p.stem for p in sorted(S.DIR.glob("*.yaml"))]


def test_ready_scenarios_exist():
    assert {"hungry_neighbor", "smithy_together", "tax_dodger"} <= set(NAMES)
    assert {s["name"] for s in S.listing()} == set(NAMES)


@pytest.mark.parametrize("name", NAMES)
def test_scenario_plays_on_bots_and_replays(tmp_path, name):
    log = tmp_path / f"{name}.jsonl"
    rep = S.run_scenario(name, log=log, ai=[])
    head = next(read_log(log))
    assert head["scenario"]["name"] == name and "start" in head
    ticks = [r for r in read_log(log) if r.get("type") == "tick"]
    assert ticks and replay(log).hash() == ticks[-1]["hash"]
    assert set(rep) >= {"expect", "watch", "passed"}
    assert log.with_suffix(".scenario.md").is_file()


def test_edits_land_in_the_world_and_keep_invariants():
    scn = S.load("hungry_neighbor")
    w = S.start_world(scn)
    anna, boris = w.agents["Anna"], w.agents["Boris"]
    assert w.day == 3 and anna.satiety == 8 and anna.health == 55 and anna.location == "square"
    assert anna.inventory == {"wood": 2} and not w.chests["chest_Anna"].items
    assert boris.inventory.get("fish", 0) >= 4 and boris.location == "square"
    check(w)  # the ledger books what the scenario added


def test_sites_bills_and_mayor():
    w = S.start_world(S.load("smithy_together"))
    site = next(iter(w.construction["sites"].values()))
    assert site["kind"] == "smithy" and site["started_by"] == "Dmitri" and site["given"] == site["needs"]
    w = S.start_world(S.load("tax_dodger"))
    bill = next(d for d in w.debts.values() if d.borrower == "Boris" and d.kind == "tax")
    assert bill.status == "defaulted" and bill.due_day == w.day - 1 and bill.coins_owed == 12
    assert w.governance.mayor == "Elena" and w.agents["Boris"].coins == 25


def test_memory_goes_to_ai_villagers_only():
    scn = S.load("smithy_together")
    w = S.start_world(scn)
    decide, on_night = S.brains(w, scn, model="stub")
    assert set(decide.agents) == {"Dmitri", "Boris", "Anna"} and on_night is not None
    assert "smithy" in decide.agents["Dmitri"].notes and decide.agents["Anna"].notes == ""
    assert set(decide.bots) == set(w.agents) - set(decide.agents)


def test_stub_run_reads_back(tmp_path):
    log = tmp_path / "stub.jsonl"
    rep = S.run_scenario("tax_dodger", log=log, model="stub", days=1)
    assert set(rep["turns"]) == {"Anna", "Boris", "Clara", "Dmitri", "Elena"}
    replay(log)


def test_bad_scenarios_are_refused():
    with pytest.raises(S.ScenarioError, match="no villager 'Zed'"):
        S.edit(S.start_world(S.parse({"title": "t"})), S.parse({"title": "t", "villagers": {"Zed": {"coins": 1}}}))
    with pytest.raises(S.ScenarioError, match="unknown items"):
        S.start_world(S.parse({"title": "t", "villagers": {"Anna": {"add": {"unobtainium": 1}}}}))
    with pytest.raises(S.ScenarioError, match="invalid"):
        S.parse({"title": "t", "typo": 1})
    with pytest.raises(S.ScenarioError):
        S.load("../etc/passwd")


def test_checks():
    ev = lambda kind, actor, to=(), text="", **data: {"kind": kind, "actor": actor, "to": list(to), "text": text,
                                                       "data": data, "day": 1, "hour": 9}
    events = [ev("give", "Boris", ["Anna"], "Boris gave 2 fish to Anna."), ev("construct", "A", counted=True),
              ev("construct", "A", counted=True), ev("trade", "Anna", ["Clara"], "x", partner="Clara")]
    food = S.Check(kind="give", to="Anna", text="fish|berries")
    assert S.verdict(food, events)["ok"] and S.verdict(food, events)["first"].startswith("day 1 09:00")
    assert not S.verdict(S.Check(kind="give", to="Clara"), events)["ok"]
    assert not S.verdict(S.Check(kind="construct", data={"counted": True}, actors=2), events)["ok"]
    assert S.verdict(S.Check(kind="construct", min=2), events)["ok"]
    assert not S.verdict(S.Check(kind="construct", ai=True), events, {"Anna"})["ok"]
    assert S.verdict(S.Check(kind="construct", ai=True), events, {"A"})["ok"]
    assert S.verdict(S.Check(any=[S.Check(kind="give", to="Clara"), S.Check(kind="trade", who="Clara")]), events)["ok"]


def _wait(cond, timeout=30.0):
    end = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < end, "timed out"
        time.sleep(0.01)


def test_app_plays_a_scenario(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from aivillage.server import Host, create_app
    monkeypatch.setenv("AIVILLAGE_HOME", str(tmp_path))
    for k in ("OPENAI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    host = Host(None, str(tmp_path / "runs"), str(tmp_path / "reports"), setup=True)
    c = TestClient(create_app(host=host))
    listed = c.get("/api/scenarios").json()
    assert listed["can_start"] and {s["name"] for s in listed["scenarios"]} == set(NAMES)
    assert c.post("/api/scenario", json={"name": "tax_dodger"}).status_code == 400  # AI without a key
    assert c.post("/api/scenario", json={"name": "../x", "brains": "bots"}).status_code == 400
    r = c.post("/api/scenario", json={"name": "smithy_together", "brains": "bots"})
    assert r.status_code == 200, r.text
    c.post("/api/control", json={"cmd": "pace", "seconds": 0})
    sim = host.sim
    _wait(lambda: sim.finished)
    assert sim.error is None and replay(sim.log_path).hash() == sim.world.hash()
    _wait(lambda: Path(sim.log_path).with_suffix(".scenario.md").is_file())
    assert saves.listing(tmp_path / "runs")[0]["name"] == Path(sim.log_path).stem  # it can be continued
