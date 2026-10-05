# AI Village

Деревня, где каждый житель — отдельная LLM. Сейчас готов шаг 1 из [спецификации](https://claude.ai/code/artifact/df507acc-4173-430d-9dfe-760898a4e089): детерминированный движок мира без LLM, скриптовые боты и тесты.

## Запуск

```bash
pip install pydantic pytest
python -m aivillage.run --days 10 --bots worker,worker,thief,worker,random --log runs/demo.jsonl --fire-day 3
python -m aivillage.run --replay runs/demo.jsonl     # проверить, что лог воспроизводится один в один
python -m pytest -q
```

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

Агент получает только словарь `observe(world, name)` и отвечает решением
`{"thought": "...", "action": {"name": "...", "args": {...}}, "say": "..."}`.
LLM-агенты на шаге 2 будут использовать ровно этот интерфейс, как сейчас боты.

## Как добавить механику

1. Новое действие в `actions.py` через `@ACTIONS.action(name, description, ArgsModel)`.
2. Числа — в `config.py`.
3. Тест в `tests/test_mechanics.py`. Фаззер в `tests/test_sim.py` сам начнёт вызывать новое действие.
