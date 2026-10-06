"""Population scaling: N villagers, resources that grow with them, a request queue in front of the model."""

import io
import threading
import time
import urllib.error
from collections import Counter

import pytest

from aivillage import engine, llm
from aivillage.config import DEFAULT_CONFIG, make_config
from aivillage.population import resource_scale
from aivillage.run import bots_decider, replay, run
from aivillage.runconfig import RunConfig


def test_default_config_is_unchanged():
    cfg = make_config()
    assert [a["name"] for a in cfg["agents"]] == [a["name"] for a in DEFAULT_CONFIG["agents"]]
    assert cfg["locations"]["mine"]["resources"] == DEFAULT_CONFIG["locations"]["mine"]["resources"]
    assert resource_scale(cfg) == 1.0 and cfg["orders_per_post"] == 1


def test_twenty_villagers_unique_balanced_and_seeded():
    cfg = make_config({"population": {"size": 20}})
    names = [a["name"] for a in cfg["agents"]]
    assert len(names) == len(set(names)) == 20
    assert names[:5] == [a["name"] for a in DEFAULT_CONFIG["agents"]]  # the classic five stay
    profs = Counter(a["profession"] for a in cfg["agents"])
    assert set(profs) == set(cfg["professions"]) and max(profs.values()) <= 6, profs
    assert make_config({"population": {"size": 20}})["agents"] == cfg["agents"]  # same seed, same village
    other = make_config({"seed": 2, "population": {"size": 20}})
    assert [a["name"] for a in other["agents"]] != names


def test_fewer_villagers_keeps_first_ones():
    cfg = make_config({"population": {"size": 3}})
    assert [a["name"] for a in cfg["agents"]] == ["Anna", "Boris", "Clara"]
    assert resource_scale(cfg) == 1.0


def test_resources_scale_but_water_does_not():
    cfg = make_config({"population": {"size": 20}})
    assert resource_scale(cfg) == 4.0
    fish, base = cfg["locations"]["river"]["resources"]["fish"], DEFAULT_CONFIG["locations"]["river"]["resources"]["fish"]
    assert all(fish[k] == 4 * base[k] for k in ("start", "max", "regen"))
    assert fish["slots"] == base["slots"]  # same number of shoals/trees, each holds more
    assert cfg["locations"]["river"]["resources"]["water"] == DEFAULT_CONFIG["locations"]["river"]["resources"]["water"]
    assert cfg["projects"]["bridge"]["needs"]["wood"] == 4 * DEFAULT_CONFIG["projects"]["bridge"]["needs"]["wood"]
    assert cfg["orders_per_post"] == 4
    off = make_config({"population": {"size": 20, "scale_resources": False}})
    assert off["locations"]["river"]["resources"] == DEFAULT_CONFIG["locations"]["river"]["resources"]


def test_resolve_is_idempotent_and_replay_exact(tmp_path):
    w = engine.new_world({"population": {"size": 12}})
    assert len(w.agents) == 12
    again = engine.new_world(w.config)  # what replay does with the log header
    assert again.hash() == w.hash() and again.config["locations"] == w.config["locations"]
    log = tmp_path / "big.jsonl"
    run(w, bots_decider(w, ["worker", "thief", "random"], 1), days=2, log_path=log)
    assert replay(log).hash() == w.hash()


def test_size_limits():
    with pytest.raises(ValueError):
        make_config({"population": {"size": 500}})


def test_run_config_villagers():
    rc = RunConfig(villagers=8)
    assert len(engine.new_world(rc.world_override()).agents) == 8


def test_big_village_of_loners_survives_a_season():
    """World capacity: 20 bots that never trade must not starve on the scaled map."""
    w = engine.new_world({"seed": 3, "population": {"size": 20}})
    stats = run(w, bots_decider(w, ["loner"], 3), days=7, check_every_tick=False)
    assert stats.get("hospital", 0) == 0, stats


# ---------- request queue ----------

def test_gate_caps_parallel_calls():
    gate = llm.RateGate(3)
    live, peak, lock = [0], [0], threading.Lock()

    def call():
        with gate:
            with lock:
                live[0] += 1
                peak[0] = max(peak[0], live[0])
            time.sleep(0.02)
            with lock:
                live[0] -= 1

    threads = [threading.Thread(target=call) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert peak[0] == 3 and gate.calls == 12


def test_gate_cooldown_holds_everyone():
    gate = llm.RateGate(4)
    gate.cool(0.15)
    t0 = time.monotonic()
    with gate:
        pass
    assert time.monotonic() - t0 >= 0.14 and gate.rate_limited == 1


def test_429_backs_off_then_switches_to_fallback(monkeypatch):
    seen = []

    def fake_urlopen(req, timeout):
        import json
        body = json.loads(req.data)
        seen.append(body["model"])
        if body["model"] == "main/model":
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, io.BytesIO(b""))
        return io.BytesIO(json.dumps({"model": body["model"], "usage": {"cost": 0.001},
                                      "choices": [{"message": {"content": '{"action": {"name": "wait"}}'}}]}).encode())

    monkeypatch.setattr(llm.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    monkeypatch.setitem(llm._GATES, "main/model", llm.RateGate(4))
    client = llm.OpenRouterClient("main/model", api_key="k", fallbacks=["backup/model"])
    text, usage = client.complete([{"role": "user", "content": "hi"}])
    assert seen == ["main/model", "main/model", "backup/model"]
    assert usage["model"] == "backup/model" and llm._GATES["main/model"].rate_limited == 2
    llm._GATES.pop("backup/model", None)
