"""Light log: tick views written as deltas.

Every tick record carries a `view` (what the viewer draws), and most of it (map, plots, social, honors...)
rarely changes. A view key whose value equals the previous tick's is left out of the record and named in
`_keep`; readers take it from the previous tick. The first tick of a file (and of each run appended to it)
is always whole. The engine never reads views, so replay and world hashes are unaffected.

Writers: `ViewDeltas.compact(rec)`. Readers: `read_log(path)` / `expand(records)` give whole views back.
The viewer does the same in `Viewer.push` (viewer/index.html).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Iterator


class ViewDeltas:
    """Turns a stream of tick records into delta records. Keeps the previous view as JSON text, so a view
    that shares objects with the live world is compared by what was written, not by what it is now."""

    def __init__(self) -> None:
        self.prev: dict[str, str] = {}

    def compact(self, rec: dict) -> dict:
        view = rec.get("view") if rec.get("type") == "tick" else None
        if not isinstance(view, dict):
            return rec
        enc = {k: json.dumps(v, ensure_ascii=False, sort_keys=True) for k, v in view.items()}
        keep = [k for k in view if self.prev.get(k) == enc[k]]
        self.prev = enc
        if not keep:
            return rec
        return {**rec, "view": {k: v for k, v in view.items() if k not in keep}, "_keep": keep}

    def reset(self) -> None:
        """The next tick is written whole (a reader may start there)."""
        self.prev = {}


def expand(records: Iterable[dict]) -> Iterator[dict]:
    """Delta records back to whole views (records without `_keep` pass through unchanged)."""
    prev: dict | None = None
    for rec in records:
        if rec.get("type") == "tick" and isinstance(rec.get("view"), dict):
            keep = rec.get("_keep")
            if keep:
                if prev is None:
                    raise ValueError(f"tick {rec.get('tick')}: view keys {keep} refer to a tick that is not in the log")
                rec = {k: v for k, v in rec.items() if k != "_keep"}
                rec["view"] = {**{k: prev[k] for k in keep}, **rec["view"]}
            prev = rec["view"]
        yield rec


def parse(lines: Iterable[str]) -> Iterator[dict]:
    return expand(json.loads(line) for line in lines if line.strip())


def read_log(path: str | Path) -> Iterator[dict]:
    with open(path, encoding="utf-8") as f:
        yield from parse(f)
