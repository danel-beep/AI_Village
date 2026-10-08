"""Narrator voice for highlight clips ("🎞 Видео" with the settings panel's «Озвучка» on).

A model writes one short line per clip moment (plus a line for the hook and one for the end card) in the
voice of a dry, amused nature-documentary narrator; OpenAI text-to-speech (gpt-4o-mini-tts) reads each line.
viewer/clip.js asks `POST /api/narration` for the lines and the audio and mixes them over its own music.

Lines must fit their slots in the clip (the hook ~2.4 s, a moment ~4.8 s, the end card ~3.6 s), so the
prompt caps them by words and `fit()` cuts any line that is still too long. A failed script call falls back
to the moments' titles; speech needs the OpenAI key (the player's own, from keys.py).

    python -m aivillage.narration runs/x.jsonl --day 3 --out voice/   # lines + WAV files for one day's highlights
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import urllib.error
import urllib.request
from pathlib import Path

from . import keys
from .llm import Client, parse_json_object

TTS_URL = "https://api.openai.com/v1/audio/speech"
TTS_MODEL = "gpt-4o-mini-tts"
# gpt-4o-mini-tts bills $12 per 1M audio tokens, about $0.015-0.02 per minute; ~15 characters a second of speech.
TTS_USD_PER_CHAR = 0.02 / 60 / 15
MAX_WORDS = {"hook": 7, "moment": 12, "outro": 9}
STYLE = {
    "en": ("Dry, amused British nature-documentary narrator. Calm, slightly ironic, unhurried, "
           "with a small pause before the last words of each line. Never shout."),
    "ru": ("Сухой, слегка ироничный рассказчик из документального фильма о природе. Спокойно, неторопливо, "
           "с маленькой паузой перед последними словами. Без крика."),
}
LANG_NAMES = {"ru": "Russian", "en": "English"}

PROMPT = """You write the narrator's lines for a short vertical video about a village where every villager is an AI.
The narrator sounds like a dry, amused nature-documentary voice watching these creatures. He comments,
he does not repeat what the on-screen title already says, and he never invents events: use only the moments given.
Write in {language}. Lines are read aloud: short sentences, no brackets, no numbers written as digits, no emoji.
Limits: "hook" at most 7 words (opens the video over the strongest moment, marked ★, without spoiling it), each "moments" line at most
12 words (one per moment, same order), "outro" at most 9 words (end card; invite the viewer to follow the village).
Answer ONLY a JSON object: {"hook": "...", "moments": ["...", "..."], "outro": "..."}"""

FALLBACK = {
    "en": {"hook": "Meanwhile, in the village of AIs.", "outro": "What will they do next? Follow the village."},
    "ru": {"hook": "Тем временем в деревне ИИ.", "outro": "Что они сделают дальше? Подписывайтесь."},
}


def fit(line: str, slot: str) -> str:
    """At most MAX_WORDS[slot] words, so the line fits its seconds in the clip."""
    words = " ".join(str(line or "").split()).split(" ")
    words = [w for w in words if w]
    if len(words) <= MAX_WORDS[slot]:
        return " ".join(words)
    return " ".join(words[:MAX_WORDS[slot]]).rstrip(",;:—-") + "."


def script(items: list[dict], lang: str = "en", client: Client | None = None) -> dict:
    """{"hook", "moments": [...], "outro", "source": "model"|"titles", "cost_usd"} for clip moments
    `items` ([{title, line, who, kind, top?}], clip order); the hook plays over the item with `top`."""
    lang = lang if lang in LANG_NAMES else "en"
    base = {"hook": FALLBACK[lang]["hook"], "moments": [fit(it.get("title", ""), "moment") for it in items],
            "outro": FALLBACK[lang]["outro"], "source": "titles", "cost_usd": 0.0}
    if client is None or not items:
        return base
    listing = "\n".join(f"{k + 1}. [{it.get('kind', '')}] {it.get('title', '')}: {it.get('line', '')}"
                        f" (who: {', '.join(it.get('who') or [])})" + (" ★" if it.get("top") else "")
                        for k, it in enumerate(items))
    try:
        reply, usage = client.complete([{"role": "system", "content": PROMPT.replace("{language}", LANG_NAMES[lang])},
                                        {"role": "user", "content": f"Moments in clip order:\n{listing}"}])
    except Exception:  # narration never stops a clip: the titles are read instead
        return base
    obj = parse_json_object(reply, "moments") or {}
    lines = obj.get("moments") if isinstance(obj.get("moments"), list) else []
    if len(lines) != len(items) or not all(isinstance(x, str) and x.strip() for x in lines):
        return {**base, "cost_usd": float(usage.get("cost") or 0)}
    return {"hook": fit(obj.get("hook") or base["hook"], "hook"), "moments": [fit(x, "moment") for x in lines],
            "outro": fit(obj.get("outro") or base["outro"], "outro"), "source": "model",
            "cost_usd": float(usage.get("cost") or 0)}


def speak(text: str, voice: str | None = None, lang: str = "en", key: str | None = None,
          cache: Path | None = None, timeout: float = 60) -> bytes:
    """WAV bytes of `text` read by OpenAI TTS. Cached by (text, voice, style) in `cache` when given."""
    key = key or keys.get("openai_key")
    if not key:
        raise RuntimeError("narration needs the OpenAI key (settings panel)")
    voice = voice or keys.tts_voice()
    body = {"model": TTS_MODEL, "voice": voice, "input": text, "instructions": STYLE.get(lang, STYLE["en"]),
            "response_format": "wav"}
    name = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:24] + ".wav"
    if cache is not None and (cache / name).is_file():
        return (cache / name).read_bytes()
    req = urllib.request.Request(TTS_URL, json.dumps(body).encode(),
                                 {"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"OpenAI TTS {e.code}: {detail}") from None
    if cache is not None:
        cache.mkdir(parents=True, exist_ok=True)
        (cache / name).write_bytes(data)
    return data


def narrate(items: list[dict], lang: str = "en", client: Client | None = None, voice: str | None = None,
            cache: Path | None = None, speaker=None) -> dict:
    """Lines and base64 WAVs for a clip: {"lines": {hook, moments, outro}, "audio": {hook, moments, outro},
    "voice", "source", "cost_usd"}. `speaker` is replaceable for tests."""
    lines = script(items, lang, client)
    voice = voice or keys.tts_voice()
    speaker = speaker or speak
    say = lambda t: base64.b64encode(speaker(t, voice=voice, lang=lang, cache=cache)).decode()  # noqa: E731
    audio = {"hook": say(lines["hook"]), "moments": [say(t) for t in lines["moments"]], "outro": say(lines["outro"])}
    chars = len(lines["hook"]) + len(lines["outro"]) + sum(len(t) for t in lines["moments"])
    return {"lines": {k: lines[k] for k in ("hook", "moments", "outro")}, "audio": audio, "voice": voice,
            "source": lines["source"], "cost_usd": lines["cost_usd"] + chars * TTS_USD_PER_CHAR}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Narrator lines and WAV files for one day's highlights of a log.")
    p.add_argument("log")
    p.add_argument("--day", type=int, required=True)
    p.add_argument("--lang", choices=sorted(LANG_NAMES), default=None, help="default: the settings panel's")
    p.add_argument("--model", default="default", help="model for the lines ('stub' = read the titles)")
    p.add_argument("--out", default="narration", help="folder for the WAV files")
    a = p.parse_args(argv)
    from .highlights import sidecar_path
    from .summary import make_client
    days = json.loads(sidecar_path(a.log).read_text(encoding="utf-8"))
    day = next((d for d in days if d.get("day") == a.day), None)
    if day is None:
        raise SystemExit(f"no highlights for day {a.day}: run python -m aivillage.highlights {a.log} first")
    lang = a.lang or keys.content_lang()
    out = Path(a.out)
    res = narrate(day["items"], lang, None if a.model == "stub" else make_client(a.model), cache=out / ".cache")
    out.mkdir(parents=True, exist_ok=True)
    parts = [("hook", res["lines"]["hook"], res["audio"]["hook"])]
    parts += [(f"moment{k + 1}", t, b) for k, (t, b) in enumerate(zip(res["lines"]["moments"], res["audio"]["moments"]))]
    parts.append(("outro", res["lines"]["outro"], res["audio"]["outro"]))
    for name, text, b64 in parts:
        (out / f"day{a.day}-{name}.wav").write_bytes(base64.b64decode(b64))
        print(f"{name}: {text}")
    print(f"voice {res['voice']}, lines by {res['source']}, about ${res['cost_usd']:.4f} -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
