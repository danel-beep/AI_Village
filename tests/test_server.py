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


def test_viewer_scripts_served(tmp_path):
    sim = LiveSim(engine.new_world({"seed": 1}), lambda n, o: None, 1)
    client = TestClient(create_app(sim))
    assert "Dossier" in client.get("/dossier.js").text
    assert client.get("/missing.js").status_code == 404
    assert 'src="dossier.js"' in client.get("/").text

def test_recaps_and_problem_report(tmp_path):
    import zipfile
    from aivillage.summary import StubSummaryClient, Summarizer
    world = engine.new_world({"seed": 3})
    sim = LiveSim(world, bots_decider(world, ["worker"], 3), 2, str(tmp_path / "live.jsonl"), 0.0,
                  summarizer=Summarizer(StubSummaryClient()))
    client = TestClient(create_app(sim))
    assert "/report.js" in client.get("/").text
    sim.start()
    wait(lambda: sim.finished)
    wait(lambda: len(sim.summaries) >= 1)  # day 1 recap is written in the background
    got = client.get("/api/summary").json()
    assert got["enabled"] and got["summaries"][0]["from"].startswith("день 1")
    now = client.post("/api/summary").json()
    assert now["from_tick"] > got["summaries"][0]["to_tick"]
    assert (tmp_path / "live.summary.json").exists()
    assert client.post("/api/report", json={"note": ""}).status_code == 400
    r = client.post("/api/report", json={"note": "огонь погас сам", "tick": 7}).json()
    with zipfile.ZipFile(r["path"]) as z:
        assert {"report.json", "run.jsonl", "summary.json"} <= set(z.namelist())
        assert json.loads(z.read("report.json"))["tick"] == 7
    replay(tmp_path / "live.jsonl")


def test_recaps_off_without_summarizer(tmp_path):
    sim, client = make(tmp_path)
    assert client.get("/api/summary").json()["enabled"] is False
    assert client.post("/api/summary").status_code == 400


def test_highlights_without_key_last_day_too(tmp_path):
    world = engine.new_world({"seed": 3})
    sim = LiveSim(world, bots_decider(world, ["worker", "thief", "random", "worker"], 3), 1,
                  str(tmp_path / "live.jsonl"), 0.0)
    client = TestClient(create_app(sim))
    assert "highlights.js" in client.get("/").text
    sim.god.put({"name": "fire", "args": {"person": "Anna"}})
    sim.start()
    wait(lambda: sim.finished)
    wait(lambda: sim.highlights)  # rules pick them when recaps are off; the last day has no next morning
    got = client.get("/api/highlights").json()["highlights"]
    assert [d["day"] for d in got] == [1] and got[0]["source"] == "rules"
    assert any(it["kind"] == "fire" and it["who"] == ["Anna"] for it in got[0]["items"])
    assert json.loads((tmp_path / "live.highlights.json").read_text(encoding="utf-8")) == got
    replay(tmp_path / "live.jsonl")


def test_god_queue_lands_due_events_and_never_loses_late_ones():
    from aivillage.server import GodQueue
    q = GodQueue()
    q.put({"name": "a"}, 5)
    q.put({"name": "b"}, 2)
    assert q.get(1) == []
    assert q.get(3) == [{"name": "b"}]  # tick 2 went by: lands now
    assert q.get(4) == [] and q.get(5) == [{"name": "a"}] and q.get(6) == []


def test_god_click_lands_after_the_moment_on_screen(tmp_path):
    world = engine.new_world({"seed": 3, "tick_minutes": 15})
    sim = LiveSim(world, bots_decider(world, ["worker"], 3), 1, str(tmp_path / "live.jsonl"), 0.0)
    client = TestClient(create_app(sim))
    assert client.get("/api/meta").json()["view_lag_ticks"] == 2
    sim.running.clear()
    sim.start()
    wait(lambda: len(sim.ticks) >= 1)
    victim = sorted(world.agents)[0]
    with client.websocket_connect("/ws") as ws:
        json.loads(ws.receive_text())  # header
        for _ in sim.ticks:
            ws.receive_text()
        now = sim.world.tick
        r = client.post("/api/god", json={"name": "fire", "args": {"person": victim}, "shown_tick": now + 3}).json()
        assert r["queued_for_tick"] == now + 4 and r["lead_minutes"] == 15
        pending = json.loads(ws.receive_text())
        assert pending["type"] == "god_pending" and pending["tick"] == now + 4 and pending["name"] == "fire"
        r = client.post("/api/god", json={"name": "gift", "args": {"person": victim, "coins": 1},
                                           "shown_tick": now - 2}).json()
        assert r["queued_for_tick"] == now  # the sim is ahead of the screen: the next tick it plays
    client.post("/api/control", json={"cmd": "resume"})
    wait(lambda: sim.finished)
    assert sim.error is None
    landed = {t["god"][0]["name"]: t["tick"] for t in sim.ticks if t["god"]}
    assert landed == {"fire": now + 4, "gift": now}
    replay(tmp_path / "live.jsonl")
