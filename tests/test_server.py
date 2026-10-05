import json
import time

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from aivillage import engine  # noqa: E402
from aivillage.run import bots_decider, replay  # noqa: E402
from aivillage.server import LiveSim, create_app  # noqa: E402


def make(tmp_path, days=1, pace=0.0):
    world = engine.new_world({"seed": 3})
    sim = LiveSim(world, bots_decider(world, ["worker"], 3), days, str(tmp_path / "live.jsonl"), pace)
    return sim, TestClient(create_app(sim))


def wait(cond, timeout=10.0):
    end = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < end, "timed out"
        time.sleep(0.01)


def test_stream_god_event_and_replay(tmp_path):
    sim, client = make(tmp_path)
    sim.running.clear()  # start paused so the god event lands mid-run
    sim.start()
    wait(lambda: len(sim.ticks) >= 1)
    victim = sorted(sim.world.agents)[0]
    assert client.post("/api/god", json={"name": "fire", "args": {"person": victim}}).json()["ok"]
    assert client.post("/api/god", json={"name": "fire", "args": {}}).status_code == 400
    assert client.post("/api/control", json={"cmd": "resume"}).json()["paused"] is False
    wait(lambda: sim.finished)
    assert sim.error is None
    god_ticks = [t for t in sim.ticks if t["god"]]
    assert god_ticks and god_ticks[0]["god"][0] == {"name": "fire", "args": {"person": victim}}
    assert any(e["kind"] == "fire" for e in god_ticks[0]["events"])
    # Live god events are in the log, so the run replays exactly.
    replay(tmp_path / "live.jsonl")

    # A late joiner gets the whole backlog over the websocket, then the end marker.
    with client.websocket_connect("/ws") as ws:
        first = json.loads(ws.receive_text())
        assert first["type"] == "header"
        n = sum(1 for _ in range(len(sim.ticks)) if json.loads(ws.receive_text())["type"] == "tick")
        assert n == len(sim.ticks)


def test_live_push_and_pages(tmp_path):
    sim, client = make(tmp_path, days=2, pace=0.05)
    with client.websocket_connect("/ws") as ws:
        sim.start()
        kinds = [json.loads(ws.receive_text())["type"] for _ in range(4)]
        assert kinds == ["header", "tick", "tick", "tick"]
    sim.stop()
    page = client.get("/").text
    assert "/live.js" in page and "/god.js" in page and "<canvas" in page
    assert client.get("/god.js").status_code == 200 and client.get("/live.js").status_code == 200
    meta = client.get("/api/meta").json()
    assert "fire" in meta["god"] and meta["agents"] and meta["locations"]
