// SCADA GPU v5 — Alarms page + alarm display helpers
import { G, ae } from './state.js';
import { $, esc, fmtAlarmTime, fmtAlarmDuration } from './utils.js';
import { api, API_BASE, getDeviceIdForSlot, getGenSlots, getDeviceIdsForSite, decodeAlarms, trackAlarmTimes } from './api.js';
import { ALARM_CODES } from './constants.js';

// === Alarms page state ===
let alarmsPageState = { sevFilter: '', activeOnly: false, hours: 24, page: 0, limit: 30 };
let alarmsMode = false;
let _almOpenRow = null;

// === ALARM SYSTEM ===
// HGM9520N alarms from protocol Table 27
// ALARM_CODES → modules/constants.js
function showAlarmSub(sl, sub) { const act = $(sl + 'a-act'), arc = $(sl + 'a-arc'), ab = $(sl + 'a-act-btn'), bb = $(sl + 'a-arc-btn'); if (!act || !arc) return; if (sub === 'act') { act.style.display = ''; arc.style.display = 'none'; ab.style.fontWeight = '600'; ab.style.color = 'var(--r)'; bb.style.fontWeight = ''; bb.style.color = '' } else { act.style.display = 'none'; arc.style.display = ''; bb.style.fontWeight = '600'; bb.style.color = 'var(--p)'; ab.style.fontWeight = ''; ab.style.color = ''; renderAlarmArchive(sl) } }

