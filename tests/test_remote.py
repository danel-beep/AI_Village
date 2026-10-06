"""Own AIs over MCP (aivillage/remote.py, aivillage/mcpserver.py): the villager gets the same requests as an
API villager, plays only after its person said yes, misses a turn when it is too slow, and the log replays."""

import json
import re
import threading
import time

import pytest

pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from aivillage import engine, knobs, llm, mcpserver, remote, tunnel  # noqa: E402
from aivillage.run import llm_agents, night_reflection, replay, run  # noqa: E402
from tests.test_neutrality import evaluative  # noqa: E402


def world(n=3, seats=1, **own):
    w = engine.new_world({"population": {"size": n}, "own_ai": {"seats": seats, **own}})
    return w


def app():
    a = FastAPI()
    mcpserver.mount(a)
    a.add_middleware(mcpserver.OutsideOnlyMcp)
    return TestClient(a)


class Player:
    """A fake player's AI speaking MCP over HTTP."""

    def __init__(self, client, path):
        self.c, self.path, self.n = client, path, 0

    def rpc(self, method, params=None):
        self.n += 1
        r = self.c.post(self.path, json={"jsonrpc": "2.0", "id": self.n, "method": method, "params": params or {}})
        assert r.status_code == 200, r.text
        return r.json()

    def tool(self, name, **args):
        res = self.rpc("tools/call", {"name": name, "arguments": args})["result"]
        return res["content"][0]["text"], res["isError"]

    def play(self, seen: list):
        text, _ = self.tool("next_turn")
        while True:
            if "game is over" in text or "session has ended" in text:
                return
            m = re.search(r"=== Request (\d+) \((\w+)\)", text)
            if not m:
                text, _ = self.tool("next_turn")
                continue
            seen.append(text)
            kind = m.group(2)
            reply = ({"thought": "from my own AI", "action": {"name": "wait"}} if kind == "turn" else
                     {"about_me": "I am me.", "wants": "", "today": "Look around."} if kind == "intro" else
                     {"diary": "A day.", "people": {}})
            text, err = self.tool("answer", request_id=int(m.group(1)), reply=reply)
            assert not err, text


def test_seats_get_mcp_and_owner_character():
    w = world(4, seats=2)
    models = remote.models_for(w.config)
    names = [a["name"] for a in w.config["agents"]]
    assert [models[n] for n in names] == ["mcp", "mcp", "default", "default"]
    agents = llm_agents(w, {n: ("mcp" if m == "mcp" else "stub") for n, m in models.items()})
    assert isinstance(agents[names[0]].client, remote.RemoteClient)
    assert agents[names[0]].character == remote.OWNER_CHARACTER
    assert agents[names[2]].character != remote.OWNER_CHARACTER
    assert len(remote.HUB.seats) == 2
    llm_agents(world(2, seats=1, style="self"), {n: "mcp" for n in world(2).agents})
    assert remote.HUB.style == "self"
    assert remote.models_for(world(3, seats=0).config) == ["default"]


def test_full_game_over_mcp_replays(tmp_path):
    w = world(3, seats=1)
    seat_name = w.config["agents"][0]["name"]
    agents = llm_agents(w, {n: ("mcp" if n == seat_name else "stub") for n in w.agents})
    seat = remote.HUB.by_name(seat_name)
    c = app()
    p = Player(c, f"/mcp/{seat.code}")
    init = p.rpc("initialize", {"protocolVersion": "2025-06-18", "clientInfo": {"name": "test-ai"}})["result"]
    assert init["protocolVersion"] == "2025-06-18" and "tools" in init["capabilities"]
    assert {t["name"] for t in p.rpc("tools/list")["result"]["tools"]} == {"join_village", "next_turn", "answer"}
    assert c.post(p.path, json={"jsonrpc": "2.0", "method": "notifications/initialized"}).status_code == 202

    text, err = p.tool("next_turn")  # no consent yet
    assert err and "join_village" in text
    card, _ = p.tool("join_village")
    assert remote.HUB.session in card and seat_name in card and "yes" in card
    assert seat.status()["state"] == "asking"
    wrong, _ = p.tool("join_village", confirm="nope")
    assert "Wrong session code" in wrong and not seat.confirmed
    ok, _ = p.tool("join_village", confirm=remote.HUB.session)
    assert "confirmed" in ok and seat.status()["state"] == "playing" and seat.client == "test-ai"

    seen = []
    t = threading.Thread(target=p.play, args=(seen,), daemon=True)
    t.start()
    decide = lambda name, obs: agents[name].decide(obs)  # noqa: E731
    decide.agents = agents
    log = tmp_path / "own.jsonl"
    end = run(w, decide, 1, log_path=log, on_night=lambda wd, day: night_reflection(wd, agents, day))
    remote.HUB.close(finished=True)
    t.join(10)
    assert not t.is_alive()

    kinds = [re.search(r"\((\w+)\) for", s).group(1) for s in seen]
    assert kinds[0] == "intro" and "turn" in kinds and kinds[-1] == "diary"
    assert "Rules of the world" in seen[0]  # first request carries the whole system prompt
    turns = [s for s in seen if "(turn)" in s]
    assert "Rules of the world" not in turns[1]  # later turns only what is new
    assert turns[1].count("Observation") == 1
    recs = [json.loads(l) for l in log.read_text().splitlines()]
    assert recs[0]["brains"][seat_name] == "mcp"
    mine = [r["decisions"][seat_name] for r in recs if r.get("type") == "tick" and seat_name in r.get("asked", [])]
    assert mine and all(d.get("thought") == "from my own AI" for d in mine)
    assert agents[seat_name].diary and agents[seat_name].about_me == "I am me."
    assert replay(log).hash() == w.hash()
    assert end


