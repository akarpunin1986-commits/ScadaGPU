// SCADA GPU v5 — DOM helpers & formatters
// Extracted from legacy.js Phase 1

export const $ = id => document.getElementById(id);

export function esc(s) {
  const d = document.createElement('div');
  d.textContent = s == null ? '' : String(s);
  return d.innerHTML;
}

export function _v(v, d) { return v != null ? v : d; }
export function _f1(v) { return v != null ? v.toFixed(1) : '—'; }
export function _f2(v) { return v != null ? v.toFixed(2) : '—'; }

export function R(a, b) { return +(a + Math.random() * (b - a)).toFixed(1); }
export function RI(a, b) { return Math.floor(a + Math.random() * (b - a)); }

export function now() {
  return new Date().toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

export function showM(n) { $('m-' + n).classList.add('sh'); }
export function hideM(n) { $('m-' + n).classList.remove('sh'); }

export function fmtAlarmTime(epochMs) {
  if (!epochMs) return '';
  const d = new Date(epochMs);
  const pad = n => String(n).padStart(2, '0');
  return pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds()) + ' ' + pad(d.getDate()) + '.' + pad(d.getMonth() + 1);
}

export function fmtAlarmDuration(epochMs) {
  if (!epochMs) return '';
  const min = Math.round((Date.now() - epochMs) / 60000);
  if (min < 1) return 'только что';
  if (min < 60) return min + ' мин';
  const h = Math.floor(min / 60), m = min % 60;
  if (h < 24) return h + 'ч ' + m + 'мин';
  const dd = Math.floor(h / 24);
  return dd + 'д ' + (h % 24) + 'ч';
}
