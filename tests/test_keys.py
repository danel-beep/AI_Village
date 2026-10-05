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
