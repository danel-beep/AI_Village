"""Metrics script: hand-built log for exact numbers, plus a real bot run for consistency."""

import json

from aivillage import engine
from aivillage.metrics import compute, gini, main, read_log, to_markdown
from aivillage.run import bots_decider, run


def ev(tick, day, kind, text="", actor=None, to=(), location=None, **data):
    return {"tick": tick, "day": day, "hour": 8, "kind": kind, "text": text, "actor": actor,
            "location": location, "visibility": "private", "to": list(to), "data": data}


def tick(t, day, events, coins):
    agents = {n: {"location": "square", "status": "active", "coins": c} for n, c in coins.items()}
    return {"type": "tick", "tick": t, "events": events, "view": {"day": day, "hour": 8, "agents": agents}}


def synthetic():
    c = {"Anna": 10, "Boris": 10, "Clara": 10}
    return [
        {"type": "header"},
        tick(0, 1, [
            ev(0, 1, "trade", "Anna and Boris traded: 2 bread for 3 coins.", "Boris", ["Anna"], offer="o1"),
            ev(0, 1, "lend", "Anna lent 5 coins to Boris; Boris must repay 6 by day 2 (debt_1).", "Anna",
               ["Boris"], debt="debt_1"),
            ev(0, 1, "lend", "Clara lent 4 coins to Boris; Boris must repay 5 by day 2 (debt_2).", "Clara",
               ["Boris"], debt="debt_2"),
            ev(0, 1, "lend", "Anna lent 1 coins to Clara; Clara must repay 1 by day 9 (debt_3).", "Anna",
               ["Clara"], debt="debt_3"),
        ], c),
        tick(1, 1, [
            ev(1, 1, "repay", "Boris repaid 6 coins to Anna (debt_1, 0 left).", "Boris", debt="debt_1"),
            ev(1, 1, "steal_attempt", "Clara tried to steal bread from you!", "Clara", ["Anna"]),
            ev(1, 1, "steal", "Your theft from Anna failed.", "Clara", ["Clara"], victim="Anna", success=False,
               witnesses=[]),
            ev(1, 1, "steal", "You stole 2 coins from Boris.", "Clara", ["Clara"], victim="Boris", success=True,
               qty=2, item="coins", witnesses=[]),
            ev(1, 1, "fire", "Smoke!", victim="Anna"),
            ev(1, 1, "extinguish", "Boris threw water", "Boris", location="home_Anna", helper="Boris"),
        ], {"Anna": 0, "Boris": 0, "Clara": 30}),
        tick(2, 2, [
            ev(2, 2, "fire_out", "Clara put out the fire", "Clara", helper="Clara"),
        ], {"Anna": 10, "Boris": 10, "Clara": 10}),
        tick(3, 3, [
            ev(3, 3, "default", "Boris failed to repay Clara on time (5 coins, debt_2).", ),
            ev(3, 3, "repay", "Boris repaid 5 coins to Clara (debt_2, 0 left).", "Boris", debt="debt_2"),
        ], c),
    ]


def test_synthetic_numbers():
    recs = synthetic()
    recs[3]["view"]["agents"]["Clara"]["location"] = "home_Anna"   # fire_out has no location; use view
    m = compute(recs)
    assert m["trades"]["count"] == 1 and m["trades"]["list"][0]["offerer"] == "Anna"
    d = m["debts"]
    assert (d["count"], d["repaid"], d["repaid_late"], d["defaulted"], d["open"]) == (3, 1, 1, 0, 1)
    th = m["thefts"]
    assert (th["attempts"], th["successful"], th["seen"], th["unseen"], th["successful_unseen"]) == (2, 1, 1, 1, 1)
    f = m["fires"]
    assert (f["count"], f["put_out"], f["burned"]) == (1, 1, 0)
    assert f["list"][0]["put_out_by"] == "Clara" and f["list"][0]["responders"] == {"Boris": 1, "Clara": 1}
    assert m["gini_by_day"][1]["gini_coins"] == 0.6667      # last tick of day 1: one person has everything
    assert m["gini_by_day"][2]["gini_coins"] == 0.0
    g = m["interactions"]["graph"]
    assert g["Boris"]["Anna"] == {"repay": 1, "trade": 1, "extinguish": 1}
    assert g["Clara"]["Boris"]["steal"] == 1
    md = to_markdown(m)
    assert "Долги" in md and "Clara (1)" in md


def test_gini_edges():
    assert gini([]) == 0.0 and gini([0, 0]) == 0.0 and gini([5, 5, 5]) == 0.0
    assert gini([0, 0, 0, 10]) == 0.75


def test_real_run_consistent(tmp_path):
    log = tmp_path / "run.jsonl"
    w = engine.new_world({"seed": 3})
    god = {20: [{"name": "fire", "args": {"person": "Anna"}}], 60: [{"name": "fire", "args": {"person": "Boris"}}]}
    stats = run(w, bots_decider(w, ["worker", "thief", "random", "worker"], 3), days=8, god_script=god,
                log_path=log)
    out_json, out_md = tmp_path / "m.json", tmp_path / "m.md"
    assert main([str(log), "--json", str(out_json), "--md", str(out_md)]) == 0
    m = json.loads(out_json.read_text(encoding="utf-8"))
    assert m["ticks"] == len(read_log(log)) - 1
    assert m["trades"]["count"] == stats.get("trade", 0)
    assert m["thefts"]["attempts"] == stats.get("steal", 0)
    assert m["thefts"]["seen"] + m["thefts"]["unseen"] == m["thefts"]["attempts"]
    assert m["debts"]["count"] == stats.get("lend", 0) + stats.get("promise", 0)
    assert m["fires"]["count"] == 2 and m["fires"]["put_out"] + m["fires"]["burned"] <= 2
    assert all(0.0 <= g["gini_coins"] <= 1.0 for g in m["gini_by_day"].values())
    assert "Пожары" in out_md.read_text(encoding="utf-8")
