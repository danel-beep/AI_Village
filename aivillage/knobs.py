"""Start-screen settings: every knob the app shows before "Play", in one list.

The viewer's start screen (viewer/setup.js) draws itself from `schema()`, so a new knob is one dict in
`KNOBS`, nothing else:

    {"key": "fire_chance", "path": "crises.fire_chance", "group": "Беды", "type": "range",
     "label": "Случайные пожары", "min": 0, "max": 100, "step": 5, "scale": 0.01, "unit": "%"}

- `path`: dotted key in the world config (config.DEFAULT_CONFIG). The default comes from the chosen
  economy mode (so switching the mode moves the slider), and the value lands in the run's world override.
  A knob whose path is not in DEFAULT_CONFIG yet is hidden, so knobs can be listed before their feature lands.
- no `path`: a run option handled in `to_run()` (villagers, days, mode, pace, ...).
- `action`: a toggle that switches one action on or off (off = added to `disabled_actions`); its default
  follows the mode, like `path` knobs.
- `also`: more config paths that get the same value as `path`.
- `scale`: config value = slider value * scale (percent sliders: 0.01).
- `only`: "llm" or "bots" shows the knob for that kind of village only; `mode`: shown in that economy mode only.
- `group`: fallback section title. Where a knob shows is set by MAIN (always on top) and SECTIONS (folded
  sections) below KNOBS; add a new knob's key there. `hint` (or HINTS) is the plain-word line under it.
- `hide_if`: {knob key: [values]}: hidden while every listed knob's value is in its list (tax rates with
  polities on: each polity sets its own; start coins at a camp start: there are none).
- `roster` (not a knob): optional list of {name, profession, character} from "Жители по одному".
- `type`: "range" (slider), "choice" (buttons; `options` = [[value, label], ...]), "toggle", "number".
- `sets` (on a choice): {option: {knob key: slider value}}, a preset. Picking the option moves those sliders;
  missing answers take the preset value before the mode default (the "Сколько случайностей" knob).
"""

from __future__ import annotations

import copy
from typing import Any

from . import modes, seasons
from .config import DEFAULT_CONFIG, _merge, make_config

BOT_MIXES = {
    "mixed": ["worker", "worker", "thief", "worker", "random"],
    "workers": ["worker"],
    "traders": ["trader", "worker"],
    "thieves": ["thief", "worker"],
    "homestead": ["homestead", "worker"],
}

