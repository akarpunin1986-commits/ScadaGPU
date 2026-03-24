// SCADA GPU v5 — Shared mutable state
// All modules import G and access G.S, G.cur, etc.
// Property assignment (G.S = {}) works through the shared reference.

let _S;
try { _S = JSON.parse(localStorage.getItem('s5s')) || {}; } catch(e) { _S = {}; }

export const G = {
  // Core site data
  S: _S,
  cur: localStorage.getItem('s5c') || null,
  editId: null,
  delId: null,
  evts: [],

  // Demo mode
  demo: false,
  demoIv: null,
  dStep: 0,

  // Auth
  currentUser: null,

  // Device mapping
  deviceSlotIndex: {},   // device_id → {siteKey, slot, deviceType}
  latestMetrics: {},     // device_id → last WS metrics
  latestOnlineTime: {},  // device_id → epoch ms

  // Alarms
  alarmDefs: {},
  alarmDefsLoaded: false,
  _alarmFirstSeen: {},   // deviceId → {alarmCode → epochMs}

  // API / WS
  siteApiIds: {},        // siteKey → apiSiteId
  apiAvailable: false,
  ws: null,
  wsReconnectTimer: null,
  wsReconnectDelay: 3000,
  WS_RECONNECT_MAX: 30000,

  // Navigation
  curView: 'monitoring',
  curEq: {},
  sbExp: new Set(),

  // Archive
  archiveMode: false,
  arcState: { slot: 'g1', hours: 1, group: 'power', almPage: 0, almLimit: 50, selectedFields: null },
  arcChart: null,

  // Power chart
  pwChart: null,
  pwHours: 1,
  pwMetrics: { bus: true, mains: false, load: false },

  // Event panel
  _serverEvts: [],
  _evtNewCount: 0,

  // SPR control
  sprCurrentConfig: null,
  sprSelectedLoadMode: null,
  sprCfgDirty: false,
  sprCfgReading: false,

  // Login state
  loResendTimer: null,
  loResendCD: 60,
  qrPollInterval: null,
  qrToken: null,

  // AI config
  _aiDbData: null,
  _aiEditPid: null,

  // Sanek
  _snOpen: false,
  _snSid: null,
  _snMsgCount: 0,
  _snHistOpen: false,
  _snSending: false,
};

// Persist to localStorage
export function sv() {
  localStorage.setItem('s5s', JSON.stringify(G.S));
  localStorage.setItem('s5c', G.cur || '');
}

// Add event to log
export function ae(m) {
  const now = new Date().toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  G.evts.unshift({ t: now, m, category: 'LOCAL' });
  if (G.evts.length > 40) G.evts.pop();
  // _renderEvtPanel will be called by the events module
  if (typeof window._renderEvtPanel === 'function') window._renderEvtPanel();
}
