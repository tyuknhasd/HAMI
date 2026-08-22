const token = localStorage.getItem('hami_token');
if (!token) window.location.href = '/';

const authHeaders = { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' };

const PROTOCOL_LABEL = {
  vless_ws: 'VLESS · WebSocket',
  vless_reality: 'VLESS · Reality',
  vless_xhttp: 'VLESS · XHTTP',
  trojan_ws: 'Trojan · WebSocket',
  trojan_reality: 'Trojan · Reality',
  shadowsocks: 'Shadowsocks',
};

function logout() { localStorage.removeItem('hami_token'); window.location.href = '/'; }

async function api(path, opts = {}) {
  const res = await fetch(path, { ...opts, headers: authHeaders });
  if (res.status === 401) { logout(); throw new Error('unauthorized'); }
  if (!res.ok) { const t = await res.text(); throw new Error(t); }
  return res.status === 204 ? null : res.json();
}

function toast(msg) {
  const el = document.createElement('div');
  el.className = 'toast';
  el.textContent = msg;
  document.getElementById('toast-root').appendChild(el);
  setTimeout(() => el.remove(), 2600);
}

function fmtGB(bytes) { return (bytes / (1024 ** 3)).toFixed(2) + ' GB'; }

/* ---------------- Navigation ---------------- */
document.getElementById('lang-btn').textContent = t('lang_toggle');

const NAV_LABEL_KEY = { overview: 'overview', links: 'links', speed: 'speed', mtproto: 'mtproto', settings: 'settings' };
document.querySelectorAll('.nav-item[data-view]').forEach(el => {
  el.textContent = t(NAV_LABEL_KEY[el.dataset.view]);
  el.addEventListener('click', () => switchView(el.dataset.view));
});
document.querySelector('.nav-item[onclick="logout()"]').textContent = t('log_out');
document.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = t(el.dataset.i18n); });

function switchView(view) {
  document.querySelectorAll('.nav-item[data-view]').forEach(el => el.classList.toggle('active', el.dataset.view === view));
  document.querySelectorAll('main section').forEach(s => s.style.display = 'none');
  document.getElementById(`view-${view}`).style.display = 'block';
  document.getElementById('view-title').textContent = t(view);

  const actions = document.getElementById('topbar-actions');
  actions.innerHTML = '';
  if (view === 'links') {
    const b = document.createElement('button');
    b.className = 'btn btn-primary'; b.textContent = t('new_link');
    b.onclick = openCreateLinkModal;
    actions.appendChild(b);
    loadLinks();
  } else if (view === 'mtproto') {
    const b = document.createElement('button');
    b.className = 'btn btn-violet'; b.textContent = t('new_mtproto');
    b.onclick = createMtproto;
    actions.appendChild(b);
    loadMtproto();
  } else if (view === 'speed') {
    loadSpeedPanel();
  } else if (view === 'settings') {
    loadSettingsPanel();
  } else {
    loadOverview();
  }
}

/* ---------------- Overview ---------------- */
async function loadOverview() {
  const stats = await api('/api/stats/overview');
  document.getElementById('stat-total').textContent = stats.total_links;
  document.getElementById('stat-active').textContent = stats.active_links;
  document.getElementById('stat-used').textContent = stats.total_traffic_used_gb + ' GB';
  document.getElementById('stat-today').textContent = stats.total_traffic_today_gb + ' GB';

  const series = await api('/api/stats/timeseries?days=7');
  drawBarChart(document.getElementById('chart'), series);
}

function drawBarChart(canvas, series) {
  const ctx = canvas.getContext('2d');
  const w = canvas.width = canvas.parentElement.clientWidth - 40;
  const h = canvas.height = 160;
  ctx.clearRect(0, 0, w, h);
  if (!series.length) {
    ctx.fillStyle = '#7c8b9c'; ctx.font = '13px sans-serif';
    ctx.fillText(t('no_data'), 10, h / 2);
    return;
  }
  const max = Math.max(...series.map(s => s.gb), 0.01);
  const barW = w / series.length * 0.55;
  const gap = w / series.length;

  const grad = ctx.createLinearGradient(0, 0, 0, h);
  grad.addColorStop(0, '#4fe8cf');
  grad.addColorStop(1, '#a78bfa');

  series.forEach((s, i) => {
    const barH = Math.max(3, (s.gb / max) * (h - 30));
    const x = i * gap + (gap - barW) / 2;
    const y = h - barH - 20;
    ctx.fillStyle = grad;
    roundRect(ctx, x, y, barW, barH, 4);
    ctx.fill();
    ctx.fillStyle = '#7c8b9c';
    ctx.font = '10px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(s.day.slice(5), x + barW / 2, h - 6);
  });
}
function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