# With polities on, whether there is a tax, how much and how often is up to each polity (polity.py): no world rate.
NO_WORLD_TAX = {"polities": [True]}

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
    {"key": "daily_budget", "group": "Деревня", "type": "range", "label": "Бюджет в сутки, $", "only": "llm",
     "min": 0.5, "max": 50, "step": 0.5, "default": 5.0, "unit": " $",
     "hint": "Сколько можно потратить на ИИ за одни настоящие сутки (все деревни вместе). Потратили: деревня "
             "ставится на паузу и сама продолжает на следующий день."},
    {"key": "bot_mix", "group": "Деревня", "type": "choice", "label": "Какие боты", "only": "bots",
     "default": "mixed", "options": [["mixed", "Смешанные"], ["workers", "Трудяги"], ["traders", "Торговцы"],
                                     ["thieves", "Много воров"], ["homestead", "Хозяйственные"]]},
    {"key": "characters", "group": "Деревня", "type": "choice", "label": "Характер жителей", "only": "llm",
     "default": "off", "options": [["off", "🔬 Без характеров (эксперимент)"], ["default", "😐 Нейтральный, кроме заданных"],
                                   ["random", "🎲 Случайный у каждого"]],
     "hint": "Характер: одна мягкая строка о темпераменте в подсказке жителя, не приказ. «Без характеров»: у всех "
             "одинаковый нейтральный текст, характеры из «Жители по одному» не действуют, так поведение честно "
             "сравнивается между моделями. Для показательных запусков выберите другой вариант."},
    {"key": "craft_hint", "path": "craft_hint", "group": "Деревня", "type": "toggle", "label": "Подсказка «можно приготовить»",
     "only": "llm", "hint": "Житель видит, что можно сделать из того, что у него с собой (хлеб ×7 дома), и что сырое "
                           "зерно не едят. Это факт из правил, не совет. Выключите, чтобы проверять умение планировать."},
    {"key": "own_goals", "path": "own_goals", "group": "Деревня", "type": "toggle", "label": "Свои цели жителя",
     "only": "llm", "hint": "Перед первым днём житель сам пишет, кто он и чего хочет от жизни в деревне, а каждую ночь "
                           "может это переписать и решает, что сделает завтра. Свои слова он видит весь день. Вопрос "
                           "у всех одинаковый и цель не подсказывает. +1 короткий вызов на жителя в начале."},
    {"key": "llm_memory", "path": "llm_memory", "group": "Деревня", "type": "choice", "label": "Память жителя за день",
     "only": "llm", "options": [["day", "🧠 Весь день одной беседой"], ["fresh", "🔁 Каждый ход заново (старый способ)"]],
     "hint": "«Весь день одной беседой»: житель видит все свои ходы за сегодня, что ему сказали и что он ответил, "
             "поэтому помнит просьбы и свои планы до вечера. Ночью беседа заканчивается, день переходит в дневник. "
             "Стоит столько же: повторяющееся начало беседы провайдер берёт в 10 раз дешевле. «Каждый ход заново»: "
             "житель видит только последние 3 действия и свои заметки."},
    {"key": "llm_obs", "path": "llm_obs", "group": "Деревня", "type": "choice", "label": "Что житель видит каждый ход",
     "only": "llm", "options": [["changes", "✂️ Только то, что изменилось"], ["full", "📋 Всё описание каждый ход (старый способ)"]],
     "hint": "«Только то, что изменилось»: доска, карта, земля, богатство и власть приходят жителю, только когда "
             "меняются, и остаются в его беседе за день. Где он, что вокруг, что ему сказали и новости он видит "
             "каждый ход. Ход дешевле на 14–20%, а ошибочных ходов в опыте стало вдвое меньше. Работает при памяти "
             "«Весь день одной беседой»."},
    {"key": "own_ai_seats", "path": "own_ai.seats", "group": "Свои ИИ", "type": "range",
     "label": "Жителей играют свои ИИ (MCP)", "min": 0, "max": 10, "step": 1, "only": "llm",
     "hint": "Первыми жителями играют ИИ людей: свой Claude, ChatGPT, Gemini или Codex по подписке, подключённый к "
             "деревне как коннектор. После «Играть» кнопка «🔌 Свои ИИ» даст ссылку на каждого жителя. Такой житель "
             "получает те же запросы, что и ИИ-жители по ключу. Остальными играет ИИ по ключу. 0: выключено."},
    {"key": "own_ai_wait", "path": "own_ai.wait_minutes", "group": "Свои ИИ", "type": "range",
     "label": "Сколько ждать ход своего ИИ", "min": 1, "max": 30, "step": 1, "unit": " мин", "only": "llm",
     "hint": "Деревня ждёт ответа каждого подключённого ИИ столько минут, потом его житель пропускает ход. Пока ИИ "
             "не подключился и игрок не сказал «да», деревня ждёт его (или нажмите «Играть без него»)."},
    {"key": "own_ai_style", "path": "own_ai.style", "group": "Свои ИИ", "type": "choice",
     "label": "Как играет свой ИИ", "only": "llm",
     "options": [["owner", "🪞 Как его владелец"], ["self", "🔬 Сам за себя"]],
     "hint": "«Как владелец»: мир описан тем же нейтральным текстом, а характер ИИ берёт из своей памяти о человеке, "
             "чей он. «Сам за себя»: тот же текст, что у всех жителей. Оба режима не идут в честное сравнение "
             "моделей: у приложения ИИ своя память и свой скрытый промпт."},
    {"key": "luxury", "path": "luxury.enabled", "group": "Деревня", "type": "toggle", "label": "Праздники и вещи на виду",
     "hint": "Житель может устроить праздник: делит свою еду поровну со всеми, кто рядом и не спит, гостям он становится "
             "ближе, а деревня узнаёт, кто кого угощал. При встрече видно, у кого кольцо, оружие или инструмент."},
    {"key": "hungry_seen_below", "path": "hungry_seen_below", "group": "Деревня", "type": "range",
     "label": "Голод соседа виден ниже", "min": 0, "max": 60, "step": 5,
     "hint": "Рядом стоящие видят пометку «голоден», когда сытость ниже этого числа, и «голодает» при нуле. 0: не видно."},
    {"key": "said_to_you_days", "path": "said_to_you.keep_days", "group": "Деревня", "type": "range",
     "label": "Сколько помнить сказанное тебе", "min": 0, "max": 3, "step": 1, "unit": " дн.",
     "hint": "Письма, шёпот и слова с именем жителя видны ему до конца следующего дня (или дольше), пока эти двое "
             "не передадут друг другу вещи, заём или не обменяются. 0: видно только один ход, как раньше."},
    {"key": "summaries", "group": "Деревня", "type": "toggle", "label": "Сводки «Что произошло?» и хайлайты от ИИ",
     "only": "llm", "default": True, "hint": "Пересказ каждого дня, около $0.0003 за день."},

    # --- rules ---
    {"key": "mode", "group": "Правила", "type": "choice", "label": "Режим экономики", "default": modes.DEFAULT_MODE,
     "options": [[m, v["title"]] for m, v in modes.MODES.items()],
     "about": {m: v["about"] for m, v in modes.MODES.items()},
     "hint": "Режим двигает ползунки ниже. Подсказка жителям одна и та же во всех режимах. Выбирается один режим: "
             "«С нуля» (пустая поляна, жители строят деревню сами) и «Дефицит» (готовая деревня, мало еды) "
             "разные. Чтобы начать с нуля при нехватке еды, выберите «С нуля» и ниже «Еды в мире: мало»."},
    {"key": "start_stage", "path": "progress.start_stage", "group": "Правила", "type": "choice", "mode": "survival",
     "label": "С какой стадии начать", "options": [["camp", "🔥 Лагерь (с нуля)"], ["hamlet", "🛖 Хутор"],
                                                  ["village", "🏘 Деревня"], ["town", "🏰 Посёлок"]],
     "hint": "Лагерь: ни домов, ни денег, ни профессий. Со стадии повыше всё, что нужно для неё, уже построено "
             "и открыто, старт как в «Обычном»."},
    {"key": "food", "group": "Правила", "type": "choice", "label": "Еды в мире", "default": "mode",
     "options": [["mode", "🍞 Как в режиме"], ["scarce", "🥖 Мало, как в «Дефиците»"]],
     "hide_if": {"mode": ["scarcity"]},
     "hint": "«Мало»: грядка даёт вдвое меньше зерна, рыбы, ягод и дикого зерна вдвое меньше и они медленно "
             "отрастают, еда у торговца дорогая, все начинают полуголодными. Работает с любым режимом, например "
             "«С нуля» с нехваткой еды. Дерево, камень и руда не меняются."},
    {"key": "unfairness", "path": "map.unfairness", "group": "Правила", "type": "range", "scale": 0.1,
     "label": "Нечестный старт", "min": 0, "max": 10, "step": 1,
     "hint": "0: у всех одинаковые участки, деньги и дорога до работы. 10: у кого-то большой участок и "
             "запасы, у кого-то клочок земли и пустой карман."},
    {"key": "start_coins", "path": "start_coins", "group": "Правила", "type": "range", "label": "Монет на старте",
     "min": 0, "max": 200, "step": 5, "hide_if": {"mode": ["survival"], "start_stage": ["camp", "hamlet"]},
     "hint": "В «С нуля» монеты появляются с рынком (стадия «Деревня»): при старте с лагеря или хутора их нет ни у кого."},
    {"key": "tax_amount", "path": "tax_amount", "group": "Правила", "type": "range", "label": "Налог на землю",
     "min": 0, "max": 100, "step": 5, "unit": " мон.", "hide_if": NO_WORLD_TAX,
     "hint": "Сколько монет каждый житель платит в казну в налоговый день. Староста может поменять законом."},
    {"key": "sales_pct", "path": "taxes.sales_pct", "group": "Правила", "type": "range",
     "label": "Налог с продаж торговцу и совету", "min": 0, "max": 30, "step": 1, "unit": "%",
     "hide_if": NO_WORLD_TAX, "hint": "Доля монет, полученных от торговца и заказов совета. Сделки между жителями не облагаются."},
    {"key": "wealth_pct", "path": "taxes.wealth_pct", "group": "Правила", "type": "range",
     "label": "Налог с богатства (с монет сверх 100)", "min": 0, "max": 20, "step": 1, "unit": "%",
     "hide_if": NO_WORLD_TAX, "hint": "Богатые платят больше: доля от монет, которые у жителя сверх 100."},
    {"key": "burn_pct", "path": "taxes.burn_pct", "group": "Правила", "type": "range",
     "label": "Доля налогов, которая уходит из игры", "min": 0, "max": 100, "step": 5, "unit": "%",
     "hide_if": NO_WORLD_TAX, "hint": "Эта часть налога исчезает, остальное идёт в казну. Не даёт монетам копиться без конца."},
    {"key": "tax_every_days", "path": "tax_every_days", "group": "Правила", "type": "range",
     "label": "Налог раз в", "min": 1, "max": 14, "step": 1, "unit": " дн.", "hide_if": NO_WORLD_TAX,
     "hint": "Как часто бывает налоговый день."},
    {"key": "law_enforcement", "path": "laws.enforcement", "group": "Правила", "type": "choice",
     "label": "Налоги и штрафы", "options": [["auto", "🏛 Забираются сами"], ["voluntary", "🤝 По желанию"]],
     "hint": "По желанию: налог и штраф становятся счётом в книге долгов, житель сам решает, платить ли. "
             "Все видят, кто заплатил, а кто нет. Выселения за неуплату нет."},
    {"key": "tax_board", "path": "laws.tax_board", "group": "Правила", "type": "toggle", "label": "Налоговая доска",
     "hint": "При налогах «По желанию»: всем видно, кто заплатил налог за последние налоговые дни, кто ещё нет и у "
             "кого счёт просрочен. Наказания нет, решают сами жители."},
    {"key": "polities", "path": "polity.enabled", "group": "Правила", "type": "toggle",
     "label": "Государства у ратуш",
     "hint": "Каждая построенная ратуша основывает своё государство: строители становятся его жителями, остальные "
             "вступают или живут сами по себе. Жители голосуют за название, имя монет и форму правления (все решают, "
             "совет или один правитель); сменить форму можно прошением больше половины. Налог платят только члены "
             "своему государству. Общего мэра и выборов тогда нет."},
    {"key": "eviction_days", "path": "eviction_days", "group": "Правила", "type": "range",
     "label": "Выселение за долг по налогу на", "min": 1, "max": 7, "step": 1, "unit": " дн."},
    {"key": "satiety_loss_per_hour", "path": "satiety_loss_per_hour", "group": "Правила", "type": "range",
     "label": "Как быстро хочется есть", "min": 0, "max": 6, "step": 1, "unit": " в час"},
    {"key": "death_mode", "path": "death_mode", "group": "Правила", "type": "choice", "label": "Если здоровье упало до нуля",
     "options": [["hospital", "🏥 Больница"], ["death", "💀 Смерть"]]},
    {"key": "lives", "path": "lives", "group": "Правила", "type": "choice", "label": "Сколько раз можно упасть без сил",
     "options": [[0, "Всегда больница"], [2, "2: больница, потом смерть"], [3, "3: больница дважды, потом смерть"],
                 [4, "4: больница трижды, потом смерть"]],
     "hint": "Работает при «Больнице». Последнее падение здоровья до нуля означает смерть: житель выбывает из игры, "
             "его вещи и земля переходят супругу или близкому другу, а если их нет, земля становится ничьей. "
             "Жители знают правило с начала и видят свой счёт."},
    {"key": "hospital_days", "path": "hospital_days", "group": "Правила", "type": "range",
     "label": "Дней в больнице", "min": 1, "max": 7, "step": 1, "unit": " дн."},
    {"key": "discharge_satiety", "path": "hospital_discharge.satiety", "group": "Правила", "type": "range",
     "label": "Сытость после больницы", "min": 10, "max": 100, "step": 5,
     "hint": "С какой сытостью житель выходит из больницы. Рекомендуем 30 в «С нуля» (больница не бесплатный обед), 60 в «Обычном»."},
    {"key": "seasons", "path": "seasons.enabled", "group": "Правила", "type": "toggle", "label": "Времена года",
     "hint": "Зимой грядки не засеять, что не дозрело, замерзает, ягод нет, рыбы меньше."},
    {"key": "season_days", "group": "Правила", "type": "choice", "label": "Длина сезона", "default": 0,
     "options": [[0, "Авто"], [1, "1 день"], [2, "2 дня"], [3, "3 дня"], [7, "Неделя"], [14, "2 недели"]],
     "hint": "Авто: весь год укладывается в прогон и последним идёт зима (3 дня = лето, осень, зима)."},
    {"key": "season_start", "group": "Правила", "type": "choice", "label": "С какого сезона начать", "default": "auto",
     "options": [["auto", "Авто"], ["spring", "🌱 Весна"], ["summer", "☀️ Лето"], ["autumn", "🍂 Осень"],
                 ["winter", "❄️ Зима"]],
     "hint": "Авто: так, чтобы к концу прогона наступила зима."},
    {"key": "winter_hunger", "path": "seasons.night_hunger.winter", "group": "Правила", "type": "range",
     "label": "Зимняя ночь: сытости сверх обычного", "min": 0, "max": 30, "step": 2,
     "hint": "Холод: каждая зимняя ночь отнимает у всех столько сытости в дополнение к обычной. 0 = зима не голоднее лета."},
    {"key": "winter_fish", "path": "seasons.regen_multiplier.winter.fish", "group": "Правила", "type": "range",
     "scale": 0.01, "label": "Рыба зимой, от обычного", "min": 0, "max": 100, "step": 5, "unit": "%"},

    # --- division of labour (aivillage/labor.py) ---
    {"key": "labor", "path": "labor.enabled", "group": "Ремёсла", "type": "toggle", "label": "Каждый добывает только своё",
     "hint": "Рыбу ловит только рыбак, лес рубит лесоруб, зерно сеет фермер, камень, руду и золото копает шахтёр "
             "(в режиме «Ремёсла» и ягоды собирает только фермер). Остальное жители берут друг у друга."},
    {"key": "trade_anywhere", "path": "labor.trade_anywhere", "group": "Ремёсла", "type": "toggle",
     "label": "Сделки и подарки на расстоянии",
     "hint": "Предложение обмена можно принять, а подарок отдать, не стоя рядом: товар доставят. Выключено: оба должны "
             "быть в одном месте."},
    {"key": "market_board", "path": "market.enabled", "group": "Ремёсла", "type": "toggle",
     "label": "Доска «куплю/продам»",
     "hint": "Жители выставляют товар на продажу и покупают с доски откуда угодно; видно, где и когда видели каждого."},
    {"key": "spoilage", "path": "spoilage.enabled", "group": "Ремёсла", "type": "toggle", "label": "Еда портится",
     "hint": "Рыба и молоко хранятся 2 дня, ягоды, хлеб и супы 3, яйца 4, зерно 14, мёд вечно. Испорченное пропадает на рассвете."},
    {"key": "crafting", "path": "crafting.enabled", "group": "Ремёсла", "type": "toggle", "label": "Цепочки крафта и инструменты",
     "hint": "Доски, кирпич, железо, кожа, мука; кирпич в печи, железо в кузнице. Каменные и железные топоры и кирки ускоряют сбор и изнашиваются, руду голыми руками не добыть. Хлеб пекут из муки."},
    {"key": "secret_recipes", "path": "crafting.secrets.enabled", "group": "Ремёсла", "type": "toggle",
     "label": "Секреты ремесла",
     "hint": "Простые рецепты (доски, мука, хлеб, каменные инструменты, дубина) знают все. Остальные знает только тот, "
             "кто первым их сделал, или кого он научил, даром или за плату. Работает вместе с «Цепочки крафта и инструменты»."},
    {"key": "work_hours", "path": "labor.work_hours_per_day", "group": "Ремёсла", "type": "range",
     "label": "Часов работы в день", "min": 0, "max": 12, "step": 1, "unit": " ч",
     "hint": "0: без ограничения. Работает, только когда включено «Каждый добывает только своё»."},
    {"key": "no_professions", "path": "labor.mastery.enabled", "group": "Ремёсла", "type": "toggle",
     "label": "Без профессий", "mode": "survival",
     "hint": "Каждый может всё. Мастерство растёт отдельно по каждому делу (рыбалка, поле, кузня, охота...) от "
             "практики: больше в час, больше вещей с поделки. Дело, заброшенное на несколько дней, понемногу "
             "забывается. Выключено: профессии и места по ремёслам, как в «Обычном»."},
    {"key": "mastery_bonus", "path": "labor.mastery.gather_bonus", "group": "Ремёсла", "type": "range",
     "label": "Прибавка за уровень мастерства дела", "min": 0, "max": 3, "step": 1, "unit": " в час",
     "mode": "survival", "hide_if": {"no_professions": [False]},
     "hint": "Сколько больше добываешь в час за каждый из 5 уровней мастерства этого дела."},
    {"key": "house_bonus", "path": "labor.mastery.house_bonus_pct", "group": "Ремёсла", "type": "range",
     "label": "Хозяйство от размера дома", "min": 0, "max": 50, "step": 5, "unit": "% за уровень дома",
     "mode": "survival", "hide_if": {"no_professions": [False]},
     "hint": "Насколько больше дают свой двор (грядки, животные) и то, что делаешь дома или в своей мастерской, "
             "за каждый уровень дома."},
    {"key": "skill_bonus", "path": "labor.skill_bonus", "group": "Ремёсла", "type": "range",
     "label": "Прибавка за уровень мастерства", "min": 0, "max": 3, "step": 1, "unit": " в час",
     "hint": "Мастерство растёт от часов работы по своей профессии (3 уровня).",
     "hide_if": {"no_professions": [True]}},
    {"key": "trader_buys", "path": "labor.trader_buys_per_day.default", "group": "Ремёсла", "type": "range",
     "label": "Торговец скупает в день", "min": 0, "max": 40, "step": 1, "unit": " шт.",
     "hint": "Сколько штук каждого товара торговец покупает за день у всей деревни (на 5 жителей). Кто первый, тот и продал."},
    {"key": "trader_buys_gold", "path": "labor.trader_buys_per_day.gold", "group": "Ремёсла", "type": "range",
     "label": "Из них золота", "min": 0, "max": 40, "step": 1, "unit": " шт."},
    {"key": "trader_purse", "path": "labor.trader_coins_per_trade", "group": "Ремёсла", "type": "range",
     "label": "Торговец тратит на одно ремесло", "min": 0, "max": 60, "step": 1, "unit": " монет в день",
     "hint": "Сколько монет в день торговец платит за товары одного ремесла, все вместе (на 5 жителей): камень, руда "
             "и золото шахтёра идут из одного кошелька. 0 — без такого предела."},
    {"key": "trader_sells", "path": "labor.trader_sells_per_day.default", "group": "Ремёсла", "type": "range",
     "label": "Торговец продаёт в день", "min": 0, "max": 40, "step": 1, "unit": " шт.",
     "hint": "Сколько штук каждого товара у торговца есть на продажу за день (на 5 жителей)."},
    {"key": "trader_sells_tool", "path": "labor.trader_sells_per_day.tool", "group": "Ремёсла", "type": "range",
     "label": "Из них инструментов", "min": 0, "max": 10, "step": 1, "unit": " шт.",
     "hint": "Мало: инструменты приходится покупать у кузнеца."},

    # --- prices and tools (aivillage/pricing.py) ---
    {"key": "stock_prices", "path": "trader_pricing.stock_prices", "group": "Цены и инструменты", "type": "toggle",
     "label": "Цены торговца зависят от его запаса",
     "hint": "Чем больше товара жители недавно продали торговцу, тем дешевле он его покупает и продаёт. "
             "Каждую ночь запас уменьшается."},
    {"key": "price_drop", "path": "trader_pricing.drop_per_unit", "group": "Цены и инструменты", "type": "range",
     "label": "Насколько падает цена за штуку в запасе", "min": 0, "max": 25, "step": 1, "scale": 0.01, "unit": "%",
     "hint": "На 5 жителей. 8%: после 5 проданных штук цена ниже на 40%."},
    {"key": "price_floor", "path": "trader_pricing.floor", "group": "Цены и инструменты", "type": "range",
     "label": "Ниже какой доли цена не падает", "min": 5, "max": 100, "step": 5, "scale": 0.01, "unit": "%"},
    {"key": "stock_keep", "path": "trader_pricing.keep_per_day", "group": "Цены и инструменты", "type": "range",
     "label": "Сколько запаса торговец оставляет за ночь", "min": 0, "max": 100, "step": 10, "scale": 0.01, "unit": "%"},
    {"key": "gold_value", "path": "items.gold.value", "group": "Цены и инструменты", "type": "range",
     "label": "Цена золота", "min": 2, "max": 40, "step": 1, "unit": " мон.",
     "hint": "Базовая цена; торговец платит половину. Шахтёр добывает до 2 слитков в час."},
    {"key": "tool_hours", "path": "tool_durability_hours", "group": "Цены и инструменты", "type": "range",
     "label": "Инструмент живёт", "min": 4, "max": 60, "step": 1, "unit": " ч работы",
     "hint": "С инструментом добыча вдвое больше. Новые делает кузнец."},
    {"key": "start_tool", "path": "start_items.tool", "group": "Цены и инструменты", "type": "range",
     "label": "Инструментов у каждого на старте", "min": 0, "max": 3, "step": 1, "unit": " шт."},

    # --- theft ---
    {"key": "steal_notice_chance", "path": "steal_notice_chance", "group": "Кражи", "type": "range", "scale": 0.01,
     "label": "Шанс, что кражу заметят", "min": 0, "max": 100, "step": 5, "unit": "%"},
    {"key": "steal_awake_target_success", "path": "steal_awake_target_success", "group": "Кражи", "type": "range",
     "scale": 0.01, "label": "Успех кражи у того, кто не спит", "min": 0, "max": 100, "step": 5, "unit": "%"},
    {"key": "max_steal_qty", "path": "max_steal_qty", "group": "Кражи", "type": "range",
     "label": "Сколько можно унести за раз", "min": 1, "max": 10, "step": 1, "unit": " шт."},
    {"key": "theft_rules", "path": "theft.enabled", "group": "Кражи", "type": "toggle",
     "label": "Есть что украсть, темнота и казна",
     "hint": "Включает настройки ниже: чужие запасы видны, в темноте кражу замечают реже, хозяин может не заметить "
             "вора, казну можно обокрасть."},
    {"key": "see_stores", "path": "theft.see_stores", "group": "Кражи", "type": "toggle",
     "label": "Чужие запасы на виду",
     "hint": "Житель видит монеты и еду в чужих сундуках там, где стоит, и в карманах тех, кто рядом."},
    {"key": "dark_factor", "path": "theft.dark_factor", "group": "Кражи", "type": "range", "scale": 0.01,
     "label": "Насколько темнота прячет вора", "min": 0, "max": 100, "step": 5, "unit": "%",
     "hint": "Шанс заметить кражу в тёмные часы (с 20:00, зимой раньше, и до 7:00) от дневного. 100% = темнота не помогает."},
    {"key": "owner_notice", "path": "theft.owner_notice_chance", "group": "Кражи", "type": "range", "scale": 0.01,
     "label": "Хозяин дома видит вора у сундука", "min": 0, "max": 100, "step": 5, "unit": "%"},
    {"key": "victim_notice", "path": "theft.victim_notice_chance", "group": "Кражи", "type": "range", "scale": 0.01,
     "label": "Обкрадываемый замечает вора", "min": 0, "max": 100, "step": 5, "unit": "%"},
    {"key": "steal_treasury", "path": "theft.treasury", "group": "Кражи", "type": "toggle",
     "label": "Казну можно обокрасть",
     "hint": "Любой может унести монеты из казны там, где она хранится. По книгам их не хватятся до ревизии, "
             "а ревизия не скажет, кто взял."},
    {"key": "restitution", "path": "governance.restitution", "group": "Кражи", "type": "range", "scale": 0.01,
     "label": "Краденое возвращают при доносе", "min": 0, "max": 200, "step": 50, "unit": "%",
     "hint": "Сколько украденного вор отдаёт жертве, когда на него донесли: 100% = всё, 0 = ничего. Берётся из "
             "карманов, потом из сундука вора; чего у него уже нет, то пропадает, долга не остаётся."},
    {"key": "crime_days", "path": "governance.crime_memory_days", "group": "Кражи", "type": "range",
     "label": "Сколько дней можно донести", "min": 3, "max": 30, "step": 1, "unit": " дн."},
    {"key": "theft_clue", "path": "theft.clue_chance", "group": "Кражи", "type": "range", "scale": 0.01,
     "label": "Подсказка о неизвестном воре", "min": 0, "max": 100, "step": 10, "unit": "%",
     "hint": "Если кражу никто не видел, жертва с этим шансом получает правдивую подсказку: кто был рядом за "
             "последний час, что вор теперь несёт или его оружие. Подсказка всегда подходит хотя бы двоим."},

    # --- land (aivillage/land.py) ---
    {"key": "land_claim", "path": "land.claim", "group": "Земля", "type": "choice", "label": "Пустые участки",
     "options": [["buy", "Покупают у деревни"], ["first", "Чей первый, того и участок"]],
     "hint": "«Чей первый»: участок даром занимает тот, кто встал на него первым. Суда нет: споры жители решают сами."},
    {"key": "land_jump", "path": "land.claim_jump", "group": "Земля", "type": "toggle",
     "label": "Пустой участок можно перехватить",
     "hint": "При «Чей первый»: участок, на котором ничего не построено, забирает любой, пока хозяев там нет."},

    # --- debts (aivillage/debts.py) ---
    {"key": "debt_collection", "path": "debts.collection", "group": "Долги", "type": "toggle",
     "label": "Мэр может взыскивать долги",
     "hint": "Должник не вернул вовремя: заимодавец просит мэра, мэр решает, забрать ли монеты у должника."},
    {"key": "debt_auto_collect", "path": "debts.auto_collect", "group": "Долги", "type": "toggle",
     "label": "Просроченные долги взыскиваются сами",
     "hint": "Каждую ночь после срока у должника забирают часть монет, потом вещей (еду никогда), "
             "и часть новых доходов, пока долг не закрыт."},
    {"key": "debt_seize_pct", "path": "debts.seize_pct", "group": "Долги", "type": "range",
     "label": "Сколько можно забрать за раз", "min": 10, "max": 100, "step": 10, "unit": "%",
     "hint": "Доля монет и вещей должника за ночь и доля каждого его дохода. 50% не оставляет его ни с чем."},
    {"key": "debt_collect_fee", "path": "debts.collect_fee_pct", "group": "Долги", "type": "range",
     "label": "Доля мэра (в казну) со взысканного", "min": 0, "max": 50, "step": 5, "unit": "%"},
    {"key": "debt_in_kind", "path": "debts.in_kind", "group": "Долги", "type": "toggle",
     "label": "Долги вещами",
     "hint": "В обмен можно добавить «верну потом»: например, 3 мяса сейчас за обещание отдать 4 мяса к 5-му дню. "
             "Долг виден только двоим, отдать долг можно просто подарком нужных вещей."},
    {"key": "debt_late_fee", "path": "debts.late_fee_pct", "group": "Долги", "type": "range",
     "label": "Пеня за просрочку в ночь", "min": 0, "max": 30, "step": 5, "unit": "%",
     "hint": "0: долг не растёт. Рекомендуем 0 для честного прогона, 10 для жёсткого."},

    # --- word of mouth (aivillage/reputation.py) ---
    {"key": "mishear_number", "path": "reputation.mishear_number", "group": "Слухи", "type": "range", "scale": 0.01,
     "label": "Слух искажает числа", "min": 0, "max": 100, "step": 5, "unit": "%",
     "hint": "Шанс, что слушатель запомнит другое число («украл 3 монеты» → «украл 6»). 0: слухи передаются точно."},
    {"key": "mishear_name", "path": "reputation.mishear_name", "group": "Слухи", "type": "range", "scale": 0.01,
     "label": "Слух путает, о ком речь", "min": 0, "max": 50, "step": 1, "unit": "%",
     "hint": "Шанс, что слушатель решит, что речь о другом жителе. Рекомендуем 5%."},
    {"key": "overhear", "path": "reputation.overhear", "group": "Слухи", "type": "range", "scale": 0.01,
     "label": "Шёпот подслушивают", "min": 0, "max": 100, "step": 5, "unit": "%",
     "hint": "Шанс для каждого рядом услышать шёпот или сплетню на ухо. Рекомендуем 15%."},
    {"key": "origin_hops", "path": "reputation.origin_hops", "group": "Слухи", "type": "range",
     "label": "Сколько пересказов помнят автора слуха", "min": 1, "max": 10, "step": 1, "unit": "",
     "hint": "Дальше слух идёт как «кто-то говорил»."},

    {"key": "announce_cost", "path": "reputation.announce_cost", "group": "Слухи", "type": "range",
     "label": "Цена объявления на доске", "min": 0, "max": 50, "step": 1, "unit": " мон.",
     "hint": "Объявление на площади сразу читают все жители, слово в слово. Деньги идут в казну. Рекомендуем 5."},

    # --- dice (aivillage/dice.py) ---
    {"key": "animals", "path": "animals.enabled", "group": "Охота", "type": "toggle", "label": "Звери и охота",
     "hint": "В лесах и у воды живут звери. Зайца и утку ловят в одиночку, оленя, кабана и лося только вдвоём-втроём; "
             "добычу забирает тот, кто нанёс последний удар. Звери плодятся и уходят из мест, где на них охотятся."},
    {"key": "transport", "path": "transport.enabled", "group": "Охота", "type": "toggle", "label": "Лошади, ослы и телеги",
     "hint": "С 20 вещами житель идёт обычным шагом, с большим грузом каждая дорога вдвое дольше. Лошадь (быстрее) "
             "и осёл (везёт больше) ловятся в дикой природе или покупаются у торговца; телега делается на верстаке. "
             "Животное кормят сеном или зерном, иначе оно слабеет и убегает. Его можно одолжить, отдать или увести. "
             "В «С нуля» открывается со стадии «деревня»."},
    {"key": "dice", "path": "dice.enabled", "group": "Азарт", "type": "toggle", "label": "Кости на деньги",
     "hint": "На площади жители могут играть в кости на монеты и проигрываться в долг."},
    {"key": "dice_max_stake", "path": "dice.max_stake", "group": "Азарт", "type": "range",
     "label": "Наибольшая ставка", "min": 1, "max": 100, "step": 1, "unit": " мон."},
    {"key": "dice_credit", "path": "dice.credit", "group": "Азарт", "type": "range",
     "label": "Можно ставить в долг сверх кармана", "min": 0, "max": 100, "step": 5, "unit": " мон.",
     "hint": "0: играют только на свои. Больше: проигравший без денег остаётся должен победителю."},

    # --- crises (aivillage/crises.py) ---
    {"key": "combat", "path": "combat.enabled", "group": "Драки", "type": "toggle", "label": "Драки",
     "hint": "Несколько раундов кубиков; оружие (инструмент, дубинка, копьё) помогает, победитель забирает добычу."},
    {"key": "combat_rounds", "path": "combat.rounds", "group": "Драки", "type": "range", "label": "Раундов в драке",
     "min": 1, "max": 6, "step": 1},
    {"key": "combat_loot", "path": "combat.loot_max", "group": "Драки", "type": "range",
     "label": "Победитель забирает вещей", "min": 0, "max": 10, "step": 1, "unit": " шт."},
    {"key": "combat_loot_coins", "path": "combat.loot_coins_max", "group": "Драки", "type": "range",
     "label": "Победитель забирает монет", "min": 0, "max": 50, "step": 5},
    {"key": "combat_min_health", "path": "combat.min_health", "group": "Драки", "type": "range",
     "label": "Нельзя начать драку при здоровье ниже", "min": 0, "max": 80, "step": 5},

    {"key": "land", "path": "land.enabled", "group": "Земля и шахта", "type": "toggle", "label": "Продажа участков",
     "hint": "Пустые участки можно купить у деревни и перепродать друг другу."},
    {"key": "land_price", "path": "land.price_per_cell", "group": "Земля и шахта", "type": "range",
     "label": "Цена клетки земли", "min": 1, "max": 30, "step": 1, "unit": " мон."},
    {"key": "gold", "path": "locations.mine.resources.gold.start", "also": ["locations.mine.resources.gold.max"],
     "group": "Земля и шахта", "type": "range", "label": "Золота в шахте", "min": 0, "max": 100, "step": 2,
     "unit": " шт.", "hint": "Запас конечный: выкопанное золото не возвращается."},

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

    # --- random events: the world's dice (threats.py, illness.py, conflict.random_fire, crises.py) ---
    {"key": "chaos", "group": "Случайные события", "type": "choice", "label": "Сколько случайностей",
     "default": "normal",
     "options": [["fair", "⚖️ Честно (всё 0)"], ["normal", "🎲 Обычно"], ["chaos", "🌪 Хаос"]],
     "about": {"fair": "Ничего не случается само: ни пожаров, ни болезней, ни набегов, ни кризисов. Только то, "
                       "что сделают жители и вы в режиме бога.",
               "normal": "Рекомендуемые шансы: иногда путник, редко набег или зверь, кризисы по режиму экономики.",
               "chaos": "Беды почти каждый день: пожары, болезни, набеги, звери, кризисы."},
     "hint": "Кнопка выставляет ползунки ниже; любой можно потом подвинуть вручную.",
     "sets": {"fair": {"random_fire": 0, "sickness_chance": 0, "raid_chance": 0, "beast_chance": 0,
                       "traveler_chance": 0, "hostile_max_gap": 0, "crises": False},
              "normal": {"random_fire": 3, "sickness_chance": 5, "raid_chance": 5, "beast_chance": 4,
                         "traveler_chance": 15},
              "chaos": {"random_fire": 20, "sickness_chance": 20, "raid_chance": 25, "beast_chance": 20,
                        "traveler_chance": 30, "crises": True, "crisis_chance": 90}}},
    {"key": "random_fire", "path": "random_fires.per_day", "group": "Случайные события", "type": "range",
     "scale": 0.01, "label": "Дом загорается сам", "min": 0, "max": 50, "step": 1, "unit": "% в день",
     "hint": "Рекомендуем 3%."},
    {"key": "sickness_chance", "path": "illness.per_day", "group": "Случайные события", "type": "range",
     "scale": 0.01, "label": "Кто-то заболевает", "min": 0, "max": 50, "step": 1, "unit": "% в день",
     "hint": "Рекомендуем 5%. Больной не работает, теряет здоровье по ночам и заражает тех, кто рядом."},
    {"key": "raid_chance", "path": "threats.kinds.raid.per_day", "group": "Случайные события", "type": "range",
     "scale": 0.01, "label": "Набег бандитов", "min": 0, "max": 50, "step": 1, "unit": "% в день",
     "hint": "Рекомендуем 5%. Грабят сундуки дом за домом, уходя поджигают дом. Если отбиться, бросают добычу."},
    {"key": "beast_chance", "path": "threats.kinds.beast.per_day", "group": "Случайные события", "type": "range",
     "scale": 0.01, "label": "Зверь из леса", "min": 0, "max": 50, "step": 1, "unit": "% в день",
     "hint": "Рекомендуем 4%. Ест запасы и ранит жителей, пока его не прогонят."},
    {"key": "traveler_chance", "path": "threats.kinds.traveler.per_day", "group": "Случайные события",
     "type": "range", "scale": 0.01, "label": "Приходит путник", "min": 0, "max": 50, "step": 1,
     "unit": "% в день", "hint": "Рекомендуем 15%. Просит еды; добрый благодарит, а разведчик наводит бандитов."},
    {"key": "scout_chance", "path": "threats.kinds.traveler.scout_chance", "group": "Случайные события",
     "type": "range", "scale": 0.01, "label": "Путник оказывается разведчиком", "min": 0, "max": 100, "step": 5,
     "unit": "%", "hint": "Рекомендуем 30%. Если его не прогнать, через день-два без предупреждения придут бандиты. "
                          "В «С нуля» разведчики приходят только когда бандиты уже могут прийти (см. этап ниже)."},
    {"key": "raids_from_stage", "path": "progress.unlocks.feature:raids.stage", "group": "Случайные события",
     "type": "choice", "label": "Бандиты приходят с этапа",
     "options": [["camp", "Сразу (лагерь)"], ["hamlet", "Хутор"], ["village", "Деревня"], ["town", "Посёлок"]],
     "hint": "Только для «С нуля»: до этого этапа набегов сами по себе нет. Рекомендуем хутор. Бог может "
             "прислать набег когда угодно."},
    {"key": "hostile_max_gap", "path": "threats.hostile.max_gap_days", "group": "Случайные события",
     "type": "range", "label": "Бандиты или зверь не реже чем раз в", "min": 0, "max": 30, "step": 1,
     "unit": " дн.", "hint": "Когда придут, заранее не известно, но спокойных дней подряд не больше этого. "
                             "0: только шансы выше. Рекомендуем 10."},
    {"key": "threat_warn", "path": "threats.warn_chance", "group": "Случайные события", "type": "range",
     "scale": 0.01, "label": "Набег или зверь объявлены заранее", "min": 0, "max": 100, "step": 10, "unit": "%",
     "hint": "Рекомендуем 50% (в «С нуля» 80%). Остальные приходят внезапно."},
    {"key": "threat_warn_days", "path": "threats.warn_days", "group": "Случайные события", "type": "range",
     "label": "За сколько дней предупреждают", "min": 1, "max": 7, "step": 1, "unit": " дн."},
    {"key": "illness_spread", "path": "illness.spread_chance", "group": "Случайные события", "type": "range",
     "scale": 0.01, "label": "Заразность болезни", "min": 0, "max": 50, "step": 5, "unit": "% в час",
     "hint": "Шанс заразиться за час рядом с больным. Рекомендуем 10%."},
    # --- village works and treasury (aivillage/works.py, governance.py) ---
    {"key": "works", "path": "works.enabled", "group": "Стройки и казна", "type": "toggle", "label": "Общие стройки",
     "hint": "Колодец, мост, вышка, стена (по 3 уровня). Начинает мэр (без мэра любой), строят все вместе; "
             "видно, кто помог, а кто нет."},
    {"key": "works_council", "path": "works.council_idle_days", "group": "Стройки и казна", "type": "range",
     "label": "Совет сам предлагает стройку после простоя", "min": 0, "max": 10, "step": 1, "unit": " дн.",
     "hint": "0: никогда, стройки начинают только жители. Рекомендуем 3."},
    {"key": "embezzle", "path": "treasury.embezzle", "group": "Стройки и казна", "type": "toggle",
     "label": "Мэр может украсть из казны",
     "hint": "Казна у мэра. Пропажу видно при проверке казны на площади или при смене мэра."},
    {"key": "audit_on_handover", "path": "treasury.audit_on_handover", "group": "Стройки и казна", "type": "toggle",
     "label": "Пересчёт казны при смене мэра"},
    {"key": "treasury_seed", "path": "polity.income_per_member_per_day", "group": "Стройки и казна", "type": "range",
     "label": "Затравка казны государства", "min": 0, "max": 3, "step": 1, "unit": " мон. в день на жителя",
     "hint": "Каждое утро в казну государства, у которого уже выбрана форма правления и есть хотя бы двое, "
             "появляются новые монеты: столько на каждого жителя. 0: казна пополняется только налогами и подарками. "
             "Рекомендуем 1.", "hide_if": {"polities": [False]}},
    {"key": "merchant", "path": "merchant.enabled", "group": "Стройки и казна", "type": "toggle",
     "label": "Проезжий купец",
     "hint": "После появления рынка время от времени (в случайный день) на пару дней приезжает купец. Он продаёт то, "
             "что в деревне не сделать: шубу (зимняя ночь меньше морит голодом), стальные топор и кирку, лекарство. "
             "Деньги уезжают вместе с ним. Тот, у кого казна, может купить на деньги казны, все это увидят."},

    # --- fires ---
    {"key": "allow_arson", "action": "set_fire", "group": "Пожары и заказы", "type": "toggle",
     "label": "Жители могут поджигать чужие дома", "hint": "Поджог стоит дров; семья дома видит, кто это сделал."},
    {"key": "arson_wood", "path": "combat.arson_wood", "group": "Пожары и заказы", "type": "range",
     "label": "Дров на поджог", "min": 0, "max": 5, "step": 1, "unit": " шт."},
    {"key": "fire_ticks", "path": "fire_ticks", "group": "Пожары и заказы", "type": "range",
     "label": "Сколько часов горит дом до потери", "min": 2, "max": 24, "step": 1, "unit": " ч"},
    {"key": "fire_water_needed", "path": "fire_water_needed", "group": "Пожары и заказы", "type": "range",
     "label": "Вёдер, чтобы потушить", "min": 1, "max": 8, "step": 1},
    {"key": "fire_spread_hours", "path": "fire_spread_hours", "group": "Пожары и заказы", "type": "range",
     "label": "Огонь перекидывается на соседний дом через", "min": 0, "max": 12, "step": 1, "unit": " ч",
     "hint": "Если пожар не тушат столько часов, загорается соседний дом. 0: никогда. Рекомендуем 6."},
    {"key": "order_every_days", "path": "order_every_days", "group": "Пожары и заказы", "type": "range",
     "label": "Заказы на доске раз в", "min": 1, "max": 10, "step": 1, "unit": " дн."},

    # --- map and speed ---
    {"key": "fixed_map", "group": "Карта и скорость", "type": "toggle", "label": "Старая ручная карта", "default": False,
     "hint": "Выключено: каждый раз новая деревня (река, дома, участки)."},
    {"key": "map_size", "path": "map.size", "group": "Карта и скорость", "type": "choice", "label": "Размер карты",
     "options": [["normal", "Обычная"], ["large", "Большая"], ["huge", "Огромная"]],
     "hint": "Деревня в середине такая же тесная. Вокруг дикие места: глубокий лес, озеро, пещеры с рудой и "
             "камнем, глиняные холмы. На большой карте до них 2–3 часа ходьбы, на огромной их больше и до 5 часов. "
             "Со старой ручной картой не действует."},
    {"key": "regrowth", "path": "regrowth.from_remainder", "group": "Карта и скорость", "type": "toggle",
     "label": "Природа растёт от остатка",
     "hint": "Включено: за ночь лес, рыба, ягоды, камень и руда прирастают тем медленнее, чем меньше их осталось; "
             "выбранное дочиста почти не растёт. Выключено: каждую ночь прирастает одинаково."},
    {"key": "explore", "path": "explore.enabled", "group": "Карта и скорость", "type": "toggle",
     "label": "Разведка карты",
     "hint": "Включено: житель знает только площадь, свой дом и места рядом с площадью, а дальнее узнаёт, когда сам "
             "туда дойдёт. Рассказать другим можно словами или письмом. На карте неразведанное под туманом."},
    {"key": "settle", "path": "settle.enabled", "group": "Карта и скорость", "type": "toggle",
     "label": "Место под дом выбирают сами",
     "hint": "Только в «С нуля» со старта «Лагерь». Включено: на старте пустая поляна, все ночуют у лагеря, каждый сам "
             "занимает свободное место под дом у леса, реки, шахты или где захочет (кто первый). Дорог нет: тропы "
             "протаптываются там, где ходят, и становятся дорогами. Выключено: дома стоят заранее."},
    {"key": "settle_spread", "path": "settle.spread_bonus", "group": "Карта и скорость", "type": "range",
     "label": "Простор долины (лагерь)", "min": 0, "max": 12, "step": 1, "unit": " клеток",
     "hint": "На сколько дальше от лагеря лежат лес, шахта и рощи и насколько шире карта при старте «Лагерь». "
             "Руда в карьере ещё чуть дальше. 0: как в готовой деревне."},
    {"key": "seed", "group": "Карта и скорость", "type": "number", "label": "Номер деревни", "default": None,
     "hint": "Пусто: каждый раз новая. Тот же номер даёт ту же карту."},
    {"key": "pace", "group": "Карта и скорость", "type": "range", "label": "Секунд на игровой час",
     "min": 0, "max": 10, "step": 0.5, "default": 1.0, "unit": " с",
     "hint": "Меньше: быстрее. С ИИ-жителями час всё равно идёт не быстрее, чем они думают."},
    {"key": "tick_minutes", "group": "Карта и скорость", "type": "choice", "label": "Шаг жителей",
     "default": 15, "options": [[15, "15 минут"], [20, "20 минут"], [30, "30 минут"], [60, "Час"]],
     "hint": "Как часто жители могут действовать. Короче: живее, чуть дороже (занятой работой житель не думает)."},
]

