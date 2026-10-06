"""Start-screen settings: every knob the app shows before "Play", in one list.

The viewer's start screen (viewer/setup.js) draws itself from `schema()`, so a new knob is one dict in
`KNOBS`, nothing else:

    {"key": "fire_chance", "path": "crises.fire_chance", "group": "Беды", "type": "range",
     "label": "Случайные пожары", "min": 0, "max": 100, "step": 5, "scale": 0.01, "unit": "%"}

- `path`: dotted key in the world config (config.DEFAULT_CONFIG). The default comes from the chosen
  economy mode (so switching the mode moves the slider), and the value lands in the run's world override.
  A knob whose path is not in DEFAULT_CONFIG yet is hidden, so knobs can be listed before their feature lands.
- no `path`: a run option handled in `to_run()` (villagers, days, mode, pace, ...).
- `scale`: config value = slider value * scale (percent sliders: 0.01).
- `only`: "llm" or "bots" shows the knob for that kind of village only.
- `roster` (not a knob): optional list of {name, profession, character} from "Жители по одному".
- `type`: "range" (slider), "choice" (buttons; `options` = [[value, label], ...]), "toggle", "number".
"""

from __future__ import annotations

import copy
from typing import Any

from . import modes
from .config import DEFAULT_CONFIG, make_config

BOT_MIXES = {
    "mixed": ["worker", "worker", "thief", "worker", "random"],
    "workers": ["worker"],
    "traders": ["trader", "worker"],
    "thieves": ["thief", "worker"],
    "homestead": ["homestead", "worker"],
}

