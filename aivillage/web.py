"""The public website (docs/site.md): one shared password, then every browser plays in its own workspace.

Runs in the hosting container (Dockerfile):

    AIVILLAGE_SITE_PASSWORD=... python -m aivillage.web --port $PORT --data /data

A browser that logs in gets a workspace: a random secret in the `aiv_ws` cookie. The workspace has its own game
server (`aivillage.server --setup` on a local port, started on its first request and stopped after
IDLE_MINUTES without visits while no village plays), its own runs, saves and daily spending under
<data>/ws/<id>. So several games run at once and nobody sees another's village or keys.

Keys never touch the disk: the game server keeps them in memory (AIVILLAGE_KEYS_IN_MEMORY, aivillage/keys.py)
and the browser keeps its own copy and sends it again after a restart (viewer/settings.js). Model keys in the
hosting's environment are never passed to a game server, and request bodies are never logged.

Without the password only these answer: /login, /healthz (how many villages play; the deploy gate
.github/workflows/site-deploy.yml waits for 0) and a workspace's MCP connector /p/<id>/mcp/... (the MCP
tournament's invite links; the game server itself also refuses anything else that comes from outside).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import html
import os
import secrets
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from contextlib import asynccontextmanager
from urllib.parse import parse_qs, quote

import httpx
import websockets
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from starlette.background import BackgroundTask

from . import keys

IDLE_MINUTES = 30  # a workspace's game server stops this long after its last visit, unless a village plays
MAX_GAMES = 8  # game servers at once (each ~100-200 MB)
START_TIMEOUT = 60.0  # seconds a new game server may take to listen
WS_COOKIE, AUTH_COOKIE = "aiv_ws", "aiv_auth"
COOKIE_DAYS = 365
PUBLIC_PREFIXES = ("/mcp/", "/.well-known/")  # what a workspace serves at /p/<id>/... without the password
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers",
       "transfer-encoding", "upgrade", "host", "cookie", "content-length", "origin",
       # the game server trusts proxy headers from 127.0.0.1 (uvicorn): a visitor's address there would lock
       # them out of their own settings (server.local_only)
       "forwarded", "x-forwarded-for", "x-forwarded-proto", "x-forwarded-host", "x-forwarded-port", "x-real-ip"}
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
# never handed to a game server: the hosting's own model keys and the site's password and secret
HIDDEN_ENV = (*keys.ENV.values(), "AIVILLAGE_SITE_PASSWORD", "AIVILLAGE_SITE_SECRET")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@dataclass
class Game:
    """One workspace's game server."""
    rid: str
    port: int
    proc: subprocess.Popen
    last: float = field(default_factory=time.monotonic)

    def alive(self) -> bool:
        return self.proc.poll() is None