async function renderAlarmArchive(sl) {
  const el = $(sl + 'a-arc'); if (!el || !G.cur) return;
  const devId = getDeviceIdForSlot(sl);
  if (!devId) { el.innerHTML = '<div style="color:var(--t3);font-size:12px;text-align:center;padding:15px">Устройство не настроено</div>'; return }
  el.innerHTML = '<div style="color:var(--t3);font-size:12px;text-align:center;padding:15px">⏳ Загрузка...</div>';
  try {
    const [aaAlarms, hAlarms] = await Promise.all([api.get('/api/alarm-analytics/events?device_id=' + devId + '&limit=50').catch(() => []), api.get('/api/history/alarms?device_id=' + devId + '&last_hours=720&limit=50').catch(() => [])]);
    const seen = new Set(); const alarms = [];
    for (const a of (aaAlarms || [])) { const k = (a.alarm_code || '') + '_' + (a.occurred_at || ''); if (!seen.has(k)) { seen.add(k); alarms.push(a) } }
    const _AGG = new Set(['COMMON', 'SHUTDOWN', 'WARNING', 'BLOCK', 'TRIP_STOP']); for (const h of (hAlarms || [])) { if (_AGG.has(h.alarm_code)) continue; const norm = { alarm_code: h.alarm_code, alarm_name_ru: h.message || h.alarm_code, alarm_severity: h.severity, occurred_at: h.occurred_at, cleared_at: h.cleared_at, is_active: h.is_active }; const k = (norm.alarm_code || '') + '_' + (norm.occurred_at || ''); if (!seen.has(k)) { seen.add(k); alarms.push(norm) } }
    alarms.sort((a, b) => (b.occurred_at || '').localeCompare(a.occurred_at || ''));
    if (!alarms.length) { el.innerHTML = '<div style="color:var(--t3);font-size:12px;text-align:center;padding:15px">Архив пуст</div>'; return }
    el.innerHTML = '<div style="max-height:220px;overflow-y:auto">' + alarms.map(function (a) {
      var sev = a.alarm_severity || ''; var isErr = sev === 'shutdown' || sev === 'error' || sev === 'trip_stop'; var ico = isErr ? '🔴' : '⚠'; var col = isErr ? 'var(--r)' : 'var(--y)';
      var msg = a.alarm_name_ru || a.alarm_name || a.alarm_code;
      var t = new Date(a.occurred_at + 'Z').toLocaleString('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
      var dur = ''; if (a.cleared_at) { var ms = new Date(a.cleared_at + 'Z') - new Date(a.occurred_at + 'Z'); dur = ms < 60000 ? (Math.round(ms / 1000) + 'с') : (Math.round(ms / 60000) + 'мин') }
      var status = a.is_active ? '<span style="color:var(--r);font-size:9px">● активна</span>' : '<span style="color:var(--t4);font-size:9px">✓ ' + (dur || '') + '</span>';
      return '<div class="ai ' + (isErr ? 'aa' : 'aw') + '" style="margin-bottom:2px"><span style="font-size:10px">' + ico + '</span><b style="color:' + col + ';font-size:10px;margin:0 4px">' + esc(a.alarm_code) + '</b><span style="font-size:11px;flex:1">' + esc(msg) + '</span>' + status + '<span style="color:var(--t4);font-size:9px;white-space:nowrap;margin-left:4px">' + t + '</span></div>'
    }).join('') + '</div>'
  } catch (e) { el.innerHTML = '<div style="color:var(--r);font-size:11px;text-align:center;padding:15px">Ошибка: ' + esc(e.message) + '</div>' }
}

// ===================== ALARMS PAGE =====================
function resolveDeviceName(deviceId) {
  const info = G.deviceSlotIndex[deviceId];
  if (!info) return 'Устр. #' + deviceId;
  const name = info.slot === 'spr' ? 'ШПР' : info.slot.startsWith('g') ? 'Г' + info.slot.slice(1) : info.slot;
  const siteName = G.S[info.siteKey]?.name || info.siteKey;
  return name + ' · ' + siteName;
}

function showAlarms() { stopB24Poll(); G.curView = 'alarms'; setTimeout(showUserProfile, 0);
  alarmsMode = true; G.archiveMode = false;
  const mn = $('mainArea');
  mn.innerHTML = `
<div class="dh"><div class="dt"><h1>🚨 Аварии</h1></div>
<div class="da"><button onclick="alarmsMode=false;if(G.cur&&G.S[G.cur])renderDash()">← Мониторинг</button>
<button onclick="almRefresh()">🔄 Обновить</button></div></div>
<div style="margin-bottom:12px">
<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
<h2 style="font-size:14px;font-weight:600;color:var(--r)">● Активные аварии</h2>
<span id="almActiveCount" style="font-size:11px;color:var(--t3);font-family:var(--m)"></span></div>
<div id="almActiveList"></div></div>
<div>
<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px">
<h2 style="font-size:14px;font-weight:600;color:var(--t2)">📋 Журнал аварий</h2></div>
<div class="arc-flt" style="margin-bottom:8px">
<select class="fi" id="almSite" style="width:160px;padding:6px 8px;font-size:11px" onchange="alarmsPageState.page=0;almRefresh()">
<option value="">🏭 Все объекты</option></select>
<select class="fi" id="almSev" style="width:140px;padding:6px 8px;font-size:11px" onchange="alarmsPageState.page=0;almLoadHistory()">
<option value="">Все уровни</option><option value="error">🔴 Ошибка</option><option value="warning">🟡 Предупр.</option></select>
<label style="display:flex;align-items:center;gap:4px;font-size:11px;color:var(--t2)"><input type="checkbox" id="almActiveOnly" style="accent-color:var(--g)" onchange="alarmsPageState.page=0;almLoadHistory()"> Только активные</label>
<div style="display:flex;gap:2px">
<button class="arc-tb" onclick="almPeriod(this,1)">1ч</button>
<button class="arc-tb" onclick="almPeriod(this,6)">6ч</button>
<button class="arc-tb on" onclick="almPeriod(this,24)">24ч</button>
<button class="arc-tb" onclick="almPeriod(this,168)">7д</button>
<button class="arc-tb" onclick="almPeriod(this,720)">30д</button>
<button class="arc-tb" onclick="almPeriod(this,0)">Всё</button></div></div>
<div id="almHistoryTable"></div>
<div id="almHistoryPag"></div></div>`;
  // Populate site filter dropdown
  const almSiteSel = $('almSite');
  if (almSiteSel) {
    for (const key of Object.keys(G.S)) {
      const name = G.S[key]?.name || key;
      const opt = document.createElement('option'); opt.value = key; opt.textContent = '📍 ' + name;
      almSiteSel.appendChild(opt)
    }
    if (G.cur) almSiteSel.value = G.cur
  }
  almRefresh();
}

function almPeriod(btn, hours) {
  btn.parentElement.querySelectorAll('.arc-tb').forEach(b => b.classList.remove('on'));
  btn.classList.add('on'); alarmsPageState.hours = hours; alarmsPageState.page = 0; almLoadHistory();
}

async function almLoadActive() {
  const el = $('almActiveList'), cnt = $('almActiveCount');
  if (!el) return;
  el.innerHTML = '<div style="color:var(--t3);font-size:12px;text-align:center;padding:20px">⏳ Загрузка...</div>';
  try {
    // Build device_ids filter from site dropdown
    const almSiteKey = $('almSite')?.value || '';
    const dids = almSiteKey ? getDeviceIdsForSite(almSiteKey) : [];
    const didsQ = dids.length ? '?device_ids=' + dids.join(',') : '';
    // Load from both sources: summary flags (history) + bitwise (alarm-analytics)
    const [alarmsHist, alarmsAA] = await Promise.all([
      api.get('/api/history/alarms/active' + didsQ).catch(() => []),
      api.get('/api/alarm-analytics/active' + didsQ).catch(() => []),
    ]);
    // Merge: prefer alarm-analytics (have name_ru), add history items not covered
    const aaSet = new Set(alarmsAA.map(a => a.device_id + '_' + a.alarm_code));
    const alarms = alarmsAA.map(a => ({
      ...a, message: a.alarm_name_ru || a.alarm_name || a.alarm_code,
      severity: a.alarm_severity || a.severity || 'error',
      alarm_code: a.alarm_code,
    }));
    const _HAGG = new Set(['COMMON', 'SHUTDOWN', 'WARNING', 'BLOCK', 'TRIP_STOP']);
    for (const a of alarmsHist) {
      if (_HAGG.has(a.alarm_code)) continue;
      if (!aaSet.has(a.device_id + '_' + a.alarm_code)) alarms.push(a);
    }
    if (cnt) cnt.textContent = alarms.length + ' шт.';
    if (!alarms.length) { el.innerHTML = '<div style="padding:16px 20px;background:var(--gd);border:1px solid rgba(0,224,154,.2);border-radius:var(--rad);color:var(--g);font-size:13px;text-align:center">✓ Нет активных аварий</div>'; return }
    const sevI = { error: '🔴', shutdown: '🔴', warning: '⚠', block: '🟠' }, sevC = { error: 'var(--r)', shutdown: 'var(--r)', warning: 'var(--y)', block: 'var(--r)' };
    const cards = alarms.map(a => {
      const occ = new Date(a.occurred_at);
      const durMin = Math.round((Date.now() - occ.getTime()) / 60000);
      const durStr = durMin < 60 ? durMin + ' мин' : (durMin / 60 | 0) + ' ч ' + (durMin % 60) + ' мин';
      const sev = a.alarm_severity || a.severity || 'error';
      const ic = sevI[sev] || '🔴';
      const col = sevC[sev] || 'var(--r)';
      const bg = sev === 'warning' ? 'var(--yd)' : 'var(--rd)';
      const border = sev === 'warning' ? 'rgba(255,176,32,.2)' : 'rgba(255,64,96,.2)';
      const dev = resolveDeviceName(a.device_id);
      const msg = a.alarm_name_ru || a.message || a.alarm_code;
      return `<div class="ai" data-device-id="${a.device_id}" data-alarm-code="${a.alarm_code}" data-device-type="${a.device_type || ''}" style="cursor:pointer;padding:10px 14px;background:${bg};border:1px solid ${border};border-radius:var(--rs);margin-bottom:4px;display:flex;align-items:center;gap:10px">
<span style="font-size:16px">${ic}</span>
<div style="flex:1;min-width:0">
<div style="display:flex;align-items:center;gap:8px;margin-bottom:2px">
<b style="color:${col};font-family:var(--m);font-size:12px">${esc(a.alarm_code)}</b>
<span style="font-size:12px;color:var(--t)">${esc(msg)}</span></div>
<div style="font-size:10px;color:var(--t3);font-family:var(--m)">${dev} · ${occ.toLocaleString('ru-RU')} · ${durStr}</div></div></div>`
    }).join('');
    el.innerHTML = cards;
  } catch (e) { el.innerHTML = `<div style="color:var(--r);font-size:12px;padding:20px;text-align:center">Ошибка: ${esc(e.message)}</div>` }
}

async function almLoadHistory() {
  const el = $('almHistoryTable'), pag = $('almHistoryPag');
  if (!el) return;
  el.innerHTML = '<div style="color:var(--t3);font-size:12px;text-align:center;padding:20px">⏳ Загрузка...</div>';
  const st = alarmsPageState;
  st.sevFilter = $('almSev')?.value || '';
  st.activeOnly = $('almActiveOnly')?.checked || false;
  // Build device_ids filter from site dropdown
  const almSiteKey = $('almSite')?.value || '';
  const dids = almSiteKey ? getDeviceIdsForSite(almSiteKey) : [];
  const didsParam = dids.length ? `&device_ids=${dids.join(',')}` : '';
  // Fetch from alarm-analytics (bitwise, has name_ru) as primary source
  let aaUrl = `/api/alarm-analytics/events?limit=${st.limit}&offset=${st.page * st.limit}`;
  if (st.sevFilter) aaUrl += `&severity=${st.sevFilter}`;
  if (st.activeOnly) aaUrl += '&is_active=true';
  if (st.hours) aaUrl += `&last_hours=${st.hours}`;
  aaUrl += didsParam;
  // Also fetch from history (summary flags) as fallback
  let hUrl = `/api/history/alarms?limit=${st.limit}&offset=${st.page * st.limit}`;
  if (st.sevFilter) hUrl += `&severity=${st.sevFilter}`;
  if (st.activeOnly) hUrl += '&is_active=true';
  if (st.hours) hUrl += `&last_hours=${st.hours}`;
  hUrl += didsParam;
  try {
    const [alarmsAA, alarmsH] = await Promise.all([
      api.get(aaUrl).catch(() => []),
      api.get(hUrl).catch(() => []),
    ]);
    // Merge: AA events first (sorted by occurred_at desc), then history events not in AA
    const allAlarms = alarmsAA.map(a => ({
      id: a.id, device_id: a.device_id, device_type: a.device_type || '',
      alarm_code: a.alarm_code,
      severity: a.alarm_severity || a.severity || 'error',
      message: a.alarm_name_ru || a.alarm_name || a.alarm_code,
      occurred_at: a.occurred_at, cleared_at: a.cleared_at, is_active: a.is_active,
      _src: 'aa',
    }));
    const _AGG_CODES = new Set(['COMMON', 'SHUTDOWN', 'WARNING', 'BLOCK', 'TRIP_STOP']);
    const aaIds = new Set(allAlarms.map(a => a.device_id + '_' + a.alarm_code + '_' + new Date(a.occurred_at).getTime()));
    for (const a of alarmsH) {
      if (_AGG_CODES.has(a.alarm_code)) continue;
      const key = a.device_id + '_' + a.alarm_code + '_' + new Date(a.occurred_at).getTime();
      if (!aaIds.has(key)) allAlarms.push({ ...a, _src: 'h' });
    }
    allAlarms.sort((a, b) => new Date(b.occurred_at) - new Date(a.occurred_at));
    const alarms = allAlarms.slice(0, st.limit);
    if (!alarms || !alarms.length) { el.innerHTML = '<div style="color:var(--t3);font-size:12px;text-align:center;padding:30px">Нет аварий за выбранный период ✓</div>'; if (pag) pag.innerHTML = ''; return }
    const sevI = { error: '🔴', shutdown: '🔴', warning: '🟡', block: '🟠' }, sevL = { error: 'Ошибка', shutdown: 'Аварийн.', warning: 'Предупр.', block: 'Блокир.' };
    const rows = alarms.map(a => {
      const occ = new Date(a.occurred_at), clr = a.cleared_at ? new Date(a.cleared_at) : null;
      const dur = clr ? Math.round((clr - occ) / 60000) : null;
      const durStr = dur != null ? (dur < 60 ? dur + ' мин' : (dur / 60 | 0) + 'ч ' + (dur % 60) + 'мин') : '—';
      const dev = resolveDeviceName(a.device_id);
      const sev = a.alarm_severity || a.severity || 'error';
      const msg = a.alarm_name_ru || a.message || a.alarm_code;
      const clrStr = clr ? clr.toLocaleString('ru-RU') : '—';
      const eid = a.id || 0; const src = a._src || 'aa';
      return `<tr class="alm-expand-row" onclick="almToggleRow(${eid},this,'${esc(a.alarm_code)}',${a.device_id},'${a.device_type || ''}','${src}')">
<td style="white-space:nowrap"><span class="alm-chevron">▶</span>${occ.toLocaleString('ru-RU')}</td>
<td>${esc(dev)}</td>
<td style="font-family:var(--m)"><b>${esc(a.alarm_code)}</b></td>
<td>${sevI[sev] || '⚪'} ${sevL[sev] || sev}</td>
<td>${esc(msg)}</td>
<td style="white-space:nowrap">${clrStr}</td>
<td>${durStr}</td>
<td>${a.is_active ? '<span style="color:var(--r);font-weight:600">● Активна</span>' : '<span style="color:var(--t3)">✓ Снята</span>'}</td></tr>
<tr class="alm-detail-tr" id="almDet_${eid}" style="display:none"><td colspan="8" class="alm-detail-td"><div class="alm-expand-inner" id="almDetIn_${eid}"></div></td></tr>`
    }).join('');
    el.innerHTML = `<table class="pt"><thead><tr><th>Возникла</th><th>Устройство</th><th>Код</th><th>Уровень</th><th>Сообщение</th><th>Устранена</th><th>Длит.</th><th>Статус</th></tr></thead><tbody>${rows}</tbody></table>`;
    const hasMore = alarms.length === st.limit;
    if (pag) pag.innerHTML = `<div style="display:flex;gap:8px;align-items:center;margin-top:8px">
<button class="sb-btn" style="padding:5px 12px;font-size:11px;width:auto" onclick="alarmsPageState.page=Math.max(0,alarmsPageState.page-1);almLoadHistory()" ${st.page === 0 ? 'disabled style="opacity:.4;pointer-events:none;padding:5px 12px;font-size:11px;width:auto"' : ''}>← Назад</button>
<span style="font-size:11px;color:var(--t3);font-family:var(--m)">Стр. ${st.page + 1}</span>
<button class="sb-btn" style="padding:5px 12px;font-size:11px;width:auto" onclick="alarmsPageState.page++;almLoadHistory()" ${!hasMore ? 'disabled style="opacity:.4;pointer-events:none;padding:5px 12px;font-size:11px;width:auto"' : ''}>Вперёд →</button></div>`;
  } catch (e) { el.innerHTML = `<div style="color:var(--r);font-size:12px;padding:20px;text-align:center">Ошибка: ${esc(e.message)}</div>` }
}

async function almToggleRow(eventId, rowEl, code, deviceId, deviceType, src) {
  if (!eventId) return;
  // Close previously opened row
  if (_almOpenRow && _almOpenRow !== rowEl) {
    _almOpenRow.classList.remove('open');
    const prevId = _almOpenRow.dataset.eid;
    const prevDet = document.getElementById('almDet_' + prevId);
    if (prevDet) prevDet.style.display = 'none';
  }
  rowEl.dataset.eid = eventId;
  const detTr = document.getElementById('almDet_' + eventId);
  if (!detTr) return;
  const isOpen = rowEl.classList.contains('open');
  if (isOpen) {
    rowEl.classList.remove('open'); detTr.style.display = 'none'; _almOpenRow = null; return;
  }
  rowEl.classList.add('open'); detTr.style.display = 'table-row'; _almOpenRow = rowEl;
  const inner = document.getElementById('almDetIn_' + eventId);
  if (!inner) return;
  if (inner.dataset.loaded) { return }
  if (src === 'h') {
    const connDesc = { 'CONN_LOST': 'Потеря связи с контроллером. Устройство не отвечает по Modbus. Проверить сеть, питание контроллера, порт связи.' };
    const d = connDesc[code] || ('Системное событие: ' + code);
    inner.innerHTML = '<div style="padding:8px"><div class="alm-exp-desc" style="color:var(--t2)">📖 ' + esc(d) + '</div></div>';
    inner.dataset.loaded = '1';
    return;
  }
  inner.innerHTML = '<div style="color:var(--t3);padding:8px">⏳ Загрузка...</div>';
  try {
    const ev = await api.get('/api/alarm-analytics/events/' + eventId);
    almRenderExpanded(inner, ev, code, deviceId, deviceType);
    inner.dataset.loaded = '1';
  } catch (e) {
    inner.innerHTML = '<div style="color:var(--t3);padding:8px">Нет расширенных данных</div>';
    inner.dataset.loaded = '1';
  }
}

function almRenderExpanded(el, ev, code, deviceId, deviceType) {
  let desc = '';
  if (ev.analysis_result && ev.analysis_result.manual_description) {
    desc = `<div class="alm-exp-desc">📖 ${esc(ev.analysis_result.manual_description)}</div>`;
  }
  let metricsHtml = '';
  if (ev.metrics_snapshot && typeof ev.metrics_snapshot === 'object') {
    const mx = ev.metrics_snapshot;
    const keys = ['rpm', 'oil_pressure', 'coolant_temp', 'battery_voltage',
      'gen_voltage_ab', 'gen_voltage_bc', 'gen_voltage_ca',
      'gen_current_a', 'gen_freq', 'power_total', 'power_factor',
      'gas_pressure', 'run_hours', 'mains_voltage_ab', 'mains_freq'];
    const labels = { rpm: 'Об/мин', oil_pressure: 'Давл. масла', coolant_temp: 'Темп. ОЖ', battery_voltage: 'АКБ',
      gen_voltage_ab: 'Uab ген', gen_voltage_bc: 'Ubc ген', gen_voltage_ca: 'Uca ген',
      gen_current_a: 'Ia ген', gen_freq: 'Частота ген', power_total: 'Мощность', power_factor: 'cos φ',
      gas_pressure: 'Давл. газа', run_hours: 'Моточасы', mains_voltage_ab: 'Uab сеть', mains_freq: 'Частота сети' };
    const fmtV = v => typeof v === 'number' ? (Number.isInteger(v) ? v : +v.toFixed(1)) : v;
    const items = keys.filter(k => mx[k] != null).map(k => `<div class="alm-exp-kv"><span class="ek">${labels[k] || k}</span><span class="ev">${fmtV(mx[k])}</span></div>`);
    if (items.length) { metricsHtml = `<div style="font-size:11px;color:var(--t3);margin-top:6px">📊 Метрики на момент аварии:</div><div class="alm-exp-metrics">${items.join('')}</div>` }
  }
  const almCode = ev.alarm_code || code;
  const devId = ev.device_id || deviceId;
  const devType = ev.device_type || deviceType || '';
  el.innerHTML = `${desc}${metricsHtml}
<div class="alm-exp-btns">
<button class="alm-exp-btn" onclick="event.stopPropagation();window.almShowEvent(${ev.id})">📋 Подробнее</button>
<button class="alm-exp-btn" id="almExpLlm_${ev.id}" onclick="event.stopPropagation();almAskSanek(${ev.id},'${almCode}',${devId},'${devType}')">🤖 Спросить Санька</button></div>
<div id="almExpLlmRes_${ev.id}"></div>`;
}

async function almAskSanek(evId, alarmCode, deviceId, deviceType) {
  const btn = document.getElementById('almExpLlm_' + evId);
  const res = document.getElementById('almExpLlmRes_' + evId);
  if (!btn || !res) return;
  btn.disabled = true; res.innerHTML = '';
  const t0 = Date.now();
  let ticker = setInterval(() => { const s = ((Date.now() - t0) / 1000) | 0; btn.textContent = `⏳ Санёк анализирует... ${s}с`; }, 1000);
  btn.textContent = '⏳ Санёк анализирует... 0с';
  const ac = new AbortController();
  const tId = setTimeout(() => ac.abort(), 90000);
  try {
    const resp = await fetch(API_BASE + '/api/alarm-analytics/explain', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ alarm_code: alarmCode, device_id: deviceId || 0, device_type: deviceType || 'generator' }), signal: ac.signal });
    clearTimeout(tId); clearInterval(ticker);
    const elapsed = ((Date.now() - t0) / 1000).toFixed(1);
    if (!resp.ok) {
      const errText = resp.status === 504 ? 'Сервер не ответил вовремя (504). Попробуйте ещё раз.' :
        resp.status === 502 ? 'Бэкенд недоступен (502).' : 'Ошибка сервера: ' + resp.status;
      res.innerHTML = `<div style="color:#f87171;font-size:12px;margin-top:8px">✗ ${errText}</div>`;
      btn.disabled = false; btn.textContent = '🤖 Попробовать снова'; return;
    }
    const data = await resp.json();
    if (data.success && data.explanation) {
      res.innerHTML = `<div class="sn-msg assistant" style="margin-top:10px;max-width:100%;animation:none">
<div style="font-size:11px;color:#5de4ff;font-weight:800;margin-bottom:6px">🤖 Санёк — AI-анализ <span style="opacity:.6">(${elapsed}с)</span></div>${_snFormatText(data.explanation)}</div>`;
      btn.textContent = '✅ Анализ получен';
    } else {
      res.innerHTML = `<div style="color:#f87171;font-size:12px;margin-top:8px">✗ ${data.error || 'Не удалось получить анализ'}</div>`;
      btn.disabled = false; btn.textContent = '🤖 Попробовать снова';
    }
  } catch (e) {
    clearTimeout(tId); clearInterval(ticker);
    const elapsed = ((Date.now() - t0) / 1000).toFixed(1);
    const msg = e.name === 'AbortError' ? `Таймаут (${elapsed}с). Санёк не ответил. Попробуйте ещё раз.` : e.message;
    res.innerHTML = `<div style="color:#f87171;font-size:12px;margin-top:8px">✗ ${msg}</div>`;
    btn.disabled = false; btn.textContent = '🤖 Попробовать снова';
  }
}

