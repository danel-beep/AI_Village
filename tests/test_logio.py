"""Light log (aivillage/logio.py): tick views are written as deltas, every reader gets whole views back."""
import asyncio
import json

import pytest

from aivillage import engine, logio, metrics, modes, scorecard, social_metrics
from aivillage.run import bots_decider, read_log, replay, run


def _run(tmp_path, days=3):
    w = engine.new_world(modes.world_override("survival", {"seed": 5, "population": {"size": 6}}))
    log, live = tmp_path / "run.jsonl", []
    run(w, bots_decider(w, ["worker", "random", "thief", "worker", "random", "worker"], 5), days=days,
        log_path=log, on_record=lambda r: live.append(json.loads(json.dumps(r))))
    return w, log, live


def test_log_is_light_and_reads_back_whole(tmp_path):
    w, log, live = _run(tmp_path)
    assert replay(log).hash() == w.hash()
    raw = [json.loads(line) for line in log.read_text().splitlines()]
    ticks = [r for r in raw if r["type"] == "tick"]
    assert "_keep" not in ticks[0] and any("_keep" in t for t in ticks)
    full = sum(len(json.dumps(r, ensure_ascii=False)) + 1 for r in live)
    assert log.stat().st_size <= 0.62 * full  # bots: ~40% lighter than whole views (LLM logs: ~50%)
    assert list(read_log(log)) == live  # on_record (the live server) still sees whole views
    assert metrics.read_log(log) == live


def test_readers_match_full_log(tmp_path):
    _, log, live = _run(tmp_path)
    full = tmp_path / "full.jsonl"
    full.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in live))
    assert metrics.compute(metrics.read_log(log)) == metrics.compute(live)
    assert social_metrics.compute(metrics.read_log(log)) == social_metrics.compute(live)
    strip = lambda rep: [{k: v for k, v in row.items() if k != "log"} for row in rep["villagers"]]
    assert strip(scorecard.compute([log])) == strip(scorecard.compute([full]))


def test_deltas_round_trip_and_first_tick_whole():
    shared = {"map": {"a": 1}, "day": 1}
    d = logio.ViewDeltas()
    recs = []
    for k in range(4):
        shared["day"] = 1 + k // 2  # the same dict object mutated in place, like a view sharing world objects
        recs.append({"type": "tick", "tick": k, "view": shared})
        out = d.compact(recs[-1])
        recs[-1] = json.loads(json.dumps(recs[-1]))
        if k == 0:
            assert "_keep" not in out
        else:
            assert "map" in out["_keep"] and ("day" in out["_keep"]) == (k % 2 == 1)
        recs[-1] = (recs[-1], json.loads(json.dumps(out)))
    assert list(logio.expand(r[1] for r in recs)) == [r[0] for r in recs]
    with pytest.raises(ValueError):  # a delta with nothing before it is an error, not a silent hole
        list(logio.expand([recs[1][1]]))


def test_slow_viewer_is_dropped_not_buffered():
    pytest.importorskip("fastapi")
    from aivillage import server

    q = asyncio.Queue(maxsize=3)
    for k in range(5):
        server._offer(q, str(k))
    items = [q.get_nowait() for _ in range(q.qsize())]
    assert items[-1] is None and len(items) <= 3
