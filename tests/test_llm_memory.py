"""Villager memory modes and the prompt layout for caching (docs/specs/memory-and-cache.md)."""

import json

from aivillage import engine
from aivillage.llm import CACHE_SPLIT, CACHE_POINT, DAY_LOG_LINES, LLMAgent, Usage, wire
from aivillage.run import llm_agents


class Echo:
    """Answers every turn with the same move and records what it was sent."""
    model = "echo"
    cache_key = None

    def __init__(self):
        self.calls = []

    def complete(self, messages):
        self.calls.append(messages)
        if messages[-1]["content"].startswith("End of day"):
            return json.dumps({"diary": "A day.", "people": {}}), {}
        return '{"thought": "go", "action": {"name": "wait"}, "say": "hello Boris"}', {}


def test_day_conversation_grows_and_ends_at_night():
    w = engine.new_world()
    c = Echo()
    agent = LLMAgent("Anna", "farmer", c, memory="day")
    for _ in range(3):
        agent.decide(engine.observe(w, "Anna"))
    first, last = c.calls[0], c.calls[-1]
    assert len(last) == len(first) + 4  # two earlier turns: what Anna saw + what she answered
    assert last[:len(first) - 2] == first[:len(first) - 2]  # the conversation only grows: the prefix stays cached
    assert [m["role"] for m in last[1:-2]] == ["user", "assistant"] * 2
    assert "hello Boris" in last[2]["content"]
    assert last[-2].get(CACHE_POINT) and not any(CACHE_POINT in m for m in last[:-2])
    agent.reflect(1)
    assert agent.turns == []
    agent.decide(engine.observe(w, "Anna"))
    assert len(c.calls[-1]) == len(first)


def test_fresh_mode_is_one_question():
    w = engine.new_world()
    c = Echo()
    agent = LLMAgent("Anna", "farmer", c, memory="fresh")
    for _ in range(3):
        agent.decide(engine.observe(w, "Anna"))
    assert len(c.calls[-1]) == 2 and agent.turns == []
    assert "your_last_actions" in c.calls[-1][1]["content"]


def test_day_conversation_is_capped():
    w = engine.new_world()
    agent = LLMAgent("Anna", "farmer", Echo(), memory="day")
    for _ in range(60):
        agent.remember_in_day(engine.observe(w, "Anna", consume_inbox=False), {"action": {"name": "wait"}})
    assert len(agent.turns) <= 2 * 48 and agent.turns[0]["role"] == "user"


def test_villagers_share_the_start_of_the_system_prompt():
    w = engine.new_world({"seed": 3})
    agents = llm_agents(w, ["stub"])
    heads = set()
    for name, ag in agents.items():
        msg = ag.messages(engine.observe(w, name, consume_inbox=False))[0]
        system = msg["content"]
        cut = system.index(f"You are {name}, a ")
        assert cut > len(system) // 2  # the villager's own part is at the end
        assert msg[CACHE_SPLIT] == cut - 2  # ...and is cached apart from the world part ("\n\n" before it)
        heads.add(system[:cut])
    assert len(heads) == 1
    assert {ag.client.cache_key for ag in agents.values()} == {f"aivillage-{n}" for n in agents}


def test_cache_point_on_the_wire():
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "line", CACHE_POINT: True}]
    openai = wire(msgs, True)
    assert openai[1]["content"] == [{"type": "text", "text": "line", "prompt_cache_breakpoint": {"mode": "explicit"}}]
    assert wire(msgs, False)[1] == {"role": "user", "content": "line"}
    assert CACHE_POINT in msgs[1]  # the agent's own copy is untouched
    claude = wire(msgs, "anthropic")  # Claude caches only where asked: the system prompt and the cache point
    for m in claude:
        assert m["content"] == [{"type": "text", "text": m["content"][0]["text"], "cache_control": {"type": "ephemeral"}}]
    assert wire([{"role": "user", "content": "obs"}], "anthropic") == [{"role": "user", "content": "obs"}]