def test_unconnected_seat_waits_until_skipped_and_slow_ai_misses_turn():
    w = world(2, seats=1)
    name = w.config["agents"][0]["name"]
    agents = llm_agents(w, {n: "mcp" for n in [name]})
    seat, ag = remote.HUB.by_name(name), agents[name]
    obs = engine.observe(w, name, consume_inbox=False)
    out = {}
    t = threading.Thread(target=lambda: out.update(dec=ag._decide(obs)), daemon=True)
    t.start()
    time.sleep(1.5)
    assert t.is_alive() and seat.status()["waiting"]  # the village waits for the player to connect
    seat.skipped = True
    t.join(5)
    assert out["dec"]["action"]["name"] == "wait" and "not connected" in out["dec"]["thought"]

    seat.join(remote.HUB.session)
    remote.HUB.wait_s = 0.3
    assert ag._decide(obs)["action"]["name"] == "wait" and seat.misses == 2  # too slow: the turn is missed


def test_answer_checks_and_stale_requests():
    w = world(2, seats=1)
    name = w.config["agents"][0]["name"]
    agents = llm_agents(w, {name: "mcp"})
    seat = remote.HUB.by_name(name)
    seat.join(remote.HUB.session)
    msgs = agents[name].messages(engine.observe(w, name, consume_inbox=False))
    res = {}
    t = threading.Thread(target=lambda: res.update(text=seat.ask(msgs)), daemon=True)
    t.start()
    req = seat.next_request(5)
    assert req.kind == "turn"
    assert "action" in seat.submit(req.id, {"thought": "no action"})
    assert "no longer open" in seat.submit(req.id + 5, {"action": {"name": "wait"}})
    assert "too long" in seat.submit(req.id, {"say": "x" * 9000})
    assert seat.submit(req.id, {"action": {"name": "wait"}, "say": "hi"}) is None
    t.join(5)
    assert json.loads(res["text"])["say"] == "hi"


def test_render_resends_rules_only_when_changed_or_rejoined():
    hub = remote.Hub()
    hub.reset()
    seat = hub.add("Anna")
    base = [{"role": "system", "content": "RULES A"}]
    r1 = remote.Request(1, "turn", base + [{"role": "user", "content": "obs 1"}], time.time())
    assert "RULES A" in seat.render(r1)
    r2 = remote.Request(2, "turn", base + [{"role": "user", "content": "line 1"},
                                           {"role": "assistant", "content": "{\"action\": 1}"},
                                           {"role": "user", "content": "obs 2"}], time.time())
    text = seat.render(r2)
    assert "RULES A" not in text and "obs 2" in text and "obs 1" not in text and "line 1" not in text
    r3 = remote.Request(3, "diary", [{"role": "system", "content": "DIARY RULES"},
                                     {"role": "user", "content": "End of day 1."}], time.time())
    assert "DIARY RULES" in seat.render(r3)
    seat.join()  # a new chat on the AI's side: everything again, earlier turns included
    text = seat.render(r2)
    assert "RULES A" in text and "line 1" in text and "You answered" in text


def test_tunnel_reaches_only_mcp():
    c = app()
    cf = {"cf-connecting-ip": "1.2.3.4"}
    assert c.get("/api/settings", headers=cf).status_code == 403
    r = c.post("/mcp/nope", json={"jsonrpc": "2.0", "id": 1, "method": "ping"}, headers=cf)
    assert r.status_code == 404 and "expired" in r.json()["error"]["message"]
    assert c.get("/.well-known/oauth-protected-resource", headers=cf).status_code == 404
    assert c.get("/api/settings").status_code == 404  # locally the app decides (no such route in this app)


def test_knobs_and_tunnel_helpers():
    run_opts = knobs.to_run({"own_ai_seats": 2, "own_ai_wait": 7, "own_ai_style": "self"})
    assert run_opts["override"]["own_ai"] == {"seats": 2, "wait_minutes": 7, "style": "self"}
    assert tunnel.find_url("INF |  https://quiet-river-abc.trycloudflare.com  |") == "https://quiet-river-abc.trycloudflare.com"
    assert tunnel.find_url("starting") is None
    assert tunnel.asset("Windows", "AMD64").endswith(".exe")
    assert tunnel.asset("Darwin", "arm64") == "cloudflared-darwin-arm64.tgz"
    assert tunnel.asset("Linux", "x86_64") == "cloudflared-linux-amd64"


def test_texts_the_ai_reads_are_neutral():
    hub = remote.Hub()
    hub.reset()
    seat = hub.add("Anna", "farmer")
    texts = [remote.OWNER_CHARACTER, seat.card(), seat.join(hub.session), mcpserver.INSTRUCTIONS,
             *remote.KIND_HINT.values(), *(t["description"] for t in mcpserver.TOOLS)]
    hub.style = "self"
    texts.append(seat.card())
    for text in texts:
        assert evaluative(text) == [], (text, evaluative(text))
    assert llm.SYSTEM  # the villager's own prompt is checked by test_neutrality
