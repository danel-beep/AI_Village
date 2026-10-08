import base64
import json

import pytest

from aivillage import highlights, keys, narration

ITEMS = [{"title": "Theft", "line": "Boris took Anna's bread.", "who": ["Boris", "Anna"], "kind": "steal", "top": True},
         {"title": "A deal", "line": "Clara traded fish for berries.", "who": ["Clara"], "kind": "trade"}]


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("AIVILLAGE_HOME", str(tmp_path))
    for env in keys.ENV.values():
        monkeypatch.delenv(env, raising=False)
    return tmp_path


class FakeClient:
    model = "fake"

    def __init__(self, reply):
        self.reply, self.seen = reply, []

    def complete(self, messages):
        self.seen.append(messages)
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply, {"cost": 0.0002}


def test_fit_caps_words_per_slot():
    assert narration.fit("one two three", "hook") == "one two three"
    long = " ".join(f"w{k}" for k in range(20))
    assert len(narration.fit(long, "moment").split()) == narration.MAX_WORDS["moment"]
    assert narration.fit(long, "hook").endswith(".")


def test_script_from_model_in_language_and_fallbacks():
    reply = json.dumps({"hook": "Meanwhile, a crime of bread.", "moments": ["Boris has a plan.", "Commerce, of a sort."],
                        "outro": "Follow the village."})
    c = FakeClient(reply)
    s = narration.script(ITEMS, "en", c)
    assert s["source"] == "model" and s["moments"] == ["Boris has a plan.", "Commerce, of a sort."]
    system, user = c.seen[0][0]["content"], c.seen[0][1]["content"]
    assert "English" in system and "{language}" not in system and "★" in user.splitlines()[1]
    # wrong number of lines, a failed call, no client: the titles are read, never an exception
    for client in (FakeClient(json.dumps({"moments": ["only one"]})), FakeClient(RuntimeError("down")), None):
        s = narration.script(ITEMS, "ru", client)
        assert s["source"] == "titles" and s["moments"] == ["Theft", "A deal"] and s["hook"] == narration.FALLBACK["ru"]["hook"]


def test_narrate_reads_every_line_and_counts_cost(home):
    said = []

    def speaker(text, voice=None, lang=None, cache=None):
        said.append((text, voice, lang))
        return b"RIFF" + text.encode()

    res = narration.narrate(ITEMS, "en", None, voice="marin", speaker=speaker)
    assert [t for t, *_ in said] == [res["lines"]["hook"], "Theft", "A deal", res["lines"]["outro"]]
    assert {v for _, v, _ in said} == {"marin"} and len(res["audio"]["moments"]) == 2
    assert base64.b64decode(res["audio"]["moments"][0]) == b"RIFFTheft"
    assert 0 < res["cost_usd"] < 0.01


def test_speak_posts_to_openai_tts_and_caches(home, monkeypatch):
    calls = []

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"RIFFwav"

    def urlopen(req, timeout=0):
        calls.append((req.full_url, json.loads(req.data), req.headers["Authorization"]))
        return Resp()

    monkeypatch.setattr(narration.urllib.request, "urlopen", urlopen)
    with pytest.raises(RuntimeError):
        narration.speak("hi")  # no key
    keys.save({"openai_key": "sk-test-1234567890"})
    cache = home / "tts"
    assert narration.speak("Boris has a plan.", voice="cedar", lang="en", cache=cache) == b"RIFFwav"
    assert narration.speak("Boris has a plan.", voice="cedar", lang="en", cache=cache) == b"RIFFwav"
    assert len(calls) == 1  # second time from the cache
    url, body, auth = calls[0]
    assert url == narration.TTS_URL and auth == "Bearer sk-test-1234567890"
    assert body["model"] == "gpt-4o-mini-tts" and body["voice"] == "cedar" and body["response_format"] == "wav"
    assert "documentary" in body["instructions"]


def test_settings_validate_and_show_clip_options(home):
    pub = keys.public()
    assert pub["content_lang"] == "ru" and pub["narration"] == "off" and pub["tts_voice"] == "cedar"
    keys.save({"content_lang": "en", "narration": "on", "tts_voice": "marin"})
    assert keys.content_lang() == "en" and keys.narration_on() and keys.tts_voice() == "marin"
    for bad in ({"content_lang": "de"}, {"narration": "yes"}, {"tts_voice": "robot"}):
        with pytest.raises(ValueError):
            keys.save(bad)


def test_highlights_in_english(home, tmp_path):
    from test_highlights import FakeClient as HlClient, make_log
    from aivillage.run import read_log
    from aivillage import summary
    recs = list(read_log(make_log(tmp_path)))
    day1 = summary.by_day(summary.ticks_of(recs))[0]
    rec = highlights.Highlighter(None, None, "en").pick(day1)  # rules only
    assert rec["lang"] == "en" and all(it["time"].startswith("day ") for it in rec["items"])
    assert any(it["title"] == highlights.TITLES_EN.get(it["kind"]) for it in rec["items"])
    keys.save({"content_lang": "en"})  # no explicit lang: the settings panel decides
    c = HlClient('{"highlights": []}')
    highlights.Highlighter(c, None).pick(day1)
    assert set(highlights.TITLES_EN) == set(highlights.TITLES)


def test_narration_endpoint(home, monkeypatch):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from aivillage import engine
    from aivillage.server import LiveSim, create_app
    sim = LiveSim(engine.new_world({"seed": 1}), lambda n, o: None, 1)
    client = TestClient(create_app(sim))
    assert client.post("/api/narration", json={"items": ITEMS}).status_code == 400  # no OpenAI key
    keys.save({"openai_key": "sk-test-1234567890", "content_lang": "en"})
    monkeypatch.setattr(narration, "speak", lambda text, voice=None, lang=None, cache=None: f"{lang}:{text}".encode())
    r = client.post("/api/narration", json={"items": ITEMS})
    assert r.status_code == 200
    j = r.json()
    assert base64.b64decode(j["audio"]["moments"][1]) == b"en:A deal" and j["lines"]["moments"] == ["Theft", "A deal"]
    assert sim.narration_cost == pytest.approx(j["cost_usd"]) and sim.spent() >= sim.narration_cost
    assert client.post("/api/narration", json={"items": []}).status_code == 400
    s = client.post("/api/settings", json={"content_lang": "en", "narration": "on", "tts_voice": "ash"}).json()
    assert s["narration"] == "on" and s["tts_voice"] == "ash"
