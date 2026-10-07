"""scripts/build_demo.py leaves out view keys equal to the previous tick's; the viewer must get every view back."""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_slim_views_restore_exactly(tmp_path):
    rows = [{"type": "header", "config": {"agents": []}}]
    base = {"map": {"a": 1}, "social": {"x": [1, 2]}, "day": 1, "agents": {"Anna": {"coins": 3}}}
    for k in range(6):
        view = json.loads(json.dumps(base))
        view["agents"]["Anna"]["coins"] = k            # changes every tick
        if k >= 3:
            view["social"] = {"x": [1, 2, 3]}           # changes once
        if k == 4:
            del view["map"]                             # a key that goes away is not carried over
        rows.append({"type": "tick", "tick": k, "view": view, "events": []})
        if k == 2:
            rows.append({"type": "diary", "agent": "Anna", "text": "hi"})
    log = tmp_path / "x.jsonl"
    log.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    (tmp_path / "x.highlights.json").write_text("{}")
    out = tmp_path / "x.html"
    subprocess.run([sys.executable, str(ROOT / "scripts" / "build_demo.py"), str(log), str(out)], check=True,
                   stdout=subprocess.DEVNULL)
    embedded = json.loads(re.search(r"window\.EMBEDDED_LOG = (\".*?\");</script>", out.read_text()).group(1)
                          .replace("<\\/", "</"))
    got, ticks = [json.loads(line) for line in embedded.split("\n")], []
    assert any("_keep" in r for r in got)                # it did slim something
    for row in got[1:]:                                 # what Viewer.push does
        if row.get("_keep"):
            for key in row.pop("_keep"):
                row["view"][key] = ticks[-1]["view"][key]
        if row["type"] == "tick":
            ticks.append(row)
    assert [t["view"] for t in ticks] == [r["view"] for r in rows if r["type"] == "tick"]
