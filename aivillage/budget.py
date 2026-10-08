"""Daily spending cap for the app («Бюджет в сутки, $» on the start screen, Danel 2026-10-08).

What the models cost (villagers, recaps, highlights) is added up per real calendar day (the computer's
local date) in `<home>/spend.json` (home: keys.home()), shared by every village the app runs that day, so
stopping and continuing a village does not reset the count. When today's total reaches the cap, the
running village pauses before its next tick and goes on by itself on the next real day; it is not stopped.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import date
from pathlib import Path

from . import keys

DEFAULT_USD = 5.0
_lock = threading.Lock()


def today() -> str:
    return date.today().isoformat()


def path() -> Path:
    return keys.home() / "spend.json"


def _load() -> dict:
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def spent_today() -> float:
    with _lock:
        return float(_load().get(today()) or 0.0)


def add(usd: float) -> float:
    """Count `usd` toward today's spending; returns today's total. Only the last 30 days are kept."""
    with _lock:
        data, day = _load(), today()
        data[day] = round(float(data.get(day) or 0.0) + max(0.0, usd), 6)
        data = dict(sorted(data.items())[-30:])
        try:
            path().parent.mkdir(parents=True, exist_ok=True)
            tmp = path().with_name(path().name + ".tmp")  # atomic: a crash mid-write keeps the old count
            tmp.write_text(json.dumps(data), encoding="utf-8")
            os.replace(tmp, path())
        except OSError as e:  # a read-only disk must not stop the village; the cap then counts this run only
            print(f"spend log not written: {e}")
        return data[day]
