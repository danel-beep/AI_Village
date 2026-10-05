"""Live viewer: run the simulation and stream every tick to browsers over WebSocket,
with god-mode buttons and pause / speed controls.

    pip install -e .[live]
    python -m aivillage.server --bots worker,worker,thief,worker,random --days 30
    python -m aivillage.server --models stub --agents 3        # LLM pipeline without a key
    # open http://localhost:8000

The engine is untouched: the sim runs `run.run()` in a background thread, god events are
fed through its `god_script` lookup (so they land in the log and replay stays exact),
and records are fanned out to WebSocket clients via `on_record`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import threading
import time
from collections import deque
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse

from . import engine, reports
from .summary import Summarizer, by_day, make_client, when as day_of, write_sidecar
from .registry import GOD, ActionError
from .run import bots_decider, llm_agents, night_reflection, run
from .state import World

VIEWER = Path(__file__).resolve().parent.parent / "viewer"
BACKLOG_TICKS = 5000  # late joiners get the header plus this many recent ticks


class _Stop(Exception):
    pass


class GodQueue:
    """Stands in for run()'s `god_script` dict: each tick drains whatever the viewer queued."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: list[dict] = []

    def __bool__(self) -> bool:
        return True

    def put(self, ev: dict) -> None:
        with self._lock:
            self._pending.append(ev)

    def get(self, _tick: int, _default=None) -> list[dict]:
        with self._lock:
            out, self._pending = self._pending, []
        return out