# Short plain-word hints for knobs that have no `hint` of their own (the start screen shows one under every knob).
HINTS = {
    "combat_rounds": "Сколько раз противники по очереди бросают кубики в одной драке.",
    "combat_loot": "Сколько вещей победитель может отнять у проигравшего.",
    "combat_loot_coins": "Сколько монет победитель может отнять у проигравшего.",
    "combat_min_health": "Слабый житель не может начать драку, пока не подлечится.",
    "arson_wood": "Сколько дров поджигатель тратит на растопку. 0: поджечь можно бесплатно.",
    "land_price": "Сколько монет стоит одна клетка пустого участка у деревни.",
    "days": "Сколько игровых суток длится деревня. Один день проходит за несколько минут.",
    "bot_mix": "Боты: простые программы вместо ИИ. Выберите, какие повадки будут у большинства.",
    "start_coins": "Сколько денег у каждого жителя в первый день.",
    "tax_amount": "Сколько монет житель платит за свою землю каждый налоговый день.",
    "sales_pct": "Какая часть цены продажи торговцу уходит в общую казну.",
    "wealth_pct": "Какую часть монет сверх 100 богатый житель отдаёт в казну.",
    "burn_pct": "Какая часть собранных налогов исчезает совсем, а не копится в казне.",
    "tax_every_days": "Как часто приходит налог на землю.",
    "eviction_days": "Через сколько дней неуплаты налога житель теряет дом.",
    "satiety_loss_per_hour": "На сколько падает сытость (из 100) за каждый игровой час. Больше: еды нужно больше.",
    "death_mode": "«Больница»: житель выпадает на несколько дней и возвращается. «Смерть»: уходит из игры насовсем.",
    "hospital_days": "Сколько дней житель лежит в больнице и ничего не делает.",
    "winter_fish": "Сколько рыбы зимой по сравнению с летом. 100%: столько же.",
    "trader_buys_gold": "Сколько золота торговец готов купить в день из общей дневной скупки.",
    "price_floor": "Даже при полном запасе торговец платит не меньше этой доли обычной цены.",
    "stock_keep": "Какую часть купленного торговец оставляет себе к утру. Остальное «уезжает», и цены снова растут.",
    "start_tool": "Сколько инструментов у каждого жителя в первый день. Инструмент ускоряет работу.",
    "steal_notice_chance": "Как часто прохожие замечают кражу.",
    "steal_awake_target_success": "Шанс украсть у того, кто не спит. У спящего украсть проще.",
    "max_steal_qty": "Сколько вещей вор уносит за одну кражу.",
    "owner_notice": "Шанс, что хозяин, стоящий дома, поймает вора у своего сундука.",
    "victim_notice": "Шанс, что житель заметит, как у него тащат из кармана.",
    "debt_collect_fee": "Какую часть взысканного долга мэр забирает в казну.",
    "dice_max_stake": "Больше этой суммы за одну игру в кости поставить нельзя.",
    "crisis_chance": "Шанс, что утром начнётся беда: неурожай, засуха, крысы и т.п.",
    "crisis_first_day": "Первые дни спокойные: так жители успеют освоиться.",
    "crisis_max_quiet": "Если бед давно не было, следующая придёт не позже этого срока.",
    "crisis_gap": "Сколько дней после беды точно ничего не случится.",
    "crisis_w_drought": "Насколько часто среди бед выпадает засуха. 0: никогда.",
    "crisis_w_rats": "Насколько часто крысы портят запасы. 0: никогда.",
    "crisis_w_shortage": "Насколько часто у торговца кончается товар. 0: никогда.",
    "crisis_w_caravan": "Насколько часто приходит караван (это хорошая новость). 0: никогда.",
    "threat_warn_days": "Если набег объявлен заранее, то за столько дней.",
    "audit_on_handover": "Новый мэр пересчитывает казну, и все узнают, если старый что-то взял.",
    "fire_ticks": "Сколько часов можно тушить горящий дом, прежде чем он сгорит.",
    "fire_water_needed": "Сколько вёдер воды надо вылить на дом, чтобы погасить огонь.",
    "order_every_days": "Как часто на доске появляется заказ от города с наградой.",
}

