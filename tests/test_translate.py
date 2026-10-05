import json

from aivillage.translate import (StubTranslateClient, Translator, batches, collect_texts, sidecar_path,
                                 translate_log)


def tick(decisions, events):
    return {"type": "tick", "decisions": decisions, "events": events}


LOG = [
    {"type": "header"},
    tick({"Anna": {"thought": "I am hungry.", "say": "Hi!"}, "Boris": {"thought": "", "say": None}},
         [{"text": "Anna arrived at Field."}]),
    tick({"Anna": {"thought": "I am hungry.", "say": "Bye"}}, [{"text": "Anna arrived at Field."}]),
]


def write_log(tmp_path):
    p = tmp_path / "run.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in LOG) + "\n")
    return p


def test_collect_unique_in_order():
    assert collect_texts(LOG) == ["I am hungry.", "Hi!", "Anna arrived at Field.", "Bye"]


def test_batches_respect_limits():
    bs = batches([f"t{i}" for i in range(95)], max_n=40)
    assert [len(b) for b in bs] == [40, 40, 15]
    assert [len(b) for b in batches(["x" * 10] * 5, max_chars=25)] == [2, 2, 1]


def test_sidecar_and_cache(tmp_path):
    log, cache = write_log(tmp_path), tmp_path / "cache.json"
    client = StubTranslateClient()
    out = translate_log(log, Translator(client, "ru", cache))
    assert out == sidecar_path(log, "ru") == tmp_path / "run.ru.json"
    data = json.loads(out.read_text())
    assert data["lang"] == "ru" and data["texts"]["Hi!"] == "[ru] Hi!" and len(data["texts"]) == 4
    calls = client.calls
    translate_log(log, Translator(client, "ru", cache))  # everything cached now
    assert client.calls == calls


class Flaky(StubTranslateClient):
    """Drops one key and answers garbage for big batches, to exercise splitting."""

    def complete(self, messages):
        obj = json.loads(messages[-1]["content"])
        self.calls += 1
        if len(obj) > 2:
            return "sorry, cannot", {}
        text, usage = super().complete(messages)
        out = json.loads(text)
        out.pop("2", None) if len(out) == 2 else None
        return "```json\n" + json.dumps(out) + "\n```", usage


def test_bad_replies_split_and_partial(tmp_path):
    texts = [f"line {i}" for i in range(7)]
    got = Translator(Flaky()).translate(texts)
    assert got == {t: f"[ru] {t}" for t in texts}  # every line ends up translated alone if needed
