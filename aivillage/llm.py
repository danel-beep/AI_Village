"""LLM agents: turn an observation into a prompt, call a model, parse the decision.

Models are reached through one interface, `Client.complete(messages) -> (text, usage)`.
`OpenRouterClient` covers GPT, Claude, Gemini, DeepSeek and others with one key;
`StubClient` answers like a scripted bot so the whole pipeline runs without a key.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from .bots import WorkerBot
from .registry import ACTIONS

SYSTEM = """You are {name}, a villager ({profession}) in a small village. You are a person, not an assistant.
Survive and live your life: eat, work, earn coins, pay the weekly tax, deal with your neighbours.
Nobody tells you what is right. You may cooperate, trade, lend, promise, lie, steal or betray. Others may do the same to you.
Coins only enter the village when someone sells to the trader at the market, who pays little and charges a lot,
so trading directly with neighbours is usually better.

Each hour you get a JSON observation and answer with ONE JSON object and nothing else:
{{"thought": "short private reasoning, nobody else sees it",
  "action": {{"name": "<action>", "args": {{...}}}},
  "say": "optional words spoken out loud to people here, or null",
  "notes": "optional: your updated private notes about people and plans (replaces old notes)"}}

Actions:
{actions}

Locations are ids like square, market, field, river, forest, mine, smithy, home_<Name>.
Item maps look like {{"bread": 2, "coins": 5}}. Keep "thought" under 40 words."""

REFLECT = """You are {name}, a villager ({profession}). The day is over and you are alone with your thoughts.
Below is what you did, said and noticed today. Answer with ONE JSON object and nothing else:
{{"diary": "your private diary entry for today, first person, at most {words} words",
  "people": {{"<Name>": "what you now think of this person: trust, debts, promises, grudges, plans (one or two sentences)"}}}}