# Start-screen layout (viewer/setup.js). MAIN: the few knobs always shown at the top; the rest sit in folded
# SECTIONS (title, one-line about, keys in order). A knob in neither lands in a section named by its own `group`.
MAIN = ["brains", "bot_mix", "mode", "start_stage", "food", "villagers", "days", "daily_budget"]
SECTIONS: list[tuple[str, str, list[str]]] = [
    ("🧠 Жители и их ИИ", "Характеры, память, свои цели и что жители видят друг о друге.",
     ["characters", "own_goals", "llm_memory", "llm_obs", "craft_hint", "summaries", "luxury", "hungry_seen_below",
      "said_to_you_days"]),
    ("💰 Деньги и налоги", "Монеты на старте, налоги, казна, государства и неравенство.",
     ["unfairness", "start_coins", "law_enforcement", "tax_amount", "tax_every_days", "sales_pct", "wealth_pct",
      "burn_pct", "tax_board", "eviction_days", "polities"]),
    ("🏛 Общие стройки и казна", "Стройки всей деревней, на что тратится казна и может ли её хранитель запустить в неё руку.",
     ["works", "works_council", "embezzle", "audit_on_handover", "steal_treasury", "treasury_seed", "merchant"]),
    ("🤝 Долги", "Долги видны только двоим. Долги вещами, взыскание силой и пени за просрочку.",
     ["debt_in_kind", "debt_collection", "debt_auto_collect", "debt_seize_pct", "debt_collect_fee", "debt_late_fee"]),
    ("❤️ Голод, здоровье и смерть", "Как быстро хочется есть и что бывает с обессилевшим.",
     ["satiety_loss_per_hour", "death_mode", "lives", "hospital_days", "discharge_satiety"]),
    ("❄️ Времена года", "Длина сезонов и насколько сурова зима.",
     ["seasons", "season_days", "season_start", "winter_hunger", "winter_fish"]),
    ("🔨 Работа и ремёсла", "Кто что добывает, крафт, инструменты, мастерство, заказы.",
     ["labor", "crafting", "secret_recipes", "work_hours", "no_professions", "mastery_bonus", "house_bonus",
      "skill_bonus", "spoilage", "start_tool", "tool_hours",
      "order_every_days"]),
    ("🏪 Торговец и рынок", "Сколько торговец покупает и продаёт, его цены, сделки между жителями.",
     ["trade_anywhere", "market_board", "trader_buys", "trader_buys_gold", "trader_purse", "trader_sells",
      "trader_sells_tool", "stock_prices", "price_drop", "price_floor", "stock_keep", "gold_value"]),
    ("🕵️ Кражи", "Насколько легко украсть и попасться.",
     ["theft_rules", "see_stores", "steal_notice_chance", "steal_awake_target_success", "max_steal_qty",
      "dark_factor", "owner_notice", "victim_notice", "restitution", "crime_days", "theft_clue"]),
    ("⚔️ Драки", "Можно ли драться, сколько длится драка и что забирает победитель.",
     ["combat", "combat_rounds", "combat_loot", "combat_loot_coins", "combat_min_health"]),
    ("🗣 Слухи и разговоры", "Как искажаются пересказы и сколько стоит объявление.",
     ["mishear_number", "mishear_name", "overhear", "origin_hops", "announce_cost"]),
    ("⚡ Беды и случайности", "Пожары, болезни, набеги, звери и кризисы. Наверху один общий переключатель.",
     ["chaos", "random_fire", "sickness_chance", "illness_spread", "raid_chance", "beast_chance", "threat_warn",
      "threat_warn_days", "raids_from_stage", "hostile_max_gap", "traveler_chance", "scout_chance", "fire_ticks", "fire_water_needed", "fire_spread_hours",
      "allow_arson", "arson_wood", "crises", "crisis_chance", "crisis_first_day", "crisis_max_quiet", "crisis_gap", "crisis_w_crop_failure",
      "crisis_w_drought", "crisis_w_rats", "crisis_w_shortage", "crisis_w_caravan"]),
    ("🐗 Звери, транспорт и азарт", "Охота, лошади и телеги, кости на деньги.",
     ["animals", "transport", "dice", "dice_max_stake", "dice_credit"]),
    ("🗺 Карта и земля", "Размер карты, разведка, участки под дома и номер деревни.",
     ["map_size", "explore", "settle", "settle_spread", "land_claim", "land_jump", "land", "land_price", "gold", "regrowth", "fixed_map", "seed"]),
    ("⏱ Скорость", "Как быстро идёт время на экране и как часто жители думают.",
     ["pace", "tick_minutes"]),
]


