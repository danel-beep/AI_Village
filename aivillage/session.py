"""End of a session: one summary of what happened, saved next to the run log after every session.

    python -m aivillage.session runs/x.jsonl          # (re)build runs/x.session.json / .md / .html

The live app's "🏁 Завершить сессию" button stops the village and opens this summary; a run that plays
all its days, "🔄 Новая деревня" and `python -m aivillage.run --log ...` save it too. A log without a
session file (the window was just closed) gets one the first time its summary is opened.

A session is built from the log and its sidecars only (scorecard, recaps, highlights), so it costs no
model calls: days without picked highlights get them by rules. The player's comment (`note`) is kept
across rebuilds and goes into the zip for Claude (`reports.make_report`).
"""

from __future__ import annotations

import argparse
import html
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from . import modes, scorecard
from .clock import time_of
from .highlights import DRAMA, Highlighter, sidecar_path as highlights_path
from .summary import by_day, sidecar_path as summary_path, when

VERSION = 1
ENDED_BY = {
    "button": "завершена кнопкой «Завершить сессию»",
    "finished": "все дни сыграны",
    "new_village": "начата новая деревня",
    "error": "игра остановилась с ошибкой",
    "closed": "окно закрыли без «Завершить сессию»",
}
# Village-wide numbers in the summary. Deeds between villagers come from the scorecard (a trade counts
# for both sides there), the rest are event counts. Only non-zero ones are shown.
DEEDS = [("trades", "Сделок", 2), ("gifts", "Подарков", 1), ("loans_given", "Займов", 1),
         ("debts_defaulted", "Просроченных долгов", 1), ("thefts_tried", "Попыток краж", 1),
         ("thefts_got", "Удачных краж", 1), ("thefts_caught", "Пойманных воров", 1)]
COUNTS = [
    (("fight",), "Драк"),
    (("fire",), "Пожаров"), (("set_fire",), "Поджогов"), (("house_burned",), "Сгоревших домов"), (("hospital",), "Попаданий в больницу"),
    (("death",), "Смертей"), (("evicted",), "Выселений"), (("land_bought",), "Куплено участков"),
    (("build",), "Построек"), (("crisis",), "Кризисов"), (("election",), "Выборов"), (("law",), "Законов"),
    (("say",), "Реплик вслух"), (("whisper",), "Шёпотом"), (("gossip",), "Сплетен"),
]
STORIES = 6  # "Главные истории": the most dramatic highlights of the whole session
STAMP = re.compile(r"(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})-(\d{2})")


def paths(log: str | Path) -> dict[str, Path]:
    base = Path(log).with_suffix("")
    return {k: Path(f"{base}.session.{k}") for k in ("json", "md", "html")}


def started_at(log: str | Path) -> datetime | None:
    """App logs are named by their start time (server.Host.start)."""
    m = STAMP.search(Path(log).stem)
    if not m:
        return None
    try:
        return datetime.fromisoformat(f"{m[1]}T{m[2]}:{m[3]}:{m[4]}")
    except ValueError:
        return None


def _sidecar(path: Path) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _scorecard(log: Path) -> dict:
    """The end-of-run scorecard: its file when it is newer than the log (the server just wrote it)."""
    sc = Path(f"{log.with_suffix('')}.scorecard.json")
    if sc.is_file() and sc.stat().st_mtime >= log.stat().st_mtime:
        try:
            return json.loads(sc.read_text(encoding="utf-8"))
        except ValueError:
            pass
    return scorecard.compute([log])


def _brains(header: dict) -> str:
    kinds = Counter(header.get("brains", {}).values())
    if not kinds:
        return "?"
    return ", ".join(f"{b.removeprefix('bot:')} ×{n}" if b.startswith("bot:") else f"ИИ {b} ×{n}"
                     for b, n in kinds.most_common())


