import json

from aivillage import engine, highlights, summary
from aivillage.run import bots_decider, read_log, replay, run


def make_log(tmp_path, days=2):
    w = engine.new_world({"seed": 3})
    god = {4: [{"name": "fire", "args": {"person": "Anna"}}], 20: [{"name": "fire", "args": {"person": "Boris"}}]}
    log = tmp_path / "h.jsonl"
    run(w, bots_decider(w, ["worker", "thief", "random", "worker"], 3), days, god_script=god, log_path=log)
    return log


class FakeClient:
    model = "fake"

    def __init__(self, reply):
        self.reply, self.seen = reply, []

    def complete(self, messages):
        self.seen.append(messages[-1]["content"])
        return self.reply, {"cost": 0.0001}


def test_rules_pick_fire_with_tick(tmp_path):
    log = make_log(tmp_path)
    assert highlights.main([str(log), "--model", "stub"]) == 0
    days = json.loads(highlights.sidecar_path(log).read_text(encoding="utf-8"))
    assert [d["day"] for d in days] == [1, 2] and all(d["source"] == "rules" for d in days)
    ticks = {t["tick"]: t for t in summary.ticks_of(read_log(log))}
    for d in days:
        assert 1 <= len(d["items"]) <= highlights.MAX_PICKS
        assert [it["tick"] for it in d["items"]] == sorted(it["tick"] for it in d["items"])
        for it in d["items"]:  # every highlight points at a tick that really has that event
            assert any(e["kind"] == it["kind"] for e in ticks[it["tick"]]["events"])
            assert summary.when(ticks[it["tick"]]) == (it["day"], it["hour"]) == (d["day"], it["hour"])
    assert any(it["kind"] == "fire" and it["tick"] == 4 for it in days[0]["items"])
    replay(log)  # the sidecar never touches the log


def test_model_picks_by_id_and_bad_reply_falls_back(tmp_path):
    ticks = summary.by_day(summary.ticks_of(read_log(make_log(tmp_path, days=1))))[0]
    cands = highlights.candidates(ticks)
    fire = next(k for k, c in enumerate(cands) if c["kind"] == "fire")
    reply = json.dumps({"highlights": [{"id": fire, "title": "Дом Анны горит", "text": "Анна в панике."},
                                       {"id": 999, "title": "x"}, {"id": f"#{fire}", "title": "дубль"},
                                       *({"id": k} for k in range(len(cands)) if k != fire)]})
    client = FakeClient(reply)
    got = highlights.Highlighter(client).pick(ticks)
    assert got["source"] == "model" and got["cost_usd"] > 0 and "Candidates:" in client.seen[0]
    assert next(c for c in cands if c["kind"] == "fire")["who"] == ["Anna"]
    first = next(it for it in got["items"] if it["kind"] == "fire")
    assert first["title"] == "Дом Анны горит" and first["tick"] == 4 and len(got["items"]) == min(highlights.MAX_PICKS, len(cands))
    bad = highlights.Highlighter(FakeClient("no json")).pick(ticks)
    assert bad["source"] == "rules" and bad["items"]


def test_quiet_day_has_no_highlights():
    assert highlights.Highlighter(None).pick([{"tick": 0, "events": [], "decisions": {}}]) is None


def test_second_person_events_name_who_and_stay_apart():
    ev = lambda to: {"kind": "starving", "text": "You are starving and losing health! Eat something.",
                     "actor": None, "visibility": "private", "to": [to]}
    ticks = [{"tick": 3, "decisions": {}, "events": [ev("Boris"), ev("Clara")]},
             {"tick": 4, "decisions": {}, "events": [ev("Boris")]}]
    c = highlights.candidates(ticks)
    assert [(x["event"].split(":")[0], x["times"], x["who"]) for x in c] == [("Boris", 2, ["Boris"]),
                                                                             ("Clara", 1, ["Clara"])]
