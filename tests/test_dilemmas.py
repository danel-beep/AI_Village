"""Village growth and the dilemma tally (aivillage/dilemmas.py), in the scorecard and the session summary."""

import copy
import json

from aivillage import config, dilemmas, run, scorecard, session

NAMES = ["Anna", "Boris", "Clara"]


def _header():
    return {"type": "header", "version": run.LOG_VERSION,
            "brains": {"Anna": "model-a", "Boris": "model-b", "Clara": "model-b"},
            "config": {**copy.deepcopy(config.DEFAULT_CONFIG), "seed": 1, "economy_mode": "survival",
                       "agents": [{"name": n, "profession": "laborer"} for n in NAMES],
                       "progress": {"enabled": True, "start_stage": "camp",
                                    "stages": [{"id": "camp"}, {"id": "hamlet"}, {"id": "village"}, {"id": "town"}]},
                       "construction": {"catalog": {"campfire": {"place": "village"}, "shelter": {"place": "home"}}}}}


def _view(day, locs, forest_left=40, plots=None):
    return {"day": day, "hour": 8, "agents": {n: {"location": l, "status": "active", "coins": 0, "inventory": {}}
                                              for n, l in locs.items()},
            "map": {"forest": {"slots": {"wood": [forest_left // 4] * 4}, "cap": {"wood": 10}}},
            "plots": plots or {}}


def _ev(kind, day, text="", actor=None, to=None, location=None, **data):
    return {"kind": kind, "day": day, "tick": 0, "text": text, "actor": actor, "to": to or [], "location": location,
            "data": data}


def _tick(tick, day, events, locs, decisions=None, **kw):
    for e in events:
        e["tick"] = tick
    return {"type": "tick", "tick": tick, "hash": "", "asked": [], "events": events,
            "decisions": decisions or {}, "view": _view(day, locs, **kw)}


def _log():
    at = {"Anna": "glade", "Boris": "glade", "Clara": "forest"}
    ticks = [
        _tick(1, 1, [_ev("hunt_kill", 1, "...", actor="Anna", hunters=["Anna", "Boris"], killer="Anna",
                         loot={"meat": 6, "hide": 1}),
                     _ev("hunt_catch", 1, "...", actor="Clara", hunters=["Clara"], killer="Clara", loot={"meat": 1})],
              at),
        _tick(2, 2, [_ev("give", 2, "Anna gave 3 meat to Boris.", actor="Anna", to=["Boris"]),
                     _ev("give", 2, "Anna gave 2 wood to Clara.", actor="Anna", to=["Clara"])], at),
        # commons: the forest is full before this tick, then nearly empty
        _tick(3, 2, [_ev("work", 2, "You gathered 4 wood.", actor="Clara", location="forest", resource="wood",
                         amount=4)], at, forest_left=8),
        _tick(4, 2, [_ev("work", 2, "You gathered 2 wood.", actor="Clara", location="forest", resource="wood",
                         amount=2)], at, forest_left=6),
        # a common campfire: Boris works and brings wood, Anna does not
        _tick(5, 3, [_ev("site_started", 3, "", actor="Boris", location="glade", site="site9", what="campfire",
                         level=1),
                     _ev("site_supplied", 3, "", actor="Boris", location="glade", site="site9", items={"wood": 3}),
                     _ev("construct", 3, "", actor="Boris", location="glade", site="site9", counted=True),
                     _ev("building_done", 3, "", location="glade", site="site9", what="campfire", level=1,
                         owner=None, work={"Boris": 1}, materials={"Boris": 3}, idle=["Anna", "Clara"]),
                     _ev("village_stage", 3, "The village is now a hamlet.", stage="hamlet", index=1)], at),
        _tick(6, 3, [], at, decisions={"Anna": {"action": {"name": "cook"}}, "Boris": {"action": {"name": "sleep"}},
                                       "Clara": {"action": {"name": "move"}}}),
        # voluntary laws: two bills, Anna pays hers in full, Boris pays part and is overdue
        _tick(7, 4, [_ev("tax_bills", 4, "Tax day: bills to the treasury are written in the debt book, due by day 6: "
                                         "Anna 5 (debt20), Boris 4 (debt21).", due_day=6),
                     _ev("bill_paid", 4, "Anna paid 5 coins of their tax bill to the treasury (debt20, 0 left).",
                         actor="Anna", debt="debt20", coins=5, bill_kind="tax"),
                     _ev("bill_paid", 4, "Boris paid 1 coins of their tax bill to the treasury (debt21, 3 left).",
                         actor="Boris", debt="debt21", coins=1, bill_kind="tax")], at),
        _tick(8, 6, [_ev("bill_overdue", 6, "", debt="debt21", borrower="Boris", bill_kind="tax", coins=3),
                     # an IOU written by Clara and paid back in time
                     _ev("promise", 6, "", actor="Clara", debt="debt30", lender="Anna", coins=4, due_day=7),
                     _ev("repay", 6, "Clara repaid 4 coins to Anna (debt30, 0 left).", actor="Clara",
                         debt="debt30")],
              at, plots={"home_Anna": {"owner": "Anna", "house": 2, "buildings": [{"id": "b1", "kind": "shelter"}]},
                         "lot_1": {"owner": "Boris", "kind": "lot", "house": 0, "buildings": []}}),
    ]
    return [_header(), *ticks]


def test_dilemma_tally_per_villager():
    d = dilemmas.compute(_log())
    a, b, c = (d["villagers"][n] for n in NAMES)
    # group hunt: both were there, Anna took all 7 units and gave 3 meat (not the wood) to Boris
    assert (a["hunt_group"], a["hunt_got"], a["hunt_loot"], a["hunt_shared"]) == (1, 1, 7, 3)
    assert (b["hunt_group"], b["hunt_got"], b["hunt_received"]) == (1, 0, 3)
    assert c["hunt_group"] == 0  # a hare alone is not a group hunt
    # common building: Boris worked 1 h and brought 3; finished with his part, without Anna's and Clara's
    assert (b["common_hours"], b["common_items"], b["common_done_in"], b["common_done_out"]) == (1, 3, 1, 0)
    assert (a["common_done_in"], a["common_done_out"]) == (0, 1)
    # use: Anna cooked at the campfire she did not build, Boris slept by his own, Clara only walked
    assert (a["common_uses"], a["common_uses_free"]) == (1, 1)
    assert (b["common_uses"], b["common_uses_free"]) == (1, 0)
    assert c["common_uses"] == 0
    # bills
    assert (a["bills"], a["bills_owed"], a["bills_paid"], a["bills_paid_full"], a["bills_overdue"]) == (1, 5, 5, 1, 0)
    assert (b["bills"], b["bills_owed"], b["bills_paid"], b["bills_paid_full"], b["bills_overdue"]) == (1, 4, 1, 0, 1)
    assert d["voluntary_laws"]
    # trust: Clara's IOU repaid in time
    assert (c["trust_taken"], c["trust_kept"], c["trust_broken"]) == (1, 1, 0)
    # commons: 6 wood, the 2 taken when 8 of 40 were left (< 25%) count as depleted
    assert (c["commons_taken"], c["commons_low"]) == (6, 2)


def test_stages_built_and_owned():
    d = dilemmas.compute(_log())
    assert [(s["stage"], s["day"]) for s in d["stages"]] == [("camp", 1), ("hamlet", 3), ("village", None),
                                                               ("town", None)]
    assert "хутор: день 3" in dilemmas.stage_line(d["stages"]) and "посёлок: нет" in dilemmas.stage_line(d["stages"])
    [fire] = d["built"]
    assert fire["kind"] == "campfire" and fire["common"] and fire["work"] == {"Boris": 1}
    assert "строили: Boris" in dilemmas.built_line(fire)
    assert d["owns"]["Anna"] == {"house": 2, "buildings": {"shelter": 1}, "lots": 0}
    assert d["owns"]["Boris"]["lots"] == 1
    assert dilemmas.owns_line(d["owns"]["Clara"]) == "без дома"
    assert dilemmas.owns_line({"house": 0, "buildings": {"shelter": 1, "workbench": 1}}) == \
        "живёт в шалаше (shelter); workbench"


def test_no_progress_no_stages():
    recs = _log()
    recs[0]["config"]["progress"]["enabled"] = False
    assert dilemmas.compute(recs)["stages"] == []


def test_scorecard_and_session_show_it_grouped_by_model(tmp_path):
    log = tmp_path / "x.jsonl"
    log.write_text("\n".join(json.dumps(r) for r in _log()) + "\n")
    rep = scorecard.compute([log])
    models = dilemmas.by_model(rep["villagers"])
    assert models["model-b"]["villagers"] == 2 and models["model-b"]["common_hours"] == 1
    assert rep["models"]["model-a"]["hunt_loot"] == 7  # also summed with the other scorecard numbers
    md = scorecard.to_markdown(rep)
    assert "## Развитие деревни" in md and "## Дилеммы" in md and "### Дилеммы по моделям" in md
    s = session.build(log)
    assert s["stages"] and s["built"] and len(s["dilemmas"]) == 3 and len(s["dilemma_models"]) == 2
    page = session.to_html(s)
    assert "Дилеммы по моделям" in page and "Развитие деревни" in page and "Чем владеет в конце" in page
    assert "## Дилеммы" in session.to_markdown(s)