def build(log: str | Path, *, ended_by: str = "closed", days_planned: int | None = None,
          note: str = "", ended: datetime | None = None) -> dict:
    log = Path(log)
    recs = scorecard.read(log)
    header = recs[0]
    cfg = header.get("config") or {}
    ticks = [r for r in recs if r.get("type") == "tick"]
    days = by_day(ticks, cfg)
    day_no = [when(d[0], cfg)[0] for d in days]

    highlights = {h["day"]: h for h in _sidecar(highlights_path(log)) if isinstance(h, dict) and "day" in h}
    rules = Highlighter(None, cfg)
    for d, dticks in zip(day_no, days):
        if d not in highlights:  # the day the session ended on, or recaps were never picked
            rec = rules.pick(dticks)
            if rec:
                highlights[d] = rec
    recaps = _sidecar(summary_path(log))
    tick_day = {t["tick"]: d for d, dticks in zip(day_no, days) for t in dticks}

    per_day = []
    for d in day_no:
        h = highlights.get(d) or {}
        per_day.append({"day": d, "recaps": [{"from": s.get("from"), "to": s.get("to"), "text": s.get("text", "")}
                                             for s in recaps if tick_day.get(s.get("from_tick")) == d],
                        "highlights": h.get("items", []), "source": h.get("source")})

    items = [it for h in highlights.values() for it in h.get("items", [])]
    stories = sorted(items, key=lambda it: (-DRAMA.get(it.get("kind"), 0), it.get("tick", 0)))[:STORIES]
    headline = stories[0]["title"] if stories else None
    stories.sort(key=lambda it: it.get("tick", 0))

    rep = _scorecard(log)
    rows = rep.get("villagers", [])
    counts = [{"label": lab, "n": n} for key, lab, per in DEEDS if (n := sum(r.get(key) or 0 for r in rows) // per)]
    kinds = Counter(e.get("kind") for t in ticks for e in t.get("events") or [])
    counts += [{"label": lab, "n": sum(kinds[k] for k in ks)} for ks, lab in COUNTS if sum(kinds[k] for k in ks)]

    villagers = [{k: v.get(k) for k in ("name", "profession", "model", "status", "hospital", "wealth_start",
                                        "wealth_end", "thefts_tried", "thefts_got", "thefts_caught", "robbed",
                                        "gifts", "trades", "loans_given", "loans_taken", "debts_defaulted",
                                        "fire_help", "gossip", "invalid", "turns", "cost_usd")}
                 for v in rows]
    extra_cost = sum(float(s.get("cost_usd") or 0) for s in recaps) + \
        sum(float(h.get("cost_usd") or 0) for h in highlights.values())
    last = ticks[-1]["view"] if ticks else {}
    mode = cfg.get("economy_mode") or modes.DEFAULT_MODE
    started = started_at(log)
    ended = ended or datetime.now()
    return {
        "version": VERSION, "name": log.stem, "log": log.name,
        "started": started.isoformat(timespec="seconds") if started else None,
        "ended": ended.isoformat(timespec="seconds"),
        "minutes": round((ended - started).total_seconds() / 60) if started else None,
        "ended_by": ended_by, "ended_by_text": ENDED_BY.get(ended_by, ended_by),
        "villagers_n": len(cfg.get("agents") or villagers), "brains": _brains(header),
        "mode": mode, "mode_title": modes.MODES.get(mode, {}).get("title", mode), "seed": cfg.get("seed"),
        "days_played": len(day_no), "days_planned": days_planned, "ticks": len(ticks),
        "reached": "день {}, {:02d}:{:02d}".format(*time_of(cfg, ticks[-1]["tick"])) if ticks else None,
        "mayor": last.get("mayor"),
        "cost_usd": round(sum(float(v.get("cost_usd") or 0) for v in villagers) + extra_cost, 4),
        "counts": counts, "headline": headline, "stories": stories, "days": per_day, "villagers": villagers,
        "note": note,
    }


def load(log: str | Path) -> dict | None:
    try:
        return json.loads(paths(log)["json"].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save(log: str | Path, **kw) -> dict:
    """Build and write the session files; a comment already saved for this session is kept."""
    old = load(log) or {}
    kw.setdefault("note", old.get("note", ""))
    if kw.get("ended_by") is None:
        kw["ended_by"] = old.get("ended_by", "closed")
    if kw.get("days_planned") is None:
        kw["days_planned"] = old.get("days_planned")
    s = build(log, **kw)
    write(log, s)
    return s


def write(log: str | Path, s: dict) -> None:
    p = paths(log)
    p["json"].write_text(json.dumps(s, ensure_ascii=False, indent=1), encoding="utf-8")
    p["md"].write_text(to_markdown(s), encoding="utf-8")
    p["html"].write_text(to_html(s), encoding="utf-8")


def ensure(log: str | Path) -> dict:
    """The saved session, or a fresh one when there is none or the log grew after it (window closed)."""
    s = load(log)
    if s is None or s.get("version") != VERSION or paths(log)["json"].stat().st_mtime < Path(log).stat().st_mtime:
        ended = datetime.fromtimestamp(Path(log).stat().st_mtime)
        s = save(log, ended_by=None if s else "closed", ended=ended)
    return s


def set_note(log: str | Path, note: str) -> dict:
    s = ensure(log)
    s["note"] = note.strip()[:5000]
    write(log, s)
    return s


def brief(log: str | Path) -> dict:
    """One line for the past-sessions list, without building anything."""
    log = Path(log)
    s = load(log)
    if s:
        top = s.get("headline")
        return {"name": log.stem, "summary": True, "started": s.get("started"), "villagers": s["villagers_n"],
                "mode": s["mode_title"], "days": s["days_played"], "brains": s["brains"],
                "cost_usd": s["cost_usd"], "ended_by": s["ended_by"], "top": top, "note": bool(s.get("note"))}
    try:
        with log.open(encoding="utf-8") as f:
            cfg = json.loads(f.readline()).get("config") or {}
    except (OSError, ValueError):
        cfg = {}
    mode = cfg.get("economy_mode") or modes.DEFAULT_MODE
    started = started_at(log)
    return {"name": log.stem, "summary": False, "started": started.isoformat(timespec="seconds") if started else None,
            "villagers": len(cfg.get("agents") or []), "mode": modes.MODES.get(mode, {}).get("title", mode)}


# --- rendering ---

def _when(iso: str | None) -> str:
    return datetime.fromisoformat(iso).strftime("%d.%m.%Y %H:%M") if iso else "?"


def _days(s: dict) -> str:
    out = f"{s['days_played']}"
    if s.get("days_planned"):
        out += f" из {s['days_planned']}"
    return out + (f" (последний ход: {s['reached']})" if s.get("reached") else "")


def facts(s: dict) -> list[tuple[str, str]]:
    when_ = f"{_when(s['started'])} → {_when(s['ended'])}" if s.get("started") else f"закончилась {_when(s['ended'])}"
    out = [("Когда", when_ + (f" ({s['minutes']} мин)" if s.get("minutes") is not None else "")),
           ("Как закончилась", s["ended_by_text"]),
           ("Деревня", f"{s['villagers_n']} жителей, режим «{s['mode_title']}», seed {s['seed']}"),
           ("Кто играл", s["brains"]),
           ("Сыграно дней", _days(s)),
           ("Мэр в конце", s.get("mayor") or "нет"),
           ("Цена", f"${s['cost_usd']:.4f}")]
    return out


def _vrow(v: dict) -> list[str]:
    from .scorecard import STATUS_RU
    return [v["name"], v["profession"], STATUS_RU.get(v["status"], v["status"]) +
            (f", больница ×{v['hospital']}" if v.get("hospital") and v["status"] != "hospital" else ""),
            f"{v['wealth_start']} → {v['wealth_end']}", f"{v['thefts_tried']} / {v['thefts_got']} / {v['thefts_caught']}",
            str(v["robbed"]), str(v["gifts"]), str(v["trades"]), f"{v['loans_given']} / {v['loans_taken']}",
            str(v["debts_defaulted"]), str(v["fire_help"]), str(v["invalid"]), f"{v['cost_usd'] or 0:.4f}"]


VCOLS = ["Житель", "Профессия", "Итог", "Богатство: было → стало", "Кражи: пытался / удачно / пойман", "Обокрали",
         "Подарки", "Сделки", "Займы дал / взял", "Не вернул долг", "Тушил чужой пожар", "Ошибки", "$"]


def to_markdown(s: dict) -> str:
    out = [f"# Сессия {s['name']}", ""]
    out += [f"- **{k}:** {v}" for k, v in facts(s)]
    if s.get("note"):
        out += ["", "## Комментарий игрока", "", s["note"]]
    if s["counts"]:
        out += ["", "## В цифрах", "", ", ".join(f"{c['label']}: {c['n']}" for c in s["counts"])]
    if s["stories"] and len(s["days"]) > 1:  # one day: its own list says it all
        out += ["", "## Главные истории", ""]
        out += [f"- {it['time']}, **{it['title']}**: {it['text']}" for it in s["stories"]]
    for d in s["days"]:
        out += ["", f"## День {d['day']}", ""]
        out += [f"> {r['text']}" for r in d["recaps"]]
        if d["recaps"]:
            out.append("")
        out += [f"- {it['time']}, **{it['title']}**: {it['text']}" for it in d["highlights"]] or ["Ничего заметного."]
    if s["villagers"]:
        out += ["", "## По жителям", "", "| " + " | ".join(VCOLS) + " |", "| --- " * len(VCOLS) + "|"]
        out += ["| " + " | ".join(_vrow(v)) + " |" for v in s["villagers"]]
    return "\n".join(out) + "\n"


CSS = """
:root { --bg:#1d2321; --card:#252c29; --ink:#e8efe9; --dim:#9db0a4; --acc:#76b041; --btn:#34403b; }
* { box-sizing:border-box; }
body { margin:0; background:var(--bg); color:var(--ink); font:15px/1.5 system-ui, sans-serif; }
main { max-width:980px; margin:0 auto; padding:16px; }
h1 { font-size:22px; margin:8px 0 4px; } h2 { font-size:15px; color:var(--dim); text-transform:uppercase; margin:22px 0 8px; }
.card { background:var(--card); border-radius:12px; padding:12px 14px; margin:8px 0; }
.facts { display:grid; grid-template-columns:max-content 1fr; gap:4px 14px; }
.facts b { color:var(--dim); font-weight:600; }
.chips span { display:inline-block; background:var(--btn); border-radius:14px; padding:3px 10px; margin:3px 4px 3px 0; }
.it { margin:6px 0; } .it .t { color:var(--dim); font-size:13px; } .it b { color:#f0d27a; }
.recap { border-left:3px solid var(--acc); padding-left:10px; margin:6px 0 10px; }
.tbl { overflow-x:auto; } table { border-collapse:collapse; width:100%; font-size:13px; }
th, td { padding:5px 8px; border-bottom:1px solid #34403b; text-align:left; white-space:nowrap; }
th { color:var(--dim); font-weight:600; white-space:normal; }
.bar { display:flex; flex-wrap:wrap; gap:8px; margin:10px 0; }
.bar a, .bar button { background:var(--btn); color:var(--ink); border:0; border-radius:20px; padding:8px 14px;
  font:600 14px system-ui; text-decoration:none; cursor:pointer; }
.bar .main { background:var(--acc); color:#1d2321; }
textarea { width:100%; min-height:80px; background:var(--btn); color:var(--ink); border:0; border-radius:8px; padding:8px; font:14px system-ui; }
.msg { color:var(--dim); font-size:13px; min-height:18px; margin-top:6px; }
.dim { color:var(--dim); }
"""

APP_JS = """
const NAME = document.body.dataset.name, msg = document.getElementById('ss-msg');
async function post(url, body) {
  const r = await fetch(url, { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body || {}) });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || 'Не получилось.');
  return d;
}
document.getElementById('ss-save').onclick = () => post(`/api/sessions/${NAME}/note`, { note: document.getElementById('ss-note').value })
  .then(() => { msg.textContent = 'Комментарий сохранён.'; }, e => { msg.textContent = e.message; });
document.getElementById('ss-zip').onclick = () => post(`/api/sessions/${NAME}/zip`, { note: document.getElementById('ss-note').value })
  .then(d => { msg.textContent = (d.revealed ? `Готово: файл ${d.name}. Папка с ним открылась сама.` : `Готово: ${d.path}.`)
                 + ' Перетащите этот файл в чат проекта с Claude.'; },
        e => { msg.textContent = e.message; });
"""


def _items(items: list[dict]) -> str:
    e = html.escape
    return "".join(f'<div class="it"><span class="t">{e(it.get("time", ""))}</span> <b>{e(it.get("title", ""))}</b>: '
                   f'{e(it.get("text", ""))}</div>' for it in items)


def to_html(s: dict, app: bool = False) -> str:
    """The summary page. `app`: served by the live app, with buttons (replay, zip for Claude, comment)."""
    e = html.escape
    started = _when(s["started"]) if s.get("started") else s["name"]
    out = [f'<!doctype html><html lang="ru"><head><meta charset="utf-8">'
           f'<meta name="viewport" content="width=device-width, initial-scale=1">'
           f'<title>Сводка сессии</title><style>{CSS}</style></head><body data-name="{e(s["name"])}"><main>',
           f'<h1>🏁 Сводка сессии {e(started)}</h1>']
    if app:
        out.append('<div class="bar"><a class="main" href="/">🔄 Новая деревня</a>'
                   f'<a href="/replay/{e(s["name"])}" target="_blank">▶ Посмотреть повтор</a>'
                   '<a href="/sessions">📂 Все сессии</a></div>')
    out.append('<div class="card facts">' + "".join(f"<b>{e(k)}</b><span>{e(str(v))}</span>" for k, v in facts(s))
               + "</div>")
    if app:
        out.append('<h2>Ваш комментарий</h2><div class="card"><textarea id="ss-note" placeholder="Что понравилось, что '
                   f'странно, что поправить? Сохранится вместе со сводкой.">{e(s.get("note") or "")}</textarea>'
                   '<div class="bar"><button id="ss-save">💾 Сохранить комментарий</button>'
                   '<button id="ss-zip" class="main">📦 Файл для Claude</button></div><div class="msg" id="ss-msg"></div>'
                   '<div class="dim">«Файл для Claude» собирает сводку, комментарий и весь журнал игры в один zip: '
                   'перетащите его в чат проекта.</div></div>')
    elif s.get("note"):
        out.append(f'<h2>Комментарий игрока</h2><div class="card">{e(s["note"])}</div>')
    if s["counts"]:
        out.append('<h2>В цифрах</h2><div class="card chips">'
                   + "".join(f"<span>{e(c['label'])}: <b>{c['n']}</b></span>" for c in s["counts"]) + "</div>")
    if s["stories"] and len(s["days"]) > 1:
        out.append(f'<h2>Главные истории</h2><div class="card">{_items(s["stories"])}</div>')
    for d in s["days"]:
        body = "".join(f'<div class="recap">{e(r["text"])}</div>' for r in d["recaps"])
        body += _items(d["highlights"]) or '<div class="dim">Ничего заметного.</div>'
        out.append(f'<h2>День {d["day"]}</h2><div class="card">{body}</div>')
    if s["villagers"]:
        out.append('<h2>По жителям</h2><div class="card tbl"><table><tr>' + "".join(f"<th>{e(c)}</th>" for c in VCOLS)
                   + "</tr>" + "".join("<tr>" + "".join(f"<td>{e(x)}</td>" for x in _vrow(v)) + "</tr>"
                                       for v in s["villagers"]) + "</table></div>")
    out.append("</main>")
    if app:
        out.append(f"<script>{APP_JS}</script>")
    out.append("</body></html>")
    return "\n".join(out)


def list_html(rows: list[dict]) -> str:
    e = html.escape
    out = [f'<!doctype html><html lang="ru"><head><meta charset="utf-8">'
           f'<meta name="viewport" content="width=device-width, initial-scale=1"><title>Прошлые сессии</title>'
           f'<style>{CSS}</style></head><body><main><h1>📂 Прошлые сессии</h1>'
           '<div class="bar"><a class="main" href="/">← В игру</a></div>']
    if not rows:
        out.append('<div class="card dim">Сессий пока нет.</div>')
    for r in rows:
        when_ = _when(r["started"]) if r.get("started") else r["name"]
        line = f"{r['villagers']} жителей, «{r['mode']}»"
        if r.get("summary"):
            line += f", {r['days']} дн., {r['brains']}, ${r['cost_usd']:.4f}"
            if r.get("top"):
                line += f". Главное: {r['top']}"
            if r.get("note"):
                line += " 💬"
        else:
            line += ". Сводка соберётся при открытии."
        out.append(f'<div class="card"><a href="/session/{e(r["name"])}" style="color:#f0d27a;font-weight:700">'
                   f'📋 {e(when_)}</a> <span class="dim">{e(line)}</span> '
                   f'<a href="/replay/{e(r["name"])}" target="_blank" style="color:#9db0a4">▶ повтор</a></div>')
    out.append("</main></body></html>")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Build the end-of-session summary of a run log.")
    p.add_argument("log")
    a = p.parse_args(argv)
    save(a.log, ended_by=None, ended=datetime.fromtimestamp(Path(a.log).stat().st_mtime))
    print(paths(a.log)["md"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
