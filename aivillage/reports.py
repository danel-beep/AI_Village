"""Problem reports: the run log plus the player's note, packed into one zip to drop into the project chat.

    python -m aivillage.reports show report.zip [--hours 3]   # read a report: note + what happened around it

Made by the viewer's "Сообщить о проблеме" button (POST /api/report on the live server) or by the
start screen, or by a session summary's "📦 Файл для Claude" (`session_<time>.zip`, plus `session.md` /
`session.json`, aivillage/session.py). A report holds `report.json` (note, the tick the player was looking at, versions),
`run.jsonl` (the whole replayable log so far) and `summary.json` (recaps, if any).
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

from . import logio
from .clock import per_hour
from .summary import digest, ticks_of


def make_report(out_dir: str | Path, log: str | Path | None, note: str, tick: int | None = None,
                extra: dict | None = None, summaries: list[dict] | None = None,
                files: dict[str, str] | None = None, prefix: str = "report") -> Path:
    """`files`: more text files for the zip (a session's summary), `prefix`: the zip name's first word."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    path = out_dir / f"{prefix}_{now:%Y-%m-%d_%H-%M-%S}.zip"
    meta = {"note": note.strip(), "tick": tick, "created": now.isoformat(timespec="seconds"),
            "log_name": Path(log).name if log else None, "python": sys.version.split()[0],
            "os": platform.platform(), **(extra or {})}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("report.json", json.dumps(meta, ensure_ascii=False, indent=1))
        if log and Path(log).exists():
            z.write(log, "run.jsonl")
        if summaries:
            z.writestr("summary.json", json.dumps(summaries, ensure_ascii=False, indent=1))
        for name, text in (files or {}).items():
            z.writestr(name, text)
    return path


def reveal(path: Path) -> None:
    """Show the file in the system file manager so it can be dragged into the chat."""
    try:
        if sys.platform.startswith("win"):
            subprocess.Popen(["explorer", "/select,", str(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path.parent)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def read_report(path: str | Path) -> tuple[dict, list[dict]]:
    with zipfile.ZipFile(path) as z:
        meta = json.loads(z.read("report.json"))
        recs = []
        if "run.jsonl" in z.namelist():
            recs = list(logio.parse(z.read("run.jsonl").decode("utf-8").splitlines()))
    return meta, recs


def around(recs: list[dict], tick: int | None, hours: int) -> list[dict]:
    ticks = ticks_of(recs)
    cfg = next((r["config"] for r in recs if r.get("type") == "header"), {})
    n = hours * per_hour(cfg)  # old hourly logs have no tick_minutes: one tick per hour
    if tick is None:
        return ticks[-n:]
    return [t for t in ticks if tick - n <= t["tick"] <= tick + 1]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Read a problem report made by the viewer.")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("show")
    s.add_argument("zip")
    s.add_argument("--hours", type=int, default=3, help="game hours before the reported moment to print")
    a = p.parse_args(argv)
    meta, recs = read_report(a.zip)
    print(json.dumps(meta, ensure_ascii=False, indent=1))
    with zipfile.ZipFile(a.zip) as z:  # a session zip ("📦 Файл для Claude") has its summary too
        if "session.md" in z.namelist():
            print("\n" + z.read("session.md").decode("utf-8"))
    ticks = ticks_of(recs)
    print(f"\nlog: {len(ticks)} ticks" + (f", last tick {ticks[-1]['tick']}" if ticks else ""))
    errors = [e for t in ticks for e in t.get("events") or [] if e.get("kind") == "error"]
    print(f"rejected actions in the whole log: {len(errors)}")
    cfg = next((r["config"] for r in recs if r.get("type") == "header"), None)
    print("\n" + digest(around(recs, meta.get("tick"), a.hours), max_lines=400, cfg=cfg))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