KNOBS: list[dict[str, Any]] = [
    # --- village ---
    {"key": "brains", "group": "Деревня", "type": "choice", "label": "Кто живёт в деревне", "default": "llm",
     "options": [["llm", "🧠 ИИ-жители"], ["bots", "🤖 Боты (бесплатно)"]],
     "hint": "ИИ-жители думают через ключ OpenAI или OpenRouter (кнопка «⚙️ Настройки»), стоят центы. "
             "Боты: простые программы, бесплатно, для проверки мира."},
    {"key": "villagers", "group": "Деревня", "type": "range", "label": "Сколько жителей",
     "min": 2, "max": 60, "step": 1, "default": 5,
     "hint": "Больше пяти: новые жители получают имена и профессии сами, ресурсов в мире больше."},
    {"key": "days", "group": "Деревня", "type": "range", "label": "Сколько игровых дней",
     "min": 1, "max": 60, "step": 1, "default": 3, "unit": " дн."},
    {"key": "bot_mix", "group": "Деревня", "type": "choice", "label": "Какие боты", "only": "bots",
     "default": "mixed", "options": [["mixed", "Смешанные"], ["workers", "Трудяги"], ["traders", "Торговцы"],
                                     ["thieves", "Много воров"], ["homestead", "Хозяйственные"]]},
    {"key": "characters", "group": "Деревня", "type": "choice", "label": "Характер жителей", "only": "llm",
     "default": "default", "options": [["default", "😐 Нейтральный у всех"], ["random", "🎲 Случайный у каждого"]],
     "hint": "Характер: одна мягкая строка о темпераменте в подсказке жителя, не приказ. Каждого жителя "
             "можно настроить отдельно ниже, в «Жители по одному»."},
    {"key": "summaries", "group": "Деревня", "type": "toggle", "label": "Сводки «Что произошло?» и хайлайты от ИИ",
     "only": "llm", "default": True, "hint": "Пересказ каждого дня, около $0.0003 за день."},

    # --- rules ---
    {"key": "mode", "group": "Правила", "type": "choice", "label": "Режим экономики", "default": modes.DEFAULT_MODE,
     "options": [[m, v["title"]] for m, v in modes.MODES.items()],
     "about": {m: v["about"] for m, v in modes.MODES.items()},
     "hint": "Режим двигает ползунки ниже. Подсказка жителям одна и та же во всех режимах."},
    {"key": "unfairness", "path": "map.unfairness", "group": "Правила", "type": "range", "scale": 0.1,
     "label": "Нечестный старт", "min": 0, "max": 10, "step": 1,
     "hint": "0: у всех одинаковые участки, деньги и дорога до работы. 10: у кого-то большой участок и "
             "запасы, у кого-то клочок земли и пустой карман."},
    {"key": "start_coins", "path": "start_coins", "group": "Правила", "type": "range", "label": "Монет на старте",
     "min": 0, "max": 200, "step": 5},
    {"key": "tax_amount", "path": "tax_amount", "group": "Правила", "type": "range", "label": "Налог",
     "min": 0, "max": 100, "step": 5, "unit": " мон."},
    {"key": "tax_every_days", "path": "tax_every_days", "group": "Правила", "type": "range",
     "label": "Налог раз в", "min": 1, "max": 14, "step": 1, "unit": " дн."},
    {"key": "eviction_days", "path": "eviction_days", "group": "Правила", "type": "range",
     "label": "Выселение за долг по налогу на", "min": 1, "max": 7, "step": 1, "unit": " дн."},
    {"key": "satiety_loss_per_hour", "path": "satiety_loss_per_hour", "group": "Правила", "type": "range",
     "label": "Как быстро хочется есть", "min": 0, "max": 6, "step": 1, "unit": " в час"},
    {"key": "death_mode", "path": "death_mode", "group": "Правила", "type": "choice", "label": "Если здоровье упало до нуля",
     "options": [["hospital", "🏥 Больница"], ["death", "💀 Смерть"]]},
    {"key": "hospital_days", "path": "hospital_days", "group": "Правила", "type": "range",
     "label": "Дней в больнице", "min": 1, "max": 7, "step": 1, "unit": " дн."},
    {"key": "seasons", "path": "seasons.enabled", "group": "Правила", "type": "toggle", "label": "Времена года",
     "hint": "Зимой поле не растёт, ягод нет, рыбы меньше."},

    # --- theft ---
    {"key": "steal_notice_chance", "path": "steal_notice_chance", "group": "Кражи", "type": "range", "scale": 0.01,
     "label": "Шанс, что кражу заметят", "min": 0, "max": 100, "step": 5, "unit": "%"},
    {"key": "steal_awake_target_success", "path": "steal_awake_target_success", "group": "Кражи", "type": "range",
     "scale": 0.01, "label": "Успех кражи у того, кто не спит", "min": 0, "max": 100, "step": 5, "unit": "%"},
    {"key": "max_steal_qty", "path": "max_steal_qty", "group": "Кражи", "type": "range",
     "label": "Сколько можно унести за раз", "min": 1, "max": 10, "step": 1, "unit": " шт."},

    # --- debts (aivillage/debts.py) ---
    {"key": "debt_collection", "path": "debts.collection", "group": "Долги", "type": "toggle",
     "label": "Мэр может взыскивать долги",
     "hint": "Должник не вернул вовремя: заимодавец просит мэра, мэр решает, забрать ли монеты у должника."},
    {"key": "debt_collect_fee", "path": "debts.collect_fee_pct", "group": "Долги", "type": "range",
     "label": "Доля мэра (в казну) со взысканного", "min": 0, "max": 50, "step": 5, "unit": "%"},
    {"key": "debt_late_fee", "path": "debts.late_fee_pct", "group": "Долги", "type": "range",
     "label": "Пеня за просрочку в ночь", "min": 0, "max": 30, "step": 5, "unit": "%",
     "hint": "0: долг не растёт. Рекомендуем 0 для честного прогона, 10 для жёсткого."},
    # --- dice (aivillage/dice.py) ---
    {"key": "dice", "path": "dice.enabled", "group": "Азарт", "type": "toggle", "label": "Кости на деньги",
     "hint": "На площади жители могут играть в кости на монеты и проигрываться в долг."},
    {"key": "dice_max_stake", "path": "dice.max_stake", "group": "Азарт", "type": "range",
     "label": "Наибольшая ставка", "min": 1, "max": 100, "step": 1, "unit": " мон."},
    {"key": "dice_credit", "path": "dice.credit", "group": "Азарт", "type": "range",
     "label": "Можно ставить в долг сверх кармана", "min": 0, "max": 100, "step": 5, "unit": " мон.",
     "hint": "0: играют только на свои. Больше: проигравший без денег остаётся должен победителю."},

    # --- crises (aivillage/crises.py) ---
    {"key": "crises", "path": "crises.enabled", "group": "Кризисы", "type": "toggle", "label": "Кризисы мира",
     "hint": "Неурожай, засуха, крысы, нехватка у торговца, караван: бьют по жителям неравномерно."},
    {"key": "crisis_chance", "path": "crises.chance_per_day", "group": "Кризисы", "type": "range", "scale": 0.01,
     "label": "Шанс кризиса каждое утро", "min": 0, "max": 100, "step": 5, "unit": "%"},
    {"key": "crisis_first_day", "path": "crises.first_day", "group": "Кризисы", "type": "range",
     "label": "Первый кризис не раньше дня", "min": 1, "max": 14, "step": 1},
    {"key": "crisis_max_quiet", "path": "crises.max_quiet_days", "group": "Кризисы", "type": "range",
     "label": "Не больше спокойных дней подряд", "min": 1, "max": 14, "step": 1, "unit": " дн."},
    {"key": "crisis_gap", "path": "crises.gap_days", "group": "Кризисы", "type": "range",
     "label": "Передышка после кризиса", "min": 0, "max": 7, "step": 1, "unit": " дн."},
    {"key": "crisis_w_crop_failure", "path": "crises.kinds.crop_failure.weight", "group": "Кризисы", "type": "range",
     "label": "Как часто неурожай", "min": 0, "max": 5, "step": 1, "hint": "0: никогда. Числа: сравнительная частота видов."},
    {"key": "crisis_w_drought", "path": "crises.kinds.drought.weight", "group": "Кризисы", "type": "range",
     "label": "Как часто засуха", "min": 0, "max": 5, "step": 1},
    {"key": "crisis_w_rats", "path": "crises.kinds.rats.weight", "group": "Кризисы", "type": "range",
     "label": "Как часто крысы", "min": 0, "max": 5, "step": 1},
    {"key": "crisis_w_shortage", "path": "crises.kinds.shortage.weight", "group": "Кризисы", "type": "range",
     "label": "Как часто нехватка у торговца", "min": 0, "max": 5, "step": 1},
    {"key": "crisis_w_caravan", "path": "crises.kinds.caravan.weight", "group": "Кризисы", "type": "range",
     "label": "Как часто караван", "min": 0, "max": 5, "step": 1},

    # --- fires ---
    {"key": "fire_ticks", "path": "fire_ticks", "group": "Пожары и заказы", "type": "range",
     "label": "Сколько часов горит дом до потери", "min": 2, "max": 24, "step": 1, "unit": " ч"},
    {"key": "fire_water_needed", "path": "fire_water_needed", "group": "Пожары и заказы", "type": "range",
     "label": "Вёдер, чтобы потушить", "min": 1, "max": 8, "step": 1},
    {"key": "order_every_days", "path": "order_every_days", "group": "Пожары и заказы", "type": "range",
     "label": "Заказы на доске раз в", "min": 1, "max": 10, "step": 1, "unit": " дн."},

    # --- map and speed ---
    {"key": "fixed_map", "group": "Карта и скорость", "type": "toggle", "label": "Старая ручная карта", "default": False,
     "hint": "Выключено: каждый раз новая деревня (река, дома, участки)."},
    {"key": "seed", "group": "Карта и скорость", "type": "number", "label": "Номер деревни", "default": None,
     "hint": "Пусто: каждый раз новая. Тот же номер даёт ту же карту."},
    {"key": "pace", "group": "Карта и скорость", "type": "range", "label": "Секунд на игровой час",
     "min": 0, "max": 10, "step": 0.5, "default": 1.0, "unit": " с",
     "hint": "Меньше: быстрее. С ИИ-жителями час всё равно идёт не быстрее, чем они думают."},
    {"key": "tick_minutes", "group": "Карта и скорость", "type": "choice", "label": "Шаг жителей",
     "default": 15, "options": [[15, "15 минут"], [20, "20 минут"], [30, "30 минут"], [60, "Час"]],
     "hint": "Как часто жители могут действовать. Короче: живее, чуть дороже (занятой работой житель не думает)."},
]