/* ---------------- Links ---------------- */
async function loadLinks() {
  const links = await api('/api/links');
  const root = document.getElementById('links-list');
  root.innerHTML = '';
  if (!links.length) {
    root.innerHTML = `<div class="card" style="text-align:center; color:var(--muted);">${t('no_links')}</div>`;
    return;
  }
  links.forEach(l => root.appendChild(renderLinkRow(l)));
}

function renderLinkRow(l) {
  const row = document.createElement('div');
  row.className = 'link-row';
  const pct = l.traffic_limit_bytes ? Math.min(100, (l.traffic_used_bytes / l.traffic_limit_bytes) * 100) : 0;

  row.innerHTML = `
    <span class="dot ${l.is_active ? 'on' : 'off'}"></span>
    <div style="flex:1; min-width:0;">
      <div style="display:flex; align-items:center; gap:10px;">
        <strong>${l.label || t('unnamed')}</strong>
        <span class="badge ${l.is_active ? 'on' : 'off'}">${l.is_active ? t('active') : t('inactive')}</span>
        <span class="mono" style="font-size:11.5px; color:var(--muted);">${PROTOCOL_LABEL[l.protocol]}</span>
        ${l.anti_filter ? `<span class="badge on" title="${t('anti_filter')}">🛡</span>` : ''}
      </div>
      <div style="font-size:12px; color:var(--muted); margin-top:3px;">
        ${fmtGB(l.traffic_used_bytes)} ${l.traffic_limit_bytes ? ' ' + t('of') + ' ' + fmtGB(l.traffic_limit_bytes) : ' ' + t('unlimited')}
        ${l.expires_at ? ' · ' + t('expires') + ' ' + new Date(l.expires_at).toLocaleDateString(currentLang() === 'fa' ? 'fa-IR' : 'en-US') : ''}
      </div>
      ${l.traffic_limit_bytes ? `<div class="progress"><span style="width:${pct}%"></span></div>` : ''}
    </div>
    <button class="btn btn-ghost btn-sm" data-act="qr">${t('qr_link')}</button>
    <button class="btn btn-ghost btn-sm" data-act="toggle">${l.is_active ? t('disable') : t('enable')}</button>
    <button class="btn btn-danger btn-sm" data-act="del">${t('delete')}</button>
  `;
  row.querySelector('[data-act="qr"]').onclick = () => openLinkDetail(l.id);
  row.querySelector('[data-act="toggle"]').onclick = async () => { await api(`/api/links/${l.id}/toggle`, { method: 'POST' }); loadLinks(); };
  row.querySelector('[data-act="del"]').onclick = async () => { if (confirm(t('delete_link_confirm'))) { await api(`/api/links/${l.id}`, { method: 'DELETE' }); loadLinks(); toast(t('link_deleted')); } };
  return row;
}

function openModal(innerHtml) {
  const root = document.getElementById('modal-root');
  root.innerHTML = `<div class="overlay" onclick="if(event.target===this) closeModal()"><div class="modal">${innerHtml}</div></div>`;
}
function closeModal() { document.getElementById('modal-root').innerHTML = ''; }

function openCreateLinkModal() {
  openModal(`
    <h3 style="margin-top:0;">${t('new_tunnel_link')}</h3>
    <div class="field"><label>${t('label')}</label><input id="f-label" placeholder="${t('label_ph')}"></div>
    <div class="field"><label>${t('protocol')}</label>
      <select id="f-protocol">
        ${Object.entries(PROTOCOL_LABEL).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}
      </select>
    </div>
    <div class="field"><label>${t('traffic_limit')}</label><input id="f-limit" type="number" value="0"></div>
    <div class="field"><label>${t('expires_in')}</label><input id="f-expire" type="number"></div>
    <div class="field">
      <label style="display:flex; align-items:center; gap:8px; cursor:pointer;">
        <input id="f-anti-filter" type="checkbox" style="width:auto;">
        <span>${t('anti_filter')}</span>
      </label>
      <div style="font-size:11.5px; color:var(--muted); margin-top:4px;">${t('anti_filter_hint')}</div>
    </div>
    <div class="field">
      <label style="display:flex; align-items:center; gap:8px; cursor:pointer;">
        <input id="f-high-speed" type="checkbox" style="width:auto;">
        <span>${t('high_speed')}</span>
      </label>
      <div style="font-size:11.5px; color:var(--muted); margin-top:4px;">${t('high_speed_hint')}</div>
    </div>
    <div class="field"><label>${t('join_sub')}</label><input id="f-sub-id" placeholder="${t('join_sub_ph')}"></div>
    <div style="display:flex; gap:10px; margin-top:8px;">
      <button class="btn btn-primary" style="flex:1; justify-content:center;" onclick="submitCreateLink()">${t('create_link')}</button>
      <button class="btn btn-ghost" onclick="closeModal()">${t('cancel')}</button>
    </div>
  `);
}