def test_world_part_of_the_system_prompt_is_cached_apart():
    """The world text before "You are <name>" is the same for every villager and all day: it gets its own cache
    point, so a new memory in the morning (or another villager, on Claude) does not pay for it again."""
    msgs = [{"role": "system", "content": "world. You are Anna, a cook. memory", CACHE_SPLIT: 6},
            {"role": "user", "content": "obs"}]
    for mode, mark in ((True, {"prompt_cache_breakpoint": {"mode": "explicit"}}),
                       ("anthropic", {"cache_control": {"type": "ephemeral"}})):
        sent = wire(msgs, mode)[0]
        assert sent == {"role": "system", "content": [{"type": "text", "text": "world.", **mark},
                                                      {"type": "text", "text": " You are Anna, a cook. memory"}]}
    assert wire(msgs, False)[0] == {"role": "system", "content": "world. You are Anna, a cook. memory"}


def test_usage_counts_cached_tokens():
    u = Usage()
    u.add({"prompt_tokens": 100, "prompt_tokens_details": {"cached_tokens": 80}, "completion_tokens": 5})
    u.add({"prompt_tokens": 10})
    assert (u.prompt_tokens, u.cached_tokens) == (110, 80)


def test_a_busy_day_keeps_letters_for_the_diary():
    """A morning letter used to fall out of the 40-line day log before the night diary (Anna, 2026-10-06)."""
    ag = LLMAgent("Anna", "farmer", Echo())

    def turn(hour, news):
        obs = {"time": {"hour": hour, "minute": 0}, "you": {"location": "home_Anna"}, "news": news}
        ag.remember_turn(obs, {"thought": "work", "action": {"name": "work"}})

    turn(8, ['[day 6 08:00] Letter from anonymous: "Boris will kill you today"',
             '[day 6 08:00] Boris says: "Anna, sell me bread"'])
    for h in range(9, 21):
        turn(h, [f"[day 6 {h:02d}:00] Dmitri worked an hour on Well."] * 6)
    log = "\n".join(ag.day_log)
    assert len(ag.day_log) <= DAY_LOG_LINES
    assert "Letter from anonymous" in log and "Anna, sell me bread" in log
    assert sum("I did work" in l for l in ag.day_log) == 13  # own turns stay before others' news
    sent = []
    ag.client.complete = lambda m: sent.append(m) or (json.dumps({"diary": "x", "people": {}}), {})
    ag.reflect(6)
    assert "Letter from anonymous" in sent[0][-1]["content"]


def test_a_bare_string_action_does_not_crash_the_day_log():
    """Haiku once answered "action": "wait" and remember_turn crashed the whole run (E0 arm A, 2026-10-08)."""
    ag = LLMAgent("Anna", "farmer", Echo())
    ag.remember_turn({"time": {"hour": 9, "minute": 0}, "you": {"location": "square"}}, {"action": "wait"})
    assert "I did None" in ag.day_log[-1]


def test_changes_mode_sends_the_world_only_when_it_changes():
    """`llm_obs: changes`: the board, map, land... come once in the (cached) day conversation and again only when
    they change; the current observation keeps where you are, who is here, news and what was said to you."""
    w = engine.new_world({"seed": 3})
    c = Echo()
    agent = LLMAgent("Anna", "farmer", c, memory="day", obs_mode="changes")
    for _ in range(3):
        agent.decide(engine.observe(w, "Anna"))
    first, last = c.calls[0], c.calls[-1]
    assert "World (shown again only when it changes" in first[-2]["content"]  # the first turn shows it all
    obs = json.loads(last[-1]["content"].split("\n", 1)[1])
    assert "time" in obs and "you" in obs and "board" not in obs and "explored" not in obs
    assert "as last shown above: " in last[-1]["content"].split("\n", 1)[0]
    assert last[1]["content"] == first[-2]["content"]  # the history keeps the line exactly as sent: cache prefix
    assert "World (" not in last[-2]["content"]  # nothing changed while Anna waited
    obs = engine.observe(w, "Anna")
    obs["notice_board"] = ["Lost: a grey cat"]  # the notice board changes: shown again, and only it
    agent.decide(obs)
    shown = json.loads(c.calls[-1][-2]["content"].split("null = gone): ", 1)[1])
    assert shown == {"notice_board": ["Lost: a grey cat"]}
    agent.reflect(1)
    assert agent.shown == {}  # a new day shows everything again
    full = LLMAgent("Anna", "farmer", Echo(), memory="day", obs_mode="full")
    assert "board" in json.loads(full.messages(engine.observe(w, "Anna", consume_inbox=False))[-1]["content"].split("\n", 1)[1])