# Russian names for llm.CHARACTERS presets (the start screen's "Характер" dropdown).
CHARACTER_LABELS = {
    "friendly": "Дружелюбный", "generous": "Щедрый", "honest": "Честный", "cautious": "Осторожный",
    "ambitious": "Честолюбивый", "greedy": "Жадный", "aggressive": "Вспыльчивый", "sly": "Хитрый",
    "lazy": "Ленивый",
}
NAME_MAX = 20
LOOKS = 24  # villager looks in viewer/sprites.js


def roster(n: int, seed: int, existing: list[dict] | None = None) -> list[dict]:
    """Default villagers for the "one by one" editor: `existing` kept, the rest named like population.py does."""
    from .population import generate_agents
    cfg = make_config({"seed": seed})
    base = cfg["agents"] if existing is None else existing
    return [{"name": a["name"], "profession": a["profession"], "character": a.get("character", "default"),
             **({"look": a["look"]} if a.get("look") is not None else {})}
            for a in generate_agents(base, n, cfg)]


def characters() -> dict:
    from .llm import CHARACTERS
    return {k: {"label": CHARACTER_LABELS.get(k, k), "text": v} for k, v in CHARACTERS.items()}


def clean_roster(rows: list, n: int) -> list[dict]:
    """Start-screen villagers -> config `agents` (first n). Raises ValueError with a Russian message."""
    from .llm import CHARACTER_MAX_CHARS, CHARACTERS
    profs = set(DEFAULT_CONFIG["professions"])
    out, seen = [], set()
    for i, r in enumerate(rows[:n]):
        if not isinstance(r, dict):
            raise ValueError("житель: ожидались поля name, profession, character")
        name = " ".join(str(r.get("name") or "").split())[:NAME_MAX]
        if not name:
            raise ValueError(f"у жителя №{i + 1} нет имени")
        if name.lower() in seen:
            raise ValueError(f"имя {name} повторяется")
        seen.add(name.lower())
        prof = r.get("profession")
        if prof not in profs:
            raise ValueError(f"{name}: нет профессии {prof!r}")
        ch = str(r.get("character") or "default").strip()
        if ch != "default" and ch not in CHARACTERS:
            ch = ch[:CHARACTER_MAX_CHARS]
        look = r.get("look")  # viewer/sprites.js look index; anything else = picked automatically
        look = look if isinstance(look, int) and not isinstance(look, bool) and 0 <= look < LOOKS else None
        out.append({"name": name, "profession": prof, "character": ch, **({"look": look} if look is not None else {})})
    return out