async function submitCreateLink() {
  const subId = document.getElementById('f-sub-id').value.trim();
  const payload = {
    label: document.getElementById('f-label').value,
    protocol: document.getElementById('f-protocol').value,
    traffic_limit_gb: parseFloat(document.getElementById('f-limit').value || 0),
    expires_in_days: document.getElementById('f-expire').value ? parseInt(document.getElementById('f-expire').value) : null,
    anti_filter: document.getElementById('f-anti-filter').checked,
    sub_id: subId || null,
  };
  const link = await api('/api/links', { method: 'POST', body: JSON.stringify(payload) });
  closeModal();
  toast(t('link_created'));
  loadLinks();
  openLinkDetail(link.id);
}

async function openLinkDetail(id) {
  const l = await api(`/api/links/${id}`);
  openModal(`
    <h3 style="margin-top:0;">${l.label || t('links')}</h3>
    <img src="data:image/png;base64,${l.qr_png_base64}" style="width:100%; border-radius:12px; margin-bottom:14px;">
    <div class="field"><label>${t('connection_link')}</label>
      <input class="mono" readonly value="${l.connect_url}" onclick="this.select()">
    </div>
    <button class="btn btn-primary" style="width:100%; justify-content:center;" onclick="navigator.clipboard.writeText('${l.connect_url}'); toast(t('copied'))">${t('copy_link')}</button>

    <div class="field" style="margin-top:18px;"><label>${t('subscription_link')}</label>
      <input class="mono" readonly value="${l.sub_url}" onclick="this.select()">
      <div style="font-size:11.5px; color:var(--muted); margin-top:4px;">${t('subscription_hint')}</div>
    </div>
    <div style="display:flex; gap:10px;">
      <button class="btn btn-ghost" style="flex:1; justify-content:center;" onclick="navigator.clipboard.writeText('${l.sub_url}'); toast(t('copied'))">${t('copy_link')}</button>
      <a class="btn btn-ghost" style="flex:1; justify-content:center; text-decoration:none;" href="${l.sub_url}" target="_blank">${t('preview_sub_page')}</a>
    </div>

    ${l.fragment_json ? `
    <div class="field" style="margin-top:18px;"><label>${t('fragment_settings')}</label>
      <textarea class="mono" readonly rows="4" style="width:100%; resize:vertical;" onclick="this.select()">${l.fragment_json}</textarea>
      <div style="font-size:11.5px; color:var(--muted); margin-top:4px;">${t('fragment_hint')}</div>
    </div>
    <button class="btn btn-ghost" style="width:100%; justify-content:center;" onclick="navigator.clipboard.writeText(${JSON.stringify(l.fragment_json)}); toast(t('copied'))">${t('copy_link')}</button>
    ` : ''}
  `);
}

/* ---------------- Speed settings ---------------- */
async function loadSpeedPanel() {
  const root = document.getElementById('speed-panel');
  root.innerHTML = `<div class="card" style="text-align:center; color:var(--muted);">…</div>`;

  let status;
  try {
    status = await api('/api/system/network');
  } catch (e) {
    status = { available: false };
  }
  renderSpeedPanel(status);
}

