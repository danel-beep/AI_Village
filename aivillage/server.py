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
import random
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse

from . import clock, engine, keys, knobs, llm, mapgen, modes, reports
from .highlights import Highlighter, write_sidecar as write_highlights
from .summary import Summarizer, by_day, make_client, when as day_of, write_sidecar
from .registry import GOD, ActionError
from .run import bots_decider, llm_agents, night_reflection, run, with_tick_minutes
from .state import World

ROOT = Path(__file__).resolve().parent.parent
VIEWER = ROOT / "viewer"
VIEW_LAG_MINUTES = 30  # two quarter-hour ticks of buffer: smooth, and a god click lands half an hour later
BACKLOG_TICKS = 5000  # late joiners get the header plus this many recent ticks


class _Stop(Exception):
    pass


class GodQueue:
    """Stands in for run()'s `god_script` dict: each tick takes the queued events that are due.
    An event is never lost: one whose tick already went by (a click racing the sim) lands next tick."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: list[tuple[int, dict]] = []

    def __bool__(self) -> bool:
        return True

    def put(self, ev: dict, tick: int = 0) -> None:
        with self._lock:
            self._pending.append((tick, ev))

    def get(self, tick: int, _default=None) -> list[dict]:
        with self._lock:
            out = [ev for t, ev in self._pending if t <= tick]
            self._pending = [(t, ev) for t, ev in self._pending if t > tick]
        return out


class LiveSim:
    """One running simulation plus its subscribers. Thread-safe toward the asyncio side."""

    def __init__(self, world: World, decide, days: int, log_path: str | None = None, pace: float = 1.0,
                 on_night=None, summarizer: Summarizer | None = None, reports_dir: str | None = None,
                 reveal_reports: bool = False, view_lag_minutes: int = VIEW_LAG_MINUTES):
        self.world, self.decide, self.days, self.log_path = world, decide, days, log_path
        self.on_night = on_night
        # Recaps ("Что произошло?"): one per finished game day in the background, plus on demand.
        self.summarizer = summarizer
        self.summaries: list[dict] = []
        # Highlights ("⭐ Хайлайты дня"): 3-5 dramatic moments per finished day, same model as the recaps,
        # picked by rules alone when recaps are off.
        self.highlighter = Highlighter(summarizer.client if summarizer else None, world.config)
        self.highlights: list[dict] = []
        self._sum_lock = threading.Lock()
        self.reports_dir = reports_dir or str(Path(log_path or "runs/live.jsonl").parent / "reports")
        self.reveal_reports = reveal_reports
        self.pace = pace
        # The picture trails the simulation by this many ticks (the viewer's buffer, for smooth play);
        # a god event lands at least one tick after the moment on screen, at the sim's next tick.
        self.view_lag_ticks = max(1, -(-view_lag_minutes // clock.tick_minutes(world.config)))
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
        if self.ticks and not self.stopping:  # the last day has no "next morning" to trigger its recap
            last = day_of(self.ticks[-1], self.world.config)[0]
            threading.Thread(target=self._end_of_day, args=(last,), daemon=True).start()
        self._publish({"type": "end", "tick": self.world.tick})

    def _on_record(self, rec: dict) -> None:
        if rec["type"] == "header":
            self.header = rec
        elif rec["type"] == "tick":
            new_day = self.ticks and rec["view"]["day"] != self.ticks[-1]["view"]["day"]
            self.ticks.append(rec)
            if new_day:
                threading.Thread(target=self._end_of_day, args=(rec["view"]["day"] - 1,), daemon=True).start()
        self._publish(rec)
        if rec["type"] == "tick":
            self._wait()

    def _wait(self) -> None:
        """Pace the sim so people can watch; block while paused. `pace` is seconds per game hour."""
        per_tick = self.pace / clock.per_hour(self.world.config)
        deadline = time.monotonic() + per_tick
        while not self.stopping:
            if not self.running.is_set():
                self.running.wait(0.2)
                deadline = time.monotonic() + per_tick
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
    def _end_of_day(self, day: int) -> None:
        days = [d for d in by_day(list(self.ticks), self.world.config) if day_of(d[0], self.world.config)[0] == day]
        if self.summarizer:
            self._summarize_day(days)
        self._highlight_day(days[0] if days else [])

    def _highlight_day(self, ticks: list[dict]) -> None:
        try:
            rec = self.highlighter.pick(ticks)
        except Exception:  # highlights must never stop the village
            rec = None
        if not rec:
            return
        with self._sum_lock:
            self.highlights = sorted([h for h in self.highlights if h["day"] != rec["day"]] + [rec],
                                     key=lambda h: h["day"])
            if self.log_path:
                write_highlights(self.log_path, self.highlights)
        self._publish({"type": "highlights", **rec})

    def _summarize_day(self, days: list[list[dict]]) -> None:
        done = max((s["to_tick"] for s in self.summaries), default=-1)
        rest = [t for t in (days[0] if days else []) if t["tick"] > done]  # skip what a button recap covered
        if len(rest) >= 2:
            self.summarize(rest)

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
    def queue_god(self, name: str, args: dict, shown_tick: int | None = None) -> dict:
        """Schedule a god event. `shown_tick` = the tick on the player's screen when they clicked: the event
        lands at the sim's next tick, never before shown_tick + 1, so the viewer can play a lead-in
        animation from the click until the picture reaches the landing tick (announced as `god_pending`)."""
        GOD.parse(name, args)  # reject bad input now; world-dependent errors show up as god_error events
        tick = self.world.tick
        if shown_tick is not None:
            tick = max(tick, int(shown_tick) + 1)
        ev = {"name": name, "args": args}
        self.god.put(ev, tick)
        cfg = self.world.config
        pending = {"type": "god_pending", "tick": tick, "at": clock.label(cfg, tick), **ev,
                   "shown_tick": shown_tick, "lead_minutes": None if shown_tick is None else
                   (tick - int(shown_tick)) * clock.tick_minutes(cfg)}
        self._publish(pending)
        return pending

    def status(self) -> dict:
        return {"tick": self.world.tick, "day": self.world.day, "hour": self.world.hour,
                "minute": self.world.minute, "tick_minutes": clock.tick_minutes(self.world.config),
                "view_lag_ticks": self.view_lag_ticks,
                "paused": not self.running.is_set(), "pace": self.pace, "finished": self.finished,
                "error": self.error}

    def meta(self) -> dict:
        w = self.world
        return {"agents": sorted(w.agents), "locations": {l.id: l.name for l in w.locations.values()},
                "items": sorted(w.config["items"]),
                "god": {n: {"description": s.description, "schema": s.schema()} for n, s in GOD.specs.items()},
                **self.status()}


def make_sim(world: World, *, models: list[str] | None, bots: list[str], seed: int, days: int,
             log_path: str | None, pace: float = 1.0, summary_model: str | None = None,
             reports_dir: str | None = None, reveal_reports: bool = False,
             view_lag_minutes: int = VIEW_LAG_MINUTES) -> LiveSim:
    """Villager brains, nightly diaries and recaps around a fresh world (CLI and start screen alike)."""
    on_night = None
    if models:
        agents = llm_agents(world, models)
        decide = lambda name, obs: agents[name].decide(obs)
        decide.agents = agents  # lets problem reports name the models
        on_night = lambda w, day: night_reflection(w, agents, day)
    else:
        decide = bots_decider(world, bots, seed)
    sm = summary_model or ("default" if keys.has_any_key() else "off")
    summarizer = None if sm == "off" else Summarizer(make_client(sm), world.config)
    return LiveSim(world, decide, days, log_path, pace, on_night, summarizer, reports_dir, reveal_reports,
                   view_lag_minutes)


class Host:
    """The app's current village. With `setup` (the launcher), there is none until the start screen's
    "Play" (`POST /api/start`), and "New village" (`POST /api/stop`) goes back to the start screen."""

    def __init__(self, sim: LiveSim | None = None, runs_dir: str | None = None, reports_dir: str | None = None,
                 reveal_reports: bool = False, setup: bool = False):
        self.sim, self.setup = sim, setup
        self.runs_dir = Path(runs_dir or "runs")
        self.reports_dir = reports_dir
        self.reveal_reports = reveal_reports
        self.last: dict | None = None  # start-screen answers of the current run, to prefill the next one
        self._lock = threading.Lock()

    def start(self, opts: dict) -> LiveSim:
        run_opts = knobs.to_run(opts)  # ValueError on bad input, before anything stops
        seed = run_opts["seed"] or random.SystemRandom().randrange(1, 1_000_000)
        with self._lock:
            self.stop()
            world = engine.new_world(with_tick_minutes({**run_opts["override"], "seed": seed}, run_opts["tick_minutes"]))
            self.runs_dir.mkdir(parents=True, exist_ok=True)
            log = self.runs_dir / f"{datetime.now():%Y-%m-%d_%H-%M-%S}.jsonl"
            sm = None if run_opts["llm"] and run_opts["summaries"] else "off"
            self.sim = make_sim(world, models=["default"] if run_opts["llm"] else None, bots=run_opts["bots"],
                                seed=seed, days=run_opts["days"], log_path=str(log), pace=run_opts["pace"],
                                summary_model=sm, reports_dir=self.reports_dir,
                                reveal_reports=self.reveal_reports)
            self.last = {**run_opts["values"], "seed": None}
            if opts.get("roster"):
                self.last["roster"] = world.config["agents"]
            self.sim.start()
            print(f"Village seed {seed}: {log}")
            return self.sim

    def stop(self) -> None:
        if self.sim is not None:
            self.sim.stop()
            self.sim = None

    def runs(self) -> list[Path]:
        return sorted(self.runs_dir.glob("*.jsonl"), reverse=True) if self.runs_dir.is_dir() else []


def create_app(sim: LiveSim | None = None, host: Host | None = None) -> FastAPI:
    app = FastAPI(title="AI Village live")
    host = host or Host(sim)
    app.state.host = host

    def need() -> LiveSim:
        if host.sim is None:
            raise HTTPException(409, "Деревня ещё не запущена: настройте её и нажмите «Играть».")
        return host.sim

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        # The map viewer stays a plain log viewer; live mode and the god panel are injected here.
        html = (VIEWER / "index.html").read_text(encoding="utf-8")
        if host.sim is None:  # start screen only: settings first, the map comes after "Play"
            inject = '<script src="/settings.js"></script>\n<script src="/setup.js"></script>\n'
        else:
            inject = ('<script src="/live.js"></script>\n<script src="/god.js"></script>\n'
                      '<script src="/report.js"></script>\n<script src="/settings.js"></script>\n')
            if host.setup:
                inject += '<script src="/setup.js"></script>\n'
        return html.replace("</body>", inject + "</body>", 1)

    @app.get("/pixelmap.js")
    def pixelmap_js() -> FileResponse:
        return FileResponse(VIEWER / "pixelmap.js", media_type="text/javascript")

    @app.get("/maplayer.js")
    def maplayer_js() -> FileResponse:
        return FileResponse(VIEWER / "maplayer.js", media_type="text/javascript")

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

    @app.get("/api/summary")
    def summaries() -> dict:
        sim = need()
        return {"enabled": sim.summarizer is not None, "summaries": sim.summaries}

    @app.get("/api/highlights")
    def highlights() -> dict:
        return {"highlights": host.sim.highlights if host.sim else []}

    @app.post("/api/summary")
    def summary_now() -> dict:
        sim = need()
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
        path = need().report(note[:5000], int(tick) if isinstance(tick, (int, float)) else None)
        return {"ok": True, "path": str(path), "name": path.name}

    def local_only(request: Request) -> None:
        # Keys live on this computer; never let another machine on the network read or change them.
        if not request.client or request.client.host not in ("127.0.0.1", "::1", "localhost", "testclient"):
            raise HTTPException(403, "settings are only available on this computer")

    @app.get("/api/settings")
    def settings(request: Request) -> dict:
        local_only(request)
        return {**keys.public(), "default_model": llm.DEFAULT_MODEL, "home": str(keys.home())}

    @app.post("/api/settings")
    def save_settings(body: dict, request: Request) -> dict:
        local_only(request)
        changes = {k: body[k] for k in ("provider", "model", "parallel") if k in body}
        for k in ("openai_key", "openrouter_key"):
            if (body.get(k) or "").strip():  # empty field = keep the saved key
                changes[k] = body[k]
        for k in body.get("clear") or ():
            if k in ("openai_key", "openrouter_key"):
                changes[k] = ""
        try:
            keys.save(changes)
        except (ValueError, TypeError) as e:
            raise HTTPException(400, str(e))
        return {**keys.public(), "default_model": llm.DEFAULT_MODEL, "home": str(keys.home())}

    @app.post("/api/settings/check")
    def check_settings(request: Request) -> dict:
        local_only(request)
        return llm.check()

    # --- start screen (viewer/setup.js) ---
    @app.get("/api/setup")
    def setup_info() -> dict:
        return {**knobs.schema(), "running": host.sim is not None, "can_restart": host.setup,
                "last": host.last, "has_key": keys.has_any_key(),
                "model": keys.get("model") or llm.DEFAULT_MODEL,
                "finished": bool(host.sim and host.sim.finished)}

    @app.post("/api/roster")
    def roster(body: dict) -> dict:
        # Villagers for the "one by one" editor: keeps the ones given, adds seeded names up to n.
        try:
            n = max(1, min(int(body.get("n") or 5), 60))
            seed = int(body.get("seed") or random.SystemRandom().randrange(1, 1_000_000))
            existing = body.get("existing")
            if existing is not None:
                existing = knobs.clean_roster(existing, n)
        except (ValueError, TypeError) as e:
            raise HTTPException(400, str(e)) from None
        return {"roster": knobs.roster(n, seed, existing)}

    @app.post("/api/start")
    def start(body: dict, request: Request) -> dict:
        local_only(request)
        opts = dict(body or {})
        if opts.get("brains", "llm") == "llm" and not keys.has_any_key():
            raise HTTPException(400, "Для ИИ-жителей нужен ключ: «⚙️ Настройки» вверху слева. "
                                     "Или выберите ботов, они бесплатные.")
        try:
            sim = host.start(opts)
        except (ValueError, TypeError) as e:
            raise HTTPException(400, str(e)) from None
        return {"ok": True, **sim.status()}

    @app.post("/api/stop")
    def stop(request: Request) -> dict:
        local_only(request)
        if not host.setup:
            raise HTTPException(400, "this server runs one village (started without --setup)")
        host.stop()
        return {"ok": True}

    @app.get("/api/runs")
    def past_runs(request: Request) -> dict:
        local_only(request)
        current = host.sim.log_path if host.sim else None
        return {"runs": [{"name": r.stem, "kb": r.stat().st_size // 1024} for r in host.runs()[:15]
                         if str(r) != current]}

    @app.get("/replay/{name}", response_class=HTMLResponse)
    def replay_run(name: str, request: Request) -> FileResponse:
        local_only(request)
        log = host.runs_dir / f"{name}.jsonl"
        if not name.replace("-", "").replace("_", "").isalnum() or not log.is_file():
            raise HTTPException(404)
        out = log.with_suffix(".html")
        if not out.is_file() or out.stat().st_mtime < log.stat().st_mtime:
            subprocess.run([sys.executable, str(ROOT / "scripts" / "build_demo.py"), str(log), str(out)],
                           check=True, stdout=subprocess.DEVNULL)
        return FileResponse(out, media_type="text/html")

    @app.post("/api/report-last")
    def report_last(body: dict, request: Request) -> dict:
        local_only(request)
        note = str(body.get("note") or "").strip()
        runs = host.runs()
        if not note or not runs:
            raise HTTPException(400, "Напишите пару слов, что не так." if runs else "Прошлых прогонов пока нет.")
        path = reports.make_report(host.reports_dir or str(host.runs_dir.parent / "reports"), runs[0], note[:5000])
        if host.reveal_reports:
            reports.reveal(path)
        return {"ok": True, "path": str(path), "name": path.name}

    @app.get("/api/meta")
    def meta() -> dict:
        return need().meta()

    @app.get("/api/status")
    def status() -> dict:
        return need().status()

    @app.post("/api/god")
    def god(body: dict) -> dict:
        sim = need()
        try:
            shown = body.get("shown_tick")
            pending = sim.queue_god(str(body.get("name")), body.get("args") or {},
                                    int(shown) if isinstance(shown, (int, float)) else None)
        except ActionError as e:
            raise HTTPException(400, str(e)) from None
        return {"ok": True, "queued_for_tick": pending["tick"], "at": pending["at"],
                "lead_minutes": pending["lead_minutes"]}

    @app.post("/api/control")
    def control(body: dict) -> dict:
        sim = need()
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
        sim = host.sim
        if sim is None:
            await socket.close()
            return
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
    p.add_argument("--seed", type=int, default=None, help="default: a new random village every start")
    p.add_argument("--bots", default="worker,worker,thief,worker,random")
    p.add_argument("--models", default=None, help="OpenRouter model ids (comma-separated) or 'stub'")
    p.add_argument("--agents", type=int, default=0, help="number of villagers (more than 5 get generated names; resources scale up)")
    p.add_argument("--mode", default=modes.DEFAULT_MODE, choices=list(modes.MODES),
                   help="economy mode (aivillage/modes.py)")
    p.add_argument("--log", default="runs/live.jsonl", help="also write the replayable log here")
    p.add_argument("--pace", type=float, default=1.0, help="seconds per game hour (min wait; split over its ticks)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--summary-model", default=None,
                   help="model for the recap panel: OpenRouter id, 'default', 'stub' or 'off' "
                        "(default: llm.DEFAULT_MODEL when OPENROUTER_API_KEY is set, else off)")
    p.add_argument("--reports", default=None, help="where problem reports go (default: <log dir>/reports)")
    p.add_argument("--reveal-reports", action="store_true", help="open the file manager on a new report")
    p.add_argument("--setup", action="store_true",
                   help="start with the in-app start screen (all settings in the browser, then Play)")
    p.add_argument("--runs", default=None, help="with --setup: where run logs go (default: the --log folder)")
    p.add_argument("--tick-minutes", type=int, default=None, choices=clock.ALLOWED,
                   help=f"game minutes per tick (default {clock.RUN_DEFAULT}; 60 = the old hourly turns)")
    p.add_argument("--view-lag-minutes", type=int, default=VIEW_LAG_MINUTES,
                   help="game minutes the picture trails the simulation (viewer buffer for smooth play)")
    mapgen.add_args(p)
    a = p.parse_args(argv)
    if a.seed is None:
        a.seed = random.SystemRandom().randrange(1, 1_000_000)

    import uvicorn

    if a.setup:  # the app's start screen picks everything; the CLI flags are not used
        runs = a.runs or str(Path(a.log).parent)
        host = Host(None, runs, a.reports, a.reveal_reports, setup=True)
        print(f"AI Village: http://{a.host}:{a.port} (настройте деревню и нажмите «Играть»)")
        uvicorn.run(create_app(host=host), host=a.host, port=a.port, log_level="warning")
        return 0

    override: dict = {**modes.world_override(a.mode), "seed": a.seed}
    if modes.disabled(a.mode):
        override["disabled_actions"] = modes.disabled(a.mode)
    if a.agents:
        override["population"] = {"size": a.agents}
    with_tick_minutes(override, a.tick_minutes)
    world = engine.new_world(mapgen.for_run(override, a.fixed_map, a.unfairness))
    print(f"Village seed {a.seed} (run again with --seed {a.seed} to get the same map)")
    sim = make_sim(world, models=a.models.split(",") if a.models else None, bots=a.bots.split(","), seed=a.seed,
                   days=a.days or (3 if a.models else 30), log_path=a.log, pace=a.pace,
                   summary_model=a.summary_model, reports_dir=a.reports, reveal_reports=a.reveal_reports,
                   view_lag_minutes=a.view_lag_minutes)
    sim.start()
    print(f"AI Village live: http://{a.host}:{a.port}")
    uvicorn.run(create_app(sim), host=a.host, port=a.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
