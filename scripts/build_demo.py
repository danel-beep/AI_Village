"""Bundle the viewer and one run log into a single self-contained HTML file.

    python scripts/build_demo.py runs/demo.jsonl out/demo.html [--fragment]

A translation sidecar next to the log (<log>.ru.json, see aivillage/translate.py) is embedded too, and
highlights (<log>.highlights.json; picked by rules if missing, see aivillage/highlights.py).
--fragment drops the <html>/<head>/<body> wrapper (for hosts that add their own).
Every tick's view is a full snapshot, but most of it (map, plots, social, honors...) rarely changes: a view key equal
to the previous tick's is left out and named in "_keep", and the viewer (Viewer.push) takes it from the previous
tick. A 40-day log goes from ~34 MB to a few MB. The log file itself is untouched.
"""
import json
import re
import sys
from pathlib import Path

log, out = Path(sys.argv[1]), Path(sys.argv[2])
viewer = Path(__file__).parent.parent / "viewer"
html = (viewer / "index.html").read_text()


def slim(lines):
    prev = {}
    for line in lines:
        if not line.strip():
            continue
        row = json.loads(line)
        view = row.get("view") if row.get("type") == "tick" else None
        if isinstance(view, dict):
            enc = {k: json.dumps(v, sort_keys=True) for k, v in view.items()}
            keep = [k for k in view if prev.get(k) == enc[k]]
            if keep:
                row["view"] = {k: v for k, v in view.items() if k not in keep}
                row["_keep"] = keep
            prev = enc
        yield json.dumps(row, ensure_ascii=False, separators=(",", ":"))


embed = "<script>window.EMBEDDED_LOG = " + json.dumps("\n".join(slim(log.read_text().splitlines()))).replace("</", "<\\/") + ";</script>\n"
tr = log.with_name(log.name.removesuffix(".jsonl") + ".ru.json")
if tr.exists():
    embed += "<script>window.EMBEDDED_TR = " + tr.read_text().replace("</", "<\\/") + ";</script>\n"
hl = log.with_name(log.name.removesuffix(".jsonl") + ".highlights.json")
if not hl.exists():  # no sidecar from a live run: pick highlights by rules (free, no model)
    sys.path.insert(0, str(viewer.parent))
    from aivillage import highlights
    highlights.main([str(log), "--model", "stub"])
if hl.exists():
    embed += "<script>window.EMBEDDED_HIGHLIGHTS = " + hl.read_text(encoding="utf-8").replace("</", "<\\/") + ";</script>\n"
html = re.sub(r'<script src="([\w.]+)"></script>', lambda m: "<script>\n" + (viewer / m[1]).read_text() + "</script>", html)
html = html.replace("<script>", embed + "<script>", 1)
if "--fragment" in sys.argv:
    html = re.sub(r"<!doctype html>|</?html[^>]*>|</?head>|</?body>|<meta[^>]*>", "", html)
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(html)
print(f"{out} ({out.stat().st_size // 1024} KB)")