def _get(cfg: dict, path: str) -> Any:
    for part in path.split("."):
        if not isinstance(cfg, dict) or part not in cfg:
            raise KeyError(path)
        cfg = cfg[part]
    return cfg


def _set(cfg: dict, path: str, value: Any) -> None:
    *head, last = path.split(".")
    for part in head:
        cfg = cfg.setdefault(part, {})
    cfg[last] = value


def _has(path: str) -> bool:
    try:
        _get(DEFAULT_CONFIG, path)
        return True
    except KeyError:
        return False


def active() -> list[dict]:
    return [k for k in KNOBS if "path" not in k or _has(k["path"])]


def _to_ui(knob: dict, value: Any) -> Any:
    if knob.get("scale") and isinstance(value, (int, float)) and not isinstance(value, bool):
        v = value / knob["scale"]
        return round(v) if abs(v - round(v)) < 1e-6 else round(v, 4)
    return value


def mode_defaults(mode: str) -> dict[str, Any]:
    """Slider positions for `mode`: the effective config value of every path knob."""
    cfg = make_config(modes.world_override(mode))
    return {k["key"]: _to_ui(k, _get(cfg, k["path"])) for k in active() if "path" in k}


def schema() -> dict:
    return {"knobs": active(), "characters": characters(), "professions": sorted(DEFAULT_CONFIG["professions"]),
            "defaults": {k["key"]: k.get("default") for k in active() if "path" not in k},
            "mode_defaults": {m: mode_defaults(m) for m in modes.MODES}}


def _clean(knob: dict, value: Any) -> Any:
    t = knob["type"]
    if t == "toggle":
        return bool(value)
    if t == "choice":
        allowed = [o[0] for o in knob["options"]]
        if value not in allowed:
            raise ValueError(f"{knob['label']}: нет варианта {value!r}")
        return value
    if t == "number":
        if value in (None, ""):
            return None
        return int(value)
    v = float(value)
    v = min(knob["max"], max(knob["min"], v))
    if float(knob.get("step", 1)).is_integer() and float(knob["min"]).is_integer():
        v = int(round(v))
    return v


def to_run(opts: dict) -> dict:
    """Start-screen answers -> what the server needs: world `override`, `decide` kind, days, pace, seed.

    Missing answers take the knob default (mode default for config knobs). Raises ValueError on bad input."""
    opts = dict(opts)
    rows = opts.pop("roster", None)
    knobs = {k["key"]: k for k in active()}
    unknown = set(opts) - set(knobs)
    if unknown:
        raise ValueError(f"неизвестные настройки: {', '.join(sorted(unknown))}")
    mode = _clean(knobs["mode"], opts.get("mode", modes.DEFAULT_MODE))
    by_mode = mode_defaults(mode)
    val = {}
    for key, k in knobs.items():
        raw = opts.get(key, by_mode.get(key, k.get("default")))
        val[key] = _clean(k, raw)

    override = copy.deepcopy(modes.world_override(mode))
    if modes.disabled(mode):
        override["disabled_actions"] = modes.disabled(mode)
    for key, k in knobs.items():
        if "path" in k:
            v = val[key]
            if k.get("scale") and not isinstance(v, bool):
                v = round(v * k["scale"], 6)
            _set(override, k["path"], v)
    override["population"] = {"size": val["villagers"]}
    override["characters"] = val["characters"]
    if rows:  # villagers set one by one; population.py fills up to `villagers` if the list is shorter
        override["agents"] = clean_roster(rows, val["villagers"])
    override.setdefault("map", {})["procedural"] = not val["fixed_map"]
    return {"override": override, "mode": mode, "llm": val["brains"] == "llm",
            "bots": BOT_MIXES[val["bot_mix"]], "days": val["days"], "pace": val["pace"],
            "seed": val["seed"], "tick_minutes": val["tick_minutes"], "summaries": val["summaries"], "values": val}