function renderSpeedPanel(status) {
  const root = document.getElementById('speed-panel');
  const statusLine = status.available
    ? `<div style="display:flex; align-items:center; gap:10px; margin:12px 0;">
         <span class="dot ${status.bbr_active ? 'on' : 'off'}"></span>
         <span>${t('speed_current_algo')}: <strong class="mono">${status.current}</strong></span>
         <span class="badge ${status.bbr_active ? 'on' : 'off'}">${status.bbr_active ? t('speed_bbr_active') : t('speed_bbr_inactive')}</span>
       </div>`
    : `<div style="color:var(--muted); margin:12px 0;">${t('speed_bbr_unavailable')}</div>`;

  root.innerHTML = `
    <div class="card">
      <h3 style="margin-top:0;">${t('speed_server_title')}</h3>
      <div style="font-size:13px; color:var(--muted);">${t('speed_server_desc')}</div>
      ${statusLine}
      ${status.available && !status.bbr_active ? `<button class="btn btn-primary" id="btn-enable-bbr">${t('speed_enable_bbr')}</button>` : ''}
      <div id="bbr-result" style="margin-top:10px; font-size:13px;"></div>
    </div>
    <div style="height:18px;"></div>
    <div class="card">
      <h3 style="margin-top:0;">${t('speed_protocol_title')}</h3>
      <div style="font-size:13px; color:var(--muted);">${t('speed_protocol_desc')}</div>
    </div>
  `;

  const btn = document.getElementById('btn-enable-bbr');
  if (btn) btn.onclick = async () => {
    btn.disabled = true;
    const res = await api('/api/system/network/enable-bbr', { method: 'POST' });
    let msg;
    if (res.ok) {
      msg = `${t('speed_bbr_success')} ${res.persisted ? t('speed_bbr_persisted') : t('speed_bbr_not_persisted')}`;
      toast(t('speed_bbr_success'));
    } else {
      msg = res.error || t('speed_bbr_unavailable');
    }
    renderSpeedPanel(res);
    document.getElementById('bbr-result').textContent = msg;
  };
}

/* ---------------- MTProto ---------------- */
async function loadMtproto() {
  const list = await api('/api/mtproto');
  const root = document.getElementById('mtproto-list');
  root.innerHTML = '';
  if (!list.length) {
    root.innerHTML = `<div class="card" style="text-align:center; color:var(--muted);">${t('no_mtproto')}</div>`;
    return;
  }
  list.forEach(m => {
    const row = document.createElement('div');
    row.className = 'link-row';
    row.innerHTML = `
      <span class="dot ${m.is_active ? 'on' : 'off'}"></span>
      <div style="flex:1;"><strong>${m.label || t('unnamed')}</strong>
        <div class="mono" style="font-size:11.5px; color:var(--muted); margin-top:3px;">${m.secret}</div>
      </div>
      <button class="btn btn-ghost btn-sm" data-act="copy">${t('copy_link')}</button>
      <button class="btn btn-danger btn-sm" data-act="del">${t('delete')}</button>
    `;
    row.querySelector('[data-act="copy"]').onclick = () => { navigator.clipboard.writeText(m.connect_url); toast(t('copied')); };
    row.querySelector('[data-act="del"]').onclick = async () => { if (confirm(t('delete_proxy_confirm'))) { await api(`/api/mtproto/${m.id}`, { method: 'DELETE' }); loadMtproto(); } };
    root.appendChild(row);
  });
}

async function createMtproto() {
  const label = prompt(t('mtproto_name_prompt')) || '';
  await api('/api/mtproto', { method: 'POST', body: JSON.stringify({ label }) });
  toast(t('mtproto_created'));
  loadMtproto();
}

