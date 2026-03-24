// SCADA GPU v5 — Theme management
// Extracted from legacy.js Phase 1

import { $ } from './utils.js';

// Init theme from localStorage on load
(function () {
  const saved = localStorage.getItem('s5theme');
  if (saved) document.documentElement.setAttribute('data-theme', saved);
})();

export function toggleTheme() {
  const html = document.documentElement;
  const isLight = html.getAttribute('data-theme') === 'light';
  const next = isLight ? 'dark' : 'light';
  html.setAttribute('data-theme', next);
  localStorage.setItem('s5theme', next);
  updateThemeBtn();
  // updateChartTheme is called from legacy.js via window hook
  if (typeof window._updateChartTheme === 'function') window._updateChartTheme();
  if (typeof window._snUpdateThemeColors === 'function') window._snUpdateThemeColors();
}

export function updateThemeBtn() {
  const btn = $('themeBtn');
  if (!btn) return;
  const isLight = document.documentElement.getAttribute('data-theme') === 'light';
  btn.textContent = isLight ? '🌙 Тёмная тема' : '☀️ Светлая тема';
}

export function getChartColors() {
  const isLight = document.documentElement.getAttribute('data-theme') === 'light';
  return {
    grid: isLight ? 'rgba(0,0,0,.1)' : 'rgba(40,60,100,.35)',
    border: isLight ? 'rgba(0,0,0,.15)' : 'rgba(40,60,100,.5)',
    tick: isLight ? '#4a5568' : '#7a8ca0'
  };
}

setTimeout(updateThemeBtn, 0);
