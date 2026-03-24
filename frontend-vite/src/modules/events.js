import { G } from './state.js';
import { $, esc } from './utils.js';
import { API_BASE } from './api.js';
import { EVT_CAT_LABELS, EVT_CAT_CLS } from './constants.js';

async function loadServerEvents(){
  if(!G.cur)return;
  try{
    const siteId=G.siteApiIds[G.cur];if(!siteId)return;
    const r=await fetch(API_BASE+'/api/events/latest?site_id='+siteId+'&limit=100');
    if(r.ok){G._serverEvts=await r.json();_renderEvtPanel()}
  }catch(e){console.warn('loadServerEvents:',e)}
}

function _addRealtimeEvent(ev){
  // Фильтр: показываем только события текущего объекта
  if(G.cur&&G.siteApiIds[G.cur]&&ev.site_id&&ev.site_id!==G.siteApiIds[G.cur])return;
  G._serverEvts.unshift(ev);if(G._serverEvts.length>120)G._serverEvts.pop();
  const panel=$('evPanel');if(panel&&panel.classList.contains('collapsed'))G._evtNewCount++;
  _renderEvtPanel()
}

function _fmtEvTime(iso){
  if(!iso)return '';
  // Server stores UTC — append Z so JS converts to local (MSK) timezone
  const d=new Date(iso.endsWith('Z')||iso.includes('+')?iso:iso+'Z'),now=new Date();
  const time=d.toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit',second:'2-digit'});
  // Show date if not today
  if(d.toDateString()!==now.toDateString()){
    return d.toLocaleDateString('ru-RU',{day:'2-digit',month:'2-digit'})+' '+time;
  }
  return time;
}

function _renderEvtPanel(){
  const el=$('evL');if(!el)return;
  // Merge: server events first, then local UI events
  const all=[];
  for(const e of G._serverEvts.slice(0,100)){
    const sc=e.site_code?'['+e.site_code+'] ':'';
    all.push({t:_fmtEvTime(e.created_at),m:sc+(e.message||''),cat:e.category||'SYSTEM',code:e.event_code||''})
  }
  for(const e of G.evts.slice(0,Math.max(0,10))){
    all.push({t:e.t,m:e.m,cat:e.category||'LOCAL',code:''})
  }
  if(!all.length){el.innerHTML='<div style="color:var(--t4);font-size:11px;padding:4px 0">Нет событий</div>';return}
  el.innerHTML=all.map(e=>{const isCrit=e.code==='gen_critical_stop'||e.code==='gen_critical_start';const cls=isCrit?' er-crit':'';return`<div class="er${cls}"><span class="et">${e.t}</span><span class="ev-cat ev-cat-${EVT_CAT_CLS[e.cat]||'sys'}">${EVT_CAT_LABELS[e.cat]||e.cat}</span><span>${esc(e.m)}</span></div>`}).join('');
  // Badge
  const badge=$('evBadge');if(badge)badge.textContent=G._evtNewCount>0?G._evtNewCount:'';
}

function toggleEvPanel(){
  const p=$('evPanel');if(!p)return;
  p.classList.toggle('collapsed');
  if(!p.classList.contains('collapsed')){G._evtNewCount=0;_renderEvtPanel()}
  try{localStorage.setItem('evCollapsed',p.classList.contains('collapsed')?'1':'0')}catch(e){}
}

export { loadServerEvents, _addRealtimeEvent, _fmtEvTime, _renderEvtPanel, toggleEvPanel };

// Expose globally so state.js and api.js can call them
window._renderEvtPanel = _renderEvtPanel;
window._addRealtimeEvent = _addRealtimeEvent;