class LiveSim:
    """One running simulation plus its subscribers. Thread-safe toward the asyncio side."""

    def __init__(self, world: World, decide, days: int, log_path: str | None = None, pace: float = 1.0,
                 on_night=None, summarizer: Summarizer | None = None, reports_dir: str | None = None,
                 reveal_reports: bool = False):
        self.world, self.decide, self.days, self.log_path = world, decide, days, log_path
        self.on_night = on_night
        # Recaps ("Что произошло?"): one per finished game day in the background, plus on demand.
        self.summarizer = summarizer
        self.summaries: list[dict] = []
        self._sum_lock = threading.Lock()
        self.reports_dir = reports_dir or str(Path(log_path or "runs/live.jsonl").parent / "reports")
        self.reveal_reports = reveal_reports
        self.pace = pace
        self.god = GodQueue()
        self.header: dict | None = None
        self.ticks: deque[dict] = deque(maxlen=BACKLOG_TICKS)
        self.running = threading.Event()
        self.running.set()
        self.finished = False
        self.error: str | None = None
        self.stopping = False
        self._lock = threading.Lock()
        self._subs: set[tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = set()
        self._thread: threading.Thread | None = None

    # --- simulation thread ---
    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="sim", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            run(self.world, self.decide, self.days, self.god, self.log_path,
                on_night=self.on_night, on_record=self._on_record)
        except _Stop:
            pass
        except Exception as e:  # surface crashes in the viewer instead of dying silently
            self.error = f"{type(e).__name__}: {e}"
            self._publish({"type": "error", "text": self.error})
        self.finished = True
        self._publish({"type": "end", "tick": self.world.tick})

    def _on_record(self, rec: dict) -> None:
        if rec["type"] == "header":
            self.header = rec
        elif rec["type"] == "tick":
            new_day = self.ticks and rec["view"]["day"] != self.ticks[-1]["view"]["day"]
            self.ticks.append(rec)
            if new_day and self.summarizer:
                threading.Thread(target=self._summarize_day, args=(rec["view"]["day"] - 1,), daemon=True).start()
        self._publish(rec)
        if rec["type"] == "tick":
            self._wait()

    def _wait(self) -> None:
        """Pace the sim so people can watch; block while paused."""
        deadline = time.monotonic() + self.pace
        while not self.stopping:
            if not self.running.is_set():
                self.running.wait(0.2)
                deadline = time.monotonic() + self.pace
                continue
            left = deadline - time.monotonic()
            if left <= 0:
                return
            time.sleep(min(left, 0.1))
        raise _Stop  # stop() asked the thread to end

    def stop(self) -> None:
        self.stopping = True
        self.running.set()

    # --- recaps and problem reports ---
    def _summarize_day(self, day: int) -> None:
        days = [d for d in by_day(list(self.ticks), self.world.config) if day_of(d[0], self.world.config)[0] == day]
        if days:
            self.summarize(days[0])

    def summarize(self, ticks: list[dict] | None = None) -> dict | None:
        """Recap `ticks`, or by default everything since the last recap (at least the last 4 hours)."""
        if not self.summarizer:
            return None
        with self._sum_lock:
            if ticks is None:
                done = max((s["to_tick"] for s in self.summaries), default=-1)
                ticks = [t for t in self.ticks if t["tick"] > done] or list(self.ticks)[-4:]
                if len(ticks) < 4:
                    ticks = list(self.ticks)[-4:]
            try:
                rec = self.summarizer.summarize(ticks)
            except Exception as e:  # a failed recap must never stop the village
                rec = {"error": f"{type(e).__name__}: {e}"}
            if rec and "error" not in rec:
                self.summaries.append(rec)
                self.summaries.sort(key=lambda r: r["from_tick"])
                if self.log_path:
                    write_sidecar(self.log_path, self.summaries)
                self._publish({"type": "summary", **rec})
            return rec

    def report(self, note: str, tick: int | None) -> Path:
        extra = {"live_tick": self.world.tick, "day": self.world.day, "hour": self.world.hour,
                 "paused": not self.running.is_set(), "error": self.error,
                 "models": sorted({getattr(getattr(a, "client", None), "model", "?")
                                   for a in getattr(self.decide, "agents", {}).values()})}
        path = reports.make_report(self.reports_dir, self.log_path, note, tick, extra, self.summaries)
        if self.reveal_reports:
            reports.reveal(path)
        return path

    # --- fan-out ---
    def _publish(self, rec: dict) -> None:
        msg = json.dumps(rec, ensure_ascii=False)
        with self._lock:
            subs = list(self._subs)
        for loop, q in subs:
            loop.call_soon_threadsafe(q.put_nowait, msg)

    def subscribe(self) -> tuple[asyncio.Queue, list[str]]:
        """New client: a queue for future records and the backlog to send first."""
        q: asyncio.Queue = asyncio.Queue()
        with self._lock:
            backlog = ([self.header] if self.header else []) + list(self.ticks)
            self._subs.add((asyncio.get_running_loop(), q))
        return q, [json.dumps(r, ensure_ascii=False) for r in backlog]

    def unsubscribe(self, q: asyncio.Queue) -> None:
        with self._lock:
            self._subs = {s for s in self._subs if s[1] is not q}

    # --- controls ---
    def queue_god(self, name: str, args: dict) -> None:
        GOD.parse(name, args)  # reject bad input now; world-dependent errors show up as god_error events
        self.god.put({"name": name, "args": args})

    def status(self) -> dict:
        return {"tick": self.world.tick, "day": self.world.day, "hour": self.world.hour,
                "paused": not self.running.is_set(), "pace": self.pace, "finished": self.finished,
                "error": self.error}

    def meta(self) -> dict:
        w = self.world
        return {"agents": sorted(w.agents), "locations": {l.id: l.name for l in w.locations.values()},
                "items": sorted(w.config["items"]),
                "god": {n: {"description": s.description, "schema": s.schema()} for n, s in GOD.specs.items()},
                **self.status()}


def create_app(sim: LiveSim) -> FastAPI:
    app = FastAPI(title="AI Village live")
    app.state.sim = sim

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        # The map viewer stays a plain log viewer; live mode and the god panel are injected here.
        html = (VIEWER / "index.html").read_text(encoding="utf-8")
        inject = ('<script src="/live.js"></script>\n<script src="/god.js"></script>\n'
                  '<script src="/report.js"></script>\n')
        return html.replace("</body>", inject + "</body>", 1)

    @app.get("/pixelmap.js")
    def pixelmap_js() -> FileResponse:
        return FileResponse(VIEWER / "pixelmap.js", media_type="text/javascript")

    @app.get("/live.js")
    def live_js() -> FileResponse:
        return FileResponse(VIEWER / "live.js", media_type="text/javascript")

    @app.get("/god.js")
    def god_js() -> FileResponse:
        return FileResponse(VIEWER / "god.js", media_type="text/javascript")

    @app.get("/report.js")
    def report_js() -> FileResponse:
        return FileResponse(VIEWER / "report.js", media_type="text/javascript")

    @app.get("/api/summary")
    def summaries() -> dict:
        return {"enabled": sim.summarizer is not None, "summaries": sim.summaries}

    @app.post("/api/summary")
    def summary_now() -> dict:
        if sim.summarizer is None:
            raise HTTPException(400, "Сводки выключены: нужен ключ OpenRouter.")
        rec = sim.summarize()
        if rec is None:
            raise HTTPException(400, "Пока нечего пересказывать.")
        if "error" in rec:
            raise HTTPException(502, "Модель не ответила: " + rec["error"])
        return rec

    @app.post("/api/report")
    def report(body: dict) -> dict:
        note = str(body.get("note") or "").strip()
        if not note:
            raise HTTPException(400, "Напишите пару слов, что не так.")
        tick = body.get("tick")
        path = sim.report(note[:5000], int(tick) if isinstance(tick, (int, float)) else None)
        return {"ok": True, "path": str(path), "name": path.name}

    @app.get("/api/meta")
    def meta() -> dict:
        return sim.meta()

    @app.get("/api/status")
    def status() -> dict:
        return sim.status()

    @app.post("/api/god")
    def god(body: dict) -> dict:
        try:
            sim.queue_god(str(body.get("name")), body.get("args") or {})
        except ActionError as e:
            raise HTTPException(400, str(e)) from None
        return {"ok": True, "queued_for_tick": sim.world.tick}

    @app.post("/api/control")
    def control(body: dict) -> dict:
        cmd = body.get("cmd")
        if cmd == "pause":
            sim.running.clear()
        elif cmd == "resume":
            sim.running.set()
        elif cmd == "pace":
            sim.pace = max(0.0, min(60.0, float(body.get("seconds", 1.0))))
        else:
            raise HTTPException(400, f"unknown command {cmd!r}")
        return sim.status()

    @app.websocket("/ws")
    async def ws(socket: WebSocket) -> None:
        await socket.accept()
        q, backlog = sim.subscribe()
        try:
            for msg in backlog:
                await socket.send_text(msg)
            while True:
                await socket.send_text(await q.get())
        except WebSocketDisconnect:
            pass
        finally:
            sim.unsubscribe(q)

    return app


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Run the AI Village and watch it live in the browser.")
    p.add_argument("--days", type=int, default=None, help="default 3 with --models (test runs), 30 with bots")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--bots", default="worker,worker,thief,worker,random")
    p.add_argument("--models", default=None, help="OpenRouter model ids (comma-separated) or 'stub'")
    p.add_argument("--agents", type=int, default=0, help="use only the first N villagers")
    p.add_argument("--log", default="runs/live.jsonl", help="also write the replayable log here")
    p.add_argument("--pace", type=float, default=1.0, help="seconds between ticks (min wait)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--summary-model", default=None,
                   help="model for the recap panel: OpenRouter id, 'default', 'stub' or 'off' "
                        "(default: llm.DEFAULT_MODEL when OPENROUTER_API_KEY is set, else off)")
    p.add_argument("--reports", default=None, help="where problem reports go (default: <log dir>/reports)")
    p.add_argument("--reveal-reports", action="store_true", help="open the file manager on a new report")
    a = p.parse_args(argv)

    import uvicorn

    override: dict = {"seed": a.seed}
    if a.agents:
        from .config import DEFAULT_CONFIG
        override["agents"] = DEFAULT_CONFIG["agents"][: a.agents]
    world = engine.new_world(override)
    on_night = None
    if a.models:
        agents = llm_agents(world, a.models.split(","))
        decide = lambda name, obs: agents[name].decide(obs)
        decide.agents = agents  # lets problem reports name the models
        on_night = lambda w, day: night_reflection(w, agents, day)
    else:
        decide = bots_decider(world, a.bots.split(","), a.seed)
    sm = a.summary_model or ("default" if os.environ.get("OPENROUTER_API_KEY") else "off")
    summarizer = None if sm == "off" else Summarizer(make_client(sm), world.config)
    days = a.days or (3 if a.models else 30)
    sim = LiveSim(world, decide, days, a.log, a.pace, on_night, summarizer, a.reports, a.reveal_reports)
    sim.start()
    print(f"AI Village live: http://{a.host}:{a.port}")
    uvicorn.run(create_app(sim), host=a.host, port=a.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
