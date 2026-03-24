// SCADA GPU v5 — API client + WebSocket + metrics handling
import { G, ae } from './state.js';
import { ALARM_FIELDS_GEN, ALARM_FIELDS_ATS } from './constants.js';

export const API_BASE = (window.location.port === '8011' || window.location.port === '80' || window.location.port === '')
  ? ''
  : 'http://' + window.location.hostname + ':8010';

export const WS_BASE = API_BASE
  ? API_BASE.replace(/^http/, 'ws')
  : 'ws://' + window.location.host;

export const api = {
  async get(path) {
    const r = await fetch(API_BASE + path, { credentials: 'include' });
    if (r.status === 401) { location.reload(); return null; }
    if (!r.ok) throw new Error(`GET ${path}: ${r.status}`);
    return r.json();
  },
  async post(path, body) {
    const r = await fetch(API_BASE + path, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      credentials: 'include', body: JSON.stringify(body),
    });
    if (r.status === 401) { location.reload(); return null; }
    if (!r.ok) throw new Error(`POST ${path}: ${r.status}`);
    return r.json();
  },
  async patch(path, body) {
    const r = await fetch(API_BASE + path, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      credentials: 'include', body: JSON.stringify(body),
    });
    if (r.status === 401) { location.reload(); return null; }
    if (!r.ok) throw new Error(`PATCH ${path}: ${r.status}`);
    return r.json();
  },
  async put(path, body) {
    const r = await fetch(API_BASE + path, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' },
      credentials: 'include', body: JSON.stringify(body),
    });
    if (r.status === 401) { location.reload(); return null; }
    if (!r.ok) throw new Error(`PUT ${path}: ${r.status}`);
    return r.json();
  },
  async del(path) {
    const r = await fetch(API_BASE + path, { method: 'DELETE', credentials: 'include' });
    if (r.status === 401) { location.reload(); return null; }
    if (!r.ok) throw new Error(`DELETE ${path}: ${r.status}`);
  },
};

// ---- Alarm definitions loader ----
export async function loadAlarmDefs() {
  try {
    const defs = await api.get('/api/alarm-analytics/definitions');
    G.alarmDefs = {};
    for (const d of defs) {
      if (!G.alarmDefs[d.register_field]) G.alarmDefs[d.register_field] = {};
      G.alarmDefs[d.register_field][d.bit] = d;
    }
    G.alarmDefsLoaded = true;
    console.log('Alarm definitions loaded:', defs.length);
    try {
      const active = await api.get('/api/alarm-analytics/active');
      for (const a of active) {
        if (!G._alarmFirstSeen[a.device_id]) G._alarmFirstSeen[a.device_id] = {};
        G._alarmFirstSeen[a.device_id][a.alarm_code] = new Date(a.occurred_at).getTime();
      }
      if (active.length) console.log('Alarm timestamps loaded from DB:', active.length);
    } catch(e2) { /* ok */ }
  } catch(e) { console.warn('Failed to load alarm defs:', e); }
}

export function decodeAlarms(mx, deviceType) {
  if (!mx || !G.alarmDefsLoaded) return [];
  const fields = deviceType === 'ats' ? ALARM_FIELDS_ATS : ALARM_FIELDS_GEN;
  const result = [];
  for (const field of fields) {
    const val = mx[field];
    if (!val) continue;
    const defs = G.alarmDefs[field] || {};
    for (let bit = 0; bit < 16; bit++) {
      if (val & (1 << bit)) {
        const def = defs[bit];
        if (def) result.push(def);
        else result.push({ code: `${field}:${bit}`, name_ru: `Неизвестная авария (${field} бит ${bit})`, severity: 'warning' });
      }
    }
  }
  return result;
}

export function trackAlarmTimes(deviceId, alarms, controllerTime) {
  if (!G._alarmFirstSeen[deviceId]) G._alarmFirstSeen[deviceId] = {};
  const prev = G._alarmFirstSeen[deviceId];
  const currentCodes = new Set(alarms.map(a => a.code));
  for (const code of Object.keys(prev)) {
    if (!currentCodes.has(code)) delete prev[code];
  }
  const nowMs = controllerTime ? new Date(controllerTime).getTime() : Date.now();
  for (const a of alarms) {
    if (!prev[a.code]) prev[a.code] = isNaN(nowMs) ? Date.now() : nowMs;
  }
  return alarms.map(a => ({ ...a, _firstSeen: prev[a.code] }));
}

// ---- WebSocket ----
export function connectWebSocket() {
  if (G.ws) { try { G.ws.close(); } catch(e) {} }
  const url = WS_BASE + '/ws/metrics';
  try {
    G.ws = new WebSocket(url);
  } catch (e) {
    console.warn('WS connect error:', e);
    scheduleWsReconnect();
    return;
  }
  G.ws.onopen = () => {
    ae('🔌 WebSocket подключён');
    console.log('WS connected:', url);
    G.wsReconnectDelay = 3000;
  };
  G.ws.onclose = () => {
    console.log('WS closed');
    scheduleWsReconnect();
  };
  G.ws.onerror = (e) => {
    console.warn('WS error:', e);
  };
  G.ws.onmessage = (ev) => {
    if (ev.data === 'ping' || ev.data === 'pong') return;
    try {
      const msg = JSON.parse(ev.data);
      if (msg.type === 'snapshot' && Array.isArray(msg.data)) {
        for (const m of msg.data) handleMetricsUpdate(m);
      } else if (msg.type === 'maintenance_alert') {
        // handled locally
      } else if (msg.type === 'event' && msg.data) {
        if (typeof window._addRealtimeEvent === 'function') window._addRealtimeEvent(msg.data);
      } else if (msg.device_id !== undefined) {
        handleMetricsUpdate(msg);
      }
    } catch(e) { console.error('WS message parse error:', e, ev.data?.substring?.(0, 200)); }
  };
}

