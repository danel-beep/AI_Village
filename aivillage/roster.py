"""Model roster for comparison runs: which model sits in which villager, picked from the seed.

A roster is a list of brains, one per "seat" group: model ids (`openai/gpt-6-luna`, `deepseek/...`),
`default`, `stub`, or a scripted bot `bot:<kind>` (offline tests of the whole comparison pipeline).

    assign(names, roster, seed, rotate)  -> {villager: brain}

The seating is a seeded shuffle of the villagers, then the roster dealt round-robin, so:
- the same seed always gives the same village (map, start goods, characters) AND the same seating;
- every model gets floor/ceil(N/M) villagers;
- `rotate=k` shifts the deal by k: rotations 0..M-1 over one seed put every model in every seat once,
  so a model cannot win just because the seed gave it the rich plot.

`auto(...)` builds a roster from OpenRouter's public model list: per company the newest ultra-cheap model
(OpenAI's is always `llm.DEFAULT_MODEL`, which goes to OpenAI directly). `pick(catalog)` is the pure part.
"""

from __future__ import annotations

import json
import random
import time
import urllib.request

CATALOG_URL = "https://openrouter.ai/api/v1/models"
# Companies for `models: auto`, in this order (the first ones are used when there are fewer villagers).
COMPANIES = ["openai", "anthropic", "google", "deepseek", "x-ai", "qwen", "mistralai", "moonshotai", "z-ai",
             "meta-llama"]
# USD per 1M tokens. "Ultra cheap": the newest model under CHEAP; a company with none there gets its cheapest
# recent model if it stays under MAX (so Claude takes part via its smallest model).
CHEAP = (0.5, 2.5)
MAX = (1.5, 6.0)
RECENT_DAYS = 365
SKIP_WORDS = ("embed", "guard", "audio", "image", "tts", "search", "online", "research", "coder", "vision", "ocr")
# A villager-day at one turn per game hour (joint run #1, GPT-6 Luna): ~25k prompt + ~1k completion tokens.
TOKENS_PER_VILLAGER_DAY = (25_000, 1_000)
BUDGET_PER_DAY = 5.0  # Danel's budget, USD per real day


def is_bot(brain: str) -> bool:
    return brain.startswith("bot:")


def assign(names: list[str], roster: list[str], seed: int, rotate: int = 0) -> dict[str, str]:
    """{villager: brain}: a seeded seating of `names`, roster dealt round-robin from seat `rotate`."""
    if not roster:
        return {}
    seats = sorted(names)
    random.Random(f"{seed}:roster").shuffle(seats)
    return {n: roster[(i + rotate) % len(roster)] for i, n in enumerate(seats)}


def _price(m: dict) -> tuple[float, float] | None:
    p = m.get("pricing") or {}
    try:
        inp, out = float(p.get("prompt")) * 1e6, float(p.get("completion")) * 1e6
    except (TypeError, ValueError):
        return None
    return (inp, out) if inp > 0 and out > 0 else None


def _usable(m: dict) -> bool:
    mid = m.get("id", "")
    arch = m.get("architecture") or {}
    outs = arch.get("output_modalities") or [str(arch.get("modality", "text->text")).split("->")[-1]]
    return ("/" in mid and ":" not in mid and outs == ["text"]
            and not any(w in mid.lower() for w in SKIP_WORDS))


def pick(catalog: list[dict], now: float | None = None, companies: list[str] | None = None) -> dict[str, dict]:
    """{company: {"id", "in", "out", "created"}} from an OpenRouter /models list (pure)."""
    now = time.time() if now is None else now
    out: dict[str, dict] = {}
    for company in companies or COMPANIES:
        rows = []
        for m in catalog:
            price = _price(m)
            if (m.get("id", "").split("/")[0] == company and price and _usable(m)
                    and now - float(m.get("created") or 0) <= RECENT_DAYS * 86400):
                rows.append({"id": m["id"], "in": round(price[0], 4), "out": round(price[1], 4),
                             "created": int(m.get("created") or 0)})
        cheap = [r for r in rows if r["in"] <= CHEAP[0] and r["out"] <= CHEAP[1]]
        if cheap:
            out[company] = max(cheap, key=lambda r: (r["created"], -r["in"]))
            continue
        ok = [r for r in rows if r["in"] <= MAX[0] and r["out"] <= MAX[1]]
        if ok:
            out[company] = min(ok, key=lambda r: (_villager_day(r), -r["created"]))
    return out


def fetch_catalog(timeout: float = 20) -> list[dict]:
    with urllib.request.urlopen(CATALOG_URL, timeout=timeout) as r:
        return json.load(r)["data"]


def auto(count: int | None = None, catalog: list[dict] | None = None, now: float | None = None) -> list[str]:
    """Roster of the newest ultra-cheap model per company (OpenAI = llm.DEFAULT_MODEL), at most `count`."""
    from .llm import DEFAULT_MODEL
    picked = pick(catalog if catalog is not None else fetch_catalog(), now=now)
    roster = [DEFAULT_MODEL if c == "openai" else picked[c]["id"] for c in COMPANIES if c in picked or c == "openai"]
    return roster[:count] if count else roster


def _villager_day(price: dict) -> float:
    return (TOKENS_PER_VILLAGER_DAY[0] * price["in"] + TOKENS_PER_VILLAGER_DAY[1] * price["out"]) / 1e6


def estimate(seating: dict[str, str], days: int, prices: dict[str, dict], turns_scale: float = 1.0) -> dict:
    """Rough cost of a run: {"total", "by_model": {brain: usd}, "unknown": [brains without a price]}.
    `prices`: brain -> {"in", "out"} per 1M tokens; `turns_scale` multiplies turns (4 for quarter-hour turns)."""
    by: dict[str, float] = {}
    unknown = set()
    for brain in seating.values():
        if is_bot(brain) or brain == "stub":
            continue
        if brain not in prices:
            unknown.add(brain)
            continue
        by[brain] = by.get(brain, 0.0) + _villager_day(prices[brain]) * days * turns_scale
    return {"total": round(sum(by.values()), 4), "by_model": {k: round(v, 4) for k, v in by.items()},
            "unknown": sorted(unknown)}


def catalog_prices(catalog: list[dict]) -> dict[str, dict]:
    """{model id: {"in", "out"}} for every priced model in an OpenRouter catalog."""
    out = {}
    for m in catalog:
        p = _price(m)
        if p:
            out[m["id"]] = {"in": p[0], "out": p[1]}
    return out
