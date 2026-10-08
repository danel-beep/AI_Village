"""MCP endpoint for own AIs: `POST /mcp/<seat code>` speaks MCP (JSON-RPC 2.0, Streamable HTTP, plain JSON
responses, no sessions) so Claude, ChatGPT, Gemini, Claude Code or Codex can add the village as a connector.

Three tools, each the same for every client:
- `join_village(confirm?)`: first call shows the session card the AI must show its person; with the session code
  (after the person said yes) the seat starts playing.
- `next_turn()`: waits up to `remote.CALL_WAIT` s for the villager's next request and returns it as text.
- `answer(request_id, reply)`: the JSON answer to a request; accepted answers return the next request.

A seat code is the only key: one link plays one villager in one session (aivillage/remote.py). Opened in a browser,
the same link shows how to add it to each AI app (viewer/join.html).

Lobby (the «MCP-турнир»): `/mcp/join/<lobby>` is one invite link for every player. The page lets a player take a
free villager under their name and then shows that villager's connector link; `/state` is the table everyone with
the invite sees (who plays whom, alive, wealth), never anyone's connector link. Everything public lives under
`/mcp/`, the only path the internet tunnel reaches."""

from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from . import remote

PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "ai-village", "title": "AI Village", "version": "1"}
INSTRUCTIONS = ("AI Village: you play one villager in a simulated village where every villager is played by an AI. "
                "Start with join_village and follow what it says.")

TOOLS = [
    {"name": "join_village", "title": "Join the village",
     "description": "Join this AI Village session as your villager. Without `confirm` it returns the session card "
                    "to show your person; call it again with confirm = the session code only after they said yes.",
     "inputSchema": {"type": "object", "properties": {
         "confirm": {"type": "string", "description": "The session code, once your person agreed to play."}}},
     "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}},
    {"name": "next_turn", "title": "Wait for my turn",
     "description": "Wait for your villager's next request (a turn, the first-day introduction or the night "
                    "diary) and return it. If it is not your turn yet, call it again.",
     "inputSchema": {"type": "object", "properties": {}},
     "annotations": {"readOnlyHint": True, "openWorldHint": False}},
    {"name": "answer", "title": "Answer a request",
     "description": "Send your answer to a request: request_id from the request, reply = the JSON object it asks "
                    "for. Returns the next request.",
     "inputSchema": {"type": "object", "required": ["request_id", "reply"], "properties": {
         "request_id": {"type": "integer"},
         "reply": {"type": "object", "description": "The JSON object the request asks for."}}},
     "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False,
                     "openWorldHint": False}},
]


def _text(text: str, error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": error}


def _next(seat: remote.Seat, prefix: str = "") -> dict:
    hub = seat.hub
    if hub.closed:
        return _text(prefix + hub.closed_text())
    if not seat.confirmed:
        return _text(prefix + "You have not joined yet: call join_village first.", error=True)
    req = seat.next_request()
    if req is not None:
        return _text(prefix + seat.render(req))
    if hub.closed:
        return _text(prefix + hub.closed_text())
    return _text(prefix + f"Not your turn yet: {seat.name} is busy or the others are still deciding. "
                          "Call next_turn again.")


def call_tool(seat: remote.Seat, name: str, args: dict) -> dict:
    if name == "join_village":
        return _text(seat.join(str(args.get("confirm") or "")))
    if name == "next_turn":
        return _next(seat)
    if name == "answer":
        if not seat.confirmed:
            return _text("You have not joined yet: call join_village first.", error=True)
        try:
            rid = int(args.get("request_id"))
        except (TypeError, ValueError):
            return _text("request_id must be the number of the request you answer.", error=True)
        err = seat.submit(rid, args.get("reply"))
        if err:
            return _text(err, error=True)
        return _next(seat, f"Answer to request {rid} accepted.\n\n")
    raise KeyError(name)


def handle(seat: remote.Seat, msg: dict) -> dict | None:
    """One JSON-RPC message -> its response (None for notifications)."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or "method" not in msg:
        return {"jsonrpc": "2.0", "id": msg.get("id") if isinstance(msg, dict) else None,
                "error": {"code": -32600, "message": "invalid request"}}
    mid, method, params = msg.get("id"), msg["method"], msg.get("params") or {}
    if mid is None:  # notification (notifications/initialized, cancelled, ...)
        return None
    seat.touch()

    def ok(result: dict) -> dict:
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    if method == "initialize":
        seat.touch(str((params.get("clientInfo") or {}).get("name") or ""))
        asked = params.get("protocolVersion")
        return ok({"protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                   "capabilities": {"tools": {"listChanged": False}}, "serverInfo": SERVER_INFO,
                   "instructions": INSTRUCTIONS})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": TOOLS})
    if method == "tools/call":
        try:
            return ok(call_tool(seat, str(params.get("name")), params.get("arguments") or {}))
        except KeyError:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"unknown tool {params.get('name')}"}}
    if method in ("resources/list", "prompts/list"):
        return ok({method.split("/")[0]: []})
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"method not found: {method}"}}


PAGE = Path(__file__).resolve().parent.parent / "viewer" / "join.html"


def page(data: dict) -> HTMLResponse:
    """viewer/join.html with what it shows (`window.AIV`): the lobby or one villager's connector link."""
    blob = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    html = PAGE.read_text(encoding="utf-8").replace("/*AIV*/null", blob, 1)
    return HTMLResponse(html, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
                                       "X-Robots-Tag": "noindex"})


