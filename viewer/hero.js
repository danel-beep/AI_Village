// Hero page ("📖 Страница героя"): one villager's whole life on one page over the viewer. Portrait, numbers,
// a chronicle of what happened to them (click a line to watch that moment), best quotes, their star moments
// from the highlights, property, closest people, coins/health/food over time, diary.
// Opened from the dossier's 📖 button or by link: #hero=<name> (also ?follow=<name> just follows them on the map).
// Reads the viewer's globals (header, ticks, i, diaries, color, names, tr, esc, select, go, setPlaying).
(() => {
  const css = document.createElement('style');
  css.textContent = `
    #hero { position:fixed; inset:0; z-index:40; background:rgba(16,20,18,.97); overflow:auto; }
    #hero[hidden] { display:none; }
    #hero .wrap { max-width:1100px; margin:0 auto; padding:16px; }
    #hero .head { display:flex; gap:16px; align-items:center; flex-wrap:wrap; }
    #hero canvas.port { width:96px; height:128px; image-rendering:pixelated; background:#2b3531; border-radius:10px;
      border:2px solid var(--rule); flex:none; }
    #hero .who { flex:1; min-width:200px; }
    #hero .who .nm { font-size:26px; font-weight:600; }
    #hero .who .char { font-style:italic; color:var(--muted); margin-top:4px; }
    #hero .acts { display:flex; gap:6px; flex-wrap:wrap; }
    #hero .nums { display:grid; grid-template-columns:repeat(auto-fill, minmax(118px, 1fr)); gap:8px; margin:14px 0; }
    #hero .num { background:var(--card); border-radius:8px; padding:8px; }
    #hero .num b { display:block; font-size:18px; }
    #hero .cols { display:grid; grid-template-columns:minmax(0, 1.2fr) minmax(0, 1fr); gap:16px; }
    @media (max-width: 760px) { #hero .cols { grid-template-columns:minmax(0, 1fr); } #hero .wrap { padding:12px; } }
    #hero section { background:var(--panel); border-radius:10px; padding:10px 12px; margin-bottom:16px; }
    #hero h3 { margin:2px 0 8px; }
    #hero .day { margin:10px 0 4px; font-size:12px; color:var(--accent); }
    #hero .ev { display:flex; gap:8px; padding:4px 6px; border-radius:6px; cursor:pointer; }
    #hero .ev:hover { background:var(--card); }
    #hero .ev .ic { flex:none; width:22px; text-align:center; }
    #hero .ev .tm { flex:none; color:var(--muted); font-size:12px; width:40px; padding-top:1px; }
    #hero .q { border-left:3px solid var(--accent); padding:4px 8px; margin:6px 0; cursor:pointer; }
    #hero .q.th { border-color:var(--muted); font-style:italic; }
    #hero .row { border-bottom:1px solid var(--rule); padding:5px 0; }
    #hero .bar { height:6px; background:#34403b; border-radius:3px; position:relative; margin-top:3px; }
    #hero .bar i { position:absolute; top:0; bottom:0; }
    #hero svg.spark { width:100%; height:46px; display:block; }
    #hero .p { cursor:pointer; font-weight:600; }
  `;
  document.head.appendChild(css);
  const box = Object.assign(document.createElement('div'), { id: 'hero', hidden: true });
  document.body.appendChild(box);

  // Life events: kind -> [icon, Russian title, weight]. Weight 1 = everyday, shown only the first time.
  const LIFE = {
    death: ['🕯', 'Смерть', 10], house_burned: ['🏚', 'Сгорел дом', 10], steal: ['🫳', 'Кража', 9], robbed: ['🫳', 'Обокрали', 9],
    steal_attempt: ['🫳', 'Попытка кражи', 7], steal_from_plot: ['🫳', 'Кража с грядки', 8], fight: ['🥊', 'Драка', 9],
    set_fire: ['🔥', 'Поджог', 9], arson_seen: ['🔥', 'Видел поджог', 8], fire: ['🔥', 'Пожар', 8], extinguish: ['🪣', 'Тушил пожар', 6],
    fire_out: ['🪣', 'Пожар потушен', 5], evicted: ['🚪', 'Выселение', 8], hospital: ['🏥', 'В больнице', 7],
    discharged: ['🏥', 'Выписка', 3], sick: ['🤒', 'Болезнь', 4], starving: ['🍂', 'Голод', 5],
    wedding: ['💍', 'Свадьба', 9], divorce: ['💔', 'Развод', 9], proposal: ['💌', 'Предложение руки и сердца', 6],
    proposal_refused: ['💔', 'Отказ жениться', 6], inheritance: ['📜', 'Наследство', 6], hang_out: ['☕', 'Провели время вместе', 2], feast: ['🍲', 'Устроил праздник', 6],
    elected: ['🎖', 'Стал старостой', 8], candidate: ['🗳', 'Кандидат в старосты', 3], law_proposed: ['⚖', 'Предложил закон', 3],
    law_passed: ['⚖', 'Принят закон', 4], theft_report: ['📣', 'Донос', 7], witness: ['👁', 'Свидетель кражи', 6],
    whisper_seen: ['👂', 'Подслушанный шёпот', 4], gossip: ['🗣', 'Слух', 3], gossip_heard: ['🗣', 'Услышал слух', 2],
    default: ['💸', 'Долг не вернули', 8], lend: ['🤝', 'Заём', 4], repay: ['🤝', 'Вернул долг', 3], give: ['🎁', 'Подарок', 4],
    trade: ['⚖', 'Сделка', 3], decline: ['✋', 'Отказ', 2], gift: ['✨', 'Дар богов', 3], god_treasure: ['💎', 'Клад', 5],
    land_bought: ['🏡', 'Купил землю', 5], land_sold: ['🏡', 'Продал землю', 5], land_offer: ['🏡', 'Продаёт землю', 2],
    project_done: ['🏗', 'Общая стройка готова', 5], share: ['🏗', 'Вклад в общее', 2], order_done: ['📦', 'Выполнил заказ', 3],
    tool_broke: ['🔧', 'Сломался инструмент', 2], letter: ['✉', 'Письмо', 2], whisper: ['🤫', 'Шёпот', 1],
    build: ['🔨', 'Стройка', 2], craft: ['🛠', 'Ремесло', 1], plant: ['🌱', 'Посадил', 1], sell: ['🪙', 'Продал', 1],
    buy: ['🛒', 'Купил', 1], collect: ['🧺', 'Собрал урожай', 1],
  };
  const STATUS = { active: 'в порядке', hospital: 'в больнице', evicted: 'выселен', sick: 'болеет', dead: 'умер' };
  const BUILD = { garden_bed: 'грядка', coop: 'курятник', pen: 'загон', well: 'колодец', shed: 'сарай' };
  const hhmm = t => `${String(t.view.hour).padStart(2, '0')}:${String(t.view.minute || 0).padStart(2, '0')}`;
  const sign = v => (v > 0 ? '+' : '') + v;

  // Does event e concern villager n? Its actor, a named party in its data, or one of a few addressees
  // (village-wide events list everyone in `to`, which says nothing about n).
  function involves(e, n) {
    if (e.actor === n) return true;
    if (e.data) for (const v of Object.values(e.data)) if (v === n || (Array.isArray(v) && v.length <= 3 && v.includes(n))) return true;
    return e.to.length <= 3 && e.to.includes(n);
  }

  // Everything about n up to tick i, built incrementally (live runs only add ticks) and reset on a jump back.
  let st = null;
  function fresh(n) {
    return { n, k: -1, life: [], quotes: [], seen: {}, counts: {}, series: [], status: null, mayor: null, spouse: null,
      turns: 0, errors: 0, won: 0, lost: 0, given: 0, got: 0, trades: 0, thefts: 0, peak: 0, contacts: {} };
  }
  function step(s, k) {
    const t = ticks[k], n = s.n, v = t.view.agents[n];
    if (!v) return;
    const d = t.decisions[n], dayKey = t.view.day, add = (kind, text, extra) => s.life.push({ k, kind, text, ...extra });
    if (k === 0) add('start', `Начинает жизнь в деревне: ${v.profession && v.profession !== 'villager' ? v.profession + ', ' : ''}${v.coins} монет.`, { ic: '🌅', title: 'Начало' });
    if (s.status !== null && v.status !== s.status && v.status !== 'active')
      add('status', `Теперь ${STATUS[v.status] || v.status}.`, { ic: '⚠', title: 'Перемена судьбы', w: 7 });
    s.status = v.status;
    if (t.view.mayor !== s.mayor && (t.view.mayor === n || s.mayor === n) && s.mayor !== null)
      add('mayor', t.view.mayor === n ? 'Стал старостой деревни.' : 'Больше не староста.', { ic: '🎖', title: 'Староста', w: 8 });
    s.mayor = t.view.mayor || '';
    const cp = ((t.view.kin || {}).couples || []).find(c => c.includes(n)), sp = cp ? cp.find(p => p !== n) : '';
    s.spouse = sp;
    s.peak = Math.max(s.peak, v.coins);
    if (k % Math.max(1, Math.ceil(ticks.length / 240)) === 0 || k === i) s.series.push([k, v.coins, v.health, v.satiety]);
    if (d) {
      s.turns++;
      if (d.action) s.counts[d.action.name] = (s.counts[d.action.name] || 0) + 1;
      for (const [kind, txt] of [['say', d.say], ['thought', d.thought]]) if (txt && txt.length >= 15) s.quotes.push({ k, kind, text: txt });
    }
    for (const e of t.events) {
      if (e.kind === 'error') { if (e.actor === n) s.errors++; continue; }
      if (!involves(e, n)) continue;
      const other = [e.actor, ...e.to].filter(p => p && p !== n && p in color);
      for (const p of new Set(other)) s.contacts[p] = (s.contacts[p] || 0) + 1;
      if (e.kind === 'fight' && e.data && [e.data.attacker, e.data.defender].includes(n)) e.data.winner === n ? s.won++ : s.lost++;
      if (e.kind === 'give') e.actor === n ? s.given++ : e.to.includes(n) && s.got++;
      if (e.kind === 'trade') s.trades++;
      if (/^steal/.test(e.kind) && e.actor === n) s.thefts++;
      const L = LIFE[e.kind];
      if (!L) continue;
      // Everyday kinds once ever; others once per day per kind and other party (repeats counted).
      const key = L[2] <= 1 ? e.kind : `${dayKey}|${e.kind}|${other.sort().join(',')}`;
      if (s.seen[key]) { s.seen[key].times++; continue; }
      add(e.kind, e.text, { ic: L[0], title: L[2] <= 1 ? 'Впервые: ' + L[1].toLowerCase() : L[1], w: L[2], times: 1 });
      s.seen[key] = s.life[s.life.length - 1];
    }
  }
  function collect(n) {
    if (!st || st.n !== n || st.k > i || st.len > ticks.length) st = fresh(n);
    for (let k = st.k + 1; k <= i; k++) step(st, k);
    st.k = i; st.len = ticks.length;
    return st;
  }

  // Quotes worth reading: mid-length, naming other villagers, emotional, near a big moment of their life.
  function best(s, kind, max) {
    const big = new Set(s.life.filter(x => (x.w || 0) >= 6).flatMap(x => [x.k - 1, x.k, x.k + 1])), seen = new Set();
    return s.quotes.filter(q => q.kind === kind).map(q => {
      const len = q.text.length, others = names.filter(p => p !== s.n && q.text.includes(p)).length;
      const score = (len < 25 ? -3 : len > 260 ? -1 : Math.min(4, len / 40)) + 2 * Math.min(2, others)
        + (/[!?]/.test(q.text) ? 1 : 0) + (big.has(q.k) ? 3 : 0);
      return { ...q, score };
    }).sort((a, b) => b.score - a.score).filter(q => {
      const key = q.text.toLowerCase().replace(/[^\p{L}]+/gu, ' ').slice(0, 40);
      return !seen.has(key) && seen.add(key);
    }).slice(0, max).sort((a, b) => a.k - b.k);
  }

  function spark(s, idx, max, col, label) {
    const pts = s.series, k0 = pts.length ? pts[0][0] : 0, k1 = Math.max(k0 + 1, pts.length ? pts[pts.length - 1][0] : 1);
    const top = Math.max(max, ...pts.map(p => p[idx]), 1);
    const line = pts.map(p => `${(100 * (p[0] - k0) / (k1 - k0)).toFixed(1)},${(40 - 38 * p[idx] / top).toFixed(1)}`).join(' ');
    const last = pts.length ? pts[pts.length - 1][idx] : 0;
    return `<div class="muted">${label}: <b style="color:var(--ink)">${last}</b> <span>(макс ${Math.max(...pts.map(p => p[idx]), 0)})</span></div>
      <svg class="spark" viewBox="0 0 100 42" preserveAspectRatio="none" role="img" aria-label="${label} по времени">
        <polyline points="${line}" fill="none" stroke="${col}" stroke-width="1.5" vector-effect="non-scaling-stroke"/></svg>`;
  }

  // Highlights where this villager is in the picture (embedded, live rows, or /api/highlights).
  let hl = Array.isArray(window.EMBEDDED_HIGHLIGHTS) ? window.EMBEDDED_HIGHLIGHTS.slice() : [];
  const addHl = rec => { hl = hl.filter(d => d.day !== rec.day).concat([rec]); };
  window.addEventListener('village-live', e => { if (e.detail.type === 'highlights') addHl(e.detail); });
  async function fetchHl() {
    if (!location.protocol.startsWith('http')) return;
    try { (await (await fetch('/api/highlights')).json()).highlights.forEach(addHl); show(open); } catch (e) { /* static page */ }
  }

  function property(n, t, s) {
    const v = t.view.agents[n], plots = t.view.plots || {}, out = [];
    const inv = (window.ItemIcons ? ItemIcons.list(v.inventory) : Object.entries(v.inventory).map(([k, q]) => `${q} ${esc(k)}`).join(', ')) || 'пусто';
    out.push(`<div class="row">💰 <b>${v.coins}</b> монет при себе <span class="muted">(больше всего было ${s.peak})</span></div>`);
    out.push(`<div class="row">🎒 ${inv}</div>`);
    const chest = (t.view.chests || {})[n];
    if (chest) {
      const ci = window.ItemIcons ? ItemIcons.list(chest.items) : Object.entries(chest.items || {}).map(([k, q]) => `${q} ${esc(k)}`).join(', ');
      out.push(`<div class="row">🧰 Сундук${chest.locked ? ' (на замке)' : ''}: ${chest.coins} монет${ci ? ', ' + ci : ''}</div>`);
    }
    for (const [id, p] of Object.entries(plots)) {
      if (p.owner !== n) continue;
      const kinds = {};
      for (const b of p.buildings || []) kinds[b.kind] = (kinds[b.kind] || 0) + 1;
      const bl = Object.entries(kinds).map(([k, q]) => `${BUILD[k] || esc(k)} ×${q}`).join(', ');
      const ripe = (p.buildings || []).filter(b => b.crop && b.ripe_day && b.ripe_day <= t.view.day).length;
      const name = p.kind === 'lot' ? `Участок «${esc(t.view.locations[id] || id)}»` : `Дом${p.house ? `, уровень ${p.house}` : ''}`;
      out.push(`<div class="row">${p.kind === 'lot' ? '🏡' : '🏠'} ${name} · ${p.cells} клеток${p.for_sale ? ' · <b>продаётся</b>' : ''}
        ${bl ? `<div class="muted">${bl}${ripe ? ` · созрело грядок: ${ripe}` : ''}</div>` : ''}</div>`);
    }
    if (s.spouse) out.push(`<div class="row">💍 Живёт в браке с ${pname(s.spouse)}: сундуки общие</div>`);
    return out.join('');
  }

  const pname = p => `<span class="p" style="color:${color[p] || 'inherit'}" data-p="${esc(p)}">${esc(p)}</span>`;
  function closest(n, t, s) {
    const feel = ((t.view.kin || {}).feelings || {})[n] || {}, back = p => ((((t.view.kin || {}).feelings || {})[p] || {})[n] || 0);
    const all = [...new Set([...Object.keys(feel), ...Object.keys(s.contacts)])].filter(p => p !== n && p in color);
    if (!all.length) return '<div class="muted">Пока ни с кем не сблизился.</div>';
    all.sort((a, b) => Math.abs(feel[b] || 0) - Math.abs(feel[a] || 0) || (s.contacts[b] || 0) - (s.contacts[a] || 0));
    return all.slice(0, 6).map(p => {
      const f = feel[p] || 0;
      return `<div class="row">${pname(p)} <span class="muted">· чувство ${sign(f)}, в ответ ${sign(back(p))} · встреч ${s.contacts[p] || 0}</span>
        ${'kin' in t.view ? `<div class="bar"><i style="left:${f < 0 ? 50 + f / 2 : 50}%;width:${Math.abs(f) / 2}%;background:${f < 0 ? '#e4572e' : '#76b041'}"></i></div>` : ''}</div>`;
    }).join('');
  }

  function chronicle(s) {
    if (s.life.length <= 1) return '<div class="muted">Пока ничего заметного не случилось.</div>';
    let out = '', day = null;
    for (const x of s.life.slice().reverse()) {
      const t = ticks[x.k];
      if (t.view.day !== day) { day = t.view.day; out += `<div class="day">День ${day}</div>`; }
      out += `<div class="ev" data-k="${x.k}" title="Посмотреть этот момент"><span class="tm">${hhmm(t)}</span><span class="ic">${x.ic}</span>
        <span><b>${esc(x.title)}</b>${x.times > 1 && x.w > 1 ? ` <span class="muted">×${x.times}</span>` : ''} <span class="muted">${esc(tr(x.text))}</span></span></div>`;
    }
    return out;
  }

  function portrait(n) {
    const c = document.createElement('canvas'); c.className = 'port'; c.width = 24; c.height = 32;
    const sh = typeof PixelMap !== 'undefined' && PixelMap.sheet && PixelMap.sheet(n);  // const globals aren't on window
    if (sh) {
      const fw = sh.fw || 12, fh = sh.fh || 16, k = Math.min(22 / fw, 30 / fh), g = c.getContext('2d');
      g.imageSmoothingEnabled = false;
      g.drawImage(sh, 0, 0, fw, fh, Math.round((24 - fw * k) / 2), Math.round(31 - fh * k), Math.round(fw * k), Math.round(fh * k));
    }
    return c;
  }

  let open = null, shownAt = -2;
  function show(n) {
    if (!n || !ticks.length || !ticks[i].view.agents[n]) { close(); return; }
    const t = ticks[i], v = t.view.agents[n], s = collect(n), keep = open === n ? box.scrollTop : 0;
    open = n; shownAt = i;
    const brain = (header.brains || {})[n], agentCfg = ((header.config || {}).agents || []).find(a => a.name === n) || {};
    const days = t.view.day - ticks[0].view.day + 1, friends = Object.values(((t.view.kin || {}).feelings || {})[n] || {});
    const at = ((header.config || {}).family || {}).friend_at || 30;
    const stars = hl.flatMap(d => d.items || []).filter(it => (it.who || []).includes(n) && ticks.some((x, k) => k <= i && x.tick === it.tick));
    const says = best(s, 'say', 5), thoughts = best(s, 'thought', 3);
    const quote = q => `<div class="q ${q.kind === 'thought' ? 'th' : ''}" data-k="${q.k}">${q.kind === 'thought' ? '💭' : '💬'} «${esc(tr(q.text))}»
      <div class="muted">день ${ticks[q.k].view.day}, ${hhmm(ticks[q.k])}</div></div>`;
    const num = (val, label) => `<div class="num"><b>${val}</b><span class="muted">${label}</span></div>`;
    const diary = diaries.filter(d => d.at <= i && d.entries[n]).map(d => d.entries[n]);
    box.innerHTML = `<div class="wrap">
      <div class="head"><span id="hero-port"></span>
        <div class="who"><div class="nm" style="color:${color[n]}">${esc(n)}</div>
          <div>${v.profession && v.profession !== 'villager' ? esc(v.profession) + ' · ' : ''}${STATUS[v.status] || esc(v.status)} · ${v.asleep ? 'спит' : 'сейчас'} в «${esc(t.view.locations[v.location] || v.location)}»
            ${t.view.mayor === n ? ' · 🎖 староста' : ''}${s.spouse ? ` · 💍 ${pname(s.spouse)}` : ''}</div>
          <div class="muted">${brain ? `Мозг: ${esc(brain)} · ` : ''}день ${t.view.day}, ${hhmm(t)}</div>
          ${agentCfg.character ? `<div class="char">«${esc(agentCfg.character)}»</div>` : ''}</div>
        <div class="acts"><button data-a="follow" title="Закрыть страницу и следить за жителем на карте">👁 Следить на карте</button>
          <button data-a="link" title="Скопировать ссылку на эту страницу">🔗 Ссылка</button>
          <button data-a="close" title="Закрыть (Esc)">✕</button></div></div>
      <div class="nums">${num(days, 'дней в деревне')}${num(s.turns, 'ходов')}
        ${num(`${v.coins} <span class="muted">${sign(v.coins - ticks[0].view.agents[n].coins)}</span>`, 'монет')}
        ${num(`${v.health}/${v.satiety}`, 'здоровье / сытость')}${num(`${s.won}–${s.lost}`, 'драки: победы–поражения')}
        ${num(s.thefts, 'краж')}${num(`${s.given}/${s.got}`, 'подарков дал/получил')}${num(s.trades, 'сделок')}
        ${num(`${friends.filter(f => f >= at).length}/${friends.filter(f => f <= -at).length}`, 'друзей / врагов')}
        ${num(s.turns ? Math.round(100 * s.errors / s.turns) + '%' : '—', 'неудачных действий')}</div>
      <div class="cols"><div>
        <section><h3>Летопись жизни</h3><div class="muted">Нажмите на строку, чтобы посмотреть этот момент на карте.</div>${chronicle(s)}</section>
      </div><div>
        ${stars.length ? `<section><h3>⭐ Звёздные моменты</h3>${stars.map(it => `<div class="ev" data-tick="${it.tick}">
          <span class="ic">⭐</span><span><b>${esc(it.title)}</b> <span class="muted">${esc(it.time)}. ${esc(it.text && it.text !== it.event ? it.text : tr(it.event || ''))}</span></span></div>`).join('')}</section>` : ''}
        <section><h3>Лучшие цитаты</h3>${says.length || thoughts.length ? says.map(quote).join('') + thoughts.map(quote).join('')
          : '<div class="muted">Пока молчит.</div>'}</section>
        <section><h3>Имущество</h3>${property(n, t, s)}</section>
        <section><h3>Близкие люди</h3>${closest(n, t, s)}</section>
        <section><h3>Как жил</h3>${spark(s, 1, 10, '#f2c14e', 'Монеты')}${spark(s, 2, 100, '#17bebb', 'Здоровье')}${spark(s, 3, 100, '#76b041', 'Сытость')}</section>
        <section><h3>Дневник</h3>${diary.length ? diary.slice().reverse().map(d => `<div class="row"><span class="muted">День ${d.day}</span>
          <div class="thought">${esc(tr(d.text))}</div></div>`).join('') : '<div class="muted">Дневник пишется ночью.</div>'}</section>
      </div></div></div>`;
    box.querySelector('#hero-port').replaceWith(portrait(n));
    box.hidden = false; box.scrollTop = keep;
    box.querySelector('[data-a=close]').onclick = close;
    box.querySelector('[data-a=follow]').onclick = () => { follow(n); close(); };
    box.querySelector('[data-a=link]').onclick = e => {
      const url = location.href.split('#')[0] + '#hero=' + encodeURIComponent(n);
      (navigator.clipboard ? navigator.clipboard.writeText(url) : Promise.reject()).then(
        () => { e.target.textContent = '✓ Скопировано'; }, () => { e.target.textContent = url; });
    };
    for (const el of box.querySelectorAll('[data-k]')) el.onclick = () => watch(n, +el.dataset.k, false);
    for (const el of box.querySelectorAll('[data-tick]')) el.onclick = () => {
      const k = ticks.findIndex(x => x.tick === +el.dataset.tick); if (k >= 0) watch(n, k, true);
    };
    for (const el of box.querySelectorAll('[data-p]')) el.onclick = () => show(el.dataset.p);
    setHash(n);
  }

  function follow(n) { if (selected !== n) select(n); lastPanel = -1; }
  // Jump the map to tick k (a moment before it when playing it) and follow n there.
  function watch(n, k, play) {
    close(); follow(n);
    go(Math.max(0, play ? k - 1 : k), true);
    setPlaying(!!play);
  }
  function close() {
    if (box.hidden && !open) return;
    box.hidden = true; open = null; setHash(null);
  }
  function setHash(n) {
    const want = n ? '#hero=' + encodeURIComponent(n) : '';
    if (location.hash === want || (!n && !/^#hero=/.test(location.hash))) return;
    try { history.replaceState(null, '', location.pathname + location.search + want); } catch (e) { /* sandboxed frame */ }
  }

  // Called by the viewer's panel() when the shown tick changes: keep an open page current (at most once a second
  // while playing) and open the page / follow a villager named in the link once the log has them.
  let lastDraw = 0, linked = false;
  function refresh() {
    if (!linked && ticks.length) {
      const h = /^#hero=(.+)$/.exec(location.hash), f = /[?&]follow=([^&]+)/.exec(location.search);
      const want = h && decodeURIComponent(h[1]), fol = f && decodeURIComponent(f[1]);
      if (fol && ticks[i].view.agents[fol] && selected !== fol) follow(fol);
      if (want && ticks[i].view.agents[want]) { linked = true; Hero.open(want); }
      else if (!want) linked = true;
    }
    if (!open || shownAt === i) return;
    const now = performance.now();
    if (now - lastDraw < 1000) return;
    lastDraw = now; show(open);
  }
  window.addEventListener('keydown', e => { if (e.key === 'Escape' && open) close(); });
  window.Hero = { open: n => { show(n); fetchHl(); }, close, refresh, get current() { return open; } };
})();
