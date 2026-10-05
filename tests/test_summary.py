import json

from aivillage import engine, reports, summary
from aivillage.run import bots_decider, read_log, replay, run


def make_log(tmp_path, days=2):
    w = engine.new_world({"seed": 5})
    log = tmp_path / "r.jsonl"
    run(w, bots_decider(w, ["worker", "thief"], 5), days, log_path=log)
    return log


def test_digest_and_stub_recaps_per_day(tmp_path):
    log = make_log(tmp_path)
    ticks = summary.ticks_of(read_log(log))
    text = summary.digest(ticks)
    assert "D1 " in text and len(text.splitlines()) <= summary.MAX_LINES
    assert len(summary.digest(ticks, max_lines=20).splitlines()) <= 20
    assert summary.main([str(log), "--model", "stub", "--md", str(tmp_path / "s.md")]) == 0
    recaps = json.loads(summary.sidecar_path(log).read_text(encoding="utf-8"))
    assert len(recaps) == 2 and recaps[0]["from"].startswith("день 1") and "заглушка" in recaps[0]["text"]
    assert recaps[0]["to_tick"] < recaps[1]["from_tick"]
    assert "## день 2" in (tmp_path / "s.md").read_text(encoding="utf-8")
    replay(log)  # the sidecar never touches the log


def test_report_roundtrip(tmp_path, capsys):
    log = make_log(tmp_path, days=1)
    path = reports.make_report(tmp_path / "reports", log, "Борис застрял у реки", tick=5, extra={"day": 1})
    meta, recs = reports.read_report(path)
    assert meta["note"] == "Борис застрял у реки" and meta["tick"] == 5 and meta["day"] == 1
    assert recs[0]["type"] == "header" and len(summary.ticks_of(recs)) > 5
    assert reports.main(["show", str(path), "--hours", "2"]) == 0
    assert "Борис застрял" in capsys.readouterr().out
