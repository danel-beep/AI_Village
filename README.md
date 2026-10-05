# AI Village

Деревня, где каждый житель — отдельная LLM. Готовы шаги 1–2 из [спецификации](https://claude.ai/code/artifact/df507acc-4173-430d-9dfe-760898a4e089): детерминированный движок мира, скриптовые боты, LLM-агенты через OpenRouter и 2D-вьюер.

## Запуск

```bash
pip install pydantic pytest
python -m aivillage.run --days 10 --bots worker,worker,thief,worker,random --log runs/demo.jsonl --fire-day 3
python -m aivillage.run --replay runs/demo.jsonl     # проверить, что лог воспроизводится один в один
python -m pytest -q
```

## LLM-агенты и 2D-вьюер

```bash
export OPENROUTER_API_KEY=...   # ключ openrouter.ai
python -m aivillage.run --days 2 --agents 3 --models google/gemini-2.5-flash-lite --log runs/llm.jsonl
python -m aivillage.run --days 2 --models stub --log runs/stub.jsonl   # без ключа: «модель» отвечает как бот
python -m http.server 8000      # затем открыть http://localhost:8000/viewer/?log=/runs/llm.jsonl
```

`--models a,b,c` раздаёт модели жителям по кругу. Агенты думают параллельно, упавший провайдер = «ждать», а не падение деревни. В конце прогона печатаются вызовы, токены и стоимость по каждому агенту. Один ход стоит ~1300 токенов на вход.

## Живой просмотр и режим бога

```bash
pip install -e .[live]
python -m aivillage.server --days 30                                   # боты
python -m aivillage.server --agents 3 --models google/gemini-2.5-flash-lite   # LLM
# открыть http://localhost:8000
```

Ходы приходят в браузер сразу, пока идёт прогон. Кнопка «⚡ Режим бога» внизу справа: поджечь дом, клад, слух, засуха, болезнь, подарок, а также пауза и скорость (`--pace` секунд на ход). Вмешательства пишутся в лог (`runs/live.jsonl`), так что прогон по-прежнему воспроизводится через `--replay`.

## Как устроено

| Файл | Что внутри |
| --- | --- |
| `aivillage/config.py` | все числа мира: еда, цены, налог, карта, рецепты, профессии |
| `aivillage/state.py` | состояние мира (dataclasses), сериализация, хеш |
| `aivillage/registry.py` | реестр действий: из одного объявления получаются описание для промпта, JSON-схема и проверка |
| `aivillage/actions.py` | 25 действий агентов |
| `aivillage/god.py` | режим бога: пожар, клад, слух, засуха, болезнь, подарок |
| `aivillage/engine.py` | `new_world`, `observe` (всё, что видит агент), `step` (один игровой час), ночь |
| `aivillage/invariants.py` | проверки после каждого хода: ничего не берётся из ниоткуда, нет отрицательных значений |
| `aivillage/bots.py` | скриптовые агенты: random (фаззер), worker (честный), thief (вор) |
| `aivillage/run.py` | прогон, JSONL-лог, реплей |
| `aivillage/llm.py` | LLM-агент: промпт, разбор ответа, заметки агента, клиенты OpenRouter и stub |
| `viewer/index.html` | 2D-карта деревни: воспроизводит лог, мысли и реплики жителей |

Агент получает только словарь `observe(world, name)` и отвечает решением
`{"thought": "...", "action": {"name": "...", "args": {...}}, "say": "..."}`.
LLM-агенты на шаге 2 будут использовать ровно этот интерфейс, как сейчас боты.

## Как добавить механику

1. Новое действие в `actions.py` через `@ACTIONS.action(name, description, ArgsModel)`.
2. Числа — в `config.py`.
3. Тест в `tests/test_mechanics.py`. Фаззер в `tests/test_sim.py` сам начнёт вызывать новое действие.
