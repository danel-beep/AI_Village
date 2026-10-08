// «Часы судьбы» (Эфир, part 2): amber clocks from the rules of the game. Unlike viewer/foresight.js they never look at
// the future of the log, so they work the same in a replay and in a live game. A clock is a forecast that can still
// be broken (the fire put out, the hungry fed); the screen keeps at most three, the most urgent first.
//   ☠ / 🍞  when a hungry villager collapses (satiety and health run down by the config's rates, nights included);
//           ☠ when that collapse is their death (the last of `lives`, or death_mode "death")
//   🔥      a house fire: burns down in N hours, jumps to a neighbour's house on its fire_spread_hours-th hour
//   🗳 📜   a ballot (polity founding, leader, mayor election day) or a law with its closing time; a petition "k of n"
//   👑      a repeated bid for power: the Nth petition for a single ruler, the Nth election after losing the last ones
//   🧳 ⚔ 🐺 a traveler who leaves in N hours, raiders or a beast here or warned of
//   🤫      a theft nobody saw: only the viewer knows, until it is reported (or a day goes by)
//   ⚠ ❄     a crisis with days left, winter coming
// Pure (no DOM): tests/test_efir.py runs it with node. F = Fate.create(config); F.add(ticks, k) as rows arrive;
// F.lines(ticks, k, env) -> [{icon, text, score}] for the tick on screen.
const Fate = (() => {
  const SHOW = 3, HUNGER_H = 16, DEATH_H = 24, SECRET_DAYS = 1, PETITION_DAYS = 2;
  const FORM = { assembly: 'общее собрание', council: 'совет', ruler: 'один правитель' };
  const SEAT = { assembly: 'казначея', council: 'совета', ruler: 'правителя' };

  function create(cfg = {}) {
    const tm = +cfg.tick_minutes || 60, start = cfg.day_start_hour ?? 6, end = cfg.day_end_hour ?? 22;
    const perHour = Math.max(1, Math.round(60 / tm)), perDay = Math.max(1, (end - start) * perHour);
    const pol = cfg.polity || {};
    const items = [];            // {s, e, ...}: a clock from tick s until tick e (exclusive; Infinity while open)
    const open = new Map();      // key -> the open item
    const form = new Map();      // polity -> its form of government
    const losses = new Map();    // villager -> elections lost (mayor or polity seat)
    const coups = new Map();     // villager -> petitions they started for a single ruler
    const fires = new Map();     // house -> [tick a fire started there, tick it jumped (or caught it from a neighbour)]
    const candidates = new Set();
    let mayor = null, version = 0;

    const tickOf = (ticks, k) => (ticks[k] && Number.isFinite(ticks[k].tick) ? ticks[k].tick : k);
    const timeOf = t => { const d = Math.floor(t / perDay), r = t - d * perDay; return { day: d + 1, hour: start + Math.floor(r / perHour), minute: (r % perHour) * tm }; };
    function begin(key, k, it) { finish(key, k); const x = { s: k, e: Infinity, ...it }; items.push(x); if (key) open.set(key, x); version++; return x; }
    function finish(key, k) { const x = open.get(key); if (x) { x.e = Math.min(x.e, k); open.delete(key); version++; } }
    const finishAll = (prefix, k) => { for (const key of [...open.keys()]) if (key.startsWith(prefix)) finish(key, k); };
    // elections lost since the villager last won one (a win starts the count again)
    const lost = (votes, winners) => { for (const n of Object.keys(votes || {})) losses.set(n, winners.includes(n) ? 0 : (losses.get(n) || 0) + 1); for (const n of winners) losses.set(n, 0); };

    function add(ticks, k) {
      const t = tickOf(ticks, k);
      for (const e of (ticks[k] && ticks[k].events) || []) {
        const d = e.data || {}, p = d.polity;
        switch (e.kind) {
          case 'fire':
            fires.set(d.house, [k, d.spread_from ? k : Infinity]);
            if (d.spread_from && fires.has(d.spread_from)) fires.get(d.spread_from)[1] = Math.min(fires.get(d.spread_from)[1], k);
            break;
          case 'polity_founded':
            begin('ballot:' + p, k, { kind: 'ballot', what: 'form', closes: t + (pol.vote_hours ?? 24) * perHour });
            break;
          case 'polity_form':
            form.set(p, d.form);
            finishAll('petition:' + p + ':', k);
            if (!d.signed) finish('ballot:' + p, k);
            break;
          case 'polity_leaders': {
            const winners = [...(d.rulers || []), ...(d.keeper ? [d.keeper] : [])];
            if (winners.length) { finish('ballot:' + p, k); lost(d.votes, winners); }
            else begin('ballot:' + p, k, { kind: 'ballot', what: 'leader', seat: SEAT[form.get(p)], bid: bidder(), closes: t + (pol.vote_hours ?? 24) * perHour });
            break;
          }
          case 'polity_petition': {
            const signed = d.signed || [], key = `petition:${p}:${d.form}`, was = open.get(key);
            let coup = was ? was.coup : null;
            if (!was && d.form === 'ruler' && form.get(p) !== 'ruler' && e.actor) {
              coups.set(e.actor, (coups.get(e.actor) || 0) + 1); coup = { who: e.actor, n: coups.get(e.actor) };
            }
            begin(key, k, { kind: 'petition', form: d.form, signed: signed.length, needed: d.needed, coup, lapse: k + PETITION_DAYS * perDay });
            break;
          }
          case 'polity_law_proposed':
            begin('law:' + d.law, k, { kind: 'law', who: e.actor, closes: t + (pol.law_vote_hours ?? 24) * perHour });
            break;
          case 'polity_law_passed': case 'polity_law_failed':
            finish('law:' + d.law, k); break;
          case 'election_soon':
            begin('mayor', k, { kind: 'mayor', soon: true }); break;
          case 'election_day':
            begin('mayor', k, { kind: 'mayor', bid: bidder(), closes: (Math.floor(t / perDay) + 1) * perDay }); break;
          case 'candidate':
            if (e.actor && /runs for mayor/.test(e.text || '')) candidates.add(e.actor);
            break;
          case 'elected': case 'election':
            finish('mayor', k);
            if (e.kind === 'elected') { mayor = d.mayor; lost(Object.fromEntries([...candidates].map(n => [n, 1])), [d.mayor]); }
            break;
          case 'steal':
            if (d.success && e.actor && !(d.witnesses || []).length && !(d.seen_by || []).length)
              begin('secret:' + e.actor, k, { kind: 'secret', who: e.actor, victim: d.victim, item: d.item, qty: d.qty, lapse: k + SECRET_DAYS * perDay });
            break;
          case 'theft_report': case 'witness':
            finish('secret:' + (d.thief || e.actor), k); break;
          case 'polity_embezzle':
            if (e.actor) begin('embezzle:' + p, k, { kind: 'embezzle', who: e.actor, coins: d.coins, lapse: k + SECRET_DAYS * perDay });
            break;
          case 'polity_embezzlement_found':
            finish('embezzle:' + p, k); break;
        }
      }
    }

    // ---------- clocks read off the tick on screen ----------
    // Game hours until a villager collapses from hunger, at the config's rates (as aivillage/engine.py: hourly loss,
    // then the night's loss), or null if not within `limit` hours. night: it happens overnight.
    function collapse(a, v, seasonOf, limit) {
      const loss = a.asleep ? cfg.satiety_loss_asleep_per_hour ?? 2 : cfg.satiety_loss_per_hour ?? 2;
      const starve = cfg.starving_health_loss_per_hour ?? 5, nightLoss = cfg.satiety_loss_night ?? 10;
      const nightStarve = cfg.starving_health_loss_night ?? 20, nh = (cfg.seasons || {}).night_hunger || {};
      const nightLen = 24 - end + start;
      let s = a.satiety, h = a.health ?? 100, t = v.hour + (v.minute || 0) / 60, day = v.day, el = 0;
      if (!(s >= 0) || s > 40) return null;
      for (let n = 0; n < 80 && el <= limit; n++) {
        if (t < end) {
          const nx = Math.floor(t) + 1; el += nx - t; t = nx;
          s = Math.max(0, s - loss); if (s === 0) h -= starve;
          if (h <= 0) return el <= limit ? { hours: el, night: false } : null;
        } else {
          const extra = (cfg.seasons || {}).enabled && seasonOf ? +(nh[seasonOf(day)] || 0) : 0;
          s = Math.max(0, s - nightLoss - extra); if (s === 0) h -= nightStarve;
          if (h <= 0) return el <= limit ? { hours: el, night: true } : null;
          el += nightLen; t = start; day++;
        }
      }
      return null;
    }
    // Game hours until a fire's `left` burning hours run out (a night burns fire_night_hours), or 'night'.
    function burnsIn(left, v) {
      const nightH = cfg.fire_night_hours ?? 4;
      let t = v.hour + (v.minute || 0) / 60, el = 0;
      for (let n = 0; n < 60; n++) {
        if (t < end) { const nx = Math.floor(t) + 1; el += nx - t; t = nx; if (--left <= 0) return { hours: el, night: false }; }
        else { left -= nightH; if (left <= 0) return { hours: el, night: true }; el += 24 - end + start; t = start; }
      }
      return { hours: el, night: false };
    }

    const hh = x => String(x).padStart(2, '0');
    const until = (closes, v) => {
      const w = timeOf(closes), at = `${hh(w.hour)}:${hh(w.minute)}`;
      return w.day === v.day ? `до ${at}` : w.day === v.day + 1 ? `до завтра, ${at}` : `до дня ${w.day}, ${at}`;
    };
    const hrs = x => x < 1 ? 'меньше часа' : `${Math.round(x)} ч`;

    let memo = null;
    function lines(ticks, k, env = {}) {
      const r = ticks[k]; if (!r || !r.view) return [];
      if (memo && memo.k === k && memo.v === version && memo.r === r) return memo.out;
      const v = r.view, t = tickOf(ticks, k), tr = env.tr || (x => x), item = env.item || (x => x);
      const place = loc => {
        const name = v.locations && v.locations[loc], ru = name ? tr(name) : loc;
        return ru === name && /^home_/.test(loc) ? `Дом ${loc.slice(5)}` : ru;   // no translation: "Дом Elena"
      };
      const out = [];
      // hunger and the last life
      const lives = +cfg.lives || 0, deathMode = cfg.death_mode === 'death';
      for (const [n, a] of Object.entries(v.agents || {})) {
        if (a.status !== 'active') continue;
        const last = deathMode || (lives > 0 && lives <= (a.hospital_stays || 0) + 1);
        const c = collapse(a, v, env.seasonOf, last ? DEATH_H : HUNGER_H); if (!c) continue;
        const when = c.night ? 'ночью' : `≈ ${hrs(c.hours)}`;
        if (last) out.push({ icon: '☠', text: `${n} · последняя жизнь · голод, смерть ${when}`, score: 100 - c.hours / 10 });
        else out.push({ icon: '🍞', text: `${n} · сытость ${a.satiety} · обморок ${when}`, score: (c.hours <= 6 ? 80 : 40) - c.hours / 10 });
      }
      // fires
      for (const [loc, f] of Object.entries(v.fire_info || {})) {
        const b = burnsIn(f.hours_left, v), sp = cfg.fire_spread_hours || 0;
        const parts = [place(loc), b.night ? 'сгорит ночью' : `сгорит через ${hrs(b.hours)}`];
        const fx = fires.get(loc), jumped = fx && fx[0] <= k && fx[1] <= k;
        if (sp && !jumped && f.hours < sp) parts.push(`перекинется через ${hrs(sp - f.hours)}`);
        parts.push(`🪣 ${f.water_needed}`);
        out.push({ icon: '🔥', text: parts.join(' · '), score: 90 - b.hours / 10 });
      }
      // ballots, laws, petitions, secrets: intervals built by add()
      for (const x of items) {
        if (x.s > k || x.e <= k || (x.lapse && k >= x.lapse)) continue;
        if (x.kind === 'ballot') {
          const seat = x.what === 'form' ? 'Деревня выбирает, как править' : `Выбор ${x.seat || 'главы'}`;
          const bid = crown(x.bid, v);
          out.push({ icon: '🗳', text: `${seat} · ${x.closes > t ? until(x.closes, v) : 'итоги вот-вот'}${bid}`, score: 62 - Math.max(0, x.closes - t) / perDay });
        } else if (x.kind === 'mayor') {
          out.push({ icon: '🗳', text: x.soon ? 'Выборы мэра завтра' : `Выборы мэра · ${until(x.closes, v)}${crown(x.bid, v)}`, score: x.soon ? 35 : 64 });
        } else if (x.kind === 'law') {
          out.push({ icon: '📜', text: `Закон${x.who ? ' от ' + x.who : ''} · голосуют ${x.closes > t ? until(x.closes, v) : 'итоги вот-вот'}`, score: 58 });
        } else if (x.kind === 'petition') {
          const coup = x.coup && x.form === 'ruler' ? ` · 👑 ${x.coup.who}: переворот, попытка №${x.coup.n}` : '';
          out.push({ icon: '📜', text: `Петиция «${FORM[x.form] || x.form}» · ${x.signed} из ${x.needed}${coup}`, score: (coup ? 66 : 55) + x.signed });
        } else if (x.kind === 'secret') {
          const what = x.item === 'coins' ? `${x.qty} монет` : `${item(x.item)}${x.qty > 1 ? ' ×' + x.qty : ''}`;
          out.push({ icon: '🤫', text: `${x.who} → ${what} у ${x.victim} · знает только зритель`, score: 70 });
        } else if (x.kind === 'embezzle') {
          out.push({ icon: '🤫', text: `${x.who} →${x.coins ? ' ' + x.coins + ' монет' : ' монеты'} из казны · знает только зритель`, score: 72 });
        }
      }
      // outsiders: a traveler, raiders, a beast
      for (const th of v.threats || []) {
        const loc = th.location ? place(th.location) : '';
        if (th.kind === 'traveler' && th.state === 'here') {
          const need = ((cfg.threats || {}).kinds || {}).traveler ? cfg.threats.kinds.traveler.need : null;
          out.push({ icon: '🧳', text: `Путник${loc ? ' · ' + loc : ''} · уйдёт через ${hrs(th.hours_left)}${need ? ` · просит еды: ${need}` : ''}`, score: 48 });
        } else if (th.state === 'here') {
          const icon = th.kind === 'beast' ? '🐺' : '⚔', who = th.kind === 'beast' ? 'Зверь' : 'Бандиты';
          out.push({ icon, text: `${who}${loc ? ' · ' + loc : ''} · уйдут через ${hrs(th.hours_left)}`, score: 75 });
        } else if (th.state === 'coming' && th.warned && th.arrive_day) {
          const icon = th.kind === 'beast' ? '🐺' : '⚔', who = th.kind === 'beast' ? 'Зверь придёт' : 'Бандиты придут';
          const at = `${hh(th.arrive_hour)}:00`, day = th.arrive_day === v.day ? `в ${at}` : th.arrive_day === v.day + 1 ? `завтра в ${at}` : `в день ${th.arrive_day}`;
          out.push({ icon, text: `${who} ${day}`, score: 52 });
        }
      }
      // crises and the coming winter
      for (const c of v.crises || []) {
        let what = String(tr(c.text || c.kind)).split(/[.!:]\s/)[0];
        if (what.length > 60) what = what.slice(0, 58) + '…';
        out.push({ icon: '⚠', text: `${what} · ещё ${c.days_left} дн.`, score: 20 });
      }
      if (env.seasonOf && (cfg.seasons || {}).enabled && env.seasonOf(v.day) !== 'winter')
        for (let d = 1; d <= 2; d++) if (env.seasonOf(v.day + d) === 'winter') { out.push({ icon: '❄', text: d === 1 ? 'Завтра зима' : `Зима через ${d} дн.`, score: 15 }); break; }
      const top = out.sort((a, b) => b.score - a.score).slice(0, SHOW);
      memo = { k, v: version, r, out: top };
      return top;
    }
    // The villager who lost the most elections so far (at least one), when a new one opens: their attempt number.
    function bidder() {
      let best = null;
      for (const [who, n] of losses) if (n && who !== mayor && (!best || n + 1 > best.n)) best = { who, n: n + 1 };
      return best;
    }
    const crown = (b, v) => b && v.agents && v.agents[b.who] && v.agents[b.who].status === 'active' ? ` · 👑 ${b.who}, попытка №${b.n}` : '';
    return { add, lines, items, collapse, burnsIn, timeOf };
  }
  return { create, FORM };
})();
if (typeof window !== 'undefined') window.Fate = Fate;