/* ---------------- Settings ---------------- */
async function loadSettingsPanel() {
  const root = document.getElementById('settings-panel');
  let me = {}, bot = {};
  try { me = await api('/api/auth/me'); } catch (e) {}
  try { bot = await api('/api/bot/status'); } catch (e) {}

  root.innerHTML = `
    <div class="card">
      <h3 style="margin-top:0;">👤 ${t('account_settings')}</h3>
      <div class="field"><label>${t('username')}</label><input id="s-username" value="${me.username || ''}"></div>
      <div class="field"><label>${t('current_password')}</label><input id="s-cur-pw" type="password" autocomplete="current-password"></div>
      <div style="display:flex; gap:10px;">
        <button class="btn btn-primary" style="flex:1; justify-content:center;" onclick="saveUsername()">${t('save_username')}</button>
      </div>
      <div style="height:14px;"></div>
      <div class="field"><label>${t('new_password')}</label><input id="s-new-pw" type="password" autocomplete="new-password"></div>
      <div style="display:flex; gap:10px;">
        <button class="btn btn-primary" style="flex:1; justify-content:center;" onclick="savePassword()">${t('save_password')}</button>
      </div>
      <div id="acc-result" style="margin-top:10px; font-size:13px; min-height:16px;"></div>
    </div>

    <div style="height:18px;"></div>

    <div class="card">
      <h3 style="margin-top:0;">🤖 ${t('telegram_bot')}</h3>
      <div style="font-size:13px; color:var(--muted); margin-bottom:14px;">${t('telegram_bot_desc')}</div>
      <div id="bot-status-line" style="margin-bottom:12px; display:flex; align-items:center; gap:10px;">
        <span class="dot ${bot.running ? 'on' : 'off'}"></span>
        <span>${bot.running ? t('bot_running') : t('bot_stopped')}</span>
        <span class="badge ${bot.token_set ? 'on' : 'off'}">${bot.token_set ? t('token_set') : t('token_not_set')}</span>
        ${bot.username ? `<span class="mono" style="font-size:12px; color:var(--muted);">@${bot.username}</span>` : ''}
      </div>
      <div class="field"><label>${t('bot_token')}</label><input id="b-token" class="mono" placeholder="123456:ABC-DEF..." value="${bot.token_set ? '' : ''}"></div>
      <div class="field"><label>${t('bot_admin_ids')}</label><input id="b-admins" placeholder="123456789, 987654321"></div>
      <div style="font-size:11.5px; color:var(--muted); margin-top:-8px; margin-bottom:12px;">${t('bot_admin_ids_hint')}</div>
      <div style="display:flex; gap:10px;">
        <button class="btn btn-primary" style="flex:1; justify-content:center;" onclick="saveBotConfig(true)">${t('save_and_start_bot')}</button>
        <button class="btn btn-ghost" onclick="saveBotConfig(false)">${t('stop_bot')}</button>
      </div>
      <div id="bot-result" style="margin-top:10px; font-size:13px; min-height:16px;"></div>
    </div>
  `;

  // prefill saved admin ids
  const adminsEl = document.getElementById('b-admins');
  if (adminsEl && bot.admin_ids && bot.admin_ids.length) adminsEl.value = bot.admin_ids.join(', ');
}

async function saveUsername() {
  const username = document.getElementById('s-username').value.trim();
  const current_password = document.getElementById('s-cur-pw').value;
  const resEl = document.getElementById('acc-result');
  resEl.textContent = '';
  if (!username || !current_password) { resEl.textContent = t('fill_fields'); return; }
  try {
    const r = await api('/api/auth/change-username', { method: 'POST', body: JSON.stringify({ current_password, new_username: username }) });
    if (r.access_token) { localStorage.setItem('hami_token', r.access_token); }
    resEl.textContent = '✅ ' + t('username_changed');
  } catch (e) { resEl.textContent = '❌ ' + e.message; }
}

async function savePassword() {
  const current_password = document.getElementById('s-cur-pw').value;
  const new_password = document.getElementById('s-new-pw').value;
  const resEl = document.getElementById('acc-result');
  resEl.textContent = '';
  if (!current_password || !new_password) { resEl.textContent = t('fill_fields'); return; }
  try {
    const r = await api('/api/auth/change-password', { method: 'POST', body: JSON.stringify({ current_password, new_password }) });
    resEl.textContent = '✅ ' + t('password_changed');
    document.getElementById('s-new-pw').value = '';
  } catch (e) { resEl.textContent = '❌ ' + e.message; }
}

async function saveBotConfig(start) {
  const token = document.getElementById('b-token').value.trim();
  const admin_ids = document.getElementById('b-admins').value.trim();
  const resEl = document.getElementById('bot-result');
  resEl.textContent = '';
  if (start && !token && !admin_ids) { resEl.textContent = t('fill_fields'); return; }
  try {
    await api('/api/bot/config', { method: 'POST', body: JSON.stringify({ token, admin_ids }) });
    if (start) {
      await api('/api/bot/start', { method: 'POST' });
      resEl.textContent = '✅ ' + t('bot_started');
    } else {
      await api('/api/bot/stop', { method: 'POST' });
      resEl.textContent = '✅ ' + t('bot_stopped');
    }
    loadSettingsPanel();
  } catch (e) { resEl.textContent = '❌ ' + e.message; }
}

/* ---------------- Init ---------------- */
switchView('overview');