function scheduleWsReconnect() {
  if (G.wsReconnectTimer) clearTimeout(G.wsReconnectTimer);
  G.wsReconnectTimer = setTimeout(connectWebSocket, G.wsReconnectDelay);
  G.wsReconnectDelay = Math.min(G.wsReconnectDelay * 2, G.WS_RECONNECT_MAX);
}

export function handleMetricsUpdate(m) {
  if (!m || !m.device_id) return;

  // Grace period
  if (m.online === true) {
    G.latestOnlineTime[m.device_id] = Date.now();
  } else if (m.online === false) {
    const last = G.latestOnlineTime[m.device_id] || 0;
    if (Date.now() - last < 10000) m.online = true;
  }

  // Merge
  const prev = G.latestMetrics[m.device_id];
  if (prev && m.online !== false) {
    G.latestMetrics[m.device_id] = Object.assign({}, prev, m);
  } else {
    G.latestMetrics[m.device_id] = m;
  }

  const info = G.deviceSlotIndex[m.device_id];
  if (!info) return;
  const { siteKey, slot } = info;
  if (siteKey !== G.cur) return;

  // Delegate to dashboard render hooks
  if (typeof window._onMetricsUpdate === 'function') {
    window._onMetricsUpdate(m, siteKey, slot);
  }
}

export async function loadFromAPI() {
  try {
    const apiSites = await api.get('/api/sites');
    G.S = {};
    G.deviceSlotIndex = {};
    G.siteApiIds = {};
    for (const s of apiSites) {
      const key = (s.code || ('site_' + s.id)).toLowerCase();
      G.siteApiIds[key] = s.id;
      G.S[key] = {
        _apiId: s.id, name: s.name, code: s.code,
        desc: s.description || '', responsible: '', _genCount: 0, spr: {},
      };
    }
    for (const s of apiSites) {
      const key = (s.code || ('site_' + s.id)).toLowerCase();
      try {
        const devices = await api.get('/api/devices?site_id=' + s.id);
        const gens = devices.filter(d => d.device_type === 'generator').sort((a, b) => a.id - b.id);
        const ats = devices.filter(d => d.device_type === 'ats');
        G.S[key]._genCount = gens.length;
        for (let i = 0; i < gens.length; i++) {
          const slot = 'g' + (i + 1);
          G.S[key][slot] = {
            _deviceId: gens[i].id, ip: gens[i].ip_address, port: gens[i].port,
            slaveId: gens[i].slave_id, proto: gens[i].protocol || 'tcp', runHours: 0,
          };
          G.deviceSlotIndex[gens[i].id] = { siteKey: key, slot };
        }
        if (ats[0]) {
          G.S[key].spr = {
            _deviceId: ats[0].id, ip: ats[0].ip_address, port: ats[0].port,
            slaveId: ats[0].slave_id,
          };
          G.deviceSlotIndex[ats[0].id] = { siteKey: key, slot: 'spr' };
        }
      } catch (e) {
        console.warn('Failed to load devices for site', s.id, e);
      }
    }
    if (!G.cur || !G.S[G.cur]) G.cur = Object.keys(G.S)[0] || null;
    G.apiAvailable = true;
    ae('🌐 Данные загружены из API');
    return true;
  } catch (e) {
    console.warn('API unavailable, using localStorage', e);
    return false;
  }
}

// Helper: get device_id for current site's slot
export function getDeviceIdForSlot(slot) {
  if (!G.cur || !G.S[G.cur]) return null;
  const cfg = G.S[G.cur][slot];
  return cfg?._deviceId || null;
}

// Helper: get all device IDs for current site
export function getDeviceIdsForSite(siteKey) {
  const sk = siteKey || G.cur;
  if (!sk || !G.S[sk]) return [];
  const ids = [];
  for (const k of Object.keys(G.S[sk])) {
    if (G.S[sk][k]?._deviceId) ids.push(G.S[sk][k]._deviceId);
  }
  return ids;
}

// Helper: get generator slots for current site
export function getGenSlots(siteKey) {
  const sk = siteKey || G.cur;
  if (!sk || !G.S[sk]) return [];
  const n = G.S[sk]._genCount || 0;
  const slots = [];
  for (let i = 1; i <= (n || 2); i++) {
    if (G.S[sk]['g' + i]) slots.push('g' + i);
  }
  if (!slots.length) {
    if (G.S[sk].g1) slots.push('g1');
    if (G.S[sk].g2) slots.push('g2');
  }
  return slots;
}
