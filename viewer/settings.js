// Settings panel (live mode only, injected by aivillage/server.py): API keys, provider and model.
// Keys are saved by the server into <home>/settings.json on this computer; the page only ever
// sees masked keys ("sk-…abcd"). A new key applies from the next model call, no restart needed.
(function () {
  const css = document.createElement('style');
  css.textContent = `
    #st-toggle.own { position:fixed; left:8px; top:38px; z-index:30; background:#34403b; color:#e8efe9; border:0;
      border-radius:20px; padding:7px 12px; font:600 13px system-ui, sans-serif; cursor:pointer; }
    #st { position:fixed; left:8px; top:78px; z-index:32; width:340px; max-width:calc(100vw - 24px);
      max-height:calc(100vh - 140px); overflow:auto; background:#262e2b; color:#e8efe9; border-radius:10px;
      padding:12px; font:13px system-ui, sans-serif; box-shadow:0 6px 24px rgba(0,0,0,.45); display:none; }
    #st h3 { margin:0 0 8px; font-size:15px; }
    #st label { display:block; margin:10px 0 3px; color:#9db0a4; font-size:12px; }
    #st input, #st select { width:100%; box-sizing:border-box; background:#1d2321; color:#e8efe9;
      border:1px solid #4a5650; border-radius:6px; padding:6px 8px; font:13px system-ui, sans-serif; }
    #st .saved { font-size:12px; color:#9db0a4; margin-top:3px; }
    #st .saved a { color:#f2c14e; cursor:pointer; margin-left:6px; }
    #st .hint { font-size:12px; color:#9db0a4; margin-top:8px; line-height:1.4; }
    #st .row { display:flex; gap:6px; margin-top:12px; }
    #st button.b { flex:1; border:0; border-radius:6px; padding:8px; font:600 13px system-ui, sans-serif; cursor:pointer; }
    #st .save { background:#76b041; color:#1d2321; }
    #st .test { background:#3d4a44; color:#e8efe9; }
    #st .msg { font-size:12px; min-height:16px; margin-top:8px; line-height:1.4; }
    #st .ok { color:#9be38a; } #st .bad { color:#ff8a72; }
  `;
  document.head.appendChild(css);

  const btn = document.createElement('button');
  btn.id = 'st-toggle';
  btn.textContent = '⚙️ Настройки';
  const box = document.createElement('div');
  box.id = 'st';
  box.innerHTML = `
    <h3>Ключи и модель</h3>
    <label>Через кого думают жители</label>
    <select id="st-provider">
      <option value="auto">Сам выберу: модели OpenAI через OpenAI (если есть его ключ), остальные через OpenRouter</option>
      <option value="openai">Только OpenAI напрямую</option>
      <option value="openrouter">Только OpenRouter</option>
    </select>
    <label>Ключ OpenAI (начинается с sk-)</label>
    <input id="st-openai" type="password" autocomplete="off" placeholder="вставьте новый ключ">
    <div class="saved" id="st-openai-saved"></div>
    <label>Ключ OpenRouter (начинается с sk-or-)</label>
    <input id="st-openrouter" type="password" autocomplete="off" placeholder="вставьте новый ключ">
    <div class="saved" id="st-openrouter-saved"></div>
    <label>Модель</label>
    <input id="st-model" type="text" autocomplete="off">
    <label>Тариф OpenAI</label>
    <select id="st-tier">
      <option value="default">Обычный: ход ~3 с</option>
      <option value="flex">Экономный: в 2 раза дешевле, ход думает дольше (~10 с вместо ~3 с)</option>
    </select>
    <label>Сколько жителей думают одновременно (для OpenAI)</label>
    <input id="st-parallel" type="number" min="1" max="64" placeholder="16">
    <div class="row">
      <button class="b save" id="st-save">Сохранить</button>
      <button class="b test" id="st-test">Проверить ключ</button>
    </div>
    <div class="msg" id="st-msg"></div>
    <div class="hint">Ключи хранятся только на этом компьютере и не попадают в логи.
      Новый ключ и тариф начинают работать сразу, перезапуск не нужен. Модель и одновременность
      применятся со следующего запуска деревни.</div>`;
  // Joins the top-left button row of report.js when it is there (same look), else stands alone.
  const bar = document.getElementById('rp-bar');
  if (bar) { bar.appendChild(btn); bar.style.flexWrap = 'wrap'; bar.style.maxWidth = 'calc(100vw - 16px)'; } else { btn.className = 'own'; document.body.appendChild(btn); }
  document.body.appendChild(box);

  const $ = id => document.getElementById(id);
  const msg = (text, cls) => { $('st-msg').textContent = text; $('st-msg').className = 'msg ' + (cls || ''); };
  const clear = [];

  function savedLine(id, k, info) {
    const el = $(id);
    el.textContent = '';
    if (!info || !info.set) { el.textContent = 'не задан'; return; }
    el.textContent = 'сохранён: ' + info.masked + (info.from === 'env' ? ' (из настроек окружения)' : '');
    if (info.from === 'file') {
      const a = document.createElement('a');
      a.textContent = 'удалить';
      a.onclick = () => { clear.push(k); el.textContent = 'будет удалён после «Сохранить»'; };
      el.appendChild(a);
    }
  }

  function fill(s) {
    $('st-provider').value = s.provider || 'auto';
    $('st-model').value = s.model || '';
    $('st-model').placeholder = s.default_model || '';
    $('st-parallel').value = s.parallel || '';
    $('st-tier').value = s.openai_tier || 'default';
    $('st-openai').value = $('st-openrouter').value = '';
    clear.length = 0;
    savedLine('st-openai-saved', 'openai_key', s.openai_key);
    savedLine('st-openrouter-saved', 'openrouter_key', s.openrouter_key);
  }

  async function call(path, body) {
    const r = await fetch(path, body === undefined ? {} :
      { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.detail || ('ошибка ' + r.status));
    return data;
  }

  async function open() {
    box.style.display = box.style.display === 'block' ? 'none' : 'block';
    if (box.style.display !== 'block') return;
    msg('');
    try { fill(await call('/api/settings')); } catch (e) { msg('Не удалось загрузить настройки: ' + e.message, 'bad'); }
  }

  async function save() {
    const oa = $('st-openai').value.trim(), or = $('st-openrouter').value.trim();
    if (oa && (!oa.startsWith('sk-') || oa.startsWith('sk-or-'))) return msg('Ключ OpenAI начинается с sk- (но не с sk-or-).', 'bad');
    if (or && !or.startsWith('sk-or-')) return msg('Ключ OpenRouter начинается с sk-or-.', 'bad');
    const body = { provider: $('st-provider').value, model: $('st-model').value.trim(),
      parallel: $('st-parallel').value.trim(), openai_tier: $('st-tier').value, openai_key: oa, openrouter_key: or, clear: clear.slice() };
    try { fill(await call('/api/settings', body)); msg('Сохранено.', 'ok'); return true; }
    catch (e) { msg('Не сохранилось: ' + e.message, 'bad'); return false; }
  }

  async function test() {
    if (($('st-openai').value.trim() || $('st-openrouter').value.trim() || clear.length) && !(await save())) return;
    msg('Проверяю, отправляю модели короткий вопрос…');
    try {
      const r = await call('/api/settings/check', {});
      if (r.ok) {
        const who = r.provider === 'openai' ? 'OpenAI напрямую' : 'OpenRouter';
        msg('Работает: ответила ' + r.model + ' через ' + who + '.' + (r.note ? ' OpenAI не ответил: ' + r.note : ''), 'ok');
      } else {
        msg('Не работает: ' + (r.error || 'нет ответа'), 'bad');
      }
    } catch (e) { msg('Проверка не удалась: ' + e.message, 'bad'); }
  }

  btn.onclick = open;
  $('st-save').onclick = save;
  $('st-test').onclick = test;
})();
