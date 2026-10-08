"""Keys and providers: settings file, provider routing, OpenAI direct client, settings panel API."""

import io
import json
import urllib.error

import pytest

from aivillage import keys, llm

OA, OR = "sk-proj-abcdefghijklmnop1234", "sk-or-v1-zyxwvutsrqponm9876"


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("AIVILLAGE_HOME", str(tmp_path))
    for v in keys.ENV.values():
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    llm._UNSUPPORTED.clear()
    return tmp_path


def test_settings_file_wins_over_env_and_masks(home, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-env-key-000000")
    assert keys.get("openai_key") == "sk-env-key-000000"
    keys.save({"openai_key": OA, "provider": "openai", "parallel": "8"})
    assert keys.get("openai_key") == OA and keys.provider() == "openai" and keys.get("parallel") == 8
    pub = keys.public()
    assert OA not in json.dumps(pub) and pub["openai_key"] == {"set": True, "masked": "sk-…1234", "from": "file"}
    keys.save({"openai_key": ""})  # empty removes: env shows through again
    assert keys.get("openai_key") == "sk-env-key-000000" and keys.public()["openai_key"]["from"] == "env"
    with pytest.raises(ValueError):
        keys.save({"provider": "nope"})


def test_legacy_openrouter_key_file_still_read(home):
    (home / "openrouter_key").write_text(OR + "\n")
    assert keys.get("openrouter_key") == OR and keys.has_any_key()


def test_make_client_routes_by_provider_and_keys(monkeypatch):
    with pytest.raises(RuntimeError):
        llm.make_client("default")
    keys.save({"openrouter_key": OR})
    assert isinstance(llm.make_client("default"), llm.OpenRouterClient)
    keys.save({"openai_key": OA})
    c = llm.make_client("default")
    assert isinstance(c, llm.FallbackClient) and isinstance(c.primary, llm.OpenAIClient)
    assert c.primary.name == "gpt-6-luna" and c.model == llm.DEFAULT_MODEL
    assert isinstance(llm.make_client("google/gemini-x"), llm.OpenRouterClient)  # OpenAI serves only its models
    keys.save({"provider": "openrouter"})
    assert isinstance(llm.make_client("default"), llm.OpenRouterClient)
    keys.save({"provider": "auto", "openrouter_key": "", "model": "openai/gpt-5.6-luna"})
    c = llm.make_client("default")
    assert isinstance(c, llm.OpenAIClient) and c.name == "gpt-5.6-luna"
    keys.save({"provider": "openai", "openai_key": ""})
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        llm.make_client("default")


def fake_openai(monkeypatch, handler):
    seen = []

    def urlopen(req, timeout=None):
        body = json.loads(req.data)
        seen.append((req.full_url, req.headers.get("Authorization"), body))
        return handler(req, body)

    monkeypatch.setattr(llm.urllib.request, "urlopen", urlopen)
    return seen


def http_error(req, code, err):
    return urllib.error.HTTPError(req.full_url, code, "x", {}, io.BytesIO(json.dumps({"error": err}).encode()))


def ok(model="gpt-6-luna"):
    return io.BytesIO(json.dumps({"model": model, "usage": {"prompt_tokens": 1000, "completion_tokens": 200,
                                                            "prompt_tokens_details": {"cached_tokens": 400}},
                                  "choices": [{"message": {"content": '{"action": {"name": "wait"}}'}}]}).encode())


def test_openai_client_request_cost_and_dropped_param(monkeypatch):
    def handler(req, body):
        if "temperature" in body:
            raise http_error(req, 400, {"message": "Unsupported parameter: 'temperature'", "param": "temperature"})
        return ok()

    seen = fake_openai(monkeypatch, handler)
    c = llm.OpenAIClient("openai/gpt-6-luna", api_key=OA, temperature=0.5)
    text, usage = c.complete([{"role": "user", "content": "hi"}])
    url, auth, body = seen[-1]
    assert url == llm.OpenAIClient.URL and auth == f"Bearer {OA}" and body["model"] == "gpt-6-luna"
    assert body["reasoning_effort"] == "low" and "temperature" not in body and len(seen) == 2
    assert usage["model"] == "openai/gpt-6-luna"
    assert usage["cost"] == pytest.approx((600 * 0.10 + 400 * 0.01 + 200 * 0.50) / 1e6)
    c.complete([{"role": "user", "content": "again"}])
    assert len(seen) == 3  # the rejected parameter is remembered


def test_openai_flex_tier_half_price_and_busy_falls_back(monkeypatch):
    """Flex: the same model at half the price; when flex is busy the call goes at the normal price at once."""
    def handler(req, body):
        if body.get("service_tier") == "flex" and len(seen) == 1:
            raise http_error(req, 429, {"message": "Flex does not have sufficient resources available to fulfill "
                                                   "your request. You can try again later"})
        reply = json.loads(ok().getvalue())
        reply["service_tier"] = body.get("service_tier", "default")
        return io.BytesIO(json.dumps(reply).encode())

    seen = fake_openai(monkeypatch, handler)
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    c = llm.OpenAIClient("openai/gpt-6-luna", api_key=OA)
    full = (600 * 0.10 + 400 * 0.01 + 200 * 0.50) / 1e6
    _, usage = c.complete([{"role": "user", "content": "hi"}])
    assert [b.get("service_tier") for _, _, b in seen] == ["flex", None] and usage["cost"] == pytest.approx(full)
    _, usage = c.complete([{"role": "user", "content": "again"}])  # the next call tries flex again
    assert seen[-1][2]["service_tier"] == "flex" and usage["cost"] == pytest.approx(full / 2)
    keys.save({"openai_tier": "default"})  # settings panel: «Обычный»
    c.complete([{"role": "user", "content": "x"}])
    assert "service_tier" not in seen[-1][2]
    with pytest.raises(ValueError):
        keys.save({"openai_tier": "cheap"})


@pytest.mark.parametrize("code,err", [(401, {"message": "Incorrect API key"}),
                                      (429, {"code": "insufficient_quota", "message": "You exceeded your quota"})])
def test_fallback_switches_to_openrouter_for_good(monkeypatch, code, err):
    def handler(req, body):
        if "openai.com" in req.full_url:
            raise http_error(req, code, err)
        return ok("openai/gpt-6-luna")

    seen = fake_openai(monkeypatch, handler)
    keys.save({"openai_key": OA, "openrouter_key": OR})
    c = llm.make_client("default")
    for _ in range(2):
        c.complete([{"role": "user", "content": "hi"}])
    hosts = ["openai" if "openai.com" in u else "openrouter" for u, _, _ in seen]
    assert hosts == ["openai", "openrouter", "openrouter"] and c.down


def test_settings_api_never_returns_keys(tmp_path):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from aivillage import engine
    from aivillage.server import LiveSim, create_app
    sim = LiveSim(engine.new_world({"seed": 1}), lambda n, o: None, 1)
    client = TestClient(create_app(sim))
    r = client.post("/api/settings", json={"openai_key": OA, "provider": "auto", "model": "", "parallel": "12"})
    assert r.status_code == 200 and OA not in r.text and r.json()["openai_key"]["set"]
    assert keys.get("openai_key") == OA and keys.get("parallel") == 12
    r = client.post("/api/settings", json={"openai_key": "", "provider": "auto"})  # empty field keeps the key
    assert keys.get("openai_key") == OA
    r = client.post("/api/settings", json={"clear": ["openai_key"]})
    assert not r.json()["openai_key"]["set"]
    assert client.post("/api/settings", json={"provider": "bad"}).status_code == 400
    assert client.post("/api/settings/check").json()["ok"] is False  # no key left
    assert "settings.js" in client.get("/").text


def test_openai_durations_and_retry_after():
    assert llm._seconds("41.126s") == pytest.approx(41.126)
    assert llm._seconds("120ms") == pytest.approx(0.12)
    assert llm._seconds("1m2.5s") == pytest.approx(62.5)
    assert llm._seconds("20") == 20 and llm._seconds(None) is None and llm._seconds("soon") is None
    assert llm.retry_after({"retry-after-ms": "350"}) == pytest.approx(0.35)
    assert llm.retry_after({}, "Rate limit reached for tokens per min. Please try again in 1.53s.") == pytest.approx(1.53)
    assert llm.retry_after(None, "Please try again in 820ms.") == pytest.approx(0.82)
    assert llm.retry_after({}, "busy") is None


def test_openai_paces_before_the_token_budget_runs_out(monkeypatch):
    class Reply(io.BytesIO):
        headers = {"x-ratelimit-limit-tokens": "200000", "x-ratelimit-remaining-tokens": "10000",
                   "x-ratelimit-reset-tokens": "57s"}

    fake_openai(monkeypatch, lambda req, body: Reply(ok().getvalue()))
    llm._GATES.clear()
    llm.OpenAIClient("openai/gpt-6-luna", api_key=OA).complete([{"role": "user", "content": "hi"}])
    gate = llm._GATES["direct:gpt-6-luna"]
    # 10k of 200k left, the floor is 30k: wait for 20k of the 190k that refill in 57 s = 6 s
    assert gate.paced == 1 and gate.rate_limited == 0 and 5.5 < gate._cooldown() <= 6.0
    llm._GATES.clear()


def test_openai_429s_do_not_use_up_retries(monkeypatch):
    calls = []

    def handler(req, body):
        calls.append(1)
        if len(calls) <= 9:  # more 429s than retries
            raise http_error(req, 429, {"message": "Rate limit reached. Please try again in 1ms."})
        return ok()

    fake_openai(monkeypatch, handler)
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    llm._GATES.clear()
    text, _ = llm.OpenAIClient("openai/gpt-6-luna", api_key=OA, retries=2).complete([{"role": "user", "content": "x"}])
    assert len(calls) == 10 and "wait" in text
    llm._GATES.clear()


def test_villagers_sample_alike_on_every_route(monkeypatch):
    """Fairness audit: no route sets its own temperature for villagers; helpers still pass theirs."""
    seen = fake_openai(monkeypatch, lambda req, body: ok("anthropic/claude-x"))
    llm.OpenRouterClient("anthropic/claude-x", api_key="or-key").complete([{"role": "user", "content": "hi"}])
    llm.OpenAIClient("openai/gpt-6-luna", api_key=OA).complete([{"role": "user", "content": "hi"}])
    assert all("temperature" not in body for _, _, body in seen)
    llm.OpenRouterClient("google/x", api_key="or-key", temperature=0.2).complete([{"role": "user", "content": "hi"}])
    assert seen[-1][2]["temperature"] == 0.2
