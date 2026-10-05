"""Bundle the viewer and one run log into a single self-contained HTML file.

    python scripts/build_demo.py runs/demo.jsonl out/demo.html [--fragment]

--fragment drops the <html>/<head>/<body> wrapper (for hosts that add their own).
"""
import json
import re
import sys
from pathlib import Path

log, out = Path(sys.argv[1]), Path(sys.argv[2])
html = (Path(__file__).parent.parent / "viewer" / "index.html").read_text()
embed = "<script>window.EMBEDDED_LOG = " + json.dumps(log.read_text()).replace("</", "<\\/") + ";</script>\n"
html = html.replace("<script>\n// Positions", embed + "<script>\n// Positions", 1)
if "--fragment" in sys.argv:
    html = re.sub(r"<!doctype html>|</?html[^>]*>|</?head>|</?body>|<meta[^>]*>", "", html)
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(html)
print(f"{out} ({out.stat().st_size // 1024} KB)")
