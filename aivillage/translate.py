"""Translate a run log's viewer-facing texts (thoughts, says, event texts, diaries) for spectators.

Agents think and speak English; this post-processes a finished log into a sidecar file
`<log>.<lang>.json` = {"type": "translation", "lang", "model", "texts": {original: translated}}.
The log itself is never modified, so replay is unaffected. Translations are batched (one
request carries many texts as a numbered JSON object) and cached across runs.

    python -m aivillage.translate runs/x.jsonl [--lang ru] [--model M] [--stub]
"""
from __future__ import annotations

import argparse
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Iterable

from .llm import Client, Usage, make_client

DEFAULT_MODEL = "openai/gpt-6-luna"
LANG_NAMES = {"ru": "Russian"}
BATCH_TEXTS = 40
BATCH_CHARS = 6000

PROMPT = """You translate lines from a village life simulation into {lang} for viewers.
Input: a JSON object of numbered English lines. Output: ONLY a JSON object with the same keys,
each value the {lang} translation. Keep person names exactly as written (Latin letters, do not
transliterate) and numbers exact;
keep it short and natural, informal spoken style for speech. Do not add or drop keys."""


def collect_texts(records: Iterable[dict]) -> list[str]:
    """Unique viewer-facing strings of a log, in first-seen order."""
    seen: dict[str, None] = {}
    for rec in records:
        if rec.get("type") == "diary":
            for entry in (rec.get("entries") or {}).values():
                for k in ("text", "wants", "plan"):
                    if isinstance(entry, dict) and isinstance(entry.get(k), str) and entry[k].strip():
                        seen.setdefault(entry[k], None)
        if rec.get("type") != "tick":
            continue
        for d in (rec.get("decisions") or {}).values():
            for k in ("thought", "say"):
                if isinstance(d, dict) and isinstance(d.get(k), str) and d[k].strip():
                    seen.setdefault(d[k], None)
            intro = d.get("intro") if isinstance(d, dict) else None
            for k in ("about_me", "wants", "plan"):
                if isinstance(intro, dict) and isinstance(intro.get(k), str) and intro[k].strip():
                    seen.setdefault(intro[k], None)
        for e in rec.get("events") or []:
            if isinstance(e.get("text"), str) and e["text"].strip():
                seen.setdefault(e["text"], None)
            for k in ("note", "honor"):  # honor board notes and titles, shown alone in viewer/honors.js
                v = (e.get("data") or {}).get(k)
                if isinstance(v, str) and v.strip():
                    seen.setdefault(v, None)
    return list(seen)


def batches(texts: list[str], max_n: int = BATCH_TEXTS, max_chars: int = BATCH_CHARS) -> list[list[str]]:
    out, cur, size = [], [], 0
    for t in texts:
        if cur and (len(cur) >= max_n or size + len(t) > max_chars):
            out.append(cur)
            cur, size = [], 0
        cur.append(t)
        size += len(t)
    if cur:
        out.append(cur)
    return out


def parse_object(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON object in reply")
    obj = json.loads(m.group(0))
    if not isinstance(obj, dict):
        raise ValueError("reply is not an object")
    return obj


class Translator:
    def __init__(self, client: Client, lang: str = "ru", cache_path: str | Path | None = None):
        self.client, self.lang, self.usage = client, lang, Usage()
        self.cache_path = Path(cache_path) if cache_path else None
        self.cache: dict[str, str] = {}
        if self.cache_path and self.cache_path.exists():
            self.cache = json.loads(self.cache_path.read_text())

    def _request(self, batch: list[str]) -> dict[str, str]:
        """Translate one batch; on a malformed reply split it in halves, give up per single line."""
        messages = [{"role": "system", "content": PROMPT.format(lang=LANG_NAMES.get(self.lang, self.lang))},
                    {"role": "user", "content": json.dumps({str(k + 1): t for k, t in enumerate(batch)},
                                                           ensure_ascii=False)}]
        try:
            text, usage = self.client.complete(messages)
            self.usage.add(usage)
            obj = parse_object(text)
        except (ValueError, RuntimeError):
            obj = {}
        got = {t: obj[str(k + 1)] for k, t in enumerate(batch)
               if isinstance(obj.get(str(k + 1)), str) and obj[str(k + 1)].strip()}
        missing = [t for t in batch if t not in got]
        if missing and len(batch) > 1:
            for half in (missing[:len(missing) // 2], missing[len(missing) // 2:]):
                if half:
                    got.update(self._request(half))
        return got

    def translate(self, texts: list[str], workers: int = 4) -> dict[str, str]:
        todo = [t for t in dict.fromkeys(texts) if t not in self.cache]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for got in pool.map(self._request, batches(todo)):
                self.cache.update(got)
        if self.cache_path and todo:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(self.cache, ensure_ascii=False))
        return {t: self.cache[t] for t in texts if t in self.cache}


def sidecar_path(log: str | Path, lang: str) -> Path:
    log = Path(log)
    return log.with_name(log.name.removesuffix(".jsonl") + f".{lang}.json")


def translate_log(log: str | Path, translator: Translator, out: str | Path | None = None) -> Path:
    with open(log) as f:
        texts = collect_texts(json.loads(line) for line in f if line.strip())
    done = translator.translate(texts)
    out = Path(out) if out else sidecar_path(log, translator.lang)
    out.write_text(json.dumps({"type": "translation", "lang": translator.lang,
                               "model": translator.client.model, "texts": done}, ensure_ascii=False))
    return out


class StubTranslateClient(Client):
    """Offline translator for tests: prefixes every line with the language tag."""
    model = "stub"

    def __init__(self, lang: str = "ru"):
        self.lang, self.calls = lang, 0

    def complete(self, messages: list[dict]) -> tuple[str, dict]:
        self.calls += 1
        obj = json.loads(messages[-1]["content"])
        return json.dumps({k: f"[{self.lang}] {v}" for k, v in obj.items()}, ensure_ascii=False), {}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("log")
    p.add_argument("--lang", default="ru")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--out", default=None)
    p.add_argument("--cache", default="runs/.cache/translate.{lang}.json")
    p.add_argument("--stub", action="store_true", help="no network, fake translations")
    a = p.parse_args(argv)
    client = StubTranslateClient(a.lang) if a.stub else make_client(a.model, temperature=0.2, max_tokens=4000)
    tr = Translator(client, a.lang, None if a.stub else a.cache.format(lang=a.lang))
    out = translate_log(a.log, tr, a.out)
    print(f"{out}: {len(json.loads(out.read_text())['texts'])} texts, model {client.model}, "
          f"tokens in/out {tr.usage.prompt_tokens}/{tr.usage.completion_tokens}, ${tr.usage.cost_usd:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