class Site:
    def __init__(self, data: Path, password: str, secret: str | None = None, public_url: str = "",
                 max_games: int = MAX_GAMES, idle_minutes: float = IDLE_MINUTES, python: str = sys.executable):
        if not password:
            raise ValueError("AIVILLAGE_SITE_PASSWORD is not set: the site never opens without a password")
        self.data, self.password = Path(data), password
        self.secret = (secret or self._secret()).encode()
        self.public_url = public_url.rstrip("/")
        self.max_games, self.idle = max_games, idle_minutes * 60
        self.python = python
        self.games: dict[str, Game] = {}
        self._lock = asyncio.Lock()

    def _secret(self) -> str:
        """Signs the cookies; kept on the volume so logins survive a redeploy."""
        f = self.data / "secret"
        try:
            return f.read_text().strip()
        except OSError:
            self.data.mkdir(parents=True, exist_ok=True)
            s = secrets.token_hex(32)
            f.write_text(s)
            f.chmod(0o600)
            return s

    # --- cookies ---
    def auth_token(self) -> str:
        """Changes with the password: a new password logs everybody out."""
        return hmac.new(self.secret, b"login:" + self.password.encode(), hashlib.sha256).hexdigest()

    def logged_in(self, cookies: dict) -> bool:
        return hmac.compare_digest(cookies.get(AUTH_COOKIE, ""), self.auth_token())

    def check_password(self, given: str) -> bool:
        return hmac.compare_digest(given.strip().encode(), self.password.strip().encode())

    def rid(self, ws: str) -> str:
        """The workspace's public id (its folder, its MCP links). The cookie secret itself never leaves the browser."""
        return hmac.new(self.secret, b"ws:" + ws.encode(), hashlib.sha256).hexdigest()[:24]

    # --- game servers ---
    def home(self, rid: str) -> Path:
        return self.data / "ws" / rid

    def env(self, rid: str, base: str) -> dict:
        env = {k: v for k, v in os.environ.items() if k not in HIDDEN_ENV}
        env.update(AIVILLAGE_HOME=str(self.home(rid)), AIVILLAGE_KEYS_IN_MEMORY="1",
                   AIVILLAGE_PUBLIC_URL=f"{base}/p/{rid}", PYTHONUNBUFFERED="1")
        return env

    async def game(self, rid: str, base: str) -> Game:
        """The workspace's running game server, started if needed. RuntimeError when the site is full."""
        async with self._lock:
            g = self.games.get(rid)
            if g and g.alive():
                g.last = time.monotonic()
                return g
            self.games.pop(rid, None)
            if len(self.games) >= self.max_games:
                await self.reap(force_idle=True)
            if len(self.games) >= self.max_games:
                raise RuntimeError("full")
            home = self.home(rid)
            (home / "runs").mkdir(parents=True, exist_ok=True)
            port = free_port()
            proc = subprocess.Popen(
                [self.python, "-m", "aivillage.server", "--setup", "--host", "127.0.0.1", "--port", str(port),
                 "--runs", str(home / "runs"), "--reports", str(home / "reports")],
                env=self.env(rid, self.public_url or base), cwd=str(Path(__file__).resolve().parents[1]))
            g = Game(rid, port, proc)
            self.games[rid] = g
        deadline = time.monotonic() + START_TIMEOUT
        while time.monotonic() < deadline and g.alive():
            try:
                _, w = await asyncio.open_connection("127.0.0.1", port)
                w.close()
                return g
            except OSError:
                await asyncio.sleep(0.2)
        g.proc.kill()
        raise RuntimeError("did not start")

    async def busy(self, g: Game) -> bool:
        """A village or an experiment is playing there (it must not be stopped)."""
        try:
            async with httpx.AsyncClient(timeout=3) as c:
                return bool((await c.get(f"http://127.0.0.1:{g.port}/api/busy")).json().get("busy"))
        except Exception:
            return g.alive()  # can't tell: leave it alone

    async def reap(self, force_idle: bool = False) -> None:
        """Stop game servers nobody visited for `idle` seconds (any idle ones when the site is full),
        unless a village plays there. Its saves stay on the volume."""
        now = time.monotonic()
        for rid, g in list(self.games.items()):
            if not g.alive():
                self.games.pop(rid, None)
            elif (force_idle or now - g.last > self.idle) and now - g.last > 60 and not await self.busy(g):
                stop(g.proc)
                self.games.pop(rid, None)

    async def playing(self) -> int:
        return sum([await self.busy(g) for g in list(self.games.values()) if g.alive()])

    def shutdown(self) -> None:
        for g in self.games.values():
            stop(g.proc)


def stop(proc: subprocess.Popen, wait: float = 10.0) -> None:
    if proc.poll() is None:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(wait)
        except subprocess.TimeoutExpired:
            proc.kill()


LOGIN = """<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>AI Village</title>
<style>body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:#1d2321;
color:#e8efe9;font:16px system-ui,sans-serif}form{background:#262e2b;padding:28px;border-radius:12px;width:300px;
max-width:calc(100vw - 72px);box-shadow:0 6px 24px rgba(0,0,0,.45)}h1{margin:0 0 6px;font-size:22px}
p{margin:0 0 16px;color:#9db0a4;font-size:14px}input,button{width:100%;box-sizing:border-box;border-radius:8px;
padding:10px;font:16px system-ui,sans-serif}input{background:#1d2321;color:#e8efe9;border:1px solid #4a5650}
button{margin-top:12px;border:0;background:#76b041;color:#1d2321;font-weight:600;cursor:pointer}
.bad{color:#ff8a72;margin:10px 0 0;font-size:14px}</style></head><body>
<form method="post" action="/login"><h1>🏡 AI Village</h1><p>Деревня, где живут ИИ. Введите пароль.</p>
<input type="hidden" name="next" value="__NEXT__">
<input name="password" type="password" placeholder="пароль" autofocus autocomplete="current-password">
<button>Войти</button>__ERR__</form></body></html>"""