In "people" include only villagers your opinion of changed today; their old entries are kept otherwise.
Be honest with yourself: nobody else will ever read this."""

DIARY_WORDS = 150
DAY_LOG_LINES = 40
PERSON_NOTE_CHARS = 300


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    calls: int = 0
    failures: int = 0

    def add(self, other: dict) -> None:
        self.prompt_tokens += int(other.get("prompt_tokens", 0))
        self.completion_tokens += int(other.get("completion_tokens", 0))
        self.cost_usd += float(other.get("cost", 0.0) or 0.0)
        self.calls += 1


class Client:
    model = "?"

    def complete(self, messages: list[dict]) -> tuple[str, dict]:
        raise NotImplementedError


class OpenRouterClient(Client):
    URL = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(self, model: str, api_key: str | None = None, timeout: float = 90, retries: int = 2,
                 max_tokens: int = 400, temperature: float = 0.8):
        self.model, self.temperature = model, temperature
        self.key = api_key or os.environ.get("OPENROUTER_API_KEY")
        if not self.key:
            raise RuntimeError("OPENROUTER_API_KEY is not set")
        self.timeout, self.retries, self.max_tokens = timeout, retries, max_tokens

    def complete(self, messages: list[dict]) -> tuple[str, dict]:
        body = json.dumps({"model": self.model, "messages": messages, "max_tokens": self.max_tokens,
                           "temperature": self.temperature, "usage": {"include": True}}).encode()
        req = urllib.request.Request(self.URL, body, {"Authorization": f"Bearer {self.key}",
                                                      "Content-Type": "application/json"})
        last: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    data = json.load(r)
                return data["choices"][0]["message"]["content"] or "", data.get("usage", {})
            except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as e:
                last = e
                time.sleep(2 ** attempt)
        raise RuntimeError(f"{self.model}: {last}")


class StubClient(Client):
    """Answers with a WorkerBot decision the way an LLM would: JSON wrapped in prose."""
    model = "stub"

    def __init__(self, name: str):
        self.bot = WorkerBot(name)

    def complete(self, messages: list[dict]) -> tuple[str, dict]:
        if messages[-1]["content"].startswith("End of day"):
            return self.reflect(messages[-1]["content"])
        obs = json.loads(messages[-1]["content"].split("\n", 1)[1])
        obs.setdefault("offers_to_you", [])
        obs.setdefault("your_offers", [])
        obs.setdefault("fires", [])
        obs["board"].setdefault("orders", [])
        obs["board"]["trader_prices"] = {k: {"buy": int(v.split("/")[0]), "sell": int(v.split("/")[1])}
                                         for k, v in obs["board"]["trader_prices"].items()}
        dec = self.bot.decide(obs)
        usage = {"prompt_tokens": sum(len(m["content"]) for m in messages) // 4, "completion_tokens": 60}
        return "Sure! ```json\n" + json.dumps(dec) + "\n```", usage

    def reflect(self, text: str) -> tuple[str, dict]:
        seen = sorted(set(re.findall(r"\b([A-Z][a-z]+) (?:said|gave|stole|sold|bought|offered|paid|lent)", text)))
        seen = [n for n in seen if n != self.bot.name]
        reply = {"diary": f"Another day of work. I saw {', '.join(seen) or 'nobody'}.",
                 "people": {n: "Seen around today." for n in seen}}
        return json.dumps(reply), {"prompt_tokens": len(text) // 4, "completion_tokens": 40}


def parse_decision(text: str) -> dict:
    """Pull the first JSON object out of a model reply. Never raises: bad replies become `wait`."""
    d = parse_json_object(text, "action")
    if d is not None:
        return d
    return {"thought": "(unparseable reply)", "action": {"name": "wait"}, "parse_error": text[:200]}


def parse_json_object(text: str, key: str) -> dict | None:
    """The first JSON object in `text` that has `key`, or None."""
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                esc = (ch == "\\") and not esc
                if ch == '"' and not esc:
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        d = json.loads(text[start:i + 1])
                        if isinstance(d, dict) and key in d:
                            return d
                    except json.JSONDecodeError:
                        pass
                    break
        start = text.find("{", start + 1)
    return None


def compact_obs(obs: dict) -> dict:
    """Drop what the agent does not need every hour, to save tokens."""
    o = json.loads(json.dumps(obs))
    o["board"].pop("recipes", None)
    o["board"]["trader_prices"] = {k: f"{v['buy']}/{v['sell']}" for k, v in o["board"]["trader_prices"].items()}
    for k in ("fires", "offers_to_you", "your_offers"):
        if not o[k]:
            del o[k]
    for k, v in list(o["board"].items()):
        if not v:
            del o["board"][k]
    return o


@dataclass
class LLMAgent:
    name: str
    profession: str
    client: Client
    notes: str = ""
    usage: Usage = field(default_factory=Usage)
    people: dict[str, str] = field(default_factory=dict)  # memory about other villagers, updated at night
    diary: list[dict] = field(default_factory=list)  # [{"day", "text"}], one per night
    day_log: list[str] = field(default_factory=list)  # today's turns, consumed by reflect()
    villagers: set[str] = field(default_factory=set)

    def messages(self, obs: dict) -> list[dict]:
        system = SYSTEM.format(name=self.name, profession=self.profession, actions=ACTIONS.describe())
        memory = {"notes": self.notes or "none"}
        if self.people:
            memory["people"] = self.people
        if self.diary:
            memory["last_diary"] = self.diary[-1]["text"]
        user = "Observation (your memory: " + json.dumps(memory) + "):\n" + json.dumps(compact_obs(obs))
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def remember_turn(self, obs: dict, dec: dict) -> None:
        self.villagers |= {v["name"] for v in obs.get("board", {}).get("villagers", [])} - {self.name}
        t = obs.get("time", {})
        lines = [f"{t.get('hour', '?')}:00 news: {n}" for n in obs.get("news", [])]
        if obs.get("last_error"):
            lines.append(f"{t.get('hour', '?')}:00 failed: {obs['last_error']}")
        act = dec.get("action") or {}
        line = f"{t.get('hour', '?')}:00 at {obs.get('you', {}).get('location', '?')}: I did {act.get('name')}"
        if act.get("args"):
            line += " " + json.dumps(act["args"])
        if dec.get("say"):
            line += f', said "{dec["say"]}"'
        if dec.get("thought"):
            line += f" (thinking: {dec['thought']})"
        self.day_log.extend(l[:200] for l in lines + [line])
        del self.day_log[: max(0, len(self.day_log) - DAY_LOG_LINES)]

    def decide(self, obs: dict) -> dict:
        try:
            text, usage = self.client.complete(self.messages(obs))
        except Exception as e:  # a dead provider must never stop the village
            self.usage.failures += 1
            return {"thought": f"(model error: {e})"[:200], "action": {"name": "wait"}}
        self.usage.add(usage)
        dec = parse_decision(text)
        if isinstance(dec.get("notes"), str):
            self.notes = dec["notes"][:1000]
        self.remember_turn(obs, dec)
        return dec

    def reflect(self, day: int) -> dict | None:
        """Night: write a diary entry and update memory about people. Returns the entry, or None if the
        agent did nothing today or the model failed (memory is then left as it was)."""
        if not self.day_log:
            return None
        log, self.day_log = self.day_log, []
        system = REFLECT.format(name=self.name, profession=self.profession, words=DIARY_WORDS)
        user = (f"End of day {day}. What you thought of people before today: {json.dumps(self.people or 'nothing yet')}\n"
                "Today:\n" + "\n".join(log))
        try:
            text, usage = self.client.complete([{"role": "system", "content": system},
                                                {"role": "user", "content": user}])
        except Exception:
            self.usage.failures += 1
            return None
        self.usage.add(usage)
        d = parse_json_object(text, "diary")
        if not d or not isinstance(d.get("diary"), str):
            return None
        entry = {"day": day, "text": " ".join(d["diary"].split()[:DIARY_WORDS])}
        self.diary.append(entry)
        if isinstance(d.get("people"), dict):
            for who, note in d["people"].items():
                if who in self.villagers and isinstance(note, str) and note.strip():
                    self.people[who] = note.strip()[:PERSON_NOTE_CHARS]
        return {**entry, "people": dict(self.people)}


def reflect_all(agents: dict[str, LLMAgent], day: int) -> dict[str, dict]:
    """Every agent reflects at the same time. Returns {name: entry} for agents that wrote one."""
    if not agents:
        return {}
    with ThreadPoolExecutor(max_workers=len(agents)) as pool:
        results = list(pool.map(lambda a: a.reflect(day), agents.values()))
    return {name: r for name, r in zip(agents, results) if r}