def layout(knobs: list[dict]) -> tuple[list[dict], list[dict]]:
    """Knobs in screen order, each with `section` ("main" or a section title) and `hint` filled in; and the
    sections [{title, about}] in order. Keys not in MAIN/SECTIONS go last under their own `group`."""
    by_key = {k["key"]: k for k in knobs}
    placed: list[tuple[dict, str]] = [(by_key[key], "main") for key in MAIN if key in by_key]
    sections = []
    for title, about, keys in SECTIONS:
        rows = [(by_key[key], title) for key in keys if key in by_key]
        if rows:
            sections.append({"title": title, "about": about})
            placed += rows
    seen = {k["key"] for k, _ in placed}
    for k in knobs:
        if k["key"] not in seen:
            if k["group"] not in [s["title"] for s in sections]:
                sections.append({"title": k["group"], "about": ""})
            placed.append((k, k["group"]))
    out = [{**k, "section": s, "hint": k.get("hint") or HINTS.get(k["key"], "")} for k, s in placed]
    return out, sections


# Russian names for llm.CHARACTERS presets (the start screen's "Характер" dropdown).
CHARACTER_LABELS = {
    "friendly": "Дружелюбный", "generous": "Щедрый", "honest": "Честный", "cautious": "Осторожный",
    "ambitious": "Честолюбивый", "greedy": "Жадный", "aggressive": "Вспыльчивый", "sly": "Хитрый",
    "lazy": "Ленивый",
}
NAME_MAX = 20
ALWAYS = ("Boris",)  # Danel's test subject: in every app village, otherwise an ordinary random villager
LOOKS = 24  # villager looks in viewer/sprites.js


