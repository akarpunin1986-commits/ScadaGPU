// SCADA GPU v5 — Archive page, charts, date picker, power chart, zoom
// Extracted from legacy.js

import { G, ae } from './state.js';
import { $, esc, showM, hideM } from './utils.js';
import { api, API_BASE, getDeviceIdForSlot, getGenSlots } from './api.js';
import { getChartColors } from './theme.js';
import { ARC_GROUPS_GEN, ARC_GROUPS_SPR, ARC_TABS_GEN, ARC_TABS_SPR, PW_COLORS, PW_TITLES } from './constants.js';

// === Chart groups/tabs ===
function arcGetGroups(){return G.arcState.slot==='spr'?ARC_GROUPS_SPR:ARC_GROUPS_GEN}
function arcGetTabs(){return G.arcState.slot==='spr'?ARC_TABS_SPR:ARC_TABS_GEN}

// === CHART_DEFAULTS ===
const CHART_DEFAULTS={responsive:true,maintainAspectRatio:false,animation:{duration:400},
interaction:{mode:'index',intersect:false,axis:'x'},
plugins:{
  legend:{position:'top',align:'start',
    labels:{color:'#c8d4e6',font:{family:'Outfit',size:12,weight:'500'},padding:16,usePointStyle:true,pointStyle:'circle',pointStyleWidth:10,
      generateLabels:function(chart){
        const orig=Chart.defaults.plugins.legend.labels.generateLabels(chart);
        return orig.map(item=>{
          const ds=chart.data.datasets[item.datasetIndex];
          if(ds&&ds.data&&ds.data.length){
            const last=ds.data[ds.data.length-1];
            const val=last&&last.y!=null?last.y.toFixed(1):'—';
            item.text=ds.label+' ('+val+')';
          }
          return item;
        });
      }
    }
  },
  tooltip:{
    backgroundColor:'rgba(10,15,26,.95)',borderColor:'rgba(64,144,255,.3)',borderWidth:1,
    titleColor:'#e8edf5',bodyColor:'#c8d4e6',footerColor:'#5a6a80',
    titleFont:{family:'JetBrains Mono',size:12,weight:'600'},
    bodyFont:{family:'JetBrains Mono',size:11},
    footerFont:{family:'JetBrains Mono',size:9},
    padding:12,cornerRadius:8,displayColors:true,boxPadding:4,
    caretSize:6,caretPadding:8,
    callbacks:{
      label:function(ctx){return ' '+ctx.dataset.label.split(' (')[0]+': '+(ctx.parsed.y!=null?ctx.parsed.y.toFixed(2):'—')},
      footer:function(items){if(!items.length)return '';const d=items[0].parsed.x;return new Date(d).toLocaleString('ru-RU',{day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'})}
    }
  },
  crosshair:false,
  zoom:false
},
scales:(function(){const c=getChartColors();return{
  x:{type:'time',
    grid:{color:c.grid,lineWidth:1,drawTicks:true,tickLength:4},
    border:{color:c.border},
    ticks:{color:c.tick,font:{family:'JetBrains Mono',size:10},maxRotation:0,autoSkipPadding:20,
      callback:function(val,idx,ticks){
        var xScale=this.chart.scales.x;
        var rangeMs=(xScale.max||0)-(xScale.min||0);
        var d=new Date(val);
        var hh=String(d.getHours()).padStart(2,'0');
        var mm=String(d.getMinutes()).padStart(2,'0');
        var ss=String(d.getSeconds()).padStart(2,'0');
        if(rangeMs>86400000){
          // >1 day: show date + time
          var dd=String(d.getDate()).padStart(2,'0');
          var mo=String(d.getMonth()+1).padStart(2,'0');
          return dd+'.'+mo+' '+hh+':'+mm;
        }
        if(rangeMs<3600000) return hh+':'+mm+':'+ss;
        return hh+':'+mm;
      }
    },
    time:{tooltipFormat:'dd.MM.yyyy HH:mm:ss',displayFormats:{second:'HH:mm:ss',minute:'HH:mm',hour:'HH:mm',day:'dd.MM',week:'dd.MM',month:'MMM yyyy'}}
  },
  y:{
    grid:{color:c.grid,lineWidth:1},
    border:{color:c.border},
    ticks:{color:c.tick,font:{family:'JetBrains Mono',size:10},padding:8,
      callback:function(v){return v>=1000?(v/1000).toFixed(1)+'k':v>=100?Math.round(v):v.toFixed(1)}
    }
  }
}})()
};

// === Helper: _utcDate ===
function _utcDate(s){if(!s)return new Date(NaN);if(typeof s==='string'&&!s.endsWith('Z')&&!s.includes('+'))return new Date(s+'Z');return new Date(s)}

// === Date Picker state (module-local) ===
const dpState={arcFrom:null,arcTo:null,_view:{},_open:null};
const DP_MONTHS=['Январь','Февраль','Март','Апрель','Май','Июнь','Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь'];
const DP_DAYS=['Пн','Вт','Ср','Чт','Пт','Сб','Вс'];

// === Archive page ===
function showArchive(siteKey,opts){stopB24Poll();G.curView='archive';setTimeout(showUserProfile,0);
const keys=Object.keys(G.S);if(!keys.length){ae('⚠ Нет объектов');return}
const sk=siteKey||(G.cur&&G.S[G.cur]?G.cur:keys[0]);
G.arcState.siteKey=sk;G.archiveMode=true;
const s=G.S[sk],mn=$('mainArea');
// Site selector options
let siteOpts=keys.map(k=>`<option value="${k}"${k===sk?' selected':''}>${esc(G.S[k].name)}</option>`).join('');
// Device buttons for selected site
const _gSlots=getGenSlots(sk);
const firstSlot=_gSlots.find(sl=>s[sl]?.ip)||( s.spr?.ip?'spr':null);
let devBtns='';
for(const sl of _gSlots){if(s[sl]?.ip)devBtns+=`<button class="arc-dev${sl===firstSlot?' on':''}" onclick="arcDev(this,'${sl}')">Генератор ${sl.slice(1)}</button>`}
if(s.spr?.ip)devBtns+=`<button class="arc-dev${'spr'===firstSlot?' on':''}" onclick="arcDev(this,'spr')">ШПР</button>`;
G.arcState.slot=firstSlot||'g1';G.arcState.hours=1;G.arcState.group='power';G.arcState.almPage=0;G.arcState.selectedFields=null;
mn.innerHTML=`
<div class="dh"><div class="dt"><h1>📊 Архив</h1>
<select class="fi" id="arcSiteSelect" style="margin-left:12px;width:auto;padding:6px 12px;font-size:13px;font-weight:500;background:var(--bg3);border-color:var(--bd2)" onchange="arcSwitchSite(this.value)">${siteOpts}</select></div>
<div class="da"><button onclick="archiveMode=false;renderDash()">← Мониторинг</button></div></div>
<div class="arc-ctl">
<div class="arc-devs" id="arcDevsWrap">${devBtns}</div>
<div class="arc-time">
<button class="arc-tb on" onclick="arcRange(this,1)">1ч</button>
<button class="arc-tb" onclick="arcRange(this,6)">6ч</button>
<button class="arc-tb" onclick="arcRange(this,24)">24ч</button>
<button class="arc-tb" onclick="arcRange(this,168)">7д</button>
<button class="arc-tb" onclick="arcRange(this,720)">30д</button>
<span id="arcZoomLabel" class="zoom-lbl"></span>
<div class="dp-wrap"><button class="dp-btn" id="arcFromBtn" onclick="dpToggle('arcFrom')">📅 От</button><div class="dp-drop" id="arcFromDrop"></div></div>
<span style="color:var(--t3);font-size:11px">—</span>
<div class="dp-wrap"><button class="dp-btn" id="arcToBtn" onclick="dpToggle('arcTo')">📅 До</button><div class="dp-drop" id="arcToDrop"></div></div>
</div></div>
<div class="tbs" id="arcMainTabs" style="margin-bottom:12px">
<button class="tb on" onclick="arcTab(this,'arcCharts')">📈 Графики</button>
<button class="tb" onclick="arcTab(this,'arcAlarms')">🔴 Журнал аварий</button>
<button class="tb" onclick="arcTab(this,'arcDisk')">💾 Хранилище</button></div>
<div id="arcCharts" style="display:block">
<div class="tbs" style="margin-bottom:8px" id="arcChartTabs"></div>
<div class="arc-fchecks" id="arcFieldChecks"></div>
<div class="arc-chart-wrap"><canvas id="arcCanvas"></canvas></div>
<div id="arcFieldStats" class="arc-fstats"></div>
<div id="arcDesc" class="arc-desc"></div>
<div id="arcStats" class="arc-stats"></div></div>
<div id="arcAlarms" style="display:none">
<div class="arc-flt">
<select class="fi" id="arcSev" style="width:140px;padding:6px 8px;font-size:11px" onchange="arcLoadAlarms()">
<option value="">Все уровни</option><option value="error">🔴 Ошибка</option><option value="warning">🟡 Предупр.</option><option value="mains">🔵 Сеть</option></select>
<label style="display:flex;align-items:center;gap:4px;font-size:11px;color:var(--t2)"><input type="checkbox" id="arcActiveOnly" style="accent-color:var(--g)" onchange="arcLoadAlarms()"> Только активные</label>
<button class="sb-btn" style="padding:5px 10px;font-size:11px;width:auto" onclick="arcLoadAlarms()">🔄 Обновить</button></div>
<div id="arcAlarmTable"></div>
<div class="arc-pag" id="arcPag"></div></div>
<div id="arcDisk" style="display:none"><div id="arcDiskInfo"></div></div>`;
arcRenderChartTabs();if(!opts?.skipLoad){arcLoadChart();arcLoadAlarms();arcLoadDisk();}
}

// === Device selection ===
function arcDev(btn,slot){
btn.parentElement.querySelectorAll('.arc-dev').forEach(b=>b.classList.remove('on'));
btn.classList.add('on');G.arcState.slot=slot;G.arcState.almPage=0;
G.arcState.selectedFields=null;arcRenderChartTabs();arcLoadChart();arcLoadAlarms();
}

// === Field archive (open from monitoring) ===
function openFieldArchive(slot,field,group){
showArchive(G.cur,{skipLoad:true});
G.arcState.slot=slot;
G.arcState.group=group||'engine';
G.arcState.selectedFields=field?new Set([field]):null;
// Update device button selection
const devWrap=$('arcDevsWrap');
if(devWrap){devWrap.querySelectorAll('.arc-dev').forEach(b=>{
b.classList.toggle('on',b.textContent.includes(slot.startsWith('g')?slot.slice(1):'ШПР'))})}
arcRenderChartTabs();arcRenderFieldChecks();arcLoadChart();arcLoadAlarms();arcLoadDisk();
}

// === Site switching ===
function arcSwitchSite(siteKey){
if(!G.S[siteKey])return;G.arcState.siteKey=siteKey;
const s=G.S[siteKey];
const _gs2=getGenSlots(siteKey);
const firstSlot=_gs2.find(sl=>s[sl]?.ip)||(s.spr?.ip?'spr':null);
let devBtns='';
for(const sl of _gs2){if(s[sl]?.ip)devBtns+=`<button class="arc-dev${sl===firstSlot?' on':''}" onclick="arcDev(this,'${sl}')">Генератор ${sl.slice(1)}</button>`}
if(s.spr?.ip)devBtns+=`<button class="arc-dev${'spr'===firstSlot?' on':''}" onclick="arcDev(this,'spr')">ШПР</button>`;
const wrap=$('arcDevsWrap');if(wrap)wrap.innerHTML=devBtns;
G.arcState.slot=firstSlot||'g1';G.arcState.almPage=0;
arcRenderChartTabs();arcLoadChart();arcLoadAlarms();arcLoadDisk();
}

// === Internal: get device id for current archive slot ===
function arcGetDeviceId(slot){
const sk=G.arcState.siteKey;if(!sk||!G.S[sk])return null;
return G.S[sk][slot]?._deviceId||null;
}

// === Time range ===
function arcRange(btn,hours){
btn.parentElement.querySelectorAll('.arc-tb').forEach(b=>b.classList.remove('on'));
btn.classList.add('on');G.arcState.hours=hours;G.arcState.almPage=0;
dpState.arcFrom=null;dpState.arcTo=null;
const fb=$('arcFromBtn'),tb=$('arcToBtn');
if(fb){fb.textContent='📅 От';fb.classList.remove('has-val')}
if(tb){tb.textContent='📅 До';tb.classList.remove('has-val')}
_updateZoomLabel('arcZoomLabel',hours);
arcLoadChart();arcLoadAlarms();
}

function arcCustomRange(){
if(!dpState.arcFrom||!dpState.arcTo)return;
document.querySelectorAll('.arc-time .arc-tb').forEach(b=>b.classList.remove('on'));
G.arcState.hours=null;G.arcState.customFrom=dpState.arcFrom;G.arcState.customTo=dpState.arcTo;G.arcState.almPage=0;
arcLoadChart();arcLoadAlarms();
}

// === Date Picker ===
function dpToggle(id){
const drop=$(id+'Drop');if(!drop)return;
const isOpen=drop.classList.contains('open');
document.querySelectorAll('.dp-drop.open').forEach(d=>d.classList.remove('open'));
if(!isOpen){
const now=dpState[id]?new Date(dpState[id]):new Date();
dpState._view[id]={year:now.getFullYear(),month:now.getMonth(),hour:now.getHours(),minute:now.getMinutes()};
if(dpState[id]){const d=new Date(dpState[id]);dpState._view[id].selDay=d.getDate();dpState._view[id].selMonth=d.getMonth();dpState._view[id].selYear=d.getFullYear()}
dpRender(id);drop.classList.add('open');dpState._open=id;
}else{dpState._open=null}
}

function dpRender(id){
const drop=$(id+'Drop'),v=dpState._view[id];if(!drop||!v)return;
const year=v.year,month=v.month;
const firstDay=new Date(year,month,1).getDay();
const shift=firstDay===0?6:firstDay-1;
const daysInMonth=new Date(year,month+1,0).getDate();
const daysInPrev=new Date(year,month,0).getDate();
const today=new Date(),ty=today.getFullYear(),tm=today.getMonth(),td=today.getDate();

let html=`<div class="dp-hdr"><button class="dp-nav" onclick="dpNav('${id}',-1)">◀</button><span>${DP_MONTHS[month]} ${year}</span><button class="dp-nav" onclick="dpNav('${id}',1)">▶</button></div>`;
html+='<div class="dp-wk">'+DP_DAYS.map(d=>`<span>${d}</span>`).join('')+'</div>';
html+='<div class="dp-days">';
for(let i=0;i<shift;i++){const d=daysInPrev-shift+1+i;html+=`<div class="dp-d other" onclick="dpPickDay('${id}',${year},${month-1},${d})">${d}</div>`}
for(let d=1;d<=daysInMonth;d++){
let cls='dp-d';
if(d===td&&month===tm&&year===ty)cls+=' today';
if(v.selDay===d&&v.selMonth===month&&v.selYear===year)cls+=' sel';
html+=`<div class="${cls}" onclick="dpPickDay('${id}',${year},${month},${d})">${d}</div>`}
const remaining=7-((shift+daysInMonth)%7);
if(remaining<7)for(let d=1;d<=remaining;d++){html+=`<div class="dp-d other" onclick="dpPickDay('${id}',${year},${month+1},${d})">${d}</div>`}
html+='</div>';
html+=`<div class="dp-time"><label>Время:</label><input type="number" min="0" max="23" value="${String(v.hour).padStart(2,'0')}" id="${id}H" onchange="dpTimeChange('${id}')">
<span style="color:var(--t3)">:</span>
<input type="number" min="0" max="59" value="${String(v.minute).padStart(2,'0')}" id="${id}M" onchange="dpTimeChange('${id}')"></div>`;
html+=`<button class="dp-apply" onclick="dpApply('${id}')">Применить</button>`;
drop.innerHTML=html;
}

function dpNav(id,dir){
const v=dpState._view[id];v.month+=dir;
if(v.month>11){v.month=0;v.year++}if(v.month<0){v.month=11;v.year--}
dpRender(id);
}

function dpPickDay(id,y,m,d){
if(m>11){m=0;y++}if(m<0){m=11;y--}
const v=dpState._view[id];v.selDay=d;v.selMonth=m;v.selYear=y;v.year=y;v.month=m;
dpRender(id);
}

function dpTimeChange(id){
const v=dpState._view[id];
const h=$(id+'H'),m=$(id+'M');
if(h)v.hour=Math.max(0,Math.min(23,parseInt(h.value)||0));
if(m)v.minute=Math.max(0,Math.min(59,parseInt(m.value)||0));
}

function dpApply(id){
const v=dpState._view[id];
if(v.selDay==null)return;
const dt=new Date(v.selYear,v.selMonth,v.selDay,v.hour,v.minute);
dpState[id]=dt.toISOString();
const btn=$(id+'Btn');
if(btn){btn.textContent=dt.toLocaleString('ru-RU',{day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit'});btn.classList.add('has-val')}
const drop=$(id+'Drop');if(drop)drop.classList.remove('open');dpState._open=null;
arcCustomRange();
}

// Close date picker on outside click
document.addEventListener('click',function(e){
if(dpState._open&&!e.target.closest('.dp-wrap')){
document.querySelectorAll('.dp-drop.open').forEach(d=>d.classList.remove('open'));dpState._open=null}
});

// === Tabs ===
function arcTab(btn,panelId){
const tabs=$('arcMainTabs');if(tabs)tabs.querySelectorAll('.tb').forEach(b=>b.classList.remove('on'));
btn.classList.add('on');
['arcCharts','arcAlarms','arcDisk'].forEach(id=>{const el=$(id);if(el)el.style.display='none'});
const target=$(panelId);if(target)target.style.display='block';
if(panelId==='arcDisk')arcLoadDisk();
}

function arcChGroup(btn,group){
btn.closest('.tbs').querySelectorAll('.tb').forEach(b=>b.classList.remove('on'));
btn.classList.add('on');G.arcState.group=group;
// Reset selectedFields to all fields in new group
const grp=arcGetGroups()[group];
G.arcState.selectedFields=grp?new Set(grp.fields.split(',')):null;
arcRenderFieldChecks();arcLoadChart();
}

function arcRenderChartTabs(){
const wrap=$('arcChartTabs');if(!wrap)return;
const tabs=arcGetTabs();const groups=arcGetGroups();
// Reset group if current group doesn't exist for this device type
if(!groups[G.arcState.group])G.arcState.group=tabs[0]?.key||'power';
wrap.innerHTML=tabs.map(t=>`<button class="tb${t.key===G.arcState.group?' on':''}" onclick="arcChGroup(this,'${t.key}')">${t.label}</button>`).join('');
// Init selectedFields if not set
const grp=groups[G.arcState.group];
if(!G.arcState.selectedFields&&grp)G.arcState.selectedFields=new Set(grp.fields.split(','));
arcRenderFieldChecks();
}

function arcRenderFieldChecks(){
const wrap=$('arcFieldChecks');if(!wrap)return;
const grp=arcGetGroups()[G.arcState.group];
if(!grp){wrap.innerHTML='';return}
const fields=grp.fields.split(',');
const sel=G.arcState.selectedFields||new Set(fields);
wrap.innerHTML=fields.map((f,i)=>{
const checked=sel.has(f)?'checked':'';
const color=grp.colors[i]||'#888';
const lbl=(grp.labels[f]||f).replace(/\s*\(.*\)/,'');
return`<label class="arc-fchk"><input type="checkbox" ${checked} onchange="arcToggleField('${f}')"><span class="arc-fchk-dot" style="background:${color}"></span>${lbl}</label>`}).join('');
}

function arcToggleField(field){
const grp=arcGetGroups()[G.arcState.group];if(!grp)return;
if(!G.arcState.selectedFields)G.arcState.selectedFields=new Set(grp.fields.split(','));
if(G.arcState.selectedFields.has(field))G.arcState.selectedFields.delete(field);
else G.arcState.selectedFields.add(field);
if(G.arcState.selectedFields.size===0){G.arcState.selectedFields.add(field);
const wrap=$('arcFieldChecks');if(wrap){const cb=wrap.querySelector(`input[onchange*="${field}"]`);if(cb)cb.checked=true}return}
arcLoadChart();
}

// === Data loading ===
function arcBucket(hours){
if(hours<=1)return 0;if(hours<=6)return 60;if(hours<=24)return 300;if(hours<=168)return 1800;return 3600;
}

async function arcLoadChart(){
const devId=arcGetDeviceId(G.arcState.slot);
if(!devId){arcRenderNoData('Устройство не настроено');return}
const grp=arcGetGroups()[G.arcState.group],hours=G.arcState.hours;
if(!grp){arcRenderNoData('Нет данных для этой вкладки');return}
// Use selectedFields if set, otherwise all group fields
const allFields=grp.fields.split(',');
const activeFields=G.arcState.selectedFields?allFields.filter(f=>G.arcState.selectedFields.has(f)):allFields;
if(!activeFields.length){arcRenderNoData('Выберите хотя бы один параметр');return}
// _extraFetch: additional fields needed for _computed but not rendered directly
const extraFields=grp._extraFetch?grp._extraFetch.split(','):[];
const fieldsParam=[...new Set([...activeFields,...extraFields])].join(',');
const bucket=hours?arcBucket(hours):0;
let url;
if(hours){
if(bucket>0)url=`/api/history/metrics/${devId}/downsampled?last_hours=${hours}&bucket_seconds=${bucket}&fields=${fieldsParam}`;
else url=`/api/history/metrics/${devId}?last_hours=${hours}&fields=${fieldsParam}&limit=5000`;
}else{
const from=new Date(G.arcState.customFrom).toISOString(),to=new Date(G.arcState.customTo).toISOString();
const rangeH=(new Date(G.arcState.customTo)-new Date(G.arcState.customFrom))/3600000;
const cb=arcBucket(rangeH);
if(cb>0)url=`/api/history/metrics/${devId}/downsampled?start=${from}&end=${to}&bucket_seconds=${cb}&fields=${fieldsParam}`;
else url=`/api/history/metrics/${devId}?start=${from}&end=${to}&fields=${fieldsParam}&limit=5000`;
}
try{
const data=await api.get(url);arcRenderChart(data,grp);
arcRenderFieldStats(data,grp);
const stats=await api.get(`/api/history/metrics/${devId}/stats`);arcRenderStats(stats);
}catch(e){console.warn('Archive chart error:',e);arcRenderNoData('Ошибка загрузки: '+e.message)}
}

async function arcLoadAlarms(){
const devId=arcGetDeviceId(G.arcState.slot);
if(!devId){const el=$('arcAlarmTable');if(el)el.innerHTML='<div style="color:var(--t3);font-size:12px;text-align:center;padding:30px">Устройство не настроено</div>';return}
const sev=$('arcSev')?.value||'',activeOnly=$('arcActiveOnly')?.checked;
/* Alarm journal uses separate wider time window: min 24h, or match chart range if bigger */
const almHours=Math.max(G.arcState.hours||1,24);
let url=`/api/history/alarms?device_id=${devId}&limit=${G.arcState.almLimit}&offset=${G.arcState.almPage*G.arcState.almLimit}`;
if(sev)url+=`&severity=${sev}`;if(activeOnly)url+='&is_active=true';url+=`&last_hours=${almHours}`;
try{const alarms=await api.get(url);arcRenderAlarms(alarms)}
catch(e){const el=$('arcAlarmTable');if(el)el.innerHTML=`<div style="color:var(--r);font-size:12px;padding:20px;text-align:center">Ошибка: ${esc(e.message)}</div>`}
}

async function arcLoadDisk(){
try{const d=await api.get('/api/history/disk');arcRenderDisk(d)}
catch(e){const el=$('arcDiskInfo');if(el)el.innerHTML=`<div style="color:var(--r);font-size:12px;padding:20px;text-align:center">Ошибка: ${esc(e.message)}</div>`}
}

// === Crosshair vertical line plugin ===
const crosshairPlugin={id:'crosshairLine',
afterDraw(chart){
  if(chart.tooltip&&chart.tooltip._active&&chart.tooltip._active.length){
    const x=chart.tooltip._active[0].element.x;
    const yA=chart.scales.y;
    const ctx=chart.ctx;
    ctx.save();ctx.beginPath();ctx.moveTo(x,yA.top);ctx.lineTo(x,yA.bottom);
    ctx.lineWidth=1;ctx.strokeStyle='rgba(100,140,200,.4)';ctx.setLineDash([4,3]);ctx.stroke();ctx.restore();
  }
}};

// === Chart rendering ===
function arcRenderChart(data,grp){
const canvas=$('arcCanvas');if(!canvas)return;
if(G.arcChart){G.arcChart.destroy();G.arcChart=null}
if(!data||!data.length){arcRenderNoData('Нет данных за выбранный период');return}
if(typeof Chart==='undefined'){arcRenderNoData('Chart.js не загружен');return}
const allFields=grp.fields.split(',');
const fieldNames=G.arcState.selectedFields?allFields.filter(f=>G.arcState.selectedFields.has(f)):allFields;
const timeKey=data[0].bucket!==undefined?'bucket':'timestamp';

// Calculate adaptive point radius based on data density
const totalPts=data.length;
const showPts=totalPts<80;
const ptRadius=totalPts<30?3:totalPts<80?2:0;
const hoverRadius=totalPts<200?4:3;

const datasets=fieldNames.map((f,i)=>{
  const origIdx=allFields.indexOf(f);
  const clr=grp.colors[origIdx>=0?origIdx:i]||'#888';
  const pts=data.map(row=>({x:_utcDate(row[timeKey]),y:row[f]!=null?Number(row[f]):null}));
  const hasData=pts.some(p=>p.y!=null);
  if(!hasData) return null;
  return {
    label:grp.labels[f]||f,
    data:pts,
    borderColor:clr,
    backgroundColor:clr+'18',
    borderWidth:2.2,
    pointRadius:showPts?ptRadius:0,
    pointHoverRadius:hoverRadius,
    pointBackgroundColor:clr,
    pointBorderColor:clr,
    pointHitRadius:8,
    tension:0.25,
    fill:fieldNames.length<=2,
    spanGaps:false
  };
}).filter(Boolean);

// Append computed datasets (e.g. P load = busbar_p + mains_total_p)
if(grp._computed){
grp._computed.forEach(c=>{
  const pts=data.map(row=>({x:_utcDate(row[timeKey]),y:c.calc(row)}));
  const hasData=pts.some(p=>p.y!=null&&p.y!==0);
  if(hasData)datasets.push({
    label:c.label,data:pts,borderColor:c.color,backgroundColor:c.color+'18',
    borderWidth:2.2,pointRadius:showPts?ptRadius:0,pointHoverRadius:hoverRadius,
    pointBackgroundColor:c.color,pointBorderColor:c.color,pointHitRadius:8,
    tension:0.25,fill:false,spanGaps:false
  });
});
}

// Compute Y-axis bounds with padding
let yMin=Infinity,yMax=-Infinity;
for(const ds of datasets){
  for(const pt of ds.data){if(pt.y!=null){if(pt.y<yMin)yMin=pt.y;if(pt.y>yMax)yMax=pt.y}}
}
if(!isFinite(yMin)){yMin=0;yMax=100}
const yRange=yMax-yMin||1;
const yPad=yRange*0.08;
const sugMin=Math.max(0,yMin-yPad);
const sugMax=yMax+yPad;

G.arcChart=new Chart(canvas,{type:'line',data:{datasets},
plugins:[crosshairPlugin],
options:{
  ...CHART_DEFAULTS,
  plugins:{...CHART_DEFAULTS.plugins},
  scales:(function(){const c=getChartColors();return{
    x:{...CHART_DEFAULTS.scales.x, grid:{...CHART_DEFAULTS.scales.x.grid,color:c.grid},border:{color:c.border},ticks:{...CHART_DEFAULTS.scales.x.ticks,color:c.tick}},
    y:{...CHART_DEFAULTS.scales.y, grid:{...CHART_DEFAULTS.scales.y.grid,color:c.grid},border:{color:c.border},ticks:{...CHART_DEFAULTS.scales.y.ticks,color:c.tick},
      suggestedMin:sugMin,suggestedMax:sugMax,
      title:{display:!!grp.unit,text:grp.unit,color:c.tick,font:{family:'Outfit',size:11,weight:'500'},padding:{bottom:6}}
    }
  }})()

}});
// Update legend with latest values after render
G.arcChart.update();
// Show chart description
const descEl=$('arcDesc');
if(descEl)descEl.innerHTML=grp.desc?`<b>ℹ️ Пояснение:</b> ${grp.desc}`:'';
}

function arcRenderFieldStats(data,grp){
const wrap=$('arcFieldStats');if(!wrap)return;
if(!data||!data.length){wrap.innerHTML='';return}
const allF=grp.fields.split(',');
const fieldNames=G.arcState.selectedFields?allF.filter(f=>G.arcState.selectedFields.has(f)):allF;
let html='';
for(let i=0;i<fieldNames.length;i++){
  const f=fieldNames[i];
  const origIdx=allF.indexOf(f);
  const clr=grp.colors[origIdx>=0?origIdx:i]||'#888';
  const vals=data.map(r=>r[f]).filter(v=>v!=null&&isFinite(v));
  if(!vals.length)continue;
  const mn=Math.min(...vals),mx=Math.max(...vals),avg=vals.reduce((a,b)=>a+b,0)/vals.length;
  const last=vals[vals.length-1];
  const lbl=grp.labels[f]||f;
  const shortLbl=lbl.split(' (')[0]; // remove unit from label
  const u=grp.unit?' '+grp.unit:'';
  html+=`<div class="arc-fs" style="border-left-color:${clr}">
<div class="arc-fs-name" style="color:${clr}">${shortLbl}</div>
<div class="arc-fs-row"><span class="arc-fs-lbl">Мин</span><span class="arc-fs-val">${mn.toFixed(1)}${u}</span></div>
<div class="arc-fs-row"><span class="arc-fs-lbl">Средн</span><span class="arc-fs-val">${avg.toFixed(1)}${u}</span></div>
<div class="arc-fs-row"><span class="arc-fs-lbl">Макс</span><span class="arc-fs-val">${mx.toFixed(1)}${u}</span></div>
<div class="arc-fs-row"><span class="arc-fs-lbl">Текущ</span><span class="arc-fs-val" style="color:${clr}">${last.toFixed(1)}${u}</span></div>
</div>`;
}
if(grp._computed){
grp._computed.forEach(c=>{
  const vals=data.map(r=>c.calc(r)).filter(v=>v!=null&&isFinite(v));
  if(!vals.length)return;
  const mn=Math.min(...vals),mx=Math.max(...vals),avg=vals.reduce((a,b)=>a+b,0)/vals.length;
  const last=vals[vals.length-1];
  const shortLbl=c.label.split(' (')[0];
  const u=grp.unit?' '+grp.unit:'';
  html+=`<div class="arc-fs" style="border-left-color:${c.color}">
<div class="arc-fs-name" style="color:${c.color}">${shortLbl}</div>
<div class="arc-fs-row"><span class="arc-fs-lbl">Мин</span><span class="arc-fs-val">${mn.toFixed(1)}${u}</span></div>
<div class="arc-fs-row"><span class="arc-fs-lbl">Средн</span><span class="arc-fs-val">${avg.toFixed(1)}${u}</span></div>
<div class="arc-fs-row"><span class="arc-fs-lbl">Макс</span><span class="arc-fs-val">${mx.toFixed(1)}${u}</span></div>
<div class="arc-fs-row"><span class="arc-fs-lbl">Текущ</span><span class="arc-fs-val" style="color:${c.color}">${last.toFixed(1)}${u}</span></div>
</div>`;
});
}
wrap.innerHTML=html;
}

function arcRenderNoData(msg){
if(G.arcChart){G.arcChart.destroy();G.arcChart=null}
const descEl=$('arcDesc');if(descEl)descEl.innerHTML='';
const fsEl=$('arcFieldStats');if(fsEl)fsEl.innerHTML='';
const el=$('arcStats');if(el)el.innerHTML=`<div style="color:var(--t3);font-size:12px;text-align:center;padding:30px">${msg}</div>`;
}

function arcRenderStats(stats){
const el=$('arcStats');if(!el)return;
el.innerHTML=`<div style="display:flex;gap:16px;flex-wrap:wrap">
<span>📊 Записей: <b>${stats.total_rows?.toLocaleString()||0}</b></span>
<span>📅 Период: <b>${stats.days_stored||0}</b> дней</span>
<span>🕐 От: <b>${stats.oldest?new Date(stats.oldest).toLocaleString('ru-RU'):'—'}</b></span>
<span>🕐 До: <b>${stats.newest?new Date(stats.newest).toLocaleString('ru-RU'):'—'}</b></span></div>`;
}

function arcRenderAlarms(alarms){
const el=$('arcAlarmTable');if(!el)return;
const _RAGG=new Set(['COMMON','SHUTDOWN','WARNING','BLOCK','TRIP_STOP']);
alarms=(alarms||[]).filter(a=>!_RAGG.has(a.alarm_code));
if(!alarms.length){el.innerHTML='<div style="color:var(--t3);font-size:12px;text-align:center;padding:30px">Нет аварий за выбранный период ✓</div>';const p=$('arcPag');if(p)p.innerHTML='';return}
const sevI={error:'🔴',warning:'🟡',mains:'🔵'},sevL={error:'Ошибка',warning:'Предупр.',mains:'Сеть'};
const rows=alarms.map(a=>{
const occ=new Date(a.occurred_at),clr=a.cleared_at?new Date(a.cleared_at):null;
const dur=clr?Math.round((clr-occ)/60000):'—';
return`<tr>
<td style="white-space:nowrap">${occ.toLocaleString('ru-RU')}</td>
<td style="font-family:var(--m)">${esc(a.alarm_code)}</td>
<td>${sevI[a.severity]||'⚪'} ${sevL[a.severity]||a.severity}</td>
<td>${esc(a.message)}</td>
<td>${typeof dur==='number'?dur+' мин':dur}</td>
<td>${a.is_active?'<span style="color:var(--r);font-weight:600">● Активна</span>':'<span style="color:var(--t3)">✓ Снята</span>'}</td></tr>`}).join('');
el.innerHTML=`<table class="pt"><thead><tr><th>Время</th><th>Код</th><th>Уровень</th><th>Сообщение</th><th>Длит.</th><th>Статус</th></tr></thead><tbody>${rows}</tbody></table>`;
const pag=$('arcPag'),hasMore=alarms.length===G.arcState.almLimit;
if(pag)pag.innerHTML=`<div style="display:flex;gap:8px;align-items:center;margin-top:8px">
<button class="sb-btn" style="padding:5px 12px;font-size:11px;width:auto" onclick="arcState.almPage=Math.max(0,arcState.almPage-1);arcLoadAlarms()" ${G.arcState.almPage===0?'disabled style="opacity:.4;pointer-events:none;padding:5px 12px;font-size:11px;width:auto"':''}>← Назад</button>
<span style="font-size:11px;color:var(--t3);font-family:var(--m)">Стр. ${G.arcState.almPage+1}</span>
<button class="sb-btn" style="padding:5px 12px;font-size:11px;width:auto" onclick="arcState.almPage++;arcLoadAlarms()" ${!hasMore?'disabled style="opacity:.4;pointer-events:none;padding:5px 12px;font-size:11px;width:auto"':''}>Вперёд →</button></div>`;
}

function arcRenderDisk(d){
const el=$('arcDiskInfo');if(!el)return;
const pct=d.usage_pct||0;
const barColor=pct>85?'var(--r)':pct>65?'var(--y)':'var(--g)';
el.innerHTML=`<div style="max-width:500px">
<div style="font-size:13px;font-weight:600;margin-bottom:12px">💾 Использование хранилища</div>
<div style="margin-bottom:12px">
<div style="display:flex;justify-content:space-between;font-size:11px;color:var(--t2);margin-bottom:4px">
<span>PostgreSQL</span><span style="font-family:var(--m)">${d.db_size_mb} МБ / ${d.max_db_size_mb} МБ (${pct}%)</span></div>
<div style="height:8px;background:var(--bg);border-radius:4px;overflow:hidden">
<div style="height:100%;width:${Math.min(pct,100)}%;background:${barColor};border-radius:4px;transition:width .5s"></div></div></div>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
<div class="arc-stat-card">
<div style="font-size:10px;color:var(--t3);margin-bottom:4px">Таблица метрик</div>
<div style="font-family:var(--m);font-size:16px;font-weight:600;color:var(--g)">${d.metrics_table_size_mb} МБ</div>
<div style="font-size:10px;color:var(--t3);font-family:var(--m)">${(d.metrics_row_count>=0?d.metrics_row_count:0).toLocaleString()} записей</div></div>
<div class="arc-stat-card">
<div style="font-size:10px;color:var(--t3);margin-bottom:4px">Таблица аварий</div>
<div style="font-family:var(--m);font-size:16px;font-weight:600;color:var(--r)">${(d.alarms_row_count>=0?d.alarms_row_count:0).toLocaleString()}</div>
<div style="font-size:10px;color:var(--t3)">записей</div></div></div></div>`;
}

// === Power chart ===
function showPwChart(initial){
G.pwMetrics={bus:initial==='bus',mains:initial==='mains',load:initial==='load'};
G.pwHours=1;
$('pwChkBus').checked=G.pwMetrics.bus;
$('pwChkMains').checked=G.pwMetrics.mains;
$('pwChkLoad').checked=G.pwMetrics.load;
document.querySelectorAll('#m-pwchart .arc-tb').forEach((b,i)=>b.classList.toggle('on',i===0));
const t=$('pwChartTitle');if(t)t.textContent='📊 '+PW_TITLES[initial]+' — График';
showM('pwchart');
pwLoadChart();
}

function pwToggleMetric(){
G.pwMetrics.bus=$('pwChkBus').checked;
G.pwMetrics.mains=$('pwChkMains').checked;
G.pwMetrics.load=$('pwChkLoad').checked;
if(!G.pwMetrics.bus&&!G.pwMetrics.mains&&!G.pwMetrics.load){
G.pwMetrics={bus:true,mains:true,load:true};
$('pwChkBus').checked=true;$('pwChkMains').checked=true;$('pwChkLoad').checked=true;
}
pwLoadChart();
}

function pwRange(btn,hours){
btn.parentElement.querySelectorAll('.arc-tb').forEach(b=>b.classList.remove('on'));
btn.classList.add('on');G.pwHours=hours;
_updateZoomLabel('pwZoomLabel',hours);
pwLoadChart();
}

async function pwLoadChart(){
if(!G.cur||!G.S[G.cur])return;
const sprId=G.S[G.cur].spr?._deviceId;
if(!sprId){pwRenderNoData('ШПР не настроен');return}
// Always fetch both multiset_total_p and busbar_p for backward compat
// (old data has multiset_total_p=NULL, fallback to busbar_p)
const fields=['multiset_total_p','busbar_p'];
if(G.pwMetrics.mains||G.pwMetrics.load)fields.push('mains_total_p');
const bucket=arcBucket(G.pwHours);
let url;
if(bucket>0)url=`/api/history/metrics/${sprId}/downsampled?last_hours=${G.pwHours}&bucket_seconds=${bucket}&fields=${fields.join(',')}`;
else url=`/api/history/metrics/${sprId}?last_hours=${G.pwHours}&fields=${fields.join(',')}&limit=5000`;
try{
const data=await api.get(url);
if(!data||!data.length){pwRenderNoData('Нет данных за выбранный период');return}
pwRenderChart(data);
}catch(e){pwRenderNoData('Ошибка: '+e.message)}
}

function pwRenderNoData(msg){
const canvas=$('pwCanvas');
if(G.pwChart){G.pwChart.destroy();G.pwChart=null}
if(canvas){const ctx=canvas.getContext('2d');ctx.clearRect(0,0,canvas.width,canvas.height);
ctx.fillStyle='#5a6a80';ctx.font='13px Outfit';ctx.textAlign='center';
ctx.fillText(msg,canvas.width/2,canvas.height/2)}
}

function pwRenderChart(data){
const canvas=$('pwCanvas');if(!canvas)return;
if(G.pwChart){G.pwChart.destroy();G.pwChart=null}
if(typeof Chart==='undefined'){pwRenderNoData('Chart.js не загружен');return}
const timeKey=data[0].bucket!==undefined?'bucket':'timestamp';
const totalPts=data.length;
const showPts=totalPts<80;
const ptRadius=totalPts<30?3:totalPts<80?2:0;
const hoverRadius=totalPts<200?4:3;
// Helper: prefer multiset_total_p (correct gen sum), fallback to busbar_p (old data)
const _genP=r=>r.multiset_total_p!=null?Number(r.multiset_total_p):(r.busbar_p!=null?Number(r.busbar_p):null);
const datasets=[];
if(G.pwMetrics.bus){
datasets.push({label:'P генераторов',data:data.map(r=>({x:_utcDate(r[timeKey]),y:_genP(r)})),
borderColor:PW_COLORS.bus,backgroundColor:PW_COLORS.bus+'18',borderWidth:2.2,
pointRadius:showPts?ptRadius:0,pointHoverRadius:hoverRadius,pointBackgroundColor:PW_COLORS.bus,
pointBorderColor:PW_COLORS.bus,pointHitRadius:8,tension:0.25,fill:false,spanGaps:false});
}
if(G.pwMetrics.mains){
datasets.push({label:'P сети',data:data.map(r=>({x:_utcDate(r[timeKey]),y:r.mains_total_p!=null?Number(r.mains_total_p):null})),
borderColor:PW_COLORS.mains,backgroundColor:PW_COLORS.mains+'18',borderWidth:2.2,
pointRadius:showPts?ptRadius:0,pointHoverRadius:hoverRadius,pointBackgroundColor:PW_COLORS.mains,
pointBorderColor:PW_COLORS.mains,pointHitRadius:8,tension:0.25,fill:false,spanGaps:false});
}
if(G.pwMetrics.load){
datasets.push({label:'P нагрузки',data:data.map(r=>{
const b=_genP(r)||0;
const m=r.mains_total_p!=null?Number(r.mains_total_p):0;
return{x:_utcDate(r[timeKey]),y:b+m};
}),borderColor:PW_COLORS.load,backgroundColor:PW_COLORS.load+'18',borderWidth:2.2,
pointRadius:showPts?ptRadius:0,pointHoverRadius:hoverRadius,pointBackgroundColor:PW_COLORS.load,
pointBorderColor:PW_COLORS.load,pointHitRadius:8,tension:0.25,fill:false,spanGaps:false});
}
if(!datasets.length){pwRenderNoData('Выберите хотя бы одну метрику');return}
const c=getChartColors();
G.pwChart=new Chart(canvas,{type:'line',data:{datasets},
plugins:[crosshairPlugin],
options:{...CHART_DEFAULTS,
plugins:{...CHART_DEFAULTS.plugins,
legend:{...CHART_DEFAULTS.plugins.legend,labels:{...CHART_DEFAULTS.plugins.legend.labels,generateLabels:null}}},
scales:{
x:{...CHART_DEFAULTS.scales.x,grid:{...CHART_DEFAULTS.scales.x.grid,color:c.grid},border:{color:c.border},ticks:{...CHART_DEFAULTS.scales.x.ticks,color:c.tick}},
y:{...CHART_DEFAULTS.scales.y,grid:{...CHART_DEFAULTS.scales.y.grid,color:c.grid},border:{color:c.border},ticks:{...CHART_DEFAULTS.scales.y.ticks,color:c.tick},
title:{display:true,text:'кВт',color:c.tick,font:{family:'Outfit',size:11,weight:'500'},padding:{bottom:6}}}
}}});
G.pwChart.update();
}

// === Smooth wheel zoom ===
var _zoomPresets=[1,6,24,168,720];
var _zoomLabels={1:'1ч',6:'6ч',24:'24ч',168:'7д',720:'30д'};
var _zoomMin=0.1,_zoomMax=720,_zoomFactor=0.85;
var _wheelDebounceArc=null,_wheelDebouncePw=null;

function _formatZoomLabel(h){
  if(h<1){return Math.round(h*60)+'м'}
  if(h<24){return (h%1<0.05||h%1>0.95)?Math.round(h)+'ч':h.toFixed(1)+'ч'}
  var d=h/24;
  return (d%1<0.05||d%1>0.95)?Math.round(d)+'д':d.toFixed(1)+'д';
}

function _updateZoomLabel(id,h){
  var el=document.getElementById(id);if(!el)return;
  var isPreset=_zoomPresets.some(function(p){return Math.abs(h-p)/p<0.01});
  if(isPreset){el.classList.remove('vis')}
  else{el.textContent='~'+_formatZoomLabel(h);el.classList.add('vis')}
}

function _highlightRangeBtn(container,hours){
  var btns=document.querySelectorAll(container+' .arc-tb');
  var matchLabel='';
  for(var i=0;i<_zoomPresets.length;i++){
    if(Math.abs(hours-_zoomPresets[i])/_zoomPresets[i]<0.01){matchLabel=_zoomLabels[_zoomPresets[i]];break}
  }
  btns.forEach(function(b){b.classList.toggle('on',b.textContent.trim()===matchLabel)});
}

function _smoothZoom(curH,deltaY){
  var dir=deltaY<0?_zoomFactor:(1/_zoomFactor);
  var newH=curH*dir;
  newH=Math.max(_zoomMin,Math.min(_zoomMax,newH));
  // Snap to preset if within 3%
  for(var i=0;i<_zoomPresets.length;i++){
    if(Math.abs(newH-_zoomPresets[i])/_zoomPresets[i]<0.03){newH=_zoomPresets[i];break}
  }
  return newH;
}

// Wheel zoom event listener
document.addEventListener('wheel',function(e){
  var t=e.target;
  if(!t||!t.closest)return;
  // --- Power chart ---
  if(t.id==='pwCanvas'||t.closest('#pwChartWrap')){
    e.preventDefault();e.stopPropagation();
    var newH=_smoothZoom(G.pwHours,e.deltaY);
    if(newH===G.pwHours)return;
    G.pwHours=newH;
    _highlightRangeBtn('#m-pwchart',G.pwHours);
    _updateZoomLabel('pwZoomLabel',G.pwHours);
    // Instant visual feedback — adjust X-axis
    if(G.pwChart&&G.pwChart.options&&G.pwChart.options.scales&&G.pwChart.options.scales.x){
      var now=Date.now();
      G.pwChart.options.scales.x.min=now-G.pwHours*3600000;
      G.pwChart.options.scales.x.max=now;
      G.pwChart.update('none');
    }
    clearTimeout(_wheelDebouncePw);
    _wheelDebouncePw=setTimeout(function(){pwLoadChart()},400);
    return;
  }
  // --- Archive chart ---
  if(t.id==='arcCanvas'||t.closest('.arc-chart-wrap')){
    e.preventDefault();e.stopPropagation();
    if(!G.arcState.hours)G.arcState.hours=1; // fallback from custom range
    var newH2=_smoothZoom(G.arcState.hours,e.deltaY);
    if(newH2===G.arcState.hours)return;
    G.arcState.hours=newH2;
    G.arcState.almPage=0;
    dpState.arcFrom=null;dpState.arcTo=null;
    var fb=$('arcFromBtn'),tb=$('arcToBtn');
    if(fb){fb.textContent='📅 От';fb.classList.remove('has-val')}
    if(tb){tb.textContent='📅 До';tb.classList.remove('has-val')}
    _highlightRangeBtn('.arc-time',G.arcState.hours);
    _updateZoomLabel('arcZoomLabel',G.arcState.hours);
    // Instant visual feedback — adjust X-axis
    if(G.arcChart&&G.arcChart.options&&G.arcChart.options.scales&&G.arcChart.options.scales.x){
      var now2=Date.now();
      G.arcChart.options.scales.x.min=now2-G.arcState.hours*3600000;
      G.arcChart.options.scales.x.max=now2;
      G.arcChart.update('none');
    }
    clearTimeout(_wheelDebounceArc);
    _wheelDebounceArc=setTimeout(function(){arcLoadChart();arcLoadAlarms()},400);
    return;
  }
},{passive:false,capture:true});

// === Exports ===
export {
  // Archive page
  showArchive,
  // Chart groups/tabs
  arcGetGroups, arcGetTabs, arcTab, arcChGroup, arcRenderChartTabs, arcRenderFieldChecks, arcToggleField,
  // Data loading
  arcRange, arcDev, arcSwitchSite, arcLoadAlarms,
  // Chart rendering
  CHART_DEFAULTS, arcRenderChart, arcRenderFieldStats, arcRenderStats, arcRenderAlarms, arcRenderDisk, arcRenderNoData,
  // Date picker
  dpToggle, dpRender, dpNav, dpPickDay, dpTimeChange, dpApply, arcCustomRange,
  // Power chart
  showPwChart, pwToggleMetric, pwRange, pwRenderChart, pwRenderNoData, pwLoadChart,
  // Field archive
  openFieldArchive,
  // Zoom
  _smoothZoom, _formatZoomLabel, _updateZoomLabel, _highlightRangeBtn,
  // Helper
  _utcDate,
  // Internal (needed by other modules)
  arcBucket, arcLoadChart, arcLoadDisk, arcGetDeviceId, crosshairPlugin,
  // Date picker state (for external access if needed)
  dpState
};
