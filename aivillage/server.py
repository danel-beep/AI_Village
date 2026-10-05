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
import threading
import time
from collections import deque
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse

from . import engine
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
                 on_night=None):
        self.world, self.decide, self.days, self.log_path = world, decide, days, log_path
        self.on_night = on_night
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
            self.ticks.append(rec)
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
        inject = '<script src="/live.js"></script>\n<script src="/god.js"></script>\n'
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

    @app.get("/{name}.js")
    def viewer_js(name: str) -> FileResponse:
        # Any other viewer script (dossier.js, ...) that index.html loads by relative path.
        path = VIEWER / f"{name}.js"
        if not name.replace("_", "").isalnum() or not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, media_type="text/javascript")

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
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--bots", default="worker,worker,thief,worker,random")
    p.add_argument("--models", default=None, help="OpenRouter model ids (comma-separated) or 'stub'")
    p.add_argument("--agents", type=int, default=0, help="use only the first N villagers")
    p.add_argument("--log", default="runs/live.jsonl", help="also write the replayable log here")
    p.add_argument("--pace", type=float, default=1.0, help="seconds between ticks (min wait)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
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
        on_night = lambda w, day: night_reflection(w, agents, day)
    else:
        decide = bots_decider(world, a.bots.split(","), a.seed)
    sim = LiveSim(world, decide, a.days, a.log, a.pace, on_night)
    sim.start()
    print(f"AI Village live: http://{a.host}:{a.port}")
    uvicorn.run(create_app(sim), host=a.host, port=a.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