def roster(n: int, seed: int, existing: list[dict] | None = None) -> list[dict]:
    """Default villagers for the "one by one" editor: `existing` kept, the rest named like population.py does."""
    from .population import generate_agents
    cfg = make_config({"seed": seed, "population": {"always": list(ALWAYS)}})
    base = [] if existing is None else existing  # fresh roster: all names seeded, like an app start
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
    off = set(modes.disabled(mode))
    out = {k["key"]: _to_ui(k, _get(cfg, k["path"])) for k in active() if "path" in k}
    out.update({k["key"]: k["action"] not in off for k in active() if "action" in k})
    return out


def schema() -> dict:
    ordered, sections = layout(active())
    return {"knobs": ordered, "sections": sections, "characters": characters(), "professions": sorted(DEFAULT_CONFIG["professions"]),
            "defaults": {k["key"]: k.get("default") for k in active() if "path" not in k and "action" not in k},
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


def _preset(knobs: dict, opts: dict) -> dict:
    """Slider values of the chosen "sets" knob (the random-events preset); they sit between mode and hand."""
    out: dict = {}
    for key, k in knobs.items():
        if k.get("sets"):
            out.update(k["sets"].get(_clean(k, opts.get(key, k.get("default"))), {}))
    return out


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
    by_mode = {**mode_defaults(mode), **_preset(knobs, opts)}
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
            for path in [k["path"], *k.get("also", [])]:
                _set(override, path, v)
        elif "action" in k:
            off = set(override.get("disabled_actions", [])) - {k["action"]}
            override["disabled_actions"] = sorted(off if val[key] else off | {k["action"]})
    if val["food"] == "scarce" and mode != "scarcity":
        override = _merge(override, modes.scarce_food(make_config(override)))
    override["population"] = {"size": val["villagers"], "always": list(ALWAYS)}
    override["characters"] = val["characters"]
    # Villagers set one by one; population.py fills up to `villagers` if the list is shorter. Without a
    # list every name and profession is drawn from the seed, so no name keeps the same seat run after run.
    override["agents"] = clean_roster(rows, val["villagers"]) if rows else []
    override.setdefault("map", {})["procedural"] = not val["fixed_map"]
    if val["seasons"]:
        cal = seasons.calendar(val["days"], val["season_days"])
        if val["season_start"] != "auto":
            cal.update(start=val["season_start"], offset_days=0)
        for k, v in cal.items():
            _set(override, f"seasons.{k}", v)
    return {"override": override, "mode": mode, "llm": val["brains"] == "llm",
            "bots": BOT_MIXES[val["bot_mix"]], "days": val["days"], "pace": val["pace"],
            "seed": val["seed"], "tick_minutes": val["tick_minutes"], "summaries": val["summaries"],
            "daily_budget": val["daily_budget"], "values": val}