function almRefresh() { almLoadActive(); almLoadHistory() }

// === Dashboard alarm helpers (scrollToAlarm uses openAlarms from dashboard) ===
function scrollToAlarm() { const cards = ['cg1', 'cg2', 'cspr']; for (const id of cards) { const c = $(id); if (c && (c.classList.contains('s-wrn') || c.classList.contains('s-alm'))) { const sl = id.replace('c', ''); const aTab = id === 'cspr' ? 'spra' : sl + 'a'; openAlarms(id, aTab); return } } }

// === Legacy bridge: functions still in legacy.js, accessed via window ===
function stopB24Poll() { if (window.stopB24Poll) window.stopB24Poll(); }
function showUserProfile() { if (window.showUserProfile) window.showUserProfile(); }
function renderDash() { if (window.renderDash) window.renderDash(); }
function openAlarms(cardId, alarmTabId) { if (window.openAlarms) window.openAlarms(cardId, alarmTabId); }
function _snFormatText(text) { return window._snFormatText ? window._snFormatText(text) : text; }

// ===================== EXPORTS =====================
export {
  alarmsPageState,
  alarmsMode,
  showAlarmSub,
  renderAlarmArchive,
  resolveDeviceName,
  showAlarms,
  almPeriod,
  almLoadActive,
  almLoadHistory,
  almToggleRow,
  almRenderExpanded,
  almAskSanek,
  almRefresh,
  scrollToAlarm,
};
