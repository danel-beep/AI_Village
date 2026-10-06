// Weekly highlight reel: the best moments of a game week (7 days of highlights, viewer/highlights.js) become one clip
// (viewer/clip.js). Live mode makes it by itself when the 7th day's highlights arrive, and when a run ends inside a
// week that already has 2+ days; weeks that ended while the viewer was closed are made on the next visit. The server
// keeps the files in AIVillage/videos (GET /api/clips says which exist). "🎞 Неделя N" buttons in the highlights panel
// make any week by hand, also one still going.
const Reel = (() => {
  const WEEK = 7, PICKS = 8, PER_KIND = 2, PER_DAY = 2;
  const live = () => !!document.getElementById('live-badge');
  const weekOf = day => Math.ceil(day / WEEK);
  let made = new Set(), checked = false;

  // days: highlight days with items that already have `line` (Highlights.days()).
  function spec(days, w) {
    const lo = (w - 1) * WEEK + 1, hi = w * WEEK, mine = days.filter(d => d.day >= lo && d.day <= hi && d.items.length);
    if (!mine.length) return null;
    const all = mine.flatMap(d => d.items.map((it, k) => ({ ...it, score: it.score ?? 3, order: k })));
    // strongest first, at most 2 of a kind (never twice on one day) and 2 a day, then in the order they happened
    all.sort((a, b) => b.score - a.score || a.order - b.order || a.tick - b.tick);
    const kinds = {}, perDay = {}, pick = [];
    for (const it of all) {
      if (pick.length >= PICKS) break;
      if ((kinds[it.kind] || 0) >= PER_KIND || (perDay[it.day] || 0) >= PER_DAY ||
          pick.some(p => p.kind === it.kind && p.day === it.day)) continue;
      kinds[it.kind] = (kinds[it.kind] || 0) + 1; perDay[it.day] = (perDay[it.day] || 0) + 1; pick.push(it);
    }
    for (const it of all) if (pick.length < Math.min(PICKS, 5) && !pick.includes(it)) pick.push(it);   // a quiet week
    const last = mine[mine.length - 1].day;
    return { key: `nedelya-${w}`, label: `Неделя ${w}`, from: lo, to: Math.min(hi, last), days: WEEK,
             items: pick.sort((a, b) => a.tick - b.tick) };
  }

  function buttons(days) {
    const row = document.createElement('div');
    row.className = 'msg';
    const weeks = [...new Set(days.filter(d => d.items.length).map(d => weekOf(d.day)))];
    if (!weeks.length || typeof Clip === 'undefined' || !Clip.supported()) return row;
    row.textContent = 'Ролик недели: ';
    for (const w of weeks) {
      const s = spec(days, w);
      if (s) { const b = Clip.button(s, `🎞 Неделя ${w}`); b.style.float = 'none'; row.append(b); }
    }
    return row;
  }

  async function known() {
    try { (await (await fetch('/api/clips')).json()).clips.forEach(c => made.add(c.key)); } catch (e) { /* static file */ }
  }
  async function auto(w, days) {
    const s = spec(days, w);
    if (!s || made.has(s.key) || typeof Clip === 'undefined' || !Clip.supported()) return;
    made.add(s.key);   // once per session, even if it is cancelled
    await Clip.make(s, { auto: true });
  }
  // Every finished week that has no clip yet (the viewer was closed when it ended).
  async function catchUp(final) {
    if (!live() || !window.Highlights) return;
    if (!checked) { checked = true; await known(); }
    const days = await Highlights.load();
    const done = days.filter(d => !d.partial);
    if (!done.length) return;
    const lastDay = done[done.length - 1].day;
    for (let w = 1; w <= weekOf(lastDay); w++) {
      const full = done.some(d => d.day === w * WEEK);
      const tail = final && w === weekOf(lastDay) && done.filter(d => weekOf(d.day) === w).length >= 2;
      if (full || tail) await auto(w, days);
    }
  }
  let ended = false;
  window.addEventListener('village-live', e => {
    const r = e.detail;
    if (r.type === 'highlights' && !r.partial && r.day % WEEK === 0) setTimeout(() => catchUp(ended), 1500);
    if (r.type === 'end') { ended = true; setTimeout(() => catchUp(true), 4000); }   // the last day's highlights come first
  });
  // On opening a running village: weeks that ended meanwhile (after the backlog of ticks is loaded).
  window.addEventListener('load', () => setTimeout(() => { if (live() && ticks.length) catchUp(ended); }, 8000));
  return { spec, buttons, catchUp };
})();
