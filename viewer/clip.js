// Highlight video ("🎞 Видео"): a vertical 720x1280 (9:16) clip of highlights for social media, rendered frame by
// frame, not recorded in real time: every frame the viewer's map is drawn for a synthetic time, cropped to 9:16 around
// the moment's villager and titled, WebCodecs encodes it and viewer/mp4_muxer.js writes an MP4. So the clip does not
// break when the tab is hidden, is built faster than it plays, and gets a soundtrack made for it (OfflineAudioContext:
// a beat, the cuts on the downbeat, a hit on every new moment).
// Shape: a hook (the strongest moment), 4.8 s per moment (fast up to it, slow motion and a punch-in on it, the
// villager's words typed out), then the totals of the period and a call to follow the village.
// A clip spec: { key, label, from, to, items: [{tick, title, line, who, kind, score}] } (a day: highlights.js, a week:
// viewer/reel.js). Uses the viewer globals ticks / i / frac / playing / userPaused / selected / lastPanel / header /
// color / tr / g and Camera / PixelMap; the viewer's loop() draws nothing while Clip.busy().
const Clip = (() => {
  const OW = 720, OH = 1280, FPS = 30, BEAT = 0.6;             // 100 BPM: every cut lands on a downbeat
  const INTRO = 4 * BEAT, MOMENT = 8 * BEAT, OUTRO = 6 * BEAT, SETTLE = 45;   // SETTLE: unrecorded frames per cut
  const SR = 48000;
  const ICON = { fire: '🔥', set_fire: '🔥', arson_seen: '🔥', house_burned: '🔥', fire_grows: '🔥', extinguish: '🧯',
    steal: '💰', robbed: '💰', steal_attempt: '👀', theft_report: '🚨', fight: '👊', death: '🪦', wedding: '💍',
    divorce: '💔', proposal: '💌', proposal_refused: '💔', elected: '🗳️', election: '🗳️', law_passed: '📜',
    default: '💸', debt_collected: '💸', debt_seized: '💸', pledge_forfeited: '💸', debt_claim: '💸', promise: '✍️',
    evicted: '🏚️', hospital: '🏥', sick: '🤒', starving: '😫', gift: '🎁', give: '🎁', trade: '🤝', lend: '🤝',
    crisis: '⚠️', drought: '☀️', rats: '🐀', crop_failed: '🌾', dice: '🎲', gossip: '🗣️', gossip_heard: '🗣️',
    overheard: '👂', whisper_seen: '👂', announcement: '📣', embezzlement_found: '🕵️', embezzle: '🕵️',
    land_bought: '🏡', land_sold: '🏡', inheritance: '📜', work_started: '🔨', project_done: '🏗️', god_treasure: '✨' };
  const VIOLENT = new Set(['fire', 'set_fire', 'arson_seen', 'house_burned', 'fight', 'steal', 'robbed', 'death']);
  // Totals for the end card: [label forms (1, 2-4, 5+), kinds]
  const STATS = [[['кража', 'кражи', 'краж'], ['steal']], [['пожар', 'пожара', 'пожаров'], ['fire', 'set_fire']],
    [['драка', 'драки', 'драк'], ['fight']], [['свадьба', 'свадьбы', 'свадеб'], ['wedding']],
    [['смерть', 'смерти', 'смертей'], ['death']], [['выселение', 'выселения', 'выселений'], ['evicted']],
    [['сделка', 'сделки', 'сделок'], ['trade']], [['подарок', 'подарка', 'подарков'], ['gift', 'give']]];

  const css = document.createElement('style');
  css.textContent = `
    #clip-box { position:fixed; inset:0; z-index:60; display:flex; align-items:center; justify-content:center;
      background:rgba(0,0,0,.72); font:14px/1.45 system-ui, sans-serif; color:#e8efe9; }
    #clip-box[hidden] { display:none; }
    #clip-box .card { background:#252c29; border-radius:12px; padding:14px; box-shadow:0 4px 16px rgba(0,0,0,.6);
      max-width:calc(100vw - 32px); display:flex; flex-direction:column; gap:8px; align-items:center; }
    #clip-box video, #clip-box canvas { height:min(64vh, 640px); max-width:100%; border-radius:8px; background:#000; }
    #clip-box .row { display:flex; gap:8px; flex-wrap:wrap; justify-content:center; }
    #clip-box a, #clip-box button { background:#34403b; color:#e8efe9; border:0; padding:7px 12px; border-radius:8px;
      cursor:pointer; text-decoration:none; font-weight:600; }
    #clip-box .main { background:#f2c14e; color:#1d2321; }
    #clip-box .muted { color:#9db0a4; font-size:12px; text-align:center; max-width:360px; }
    #clip-box .bar { width:100%; height:6px; background:#34403b; border-radius:3px; overflow:hidden; }
    #clip-box .bar i { display:block; height:100%; width:0; background:#f2c14e; }
    .hl-video { float:right; background:#34403b; color:#e8efe9; border:0; border-radius:12px; padding:2px 8px;
      font:600 11px system-ui; cursor:pointer; text-transform:none; margin-left:4px; }
  `;
  document.head.appendChild(css);
  const box = Object.assign(document.createElement('div'), { id: 'clip-box', hidden: true });
  const out = Object.assign(document.createElement('canvas'), { width: OW, height: OH });
  const o = out.getContext('2d');
  let job = null;
  const queue = [];
  const live = () => !!document.getElementById('live-badge');   // live.js is on the page: the server can keep the file

  const supported = () => !!(window.VideoEncoder && window.VideoFrame && window.Mp4Muxer);
  const clamp = (v, a = 0, b = 1) => Math.max(a, Math.min(b, v));
  const ease = u => 1 - (1 - clamp(u)) ** 3;
  const plural = (n, f) => f[n % 10 === 1 && n % 100 !== 11 ? 0 : n % 10 >= 2 && n % 10 <= 4 && (n % 100 < 10 || n % 100 >= 20) ? 1 : 2];
  const icon = it => ICON[it.kind] || '⭐';

  // ---------- drawing ----------
  function wrap(s, maxW, maxLines) {
    const words = String(s || '').split(/\s+/).filter(Boolean), lines = [];
    let cur = '';
    for (const w of words) {
      const t = cur ? cur + ' ' + w : w;
      if (o.measureText(t).width <= maxW || !cur) cur = t; else { lines.push(cur); cur = w; }
      if (lines.length === maxLines) break;
    }
    if (cur && lines.length < maxLines) lines.push(cur);
    if (lines.length === maxLines && words.join(' ').length > lines.join(' ').length)
      lines[maxLines - 1] = lines[maxLines - 1].replace(/\s*\S*$/, '').replace(/[.…,;:]+$/, '') + '…';
    return lines;
  }
  function text(lines, x, y, lh, fill, stroke = 7) {
    o.lineJoin = 'round'; o.lineWidth = stroke; o.strokeStyle = 'rgba(10,12,10,.9)'; o.fillStyle = fill;
    lines.forEach((l, k) => { if (stroke) o.strokeText(l, x, y + k * lh); o.fillText(l, x, y + k * lh); });
    return y + lines.length * lh;
  }
  function band(y0, y1, down, a = .9) {
    const gr = o.createLinearGradient(0, y0, 0, y1);
    gr.addColorStop(down ? 0 : 1, `rgba(14,18,16,${a})`); gr.addColorStop(down ? 1 : 0, 'rgba(14,18,16,0)');
    o.fillStyle = gr; o.fillRect(0, y0, OW, y1 - y0);
  }
  function pill(x, y, w, h, fill) {
    o.fillStyle = fill; o.beginPath();
    if (o.roundRect) o.roundRect(x, y, w, h, h / 2); else o.rect(x, y, w, h);
    o.fill();
  }
  // The map canvas cropped to 9:16 around (fx, fy) canvas pixels, zoomed in by z, shaken by (dx, dy).
  function map(cv, fx, fy, z = 1, dx = 0, dy = 0) {
    const cw = Math.min(cv.width, cv.height * 9 / 16) / z, ch = cw * 16 / 9;
    const sx = clamp(fx - cw / 2, 0, cv.width - cw), sy = clamp(fy - ch / 2, 0, cv.height - ch);
    o.imageSmoothingEnabled = false; o.fillStyle = '#2a3a24'; o.fillRect(0, 0, OW, OH);
    o.drawImage(cv, sx, sy, cw, ch, dx, dy, OW, OH);
  }
  const clock = t => `День ${t.view.day} · ${String(t.view.hour).padStart(2, '0')}:${String(t.view.minute || 0).padStart(2, '0')}`;

  function hook(J, el) {   // first seconds: the strongest moment, big
    const top = J.top.it, a = clamp(el / .35), s = 1.12 - .12 * ease(el / .5);
    band(0, 360, true); band(OH - 520, OH, false);
    o.save(); o.translate(OW / 2, OH / 2); o.scale(s, s); o.translate(-OW / 2, -OH / 2); o.globalAlpha = a;
    o.textAlign = 'center'; o.textBaseline = 'alphabetic';
    const pop = header && header.config.agents.length;   // the villager stays visible in the middle, words above and below
    o.font = '800 30px system-ui, sans-serif'; text([`AI VILLAGE · ${J.spec.label.toUpperCase()}`], OW / 2, 170, 36, '#f2c14e', 6);
    o.font = '700 34px system-ui, sans-serif';
    text(wrap(`${pop ? pop + ' жителей. ' : ''}Все они ИИ. Никакого сценария.`, OW - 120, 2), OW / 2, 226, 42, '#e8efe9', 6);
    o.font = '900 84px system-ui, sans-serif'; text([icon(top)], OW / 2, OH - 380, 90, '#fff', 0);
    o.font = '900 72px system-ui, sans-serif';
    text(wrap(top.title, OW - 90, 2), OW / 2, OH - 290, 80, '#ffffff', 10);
    o.restore(); o.globalAlpha = 1;
  }
  function overlay(J, s, k, u, el, t, quotes) {
    const n = J.shots.length;
    band(0, 340, true); band(OH - 470, OH, false, .92);
    o.textAlign = 'left'; o.textBaseline = 'alphabetic';
    o.font = '800 26px system-ui, sans-serif'; text(['AI VILLAGE'], 40, 62, 30, '#f2c14e', 5);
    o.textAlign = 'right'; o.font = '600 26px system-ui, sans-serif'; text([clock(t)], OW - 40, 62, 30, '#cfe3d6', 5);
    o.textAlign = 'left';
    const gw = (OW - 80 - (n - 1) * 8) / n;   // one progress segment per moment
    for (let j = 0; j < n; j++) {
      pill(40 + j * (gw + 8), 82, gw, 7, 'rgba(232,239,233,.3)');
      const f = j < k ? 1 : j === k ? u : 0;
      if (f > 0) pill(40 + j * (gw + 8), 82, Math.max(7, gw * f), 7, '#f2c14e');
    }
    const a = ease(el / .35), x = 40 - 60 * (1 - a);   // the title slides in on the cut
    o.globalAlpha = a; o.font = '900 58px system-ui, sans-serif';
    text(wrap(`${icon(s.it)} ${s.it.title}`, OW - 80, 3), x, 164, 66, '#ffffff', 10);
    o.globalAlpha = 1;
    o.font = '600 34px system-ui, sans-serif';
    const two = quotes.length > 1;
    let y = text(wrap(s.it.line, OW - 80, two ? 3 : 4), 40, OH - (two ? 470 : 380), 44, '#f4f7f5');
    quotes.forEach((q, n) => {   // the villagers' own words (else thoughts), typed out one after the other
      const from = .6 + n * 1.8; if (el <= from) return;
      o.font = '800 28px system-ui, sans-serif';
      const w = o.measureText(q.who).width + 28;
      pill(40, y + 8, w, 40, color[q.who] || '#9db0a4');
      o.fillStyle = '#121614'; o.fillText(q.who, 54, y + 37);
      o.font = `italic 600 ${two ? 30 : 32}px system-ui, sans-serif`;
      const room = wrap(q.text, OW - 80, two ? 2 : 4).length;   // lines the whole quote takes, so the next one does not jump
      text(wrap(q.text.slice(0, Math.floor((el - from) * 48)), OW - 80, room), 40, y + 88, 40, '#fff6d6');
      y += 68 + room * 40;
    });
  }

  function outro(J, el) {
    const a = clamp(el / .4);
    o.fillStyle = `rgba(14,18,16,${.8 * a})`; o.fillRect(0, 0, OW, OH);
    o.globalAlpha = a; o.textAlign = 'center'; o.textBaseline = 'alphabetic';
    o.font = '800 30px system-ui, sans-serif'; text([`AI VILLAGE · ${J.spec.label.toUpperCase()}`], OW / 2, 250, 36, '#f2c14e', 6);
    o.font = '900 60px system-ui, sans-serif'; text([J.spec.days > 1 ? 'Итоги недели' : 'Итоги дня'], OW / 2, 330, 66, '#fff', 8);
    const st = J.stats;
    st.top.forEach(([n, label], k) => {   // up to 4 big numbers, 2 x 2, popping in one after another
      const p = ease((el - .25 - k * .18) / .3); if (p <= 0) return;
      const cx = OW / 2 + (k % 2 ? 150 : -150), cy = 470 + Math.floor(k / 2) * 190;
      o.globalAlpha = a * p;
      o.font = '900 96px system-ui, sans-serif'; text([String(n)], cx, cy, 96, '#f2c14e', 8);
      o.font = '700 32px system-ui, sans-serif'; text([label], cx, cy + 48, 36, '#e8efe9', 6);
    });
    o.globalAlpha = a;
    let y = 470 + Math.ceil(st.top.length / 2) * 190 + (st.top.length ? 0 : -60);
    if (!st.top.length) { o.font = '700 40px system-ui, sans-serif'; y = text(['Тихо. Слишком тихо…'], OW / 2, y, 48, '#e8efe9', 6); }
    if (st.rich) { o.font = '600 32px system-ui, sans-serif'; y = text(wrap(`💰 Богаче всех: ${st.rich}`, OW - 100, 2), OW / 2, y + 20, 42, '#cfe3d6', 6); }
    const p = ease((el - 1.2) / .4);
    o.globalAlpha = a * p; o.font = '900 46px system-ui, sans-serif';
    text(wrap('Что будет дальше?', OW - 80, 2), OW / 2, OH - 260, 54, '#ffffff', 8);
    o.font = '700 32px system-ui, sans-serif'; text(['Подписывайтесь 👀'], OW / 2, OH - 200, 40, '#f2c14e', 6);
    o.globalAlpha = 1;
  }

  // ---------- what goes into a clip ----------
  // Latest words (or else thought) of the moment's villager up to the tick on screen.
  function quoteOf(who, upto, from) {
    if (!who) return null;
    for (let k = upto; k >= from; k--) {
      const d = ((ticks[k] || {}).decisions || {})[who]; if (!d) continue;
      const act = d.action || {}, args = act.args || {};
      const said = d.say || (act.name === 'say' || act.name === 'whisper') && args.text;
      if (said) return { who, raw: said, text: '«' + tr(said) + '»' };
      if (d.thought) return { who, raw: d.thought, text: '💭 ' + tr(d.thought) };
    }
    return null;
  }
  function plan(items) {
    const per = ticks.length ? 60 / (ticks[0].view.tick_minutes || 60) : 1;   // ticks per game hour
    const shots = [];
    for (const it of items) {
      const k = ticks.findIndex(t => t.tick === it.tick); if (k < 0) continue;
      const a = Math.max(0, k - Math.round(per * .75)), b = Math.min(ticks.length - 1, k + Math.max(1, Math.round(per * .5)));
      if (b <= a) continue;
      shots.push({ it, a, b, k, m: clamp((k - a + .5) / (b - a), .05, .95) });
    }
    return shots.sort((p, q) => p.k - q.k);
  }
  // Time in a shot (0..1) -> game progress (0..1): quick up to the moment, slow motion on it, quick after.
  function ramp(u, m) {
    const g1 = clamp(m - .1, .02, .98), g2 = clamp(m + .1, g1, .99), T = [0, .3, .78, 1], G = [0, g1, g2, 1];
    for (let j = 1; j < 4; j++) if (u <= T[j]) return G[j - 1] + (G[j] - G[j - 1]) * (u - T[j - 1]) / (T[j] - T[j - 1]);
    return 1;
  }
  function stats(spec, shots) {
    const lo = spec.from || ticks[shots[0].a].view.day, hi = spec.to || ticks[shots[shots.length - 1].b].view.day;
    const count = {}; let last = null;
    for (const t of ticks) {
      if (t.view.day < lo || t.view.day > hi) continue;
      last = t;
      for (const e of t.events || []) count[e.kind] = (count[e.kind] || 0) + 1;
    }
    const top = STATS.map(([f, kinds]) => [kinds.reduce((s, k) => s + (count[k] || 0), 0), f])
      .filter(([n]) => n > 0).slice(0, 4).map(([n, f]) => [n, plural(n, f)]);
    let rich = null;
    if (last) {
      const alive = Object.entries(last.view.agents).filter(([, v]) => v.status !== 'dead');
      const best = alive.sort((p, q) => (q[1].coins || 0) - (p[1].coins || 0))[0];
      if (best && best[1].coins > 0) rich = `${best[0]}, ${best[1].coins} ${plural(best[1].coins, ['монета', 'монеты', 'монет'])}`;
    }
    return { top, rich };
  }

  // ---------- soundtrack ----------
  async function soundtrack(J) {
    const Off = window.OfflineAudioContext || window.webkitOfflineAudioContext;
    if (!Off) return null;
    const total = J.total, ac = new Off(2, Math.ceil(total * SR), SR);
    const comp = ac.createDynamicsCompressor(), master = ac.createGain();
    master.gain.value = .8; master.connect(comp); comp.connect(ac.destination);
    const noise = ac.createBuffer(1, SR, SR), nd = noise.getChannelData(0);
    for (let k = 0; k < nd.length; k++) nd[k] = Math.random() * 2 - 1;
    const env = (gn, t, a, peak, d) => { gn.gain.setValueAtTime(0, t); gn.gain.linearRampToValueAtTime(peak, t + a); gn.gain.exponentialRampToValueAtTime(.0001, t + a + d); };
    const osc = (type, f, t, dur, peak, a = .005, to) => {
      const s = ac.createOscillator(), gn = ac.createGain();
      s.type = type; s.frequency.setValueAtTime(f, t); if (to) s.frequency.exponentialRampToValueAtTime(to, t + dur);
      env(gn, t, a, peak, dur); s.connect(gn); gn.connect(master); s.start(t); s.stop(t + a + dur + .05);
    };
    const hiss = (t, dur, peak, type, f, f2) => {
      const s = ac.createBufferSource(), fl = ac.createBiquadFilter(), gn = ac.createGain();
      s.buffer = noise; s.loop = true; fl.type = type; fl.frequency.setValueAtTime(f, t);
      if (f2) fl.frequency.exponentialRampToValueAtTime(f2, t + dur);
      if (f2) { gn.gain.setValueAtTime(.0001, t); gn.gain.exponentialRampToValueAtTime(peak, t + dur); gn.gain.linearRampToValueAtTime(0, t + dur + .02); }
      else env(gn, t, .002, peak, dur);
      s.connect(fl); fl.connect(gn); gn.connect(master); s.start(t); s.stop(t + dur + .05);
    };
    const hz = m => 440 * 2 ** ((m - 69) / 12);
    const CH = [[57, 60, 64], [53, 57, 60], [48, 52, 55], [55, 59, 62]];   // Am F C G
    const end = INTRO + J.shots.length * MOMENT, bars = Math.ceil(total / (4 * BEAT));
    for (let b = 0; b < bars; b++) {   // pad: a chord per bar
      const t = b * 4 * BEAT, ch = CH[b % 4];
      for (const m of ch) {
        const s = ac.createOscillator(), fl = ac.createBiquadFilter(), gn = ac.createGain();
        s.type = 'sawtooth'; s.frequency.value = hz(m); s.detune.value = (m % 3 - 1) * 6;
        fl.type = 'lowpass'; fl.frequency.value = t >= end ? 900 : 1400;
        gn.gain.setValueAtTime(0, t); gn.gain.linearRampToValueAtTime(.035, t + .25); gn.gain.setValueAtTime(.035, t + 4 * BEAT - .2);
        gn.gain.linearRampToValueAtTime(0, t + 4 * BEAT + .05);
        s.connect(fl); fl.connect(gn); gn.connect(master); s.start(t); s.stop(t + 4 * BEAT + .1);
      }
    }
    for (let bt = 0; bt * BEAT < total - .01; bt++) {
      const t = bt * BEAT, root = CH[Math.floor(bt / 4) % 4][0] - 24;
      if (t < INTRO) { hiss(t + BEAT / 2, .05, .05, 'highpass', 7000); continue; }   // the hook: hats only, then the drop
      if (t >= end) continue;                                                        // the end card: pad only
      osc('sine', 130, t, .28, .9, .002, 42);                                        // kick
      if (bt % 2) hiss(t, .12, .12, 'bandpass', 1800);                               // snare-ish on 2 and 4
      hiss(t + BEAT / 2, .05, .07, 'highpass', 7000);                               // hat
      osc('triangle', hz(root), t, BEAT * .8, .28, .01);                            // bass
      osc('triangle', hz(root + 12), t + BEAT / 2, BEAT * .4, .12, .01);
    }
    for (let k = 0; k <= J.shots.length; k++) {   // every cut: a riser into it and a hit on it
      const t = INTRO + k * MOMENT;
      if (t > total - .1) break;
      hiss(t - BEAT * 2, BEAT * 2, .09, 'bandpass', 400, 6000);
      osc('sine', 70, t, 1.1, .7, .002, 38); hiss(t, .5, .16, 'lowpass', 3000);
    }
    return ac.startRendering();
  }
  async function encodeAudio(buf, muxer, codec) {
    let err = null;
    const enc = new AudioEncoder({ output: (c, meta) => muxer.addAudioChunk(c, meta), error: e => { err = e; } });
    enc.configure({ codec, sampleRate: SR, numberOfChannels: 2, bitrate: 128000 });
    const L = buf.getChannelData(0), R = buf.getChannelData(1), N = 4800;
    for (let s = 0; s < buf.length; s += N) {
      const n = Math.min(N, buf.length - s), data = new Float32Array(n * 2);
      data.set(L.subarray(s, s + n), 0); data.set(R.subarray(s, s + n), n);
      const ad = new AudioData({ format: 'f32-planar', sampleRate: SR, numberOfFrames: n, numberOfChannels: 2, timestamp: Math.round(s / SR * 1e6), data });
      enc.encode(ad); ad.close();
    }
    await enc.flush(); enc.close();
    if (err) throw err;
  }
  async function pickCodecs() {
    let video = null, audio = null;
    for (const [codec, mux] of [['avc1.640028', 'avc'], ['avc1.4d0028', 'avc'], ['avc1.42e028', 'avc'], ['avc1.42001f', 'avc'],
                                ['vp09.00.40.08', 'vp9'], ['av01.0.08M.08', 'av1']]) {
      const cfg = { codec, width: OW, height: OH, bitrate: 6e6, framerate: FPS, ...(mux === 'avc' ? { avc: { format: 'avc' } } : {}) };
      try { if ((await VideoEncoder.isConfigSupported(cfg)).supported) { video = { cfg, mux }; break; } } catch (e) {}
    }
    if (window.AudioEncoder && window.AudioData)
      for (const [codec, mux] of [['mp4a.40.2', 'aac'], ['opus', 'opus']]) {
        try { if ((await AudioEncoder.isConfigSupported({ codec, sampleRate: SR, numberOfChannels: 2, bitrate: 128000 })).supported) { audio = { codec, mux }; break; } } catch (e) {}
      }
    return { video, audio };
  }

  // ---------- rendering ----------
  const idle = () => new Promise(r => { const ch = new MessageChannel(); ch.port1.onmessage = () => r(); ch.port2.postMessage(0); });   // not throttled in hidden tabs

  function cue(J, s) {   // jump to a shot and let the camera settle on it before anything is recorded
    if (s.it.who && s.it.who.length) { Camera.setDirector(false, false); selected = s.it.who[0]; }
    else { selected = null; Camera.setDirector(true, false); }
    lastPanel = -1;
    const at = selected ? s.a : s.k;
    for (let f = 0; f < SETTLE; f++) draw(J, at, 1);
  }
  function draw(J, k, fr) {   // the viewer's map at tick k, frac fr, one frame later than the last
    J.time += 1000 / FPS;
    i = k; frac = fr;
    const t = ticks[k], prev = ticks[Math.max(0, k - 1)];
    PixelMap.draw(g, { t, prev, frac: fr, selected, time: J.time, tr, hourSec: J.hourSec });
    return t;
  }
  function focus(cv) {
    const spot = selected && PixelMap.where && PixelMap.where(selected);
    return spot ? Camera.toScreen(spot[0], spot[1]) : [cv.width / 2, cv.height / 2];
  }
  function frame(J, f) {
    const cv = document.getElementById('c'), el = f / FPS, n = J.shots.length;
    if (el < INTRO) {   // hook: the strongest moment in slow motion
      const s = J.top;
      if (J.cur !== 'hook') { J.cur = 'hook'; cue(J, s); }
      const p = clamp(s.m - .12 + .14 * el / INTRO) * (s.b - s.a), ki = Math.min(s.b, s.a + Math.floor(p));
      const t = draw(J, ki, ki === s.b ? 1 : Math.max(.001, p - Math.floor(p)));
      const [fx, fy] = focus(cv);
      map(cv, fx, fy, 1.5 + .12 * el / INTRO);
      hook(J, el);
      return t;
    }
    if (el < INTRO + n * MOMENT) {
      const k = Math.min(n - 1, Math.floor((el - INTRO) / MOMENT)), s = J.shots[k], local = el - INTRO - k * MOMENT, u = local / MOMENT;
      if (J.cur !== k) { J.cur = k; cue(J, s); J.fx = null; }
      const p = ramp(u, s.m) * (s.b - s.a), ki = Math.min(s.b, s.a + Math.floor(p));
      const t = draw(J, ki, ki === s.b ? 1 : Math.max(.001, p - Math.floor(p)));
      const [fx, fy] = focus(cv);
      if (J.fx === null) { J.fx = fx; J.fy = fy; }
      const fe = 1 - Math.exp(-5 / FPS); J.fx += (fx - J.fx) * fe; J.fy += (fy - J.fy) * fe;
      const z = 1.3 + .06 * u + .3 * ease((u - .26) / .08);                       // Ken Burns drift + punch-in on the moment
      const hit = u - .3, shake = VIOLENT.has(s.it.kind) && hit > 0 && hit < .14 ? 9 * (1 - hit / .14) : 0;
      map(cv, J.fx, J.fy, z, shake * Math.sin(f * 2.1), shake * Math.cos(f * 2.9));
      overlay(J, s, k, u, local, t, (s.it.who || []).slice(0, 2).map(w => quoteOf(w, ki, s.a)).filter(Boolean));
      if (local < .14) { o.fillStyle = `rgba(255,255,255,${.75 * (1 - local / .14)})`; o.fillRect(0, 0, OW, OH); }   // flash cut
      return t;
    }
    // end card over the village at the last moment
    const s = J.shots[n - 1];
    if (J.cur !== 'end') { J.cur = 'end'; selected = null; Camera.setDirector(false, false); }
    const t = draw(J, s.b, 1);
    map(cv, J.fx ?? cv.width / 2, J.fy ?? cv.height / 2, 1.3);
    outro(J, el - INTRO - n * MOMENT);
    return t;
  }

  function progress(J, f, what) {
    const bar = box.querySelector('.bar i'), pr = box.querySelector('#clip-pr');
    if (bar) bar.style.width = Math.round(100 * f) + '%';
    if (pr) pr.textContent = what;
  }

  // Builds the clip; resolves to {blob, name, url, seconds} or null (cancelled / impossible).
  function make(spec, opts = {}) {
    if (job) return new Promise(res => queue.push(() => make(spec, opts).then(res)));
    if (!supported()) { if (!opts.auto) message('Этот браузер не умеет собирать видео. Откройте деревню в свежем Chrome или Edge.'); return Promise.resolve(null); }
    const shots = plan(spec.items || []);
    if (!shots.length) { if (!opts.auto) message('Моменты ещё не загружены в окно просмотра.'); return Promise.resolve(null); }
    const top = shots.slice().sort((p, q) => (q.it.score || 0) - (p.it.score || 0) || p.k - q.k)[0];
    const per = 60 / (ticks[0].view.tick_minutes || 60);
    const J = job = { spec, shots, top, total: INTRO + shots.length * MOMENT + OUTRO, cancelled: false, time: performance.now(),
      hourSec: MOMENT / ((shots[0].b - shots[0].a) / per) * .6, cur: null, fx: null, fy: null,
      saved: { i, frac, playing, userPaused, selected, dir: Camera.directorOn() } };
    J.stats = stats(spec, shots);
    playing = false; userPaused = true;   // the clip drives i / frac itself; live ticks keep arriving
    box.hidden = false;
    box.innerHTML = `<div class="card"><b>🎞 Собираю ролик: ${spec.label}${opts.auto ? ' (автоматически)' : ''}</b></div>`;
    const card = box.querySelector('.card');
    card.append(out);
    card.insertAdjacentHTML('beforeend', `<div class="bar"><i></i></div><span class="muted" id="clip-pr">готовлю музыку…</span>
      <span class="muted">Собирается быстрее, чем идёт; вкладку можно свернуть.</span><button id="clip-stop">Отменить</button>`);
    box.querySelector('#clip-stop').onclick = () => { J.cancelled = true; };
    return run(J).catch(e => { J.error = e; console.error(e); return null; }).then(res => {
      restore(J); job = null;
      if (J.cancelled) box.hidden = true;
      else if (!res) message('Не получилось собрать ролик: ' + (J.error && J.error.message || 'неизвестная ошибка'));
      else done(J, res, opts);
      const next = queue.shift(); if (next) setTimeout(next, 0);
      return res;
    });
  }
  async function run(J) {
    const { video, audio } = await pickCodecs();
    if (!video) throw new Error('нет подходящего видеокодека');
    const muxer = new Mp4Muxer.Muxer({ target: new Mp4Muxer.ArrayBufferTarget(), fastStart: 'in-memory', firstTimestampBehavior: 'offset',
      video: { codec: video.mux, width: OW, height: OH, frameRate: FPS },
      ...(audio ? { audio: { codec: audio.mux, numberOfChannels: 2, sampleRate: SR } } : {}) });
    if (audio) try { const buf = await soundtrack(J); if (buf) await encodeAudio(buf, muxer, audio.codec); } catch (e) { console.warn('clip sound', e); }
    let err = null;
    const enc = new VideoEncoder({ output: (c, meta) => muxer.addVideoChunk(c, meta), error: e => { err = e; } });
    enc.configure(video.cfg);
    const N = Math.round(J.total * FPS);
    for (let f = 0; f < N; f++) {
      if (J.cancelled) { enc.close(); return null; }
      if (err) throw err;
      frame(J, f);
      const vf = new VideoFrame(out, { timestamp: Math.round(f * 1e6 / FPS), duration: Math.round(1e6 / FPS) });
      enc.encode(vf, { keyFrame: f % (FPS * 2) === 0 }); vf.close();
      while (enc.encodeQueueSize > 4) await idle();
      if (f % 4 === 0) { progress(J, f / N, `${Math.round(100 * f / N)}% · ролик ${Math.round(J.total)} с`); await idle(); }
    }
    await enc.flush(); enc.close();
    if (err) throw err;
    muxer.finalize();
    const s = J.spec, blob = new Blob([muxer.target.buffer], { type: 'video/mp4' });
    return { blob, name: `aivillage-${s.key}.mp4`, url: URL.createObjectURL(blob), seconds: J.total };
  }
  function restore(J) {
    const s = J.saved;
    i = s.i; frac = s.frac; selected = s.selected; lastPanel = -1; Camera.setDirector(s.dir, false);
    playing = s.playing; userPaused = s.userPaused;
  }
  async function done(J, res, opts) {
    window.lastClip = res;   // for tests and the console
    let saved = '';
    if (live()) try {   // the server keeps every clip in AIVillage/videos
      const r = await fetch('/api/clips/' + J.spec.key, { method: 'POST', headers: { 'Content-Type': 'video/mp4' }, body: res.blob });
      if (r.ok) { const j = await r.json(); saved = `Сохранено в папку ${j.folder}: ${j.file}`; res.saved = j; }
    } catch (e) { /* no server: the download button is enough */ }
    const file = new File([res.blob], res.name, { type: 'video/mp4' });
    box.hidden = false;
    box.innerHTML = `<div class="card"><b>🎞 Ролик готов: ${J.spec.label}</b><video src="${res.url}" controls ${opts.auto ? '' : 'autoplay'} playsinline></video>
      <div class="row"><a class="main" href="${res.url}" download="${res.name}">⬇ Скачать</a><button id="clip-share" hidden>Поделиться</button>
      <button id="clip-close">Закрыть</button></div>
      <span class="muted">MP4, вертикальный 9:16, ${Math.round(res.seconds)} с, со своей музыкой. ${saved}</span></div>`;
    const share = box.querySelector('#clip-share');
    if (navigator.canShare && navigator.canShare({ files: [file] })) {
      share.hidden = false; share.onclick = () => navigator.share({ files: [file], title: `AI Village, ${J.spec.label}` }).catch(() => {});
    }
    box.querySelector('#clip-close').onclick = () => { box.hidden = true; };
  }
  function message(s) {
    box.hidden = false;
    box.innerHTML = `<div class="card"><span>${s}</span><button id="clip-close">Понятно</button></div>`;
    box.querySelector('#clip-close').onclick = () => { box.hidden = true; };
  }

  // A "🎞 Видео" button for a day header of the highlights panel. items: [{tick, title, line, who, kind, score}].
  function button(spec, textContent = '🎞 Видео') {
    const b = Object.assign(document.createElement('button'), { className: 'hl-video', textContent,
      title: 'вертикальный ролик из хайлайтов (9:16, для соцсетей)' });
    b.onclick = e => { e.stopPropagation(); const p = document.getElementById('hl-panel'); if (p) p.hidden = true; make(spec); };
    return b;
  }
  const record = dayRec => make({ key: `den-${dayRec.day}`, label: `День ${dayRec.day}`, from: dayRec.day, to: dayRec.day, days: 1, items: dayRec.items });

  if (document.body) document.body.append(box); else window.addEventListener('DOMContentLoaded', () => document.body.append(box));
  return { make, record, button, supported, busy: () => !!job, canvas: out, plan, ramp };
})();
window.Clip = Clip;   // index.html's loop() and efir.js check window.Clip.busy()