def wants_page(request: Request) -> bool:
    """A browser opening the link (not an MCP client asking for an event stream)."""
    accept = request.headers.get("accept", "")
    return "text/html" in accept and "text/event-stream" not in accept


def mount(app: FastAPI, hub: remote.Hub | None = None) -> None:
    hub_of = (lambda: hub) if hub is not None else (lambda: remote.HUB)

    def seat_or_404(code: str) -> remote.Seat | None:
        return hub_of().get(code)

    def lobby_or_404(lobby: str) -> remote.Hub:
        h = hub_of()
        if not h.seats or not h.lobby or not secrets.compare_digest(h.lobby, lobby):
            raise HTTPException(404, "Эта ссылка-приглашение устарела: попросите у хозяина деревни новую.")
        return h

    # --- lobby (registered before /mcp/{code} so "join" is never taken for a seat code) ---

    @app.get("/mcp/join/{lobby}")
    def lobby_page(lobby: str) -> Response:
        h = lobby_or_404(lobby)
        return page({"mode": "lobby", "base": f"/mcp/join/{lobby}", "session": h.session})

    @app.get("/mcp/join/{lobby}/state")
    def lobby_state(lobby: str, claim: str = "") -> dict:
        h = lobby_or_404(lobby)
        out = h.lobby_status()
        seat = h.by_claim(claim)
        if seat is not None:
            out["mine"] = {"name": seat.name, "path": f"/mcp/{seat.code}", "state": seat.state()}
        return out

    @app.post("/mcp/join/{lobby}/take")
    def lobby_take(lobby: str, body: dict = Body(...)) -> dict:
        h = lobby_or_404(lobby)
        old = h.by_claim(str(body.get("claim") or ""))
        if old is not None:  # the same browser again: keep its villager
            return {"claim": old.claim, "name": old.name, "path": f"/mcp/{old.code}"}
        try:
            seat = h.take(str(body.get("player") or ""), str(body.get("ai") or ""))
        except ValueError as e:
            return JSONResponse({"detail": str(e)}, 409)
        return {"claim": seat.claim, "name": seat.name, "path": f"/mcp/{seat.code}"}

    @app.post("/mcp/join/{lobby}/leave")
    def lobby_leave(lobby: str, body: dict = Body(...)) -> dict:
        h = lobby_or_404(lobby)
        seat = h.by_claim(str(body.get("claim") or ""))
        if seat is not None and not seat.confirmed:  # a villager already playing stays with its AI
            h.release(seat)
        return {"ok": True}

    @app.post("/mcp/{code}")
    def mcp_post(code: str, body: Any = Body(...)) -> Response:  # sync: tool calls block in the thread pool
        seat = seat_or_404(code)
        if seat is None:
            return JSONResponse({"jsonrpc": "2.0", "id": None,
                                 "error": {"code": -32001, "message": "unknown or expired village link"}}, 404)
        if isinstance(body, list):
            out = [r for r in (handle(seat, m) for m in body) if r is not None]
            return JSONResponse(out) if out else Response(status_code=202)
        r = handle(seat, body)
        return JSONResponse(r) if r is not None else Response(status_code=202)

    @app.get("/mcp/{code}")
    def mcp_get(code: str, request: Request) -> Response:  # no server-initiated stream
        seat = seat_or_404(code) if wants_page(request) else None
        if seat is not None:  # the link opened in a browser: how to add it to your AI
            return page({"mode": "seat", "name": seat.name, "session": seat.hub.session, "player": seat.player})
        return Response(status_code=405, headers={"Allow": "POST"})

    @app.delete("/mcp/{code}")
    def mcp_delete(code: str) -> Response:
        return Response(status_code=200 if seat_or_404(code) else 404)


class OutsideOnlyMcp:
    """ASGI middleware: requests that came through the internet tunnel (Cloudflare adds `cf-connecting-ip` /
    `cf-ray`) may reach `/mcp/...` (and `/.well-known/...`, which 404s) only, never the host's viewer, god panel, settings or keys."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        # /.well-known stays reachable so clients' OAuth discovery gets a plain 404 (no login needed)
        if scope["type"] in ("http", "websocket") and not path.startswith(("/mcp/", "/.well-known/")):
            names = {k.lower() for k, _ in scope.get("headers") or []}
            if b"cf-connecting-ip" in names or b"cf-ray" in names:
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 1008})
                    return
                body = "Only the village connector is open from the internet.".encode()
                await send({"type": "http.response.start", "status": 403,
                            "headers": [(b"content-type", b"text/plain; charset=utf-8")]})
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)