BUSY = """<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>AI Village</title>
<meta http-equiv="refresh" content="20"></head><body style="background:#1d2321;color:#e8efe9;font:16px system-ui;
padding:40px">Сейчас на сайте играет слишком много деревень. Страница сама попробует снова через 20 секунд.</body></html>"""


def base_url(request) -> str:
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}"


def same_site(conn) -> bool:
    """A browser request from another website (its `Origin`) may not use a logged-in player's cookies. The game
    server behind gets no `Origin` at all: it sees the site as this computer (its own guard, server.py)."""
    origin = conn.headers.get("origin")
    if origin is None:
        return True
    return origin.rstrip("/").lower() == base_url(conn).lower()


def create_app(site: Site) -> FastAPI:
    async def reaper() -> None:
        while True:
            await asyncio.sleep(60)
            try:
                await site.reap()
            except Exception as e:  # keep reaping
                print(f"site: reap failed: {type(e).__name__}: {e}", flush=True)

    @asynccontextmanager
    async def lifespan(app):
        app.state.client = httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=None, write=None, pool=None))
        task = asyncio.create_task(reaper())
        try:
            yield
        finally:
            task.cancel()
            await app.state.client.aclose()
            site.shutdown()

    app = FastAPI(title="AI Village site", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)

    def secure(request) -> bool:
        return base_url(request).startswith("https:")

    def set_cookie(resp, request, name: str, value: str) -> None:
        resp.set_cookie(name, value, max_age=COOKIE_DAYS * 86400, httponly=True, samesite="lax", secure=secure(request))

    def safe_next(nxt: str) -> str:
        return nxt if nxt.startswith("/") and not nxt.startswith("//") else "/"

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"ok": True, "playing": await site.playing(), "games": len(site.games)}

    @app.get("/login", response_class=HTMLResponse)
    def login_page(next: str = "/") -> str:
        return LOGIN.replace("__NEXT__", html.escape(safe_next(next))).replace("__ERR__", "")

    @app.post("/login")
    async def login(request: Request):
        form = parse_qs((await request.body()).decode("utf-8", "replace"))
        nxt = safe_next((form.get("next") or ["/"])[0])
        if not site.check_password((form.get("password") or [""])[0]):
            await asyncio.sleep(1.0)  # slows down guessing
            page = LOGIN.replace("__NEXT__", html.escape(nxt)).replace(
                "__ERR__", '<p class="bad">Пароль не подошёл.</p>')
            return HTMLResponse(page, status_code=401)
        resp = RedirectResponse(nxt, status_code=303)
        set_cookie(resp, request, AUTH_COOKIE, site.auth_token())
        if not request.cookies.get(WS_COOKIE):
            set_cookie(resp, request, WS_COOKIE, secrets.token_hex(16))
        return resp

    async def forward(request: Request, g: Game, path: str, public: bool) -> Response:
        headers = [(k, v) for k, v in request.headers.raw if k.decode("latin-1").lower() not in HOP]
        has_body = "content-length" in request.headers or "transfer-encoding" in request.headers
        if public:  # the game server's own guard (mcpserver.OutsideOnlyMcp) treats it as outside traffic
            headers.append((b"cf-ray", b"site"))
        url = f"http://127.0.0.1:{g.port}{quote(path)}" + (f"?{request.url.query}" if request.url.query else "")
        client = request.app.state.client
        req = client.build_request(request.method, url, headers=headers,
                                   content=request.stream() if has_body else None)
        try:
            r = await client.send(req, stream=True)
        except httpx.HTTPError:
            return Response("Игра не отвечает, обновите страницу.", status_code=502)
        out = [(k, v) for k, v in r.headers.raw if k.decode("latin-1").lower() not in HOP | {"set-cookie"}]
        resp = StreamingResponse(r.aiter_raw(), status_code=r.status_code, background=BackgroundTask(r.aclose))
        resp.raw_headers = out
        return resp

    @app.api_route("/p/{rid}/{path:path}", methods=["GET", "POST", "DELETE", "OPTIONS", "HEAD"])
    async def public(rid: str, path: str, request: Request) -> Response:
        """A workspace's MCP connector, open without the password (the tournament's AIs connect here)."""
        path = "/" + path
        g = site.games.get(rid)
        if not path.startswith(PUBLIC_PREFIXES) or g is None or not g.alive():
            return Response("Not found", status_code=404)
        g.last = time.monotonic()
        return await forward(request, g, path, public=True)

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])
    async def private(path: str, request: Request) -> Response:
        ws = request.cookies.get(WS_COOKIE, "")
        if request.method not in SAFE_METHODS and not same_site(request):
            return JSONResponse({"detail": "Запрос с чужого сайта."}, status_code=403)
        if not site.logged_in(request.cookies) or not ws:
            if request.method == "GET" and not path.startswith("api/"):
                target = "/" + path + (f"?{request.url.query}" if request.url.query else "")
                return RedirectResponse("/login?next=" + quote(target, safe=""), status_code=303)
            return JSONResponse({"detail": "Войдите на сайт заново (нужен пароль)."}, status_code=401)
        try:
            g = await site.game(site.rid(ws), base_url(request))
        except RuntimeError:
            return HTMLResponse(BUSY, status_code=503)
        return await forward(request, g, "/" + path, public=False)

    @app.websocket("/{path:path}")
    async def socket_(path: str, websocket: WebSocket) -> None:
        ws = websocket.cookies.get(WS_COOKIE, "")
        if not site.logged_in(websocket.cookies) or not ws or not same_site(websocket):
            await websocket.close(code=1008)
            return
        try:
            g = await site.game(site.rid(ws), base_url(websocket))
        except RuntimeError:
            await websocket.close(code=1013)
            return
        await websocket.accept()
        q = f"?{websocket.url.query}" if websocket.url.query else ""
        try:
            async with websockets.connect(f"ws://127.0.0.1:{g.port}/{path}{q}", max_size=None) as up:
                async def down() -> None:
                    async for msg in up:
                        g.last = time.monotonic()
                        await (websocket.send_text(msg) if isinstance(msg, str) else websocket.send_bytes(msg))

                async def upward() -> None:
                    while True:
                        m = await websocket.receive()
                        if m["type"] == "websocket.disconnect":
                            return
                        await up.send(m["text"] if m.get("text") is not None else m.get("bytes") or b"")

                tasks = [asyncio.create_task(down()), asyncio.create_task(upward())]
                _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for t in pending:
                    t.cancel()
        except Exception:
            pass
        try:
            await websocket.close()
        except Exception:
            pass

    return app


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="AI Village website: password, then one game per browser.")
    p.add_argument("--port", type=int, default=int(os.environ.get("PORT") or 8080))
    p.add_argument("--data", default=os.environ.get("AIVILLAGE_DATA") or "/data")
    p.add_argument("--max-games", type=int, default=int(os.environ.get("AIVILLAGE_MAX_GAMES") or MAX_GAMES))
    a = p.parse_args(argv)
    domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN")
    public_url = os.environ.get("AIVILLAGE_PUBLIC_URL") or (f"https://{domain}" if domain else "")
    site = Site(Path(a.data), os.environ.get("AIVILLAGE_SITE_PASSWORD", ""), os.environ.get("AIVILLAGE_SITE_SECRET"),
                public_url, max_games=a.max_games)
    import uvicorn
    print(f"AI Village site on port {a.port}, data in {a.data}", flush=True)
    uvicorn.run(create_app(site), host="0.0.0.0", port=a.port, log_level="warning", proxy_headers=True,
                forwarded_allow_ips="*")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
