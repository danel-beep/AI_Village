// Foresight: what is coming up in the log, for the «Эфир» replay (viewer/efir.js). A replay knows its whole future, so
// the director can be on the spot before something happens and count down to it. Pure: reads ticks only (no DOM), so
// tests/test_efir.py runs it with node. Built tick by tick as rows arrive: F = Foresight.create(score); F.add(ticks, k).
//
// A countdown waits for one moment: tick k (the moment happens as tick k starts playing), from tick s (s < k).
//   temptation  a hungry villager with no food of their own stands where someone else has food. It ends when they
//               steal (real) or when the chance goes by: they eat, get food, someone leaves (a decoy). Until zero both
//               look the same, so the countdown never tells which way it goes. Villagers announce a theft only 0-2
//               ticks ahead, but in the villain run a thief stood hungry next to the food for hours before.
//   answer      a marriage proposal waiting for its answer (wedding / refused).
//   event       a big moment from the log: a theft without such a build-up, arson, a fight, a fire, a collapse, a
//               death, a beast, an election result, a law decided, the treasury robbed...
// The outcome is read from the log only at zero (Foresight.outcome).
const Foresight = (() => {
  const HUNGRY = 30, MIN_WAIT = 3, DECOY_GAP = 128, LEAD = 8, EV_LEAD = 6, AFTER = 2, EV_MIN = 7;
  const FOOD = /^(berries|fish|meat|cooked_meat|smoked_fish|smoked_meat|bread|fish_soup|milk|egg|honey|apple|stew)$/;
  const isFood = k => {
    const it = typeof Icons !== 'undefined' && Icons.ITEMS && Icons.ITEMS[k];
    return it ? it.group === 'food' : FOOD.test(k);
  };
  const food = inv => { let s = 0; for (const k in inv || {}) if (isFood(k)) s += inv[k]; return s; };
  const FIGHT = /fight|attack|duel|brawl|hit/;
  const CHOICE = /^(steal|steal_attempt|set_fire|polity_embezzle|divorce|exile|proposal)$/;
  const FATE = /^(fire|burned_down|hospital|death|beast_attack|plundered|polity_embezzlement_found)$/;
  const POLITY = /^(polity_form|polity_law_passed|polity_law_failed|elected|law_passed|law_failed)$/;
  // What kind of countdown an event starts, or null. Election results count, the "vote until ..." notice does not.
  function classify(e, agents) {
    const k = e.kind, d = e.data || {};
    if (POLITY.test(k) || (k === 'polity_leaders' && (d.keeper || (d.rulers || []).length))) return 'polity';
    if (k === 'threat_arrived') return d.threat_kind && d.threat_kind !== 'traveler' ? 'fate' : null;
    if (FATE.test(k)) return 'fate';
    if (CHOICE.test(k)) return e.actor ? 'choice' : null;
    if (FIGHT.test(k) && !/^(beast|threat)/.test(k)) return e.actor && agents[e.actor] ? 'choice' : null;
    return null;
  }
  // The villager a moment is about: the actor, else the victim, else the first villager named in the text.
  function whoOf(e, agents) {
    const d = e.data || {};
    if (e.actor && agents[e.actor]) return e.actor;
    if (d.victim && agents[d.victim]) return d.victim;
    if (d.person && agents[d.person]) return d.person;
    const text = String(e.text || '');
    let best = null, at = 1e9;
    for (const n of Object.keys(agents)) { const p = text.indexOf(n); if (p >= 0 && p < at) { at = p; best = n; } }
    return best;
  }
  const FORM = { assembly: 'общее собрание', council: 'совет', ruler: 'один правитель' };
  // Where a moment happens. A death or a collapse follows the villager (a death's location is their home, the grave).
  const placeOf = e => {
    const d = e.data || {};
    return /^(death|hospital)$/.test(e.kind) ? null : e.location || d.house || d.home || d.location || d.target || null;
  };

  function create(score = () => 0) {
    const list = [];             // countdowns, sorted by k
    const busy = [];             // busy[k] = best event score of tick k (quiet stretches, camera pre-roll)
    const open = new Map();      // hero -> temptation episode {s, low, owner}
    const asked = new Map();     // "a|b" -> ticks when a spoke or wrote to b
    const lastDecoy = new Map(); // hero -> tick of their last decoy
    const props = new Map();     // "proposer|proposed to" -> tick of the proposal
    const overlaps = (a, b) => a.s <= b.k + AFTER && b.s <= a.k + AFTER;

    function push(c) {
      if (!c.real) { if (list.some(o => overlaps(o, c))) return; }
      else for (let j = list.length - 1; j >= 0 && list[j].k + AFTER >= c.s; j--) if (!list[j].real && overlaps(list[j], c)) list.splice(j, 1);
      list.push(c);
    }

    function add(ticks, k) {
      const t = ticks[k], A = t.view.agents, evs = t.events || [];
      let top = 0;
      for (const e of evs) top = Math.max(top, score(e.kind, e.data || {}));
      busy[k] = top;
      for (const [n, d] of Object.entries(t.decisions || {})) {
        const a = d.action || {}, to = (a.args || {}).to;
        if (to && /^(say|whisper|letter)$/.test(a.name)) { const key = n + '|' + to; if (!asked.has(key)) asked.set(key, []); asked.get(key).push(k); }
      }
      // thefts of this tick, by thief (the 'steal' event carries victim, success and who saw it)
      const thefts = new Map();
      for (const e of evs) if ((e.kind === 'steal' || e.kind === 'steal_attempt') && e.actor) {
        const prev = thefts.get(e.actor);
        if (!prev || (prev.kind !== 'steal' && e.kind === 'steal')) thefts.set(e.actor, e);
      }
      // temptations: hungry, nothing to eat, someone here has food
      const now = new Map();
      for (const [n, v] of Object.entries(A)) {
        if (v.status !== 'active' || v.asleep || v.satiety >= HUNGRY || food(v.inventory) > 0) continue;
        const owner = Object.keys(A).find(m => m !== n && A[m].status === 'active' && A[m].location === v.location && food(A[m].inventory) > 0);
        if (owner) now.set(n, owner);
      }
      for (const [n, owner] of now) {
        const ep = open.get(n), sat = A[n].satiety;
        if (ep) ep.low = Math.min(ep.low, sat); else open.set(n, { s: k, low: sat, owner });
      }
      const used = new Set();
      // A wait counts only from MIN_WAIT ticks, for thefts and decoys alike: nothing on the plaque (how long it ran,
      // how hungry) may tell them apart. Decoys are rarer per villager, which the plaque cannot show.
      const P = k > 0 ? ticks[k - 1].view.agents : A;
      for (const [hero, ep] of [...open]) {
        const theft = thefts.get(hero);
        if (!theft && now.has(hero)) continue;
        open.delete(hero);
        if (k - ep.s < MIN_WAIT) continue;
        if (theft) {
          // only food taken from a villager who was right there (not coins, not the treasury, not a chest far away)
          const d = theft.data || {}, victim = d.victim || (theft.to || []).find(m => m !== hero);
          const there = victim && P[victim] && P[hero] && P[victim].location === P[hero].location;
          if (there && (!d.item || isFood(d.item))) { used.add(theft); push({ type: 'temptation', s: Math.max(ep.s, k - LEAD), k, hero, owner: victim, ev: theft, sc: 9, real: true }); }
          continue;
        }
        if (k - (lastDecoy.has(hero) ? lastDecoy.get(hero) : -1e9) >= DECOY_GAP) {
          lastDecoy.set(hero, k);
          push({ type: 'temptation', s: Math.max(ep.s, k - LEAD), k, hero, owner: ep.owner, sc: 8, real: false });
        }
      }
      // the biggest moment of the tick, if it is one worth a countdown
      let cand = null;
      for (const e of evs) {
        if (used.has(e) || (used.size && /^(steal|steal_attempt|robbed|witness)$/.test(e.kind))) continue;
        const type = classify(e, A); if (!type) continue;
        const sc = score(e.kind, e.data || {});
        if (type !== 'polity' && sc < EV_MIN) continue;
        if (!cand || sc > cand.sc) cand = { type, s: Math.max(0, k - EV_LEAD), k, ev: e, sc, hero: whoOf(e, A), loc: placeOf(e), real: true };
      }
      if (cand && cand.s < k) push(cand);
      // proposals and their answers
      for (const e of evs) {
        if (e.kind === 'proposal' && e.actor && (e.to || [])[0]) props.set(e.actor + '|' + e.to[0], k);
        // the answer: actor = the one who answers, to = [the one who proposed]
        const key = e.actor && (e.to || [])[0] && e.to[0] + '|' + e.actor;
        if ((e.kind === 'wedding' || e.kind === 'proposal_refused') && key && props.has(key)) {
          const pk = props.get(key); props.delete(key);
          if (pk < k) push({ type: 'answer', s: Math.max(pk, k - LEAD), k, hero: e.actor, owner: e.to[0], ev: e, sc: 8, real: true });
        }
      }
    }

    // First index with list[j].k >= k (list is sorted by k).
    function from(k) { let lo = 0, hi = list.length; while (lo < hi) { const m = (lo + hi) >> 1; if (list[m].k < k) lo = m + 1; else hi = m; } return lo; }
    // The countdown on screen at tick i: {c, wait: true} while it runs (s <= i < k), then {c, wait: false} for AFTER
    // ticks from zero. What just happened keeps the screen for its AFTER ticks (a countdown that started meanwhile shows
    // up after it, with less time left); among waiting ones the first started keeps it, a real one beats a decoy.
    function at(i) {
      let wait = null, after = null;
      for (let j = from(i - AFTER); j < list.length && list[j].k <= i + LEAD + 1; j++) {
        const c = list[j];
        if (c.s <= i && i < c.k) { if (!wait || (c.real && !wait.real) || (c.real === wait.real && c.s < wait.s)) wait = c; }
        else if (c.k <= i && i <= c.k + AFTER) { if (!after || c.k > after.k) after = c; }
      }
      return after ? { c: after, wait: false } : wait ? { c: wait, wait: true } : null;
    }
    // Next tick in (i, i + h] whose events score at least min, else -1.
    function next(i, h, min) { for (let k = i + 1; k <= i + h && k < busy.length; k++) if (busy[k] >= min) return k; return -1; }
    // A countdown starting in (i, i + h]?
    function starts(i, h) { for (let j = from(i); j < list.length && list[j].k <= i + h + LEAD; j++) if (list[j].s > i && list[j].s <= i + h) return list[j]; return null; }
    // Did a speak or write to b in [k0, k1]? (a request before a theft is part of its build-up)
    const spoke = (a, b, k0, k1) => (asked.get(a + '|' + b) || []).some(k => k >= k0 && k <= k1);
    return { add, at, next, starts, spoke, busy: k => busy[k] || 0, list };
  }

  // Seconds left until zero: the rest of tick i, then every tick before k. dur(k) = seconds that tick lasts on screen.
  function eta(dur, i, frac, k) {
    if (i >= k) return 0;
    let s = dur(i) * (1 - Math.min(1, frac));
    for (let j = i + 1; j < k; j++) s += dur(j);
    return s;
  }

  // What happened at zero, from the log: {title, line}. names(item) -> Russian item name.
  function outcome(ticks, c, names = x => x) {
    const t = ticks[c.k], A = t.view.agents, P = ticks[Math.max(0, c.k - 1)].view.agents, evs = t.events || [];
    const list = xs => xs.join(', ');
    if (c.type === 'temptation' && c.real || c.ev && /^(steal|steal_attempt)$/.test(c.ev.kind)) {
      const e = c.ev, d = e.data || {}, victim = d.victim || c.owner, seen = [...(d.witnesses || []), ...(d.seen_by || [])];
      const title = e.kind === 'steal' && d.success !== false
        ? `🕵 Кража! ${e.actor} → ${d.item ? names(d.item) + ' ' : ''}у ${victim}`
        : `🕵 Кража сорвалась: ${e.actor} → ${victim}`;
      return { title, line: seen.length ? `👁 Видели: ${list([...new Set(seen)])}` : e.kind === 'steal' ? '🙈 Никто не заметил' : '' };
    }
    if (c.type === 'temptation') {
      const h = c.hero, o = c.owner, a = A[h] || {}, p = P[h] || {};
      const gave = evs.find(e => /^(give|gift|share|trade)$/.test(e.kind) && (e.to || []).includes(h));
      let title;
      // present tense and no gendered verbs: the viewer does not know who is he or she
      if (gave) title = gave.kind === 'trade' ? `🤝 ${h} выменивает еду` : `🎁 ${gave.actor || o} делится едой с ${h}`;
      else if (evs.some(e => e.kind === 'eat' && e.actor === h) || food(a.inventory) > 0) title = `🧺 ${h} находит себе еду`;
      else if (a.location !== p.location) title = `🚶 ${h} уходит ни с чем`;
      else if (A[o] && P[o] && A[o].location !== P[o].location) title = `🚶 ${o} уходит вместе с едой`;
      else if (a.asleep) title = `💤 ${h} засыпает на пустой желудок`;
      else title = `🤚 ${h} не трогает чужое`;
      return { title, line: `сытость ${a.satiety != null ? a.satiety : '?'}` };
    }
    if (c.type === 'answer') {
      return c.ev.kind === 'wedding' ? { title: `💍 Да! ${c.hero} и ${c.owner} теперь супруги`, line: '' }
        : { title: `💔 ${c.hero} отвечает ${c.owner} отказом`, line: '' };
    }
    const e = c.ev, d = e.data || {};
    if (e.kind === 'polity_leaders') {
      const votes = Object.entries(d.votes || {}).sort((x, y) => y[1] - x[1]).map(([n, v]) => `${n} ${v}`).join(' : ');
      return { title: `🏛 Казначей: ${d.keeper || list(d.rulers || [])}`, line: votes ? `голоса: ${votes}` : '' };
    }
    if (e.kind === 'polity_form') return { title: `🏛 Правление: ${FORM[d.form] || d.form || '?'}`, line: '' };
    if (/law_passed$/.test(e.kind)) return { title: '📜 Закон принят', line: '' };
    if (/law_failed$/.test(e.kind)) return { title: '📜 Закон не прошёл', line: '' };
    return { title: null, line: '' };   // the caller labels it like the director camera does
  }

  const api = { create, eta, outcome, food, classify, placeOf, AFTER, LEAD };
  if (typeof window !== 'undefined') window.Foresight = api;
  return api;
})();
if (typeof module !== 'undefined') module.exports = Foresight;
