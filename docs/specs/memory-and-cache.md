# Villager memory and prompt caching

What a villager sees on every turn, how much of it the provider bills at the cached price, and why.
Measurements: `/mnt/project-files/reports/memory-cache/otchet.md` (Russian, for Danel).

## Layout of a turn (`llm.LLMAgent.messages`)

`llm_memory: day` (default, config key, app setting «Память жителя за день»):

| # | role | content | changes |
|---|------|---------|---------|
| 1 | system | `SYSTEM`: world rules, handbook, world facts (identical for every villager), then `You are <name>, a <profession>.` + goals + character, then `Your memory of earlier days:` own words (about_me / wants / plan), `people`, `your_diary` (last `DAY_DIARIES` = 3 days) | at night, or when an action unlocks |
| 2.. | user / assistant | today's earlier turns: `turn_line(obs)` (time, place, satiety, health, coins, news, last error) and the villager's own reply (thought, action, say) | append-only during the day |
| n-1 | user | `turn_line` of the current turn, marked `CACHE_POINT` | every turn (becomes history next turn) |
| n | user | `Observation (your notes: ...)` + full `compact_obs` | every turn (replaced next turn) |

The conversation is reset in `reflect()` (the diary carries the day over) and capped at `DAY_TURNS` = 48 turns (the
older half is dropped at once, one cache miss). Saves keep it (`saves.py`, `turns`).

`llm_memory: fresh`: the old way, two messages: the same `SYSTEM`, then one user message with memory (own words,
notes, last 3 actions, people, last diary) and the observation.

## Caching rules this layout relies on (measured on `gpt-6-luna`, OpenAI direct, 2026-10-06)

- OpenAI caches implicitly at the end of the system message and at the end of the whole prompt. A prompt whose last
  message changes every turn therefore caches **only the system prompt**: history added in the middle is billed in
  full every turn (measured: 61% cached with history vs 72% with a breakpoint).
- An explicit breakpoint is a content part `{"type": "text", "text": ..., "prompt_cache_breakpoint": {"mode":
  "explicit"}}` on a **user** message (on an assistant message it is ignored). The next call reads the cache up to
  it. `prompt_cache_options: {"mode": "explicit"}` turns implicit caching off: do not send it.
- `prompt_cache_key` routes calls with the same key to the same cache; one key per villager (`aivillage-<name>`).
  Unknown to OpenRouter, so only `OpenAIClient` sends it and the breakpoint (`llm.wire`).
- Usage reports `prompt_tokens_details.cached_tokens` (read at a tenth of the input price) and `cache_write_tokens`
  (the uncached part). `openai_cost` bills writes at the input price; OpenAI says GPT-5.6+ writes have their own
  price, so check the real bill once.
- The reuse window is about 30 minutes; a villager's turns are seconds to minutes apart.
- The system message is sent in two parts (`CACHE_SPLIT`, 2026-10-08): the world text before "You are <name>"
  (handbook and world facts, ~9k tokens, the same for every villager) gets its own breakpoint. Without it the first
  turn after the intro and every morning (new memory at the end of the system message) paid for the whole prompt
  again. OpenAI shares that part only between calls with the same `prompt_cache_key`, i.e. one villager's mornings;
  Claude shares it between all villagers within its 5 minutes.
- An explicit breakpoint on a system content part works the same as on a user message (measured).
- Claude (`anthropic/*` via OpenRouter) caches nothing without `cache_control`: the client marks the same points.
  Writes cost 1.25x the input price, reads 0.1x; Claude's 5-minute window is long enough for one village day.
- OpenAI's `service_tier: "flex"` (default, settings field `openai_tier`): half price, ~10 s a call instead of ~3 s,
  about one call in five answered "busy" (429) and sent again at once at the normal price. Same model, same answers.

## Where the money goes (5 villagers x 2 days, Luna, before this change)

Uncached input (mostly the observation, ~2.5k tokens a turn) 62%, output (thought/action/say + hidden reasoning,
~200 tokens) 25%, cached input 13%. The next real saving is a smaller uncached observation: parts that rarely change
(`board`, `trader_today`, `village_structures`, `village_plots`, `government`, `land_for_sale`, ~900 tokens) could go
into the day conversation only when they change. Not done: it changes what the model sees and needs its own A/B.

## Rules for new code

- Anything the same for every villager goes into `SYSTEM` / `world_facts` (cached). Never put a per-villager or
  per-turn value before `You are {name}` in `SYSTEM`.
- Per-turn values go into the observation (last message). Values that only change at night go into
  `long_memory()`.
- New text the villager reads on every turn (`turn_line`, observation fields) must pass `tests/test_neutrality.py`.
