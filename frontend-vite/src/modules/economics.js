import { G, sv, ae } from './state.js';
import { $, esc } from './utils.js';
import { api, API_BASE, getGenSlots, getDeviceIdForSlot } from './api.js';
import { getChartColors } from './theme.js';

// ========================================================================
// ECONOMICS VIEW
// ========================================================================
let _econChart=null;
let _econPeriod=7;
let _econReportData=null; // cached report for detail popups
let _econActiveTab='report'; // 'report' | 'params'
let _econPlannedYear=new Date().getFullYear();
let _econPlannedDirty={}; // track dirty cells
let _econSiteId=null; // current apiSiteId

function showEconomics(siteKey){
  if(window.stopB24Poll)window.stopB24Poll();G.curView='economics';G.archiveMode=false;
  const sk=siteKey||(G.cur&&G.S[G.cur]?G.cur:Object.keys(G.S)[0]);
  if(!sk||!G.S[sk]){ae('Нет объектов');return}
  const apiSiteId=G.siteApiIds[sk];
  if(!apiSiteId){ae('Нет API ID для объекта');return}
  _econSiteId=apiSiteId;
  const mn=$('mainArea');
  mn.innerHTML=`
<div class="dh"><div class="dt"><h1>💰 Экономика — ${esc(G.S[sk].name)}</h1></div></div>
<div class="econ-wrap">
  <div class="econ-tabs">
    <button class="econ-tab${_econActiveTab==='report'?' on':''}" onclick="econSwitchTab('report')">📊 Отчёт</button>
    <button class="econ-tab${_econActiveTab==='params'?' on':''}" onclick="econSwitchTab('params')">⚙ Параметры</button>
  </div>

  <!-- TAB: Отчёт -->
  <div class="econ-tab-body${_econActiveTab==='report'?' on':''}" id="econTabReport">
    <div class="econ-period" style="justify-content:center;margin-bottom:10px">
      <button class="econ-pb${_econPeriod===1?' on':''}" onclick="econSetPeriod(${apiSiteId},1,this)">1 день</button>
      <button class="econ-pb${_econPeriod===7?' on':''}" onclick="econSetPeriod(${apiSiteId},7,this)">7 дней</button>
      <button class="econ-pb${_econPeriod===14?' on':''}" onclick="econSetPeriod(${apiSiteId},14,this)">14 дней</button>
      <button class="econ-pb${_econPeriod===30?' on':''}" onclick="econSetPeriod(${apiSiteId},30,this)">30 дней</button>
      <button class="econ-pb${_econPeriod===90?' on':''}" onclick="econSetPeriod(${apiSiteId},90,this)">90 дней</button>
    </div>
    <div style="padding:8px 14px;margin-bottom:10px;background:rgba(160,112,255,.08);border:1px solid rgba(160,112,255,.25);border-radius:8px;font-size:11px;color:var(--p);line-height:1.4;text-align:center"><b>⛽ Газ и ⚡ энергия — факт с контроллеров SmartGen (Modbus).</b> Постоянные затраты (ТО, персонал, лизинг) — <b>ПЛАНОВЫЕ</b>. Настройка: Параметры → Плановые затраты.</div>
    <div id="econDataWarning" style="display:none;padding:8px 14px;margin-bottom:10px;background:rgba(255,180,0,.1);border:1px solid rgba(255,180,0,.3);border-radius:8px;font-size:12px;color:#ffb020;line-height:1.4"></div>
    <div class="econ-cards" id="econCards">
      <div class="econ-card econ-card-click" onclick="econCardInfo(event,'gas')"><div class="econ-lbl">⛽ Расход газа <span class="econ-card-src">ℹ</span></div><div class="econ-val" id="econGas">—</div><div class="econ-unit" id="econGasUnit">м³ итого</div></div>
      <div class="econ-card econ-card-click" onclick="econCardInfo(event,'energy')"><div class="econ-lbl">⚡ Выработка <span class="econ-card-src">ℹ</span></div><div class="econ-val" id="econEnergy">—</div><div class="econ-unit" id="econEnergyUnit">кВт·ч итого</div></div>
      <div class="econ-card econ-card-click" onclick="econCardInfo(event,'sgc')"><div class="econ-lbl">📐 Уд. расход <span class="econ-card-src">ℹ</span></div><div class="econ-val" id="econSGC">—</div><div class="econ-unit">м³/кВт·ч (средн.)</div></div>
      <div class="econ-card econ-card-click" onclick="econCardInfo(event,'gas_cost')"><div class="econ-lbl">💵 Газ себест. <span class="econ-card-src">ℹ</span></div><div class="econ-val" id="econCost">—</div><div class="econ-unit">₽/кВт·ч (газ)</div></div>
      <div class="econ-card econ-card-click" onclick="econCardInfo(event,'full_cost')"><div class="econ-lbl">💰 Полная себест. <span class="econ-card-src">ℹ</span></div><div class="econ-val" id="econFullCost">—</div><div class="econ-unit">₽/кВт·ч (газ+пост.)</div></div>
      <div class="econ-card econ-card-click" onclick="econCardInfo(event,'grid')"><div class="econ-lbl">🔌 Цена сети <span class="econ-card-src">ℹ</span></div><div class="econ-val" id="econGridPrice">—</div><div class="econ-unit">₽/кВт·ч (тариф)</div></div>
      <div class="econ-card econ-card-click" onclick="econCardInfo(event,'util')" style="grid-column:span 1"><div class="econ-lbl">📊 Факт/План <span class="econ-card-src">ℹ</span></div><div class="econ-val" id="econUtil">—</div><div class="econ-unit" id="econUtilUnit">% выработки от номинала</div></div>
      <div class="econ-card econ-card-click" onclick="econCardInfo(event,'breakeven')"><div class="econ-lbl">🎯 Безубыточность <span class="econ-card-src">ℹ</span></div><div class="econ-val" id="econBreakeven">—</div><div class="econ-unit">% мин. выработки</div></div>
    </div>
    <div id="econDeviation" style="display:none;padding:6px 12px;margin-top:-4px;margin-bottom:8px;background:rgba(255,100,100,.08);border:1px solid rgba(255,100,100,.2);border-radius:8px;font-size:11px;color:#ff8080;line-height:1.4;text-align:center"></div>
    <div id="econPeriodInfo" style="text-align:center;font-size:11px;color:var(--t3);margin-top:-4px;margin-bottom:8px"></div>
    <div id="econComparison" class="econ-section" style="display:none"></div>
    <div class="econ-section">
      <div class="econ-section-hdr">📊 Детализация по дням</div>
      <div id="econReport"></div>
      <div class="econ-chart-wrap"><canvas id="econChartCanvas"></canvas></div>
    </div>
  </div>

  <!-- TAB: Параметры -->
  <div class="econ-tab-body${_econActiveTab==='params'?' on':''}" id="econTabParams">
    <div class="econ-section">
      <div class="econ-section-hdr">⛽ Цены на газ</div>
      <div class="econ-add-row">
        <div class="fg"><label class="fl">Дата начала</label><input type="date" class="fi" id="econPrDate" value="${new Date().toISOString().slice(0,10)}"></div>
        <div class="fg"><label class="fl">Цена ₽/м³</label><input type="number" step="0.01" min="0" class="fi" id="econPrVal" placeholder="8.50"></div>
        <div class="fg"><label class="fl">Примечание</label><input type="text" class="fi" id="econPrNote" placeholder="Необязательно"></div>
        <button class="bp" style="padding:8px 16px;white-space:nowrap" onclick="econAddPrice(${apiSiteId})">+ Добавить</button>
      </div>
      <div id="econPricesTable"></div>
    </div>
    <div class="econ-section">
      <div class="econ-section-hdr">🔌 Цены на электросеть</div>
      <div class="econ-add-row">
        <div class="fg"><label class="fl">Дата начала</label><input type="date" class="fi" id="econGridDate" value="${new Date().toISOString().slice(0,10)}"></div>
        <div class="fg"><label class="fl">Цена ₽/кВт·ч</label><input type="number" step="0.001" min="0" class="fi" id="econGridVal" placeholder="6.42"></div>
        <div class="fg"><label class="fl">Примечание</label><input type="text" class="fi" id="econGridNote" placeholder="Необязательно"></div>
        <button class="bp" style="padding:8px 16px;white-space:nowrap" onclick="econAddGridPrice(${apiSiteId})">+ Добавить</button>
      </div>
      <div id="econGridPricesTable"></div>
    </div>
    <div class="econ-section">
      <div class="econ-section-hdr">
        📋 Плановые затраты
        <span style="margin-left:12px;font-size:12px;font-weight:400;color:var(--t3)">Год:</span>
        <button class="econ-pb" style="margin-left:4px;padding:3px 10px" onclick="econPlannedYearNav(-1)">◀</button>
        <span id="econPlannedYearLabel" style="font-family:var(--m);font-size:14px;font-weight:700;color:var(--g);margin:0 6px">${_econPlannedYear}</span>
        <button class="econ-pb" style="padding:3px 10px" onclick="econPlannedYearNav(1)">▶</button>
        <button class="bp" style="margin-left:auto;padding:5px 12px;font-size:11px" onclick="econSavePlanned(${apiSiteId})">💾 Сохранить</button>
      </div>
      <div id="econPlannedTable"></div>
      <div id="econPlannedSummary"></div>
      <div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap">
        <button class="bs2" style="padding:6px 14px;font-size:11px" onclick="econAddCategory(${apiSiteId})">+ Категория</button>
        <button class="bs2" style="padding:6px 14px;font-size:11px" onclick="econCopyYear(${apiSiteId})">📋 Копировать из года</button>
      </div>
    </div>
  </div>
</div>`;
  if(_econActiveTab==='report'){
    econLoadReport(apiSiteId,_econPeriod);
    econLoadComparison(_econPeriod);
  }
  if(_econActiveTab==='params'){
    econLoadPrices(apiSiteId);
    econLoadGridPrices(apiSiteId);
    econLoadPlanned(apiSiteId,_econPlannedYear);
  }
}

function econSwitchTab(tab){
  _econActiveTab=tab;
  document.querySelectorAll('.econ-tab').forEach((b,i)=>{b.classList.toggle('on',i===(tab==='report'?0:1))});
  document.querySelectorAll('.econ-tab-body').forEach(b=>b.classList.remove('on'));
  const body=$(tab==='report'?'econTabReport':'econTabParams');
  if(body)body.classList.add('on');
  if(tab==='report'&&_econSiteId){econLoadReport(_econSiteId,_econPeriod);econLoadComparison(_econPeriod)}
  if(tab==='params'&&_econSiteId){econLoadPrices(_econSiteId);econLoadGridPrices(_econSiteId);econLoadPlanned(_econSiteId,_econPlannedYear)}
}

// ── Card Info Popups ──
const _econCardMeta={
  gas:{icon:'⛽',title:'Расход газа',
    formula:'Σ (avg_gas_m3h × hours) по всем генераторам за каждый день',
    desc:'Суммарный объём потреблённого газа за период.',
    src:'<b>Источник:</b> ModbusPoller → metrics_data.gas_flow_rate (м³/ч) × время работы генератора',
    src2:'<b>Таблица:</b> metrics_data (avg по 30-сек интервалам)'},
  energy:{icon:'⚡',title:'Выработка',
    formula:'Σ (avg_power_kw × hours) по всем генераторам за каждый день',
    desc:'Суммарная выработанная электроэнергия за период.',
    src:'<b>Источник:</b> ModbusPoller → metrics_data.active_power_kw (кВт) × время работы генератора',
    src2:'<b>Таблица:</b> metrics_data (avg по 30-сек интервалам)'},
  sgc:{icon:'📐',title:'Удельный расход газа',
    formula:'SGC = Σ gas_m3 / Σ energy_kwh',
    desc:'Средний расход газа на 1 кВт·ч выработки. Норма: 0.28-0.35 м³/кВт·ч.',
    src:'<b>Расчёт:</b> общий газ (м³) ÷ общая выработка (кВт·ч)',
    src2:'<b>Цветовая шкала:</b> 🟢 < 0.35 | 🟡 0.35-0.50 | 🔴 > 0.50'},
  gas_cost:{icon:'💵',title:'Газовая себестоимость',
    formula:'gas_cost_per_kwh = (gas_m3 × price_per_m3) / energy_kwh',
    desc:'Себестоимость 1 кВт·ч только по затратам на газ.',
    src:'<b>Источники:</b> gas_m3 (метрики) × цена газа (таблица gas_prices)',
    src2:'<b>Настройка:</b> Параметры → Цены на газ'},
  full_cost:{icon:'💰',title:'Полная себестоимость',
    formula:'full_cost = (gas_cost + planned_daily) / energy_kwh',
    desc:'Себестоимость 1 кВт·ч с учётом всех постоянных затрат (зарплата, лизинг, масло, запчасти, ТО, страховка, капремонт).',
    src:'<b>Источники:</b> газ (gas_prices) + плановые затраты (planned_costs)',
    src2:'<b>Настройка:</b> Параметры → Плановые затраты'},
  grid:{icon:'🔌',title:'Цена электросети',
    formula:'grid_price = тариф ₽/кВт·ч на дату из grid_prices',
    desc:'Тариф на покупку электроэнергии из сети. Используется для расчёта экономии/потерь от собственной генерации.',
    src:'<b>Источник:</b> таблица grid_prices (effective_from → price_per_kwh)',
    src2:'<b>Настройка:</b> Параметры → Цены на электросеть'},
  util:{icon:'📊',title:'Факт/План выработки',
    formula:'факт/план = факт_кВт·ч / (номинал_кВт × 24ч × дней) × 100%',
    desc:'Процент фактической выработки от плановой. Номинал ГПУ = 320 кВт (2 генератора × 160 кВт). Если генератор простаивает или работает на пониженной мощности — процент падает. Чем ниже % — тем выше удельная доля постоянных затрат.',
    src:'<b>Факт:</b> контроллеры SmartGen → Modbus → metrics_data (фактическая выработка кВт·ч)',
    src2:'<b>План:</b> 320 кВт (2×160) × 24ч × кол-во дней с данными'},
  breakeven:{icon:'🎯',title:'Точка безубыточности',
    formula:'breakeven = пост_затраты_день / ((сеть − газ_себест) × план_кВт·ч_день) × 100%',
    desc:'Минимальный % выработки от номинала, при котором полная себестоимость кВт·ч = тариф сети. Ниже — генерация дороже сети (убыток). Выше — генерация выгоднее.',
    src:'<b>Зависит от:</b> плановых затрат, цены газа, тарифа сети',
    src2:'<b>Цветовая шкала:</b> 🟢 текущая > безубыточности | 🔴 текущая < безубыточности'}
};

function econCardInfo(e,key){
  e.stopPropagation();
  let pop=document.getElementById('econInfoPop');
  if(pop){pop.remove()}
  const m=_econCardMeta[key];if(!m)return;
  // Build dynamic values from cached report
  let valLine='';
  if(_econReportData){
    const t=_econReportData.totals;
    if(key==='gas'&&t.gas_m3>0)valLine=`<div style="margin-top:6px;font-family:var(--m);color:var(--g)">= ${t.gas_m3.toFixed(1)} м³ за ${_econReportData.days.length} дн.</div>`;
    if(key==='energy'&&t.energy_kwh>0)valLine=`<div style="margin-top:6px;font-family:var(--m);color:var(--g)">= ${t.energy_kwh.toFixed(0)} кВт·ч за ${_econReportData.days.length} дн.</div>`;
    if(key==='sgc'&&t.energy_kwh>0)valLine=`<div style="margin-top:6px;font-family:var(--m);color:var(--g)">= ${t.gas_m3.toFixed(1)} / ${t.energy_kwh.toFixed(0)} = ${(t.gas_m3/t.energy_kwh).toFixed(3)} м³/кВт·ч</div>`;
    if(key==='gas_cost'&&t.avg_cost_per_kwh!=null)valLine=`<div style="margin-top:6px;font-family:var(--m);color:var(--g)">= ${t.total_cost!=null?t.total_cost.toFixed(0):'-'} ₽ / ${t.energy_kwh.toFixed(0)} кВт·ч = ${t.avg_cost_per_kwh.toFixed(2)} ₽/кВт·ч</div>`;
    if(key==='full_cost'&&t.avg_full_cost_per_kwh!=null)valLine=`<div style="margin-top:6px;font-family:var(--m);color:var(--g)">= (${t.total_cost!=null?t.total_cost.toFixed(0):'-'} + ${t.planned_costs!=null?t.planned_costs.toFixed(0):'-'}) / ${t.energy_kwh.toFixed(0)} = ${t.avg_full_cost_per_kwh.toFixed(2)} ₽/кВт·ч</div>`;
    if(key==='grid'&&t.avg_grid_price_per_kwh!=null)valLine=`<div style="margin-top:6px;font-family:var(--m);color:var(--b)">= ${t.avg_grid_price_per_kwh.toFixed(2)} ₽/кВт·ч (средн. за период)</div>`;
    if(key==='util'&&t.utilization_pct!=null){
      const nDays=_econReportData.days.length;
      const clr=t.utilization_pct>(t.breakeven_pct||50)?'var(--g)':'var(--r)';
      // Per-generator aggregation from days data
      const devTotals={};
      for(const day of _econReportData.days){
        for(const dv of (day.devices||[])){
          if(!devTotals[dv.name])devTotals[dv.name]={energy:0,hours:0,cnt:0,sumPwr:0};
          devTotals[dv.name].energy+=dv.energy_kwh;
          devTotals[dv.name].hours+=dv.hours;
          devTotals[dv.name].cnt++;
          devTotals[dv.name].sumPwr+=dv.avg_power_kw;
        }
      }
      let devLines='';
      for(const [name,d] of Object.entries(devTotals)){
        const avgPwr=d.cnt>0?(d.sumPwr/d.cnt).toFixed(0):0;
        const pct160=d.cnt>0?((d.sumPwr/d.cnt)/160*100).toFixed(0):0;
        const status=parseFloat(avgPwr)>5?'🟢 работает':'🔴 не работает';
        devLines+=`<tr><td style="padding:3px 6px">${name}</td><td style="text-align:right">${status}</td><td style="text-align:right;font-weight:600">${avgPwr} кВт</td><td style="text-align:right">${pct160}% от 160</td><td style="text-align:right;font-weight:600">${d.energy.toFixed(0)} кВт·ч</td></tr>`;
      }
      valLine=`<div style="margin-top:8px">
<table style="width:100%;font-size:11px;border-collapse:collapse">
<tr style="color:var(--t3);font-size:10px"><th style="text-align:left;padding:3px 6px">Генератор</th><th style="text-align:right">Статус</th><th style="text-align:right">Ср.мощность</th><th style="text-align:right">% номинала</th><th style="text-align:right">Выработка</th></tr>
${devLines}
<tr style="border-top:2px solid var(--bd2);font-weight:700"><td style="padding:4px 6px" colspan="4">ИТОГО факт</td><td style="text-align:right;color:${clr}">${t.energy_kwh.toFixed(0)} кВт·ч</td></tr>
</table>
<div style="margin-top:6px;font-family:var(--m);font-size:12px">
<b>План:</b> ${t.nominal_kw||320} кВт (2×160) × 24ч × ${nDays} дн. = <b>${t.plan_kwh!=null?t.plan_kwh.toLocaleString('ru-RU'):'-'} кВт·ч</b><br>
<b>Факт/План:</b> ${t.energy_kwh.toFixed(0)} / ${t.plan_kwh!=null?t.plan_kwh.toFixed(0):'-'} × 100% = <b style="color:${clr}">${t.utilization_pct.toFixed(1)}%</b>
</div></div>`;
    }
    if(key==='breakeven'&&t.breakeven_pct!=null){const ok=t.utilization_pct!=null&&t.utilization_pct>t.breakeven_pct;valLine=`<div style="margin-top:6px;font-family:var(--m);color:${ok?'var(--g)':'var(--r)'}">= ${t.breakeven_pct.toFixed(1)}% | Текущая: ${t.utilization_pct!=null?t.utilization_pct.toFixed(1)+'%':'—'} ${ok?'✅ В плюсе':'❌ В убытке'}</div>`}
  }
  pop=document.createElement('div');
  pop.id='econInfoPop';
  pop.className='econ-info-pop';
  pop.innerHTML=`<div class="eip-title">${m.icon} ${m.title}</div>
<div style="color:var(--t2)">${m.desc}</div>
<div class="eip-formula">${m.formula}${valLine}</div>
<div class="eip-src">${m.src}<br>${m.src2}</div>`;
  const rect=e.currentTarget.getBoundingClientRect();
  pop.style.top=(rect.bottom+8)+'px';
  pop.style.left=Math.max(8,Math.min(rect.left,window.innerWidth-400))+'px';
  document.body.appendChild(pop);
  setTimeout(()=>{document.addEventListener('click',function _c(){const p=document.getElementById('econInfoPop');if(p)p.remove();document.removeEventListener('click',_c)},{once:true})},50);
}

// ── Cost Comparison Widget ──
async function econLoadComparison(days){
  const el=$('econComparison');if(!el)return;
  try{
    const data=await api.get(`/api/economics/comparison?last_days=${days}`);
    if(!data.sites||!data.sites.length){el.style.display='none';return}
    el.style.display='block';
    const COLORS={gas:'#378ADD',maintenance:'#5DCAA5',staff:'#AFA9EC',capital:'#FAC775'};
    const LABELS={gas:'Газ',maintenance:'ТО/эксп.',staff:'Персонал',capital:'Капитальные'};
    let html='<div class="econ-section-hdr">📊 Сравнение себестоимости по объектам</div>';
    html+='<div style="text-align:center;padding:6px 12px;margin-bottom:10px;background:rgba(255,180,0,.08);border:1px solid rgba(255,180,0,.2);border-radius:8px;font-size:11px;color:#ffb020;font-weight:600">⚠ Газ и энергия — факт (SmartGen Modbus). Постоянные затраты — ПЛАНОВЫЕ, фактические могут отличаться.</div>';
    for(const s of data.sites){
      const cb=s.cost_breakdown;
      const full=s.full_cost_per_kwh;
      const grid=s.grid_price_per_kwh;
      const maxVal=Math.max(full,grid)*1.2;
      const v=s.verdict;
      const badgeTxt=v==='profitable'?`Выгодно: +${s.diff_per_kwh.toFixed(2)} ₽`:v==='marginal'?`На грани: ${s.diff_per_kwh>=0?'+':''}${s.diff_per_kwh.toFixed(2)} ₽`:`Убыток: ${s.diff_per_kwh.toFixed(2)} ₽`;
      // Stacked bar segments
      let barHtml='';
      for(const [key,color] of Object.entries(COLORS)){
        const val=cb[key]||0;
        const pct=maxVal>0?(val/maxVal*100):0;
        if(pct>0.5)barHtml+=`<div class="econ-cmp-seg" style="width:${pct}%;background:${color}">${pct>6?val.toFixed(2):''}</div>`;
      }
      const gridPct=maxVal>0?(grid/maxVal*100):0;
      // Build detail popup data as JSON attr
      const detailData=JSON.stringify({name:s.site_name,cb,full,grid,v,util:s.utilization_pct,be:s.breakeven_utilization_pct,energy:s.energy_kwh,savings:s.savings_rub,days:s.days_with_data}).replace(/"/g,'&quot;');
      html+=`<div class="econ-cmp-card econ-card-click" onclick="econCmpDetail(event,this)" data-cmp="${detailData}">
        <div class="econ-cmp-hdr">
          <div><span class="econ-cmp-site">${esc(s.site_name)}</span> <span class="econ-cmp-util">(факт/план ${s.utilization_pct}%)</span></div>
          <div class="econ-cmp-badge ${v}">${badgeTxt}</div>
        </div>
        <div class="econ-cmp-bar-wrap" title="Нажмите для подробной расшифровки">
          <div class="econ-cmp-bar">${barHtml}</div>
          <div class="econ-cmp-grid-line" style="left:${gridPct}%"></div>
          <div class="econ-cmp-grid-lbl" style="left:${gridPct}%">сеть ${grid.toFixed(2)}</div>
        </div>
        <div class="econ-cmp-legend">
          ${Object.entries(COLORS).map(([k,c])=>`<div class="econ-cmp-legend-item"><div class="econ-cmp-legend-dot" style="background:${c}"></div>${LABELS[k]} ${(cb[k]||0).toFixed(2)}</div>`).join('')}
          <div class="econ-cmp-legend-item" style="margin-left:auto;font-weight:600;color:var(--t)">Итого: ${full.toFixed(2)} ₽/кВт·ч</div>
        </div>
        <div class="econ-cmp-explain ${v}">${esc(s.explanation)}</div>
      </div>`;
    }
    el.innerHTML=html;
  }catch(e){el.style.display='none';console.warn('Comparison error:',e)}
}

// ── Comparison Detail Popup ──
function econCmpDetail(e,el){
  e.stopPropagation();
  let pop=document.getElementById('econInfoPop');if(pop)pop.remove();
  const d=JSON.parse(el.dataset.cmp);
  const cb=d.cb;
  const diff=d.grid-d.full;
  const emoji=d.v==='profitable'?'✅':d.v==='marginal'?'⚠️':'🔴';
  const verdictTxt=d.v==='profitable'?'Генерация ВЫГОДНЕЕ сети':d.v==='marginal'?'На грани окупаемости':'Генерация ДОРОЖЕ сети';
  pop=document.createElement('div');
  pop.id='econInfoPop';
  pop.className='econ-info-pop';
  pop.style.maxWidth='440px';
  pop.innerHTML=`<div class="eip-title">${emoji} ${d.name} — Расшифровка себестоимости</div>
<div style="color:var(--t2);margin-bottom:8px">${verdictTxt}</div>
<table style="width:100%;border-collapse:collapse;font-size:11px;font-family:var(--m)">
<tr style="color:var(--t3);font-size:9px;text-transform:uppercase"><td style="padding:4px">Компонент</td><td style="text-align:right;padding:4px">₽/кВт·ч</td><td style="text-align:right;padding:4px">Описание</td></tr>
<tr style="border-top:1px solid var(--ov)"><td style="padding:5px;color:#378ADD">🔵 Газ</td><td style="text-align:right;font-weight:600">${cb.gas.toFixed(2)}</td><td style="text-align:right;color:var(--t3);font-size:10px">расход газа × цена ₽/м³</td></tr>
<tr style="border-top:1px solid var(--ov)"><td style="padding:5px;color:#5DCAA5">🟢 ТО/эксплуатация</td><td style="text-align:right;font-weight:600">${cb.maintenance.toFixed(2)}</td><td style="text-align:right;color:var(--t3);font-size:10px">масло, запчасти, сервис</td></tr>
<tr style="border-top:1px solid var(--ov)"><td style="padding:5px;color:#AFA9EC">🟣 Персонал</td><td style="text-align:right;font-weight:600">${cb.staff.toFixed(2)}</td><td style="text-align:right;color:var(--t3);font-size:10px">зарплата, отчисления ФОТ</td></tr>
<tr style="border-top:1px solid var(--ov)"><td style="padding:5px;color:#FAC775">🟡 Капитальные</td><td style="text-align:right;font-weight:600">${cb.capital.toFixed(2)}</td><td style="text-align:right;color:var(--t3);font-size:10px">лизинг, капремонт, страховка</td></tr>
<tr style="border-top:2px solid var(--bd2);font-weight:700"><td style="padding:6px">ИТОГО себестоимость</td><td style="text-align:right;color:var(--g)">${d.full.toFixed(2)}</td><td></td></tr>
<tr style="border-top:1px solid var(--ov)"><td style="padding:5px;color:var(--b)">🔌 Тариф сети</td><td style="text-align:right;font-weight:600;color:var(--b)">${d.grid.toFixed(2)}</td><td></td></tr>
<tr style="border-top:2px solid var(--bd2)"><td style="padding:6px;font-weight:700">${diff>=0?'Экономия':'Убыток'} на 1 кВт·ч</td><td style="text-align:right;font-weight:700;color:${diff>=0?'var(--g)':'var(--r)'}">${diff>=0?'+':''}${diff.toFixed(2)}</td><td></td></tr>
</table>
<div class="eip-formula" style="margin-top:8px">
Выработка: ${d.energy.toLocaleString('ru-RU')} кВт·ч за ${d.days||'-'} дн. | Факт/План: ${d.util}%<br>
${diff>=0?'Экономия':'Убыток'} за период: <b style="color:${diff>=0?'var(--g)':'var(--r)'}">${Math.abs(d.savings).toLocaleString('ru-RU')} ₽</b><br>
Безубыточность: <b>${d.be}%</b> выработки от номинала
</div>
<div class="eip-src" style="margin-top:6px"><b>Как читать график:</b> Цветная полоса = себестоимость. Красный пунктир = тариф сети. Если полоса короче пунктира — выгодно (зелёная зона). Если длиннее — убыток.</div>`;
  const rect=el.getBoundingClientRect();
  pop.style.top=(rect.bottom+8)+'px';
  pop.style.left=Math.max(8,Math.min(rect.left,window.innerWidth-460))+'px';
  document.body.appendChild(pop);
  setTimeout(()=>{document.addEventListener('click',function _c(){const p=document.getElementById('econInfoPop');if(p)p.remove();document.removeEventListener('click',_c)},{once:true})},50);
}

// ── Grid Prices CRUD ──
async function econLoadGridPrices(apiSiteId){
  const el=$('econGridPricesTable');if(!el)return;
  try{
    const prices=await api.get('/api/economics/grid-prices/'+apiSiteId);
    if(!prices.length){el.innerHTML='<div class="econ-note">Нет записей. Добавьте тариф на электросеть.</div>';return}
    let html='<table class="econ-tbl"><thead><tr><th>С даты</th><th>Цена ₽/кВт·ч</th><th>Примечание</th><th></th></tr></thead><tbody>';
    for(const p of prices){
      html+=`<tr><td>${p.effective_from}</td><td style="font-weight:600;color:var(--b)">${p.price_per_kwh.toFixed(3)}</td><td style="color:var(--t3)">${esc(p.note||'—')}</td><td><button class="econ-del" onclick="econDelGridPrice(${p.id},${apiSiteId})">🗑</button></td></tr>`;
    }
    html+='</tbody></table>';
    el.innerHTML=html;
  }catch(e){el.innerHTML='<div class="econ-note">Ошибка загрузки тарифов: '+e.message+'</div>'}
}

async function econAddGridPrice(apiSiteId){
  const dt=$('econGridDate')?.value;
  const val=parseFloat($('econGridVal')?.value);
  const note=$('econGridNote')?.value||'';
  if(!dt||isNaN(val)||val<=0){ae('⚠ Укажите дату и цену > 0');return}
  try{
    await api.post('/api/economics/grid-prices',{site_id:apiSiteId,effective_from:dt,price_per_kwh:val,note:note||null});
    ae('✅ Тариф добавлен: '+val+' ₽/кВт·ч с '+dt);
    $('econGridVal').value='';$('econGridNote').value='';
    econLoadGridPrices(apiSiteId);
  }catch(e){ae('⚠ Ошибка: '+e.message)}
}

async function econDelGridPrice(priceId,apiSiteId){
  if(!confirm('Удалить этот тариф?'))return;
  try{
    await api.del('/api/economics/grid-prices/'+priceId);
    ae('🗑 Тариф удалён');
    econLoadGridPrices(apiSiteId);
  }catch(e){ae('⚠ Ошибка: '+e.message)}
}

// ── Planned Costs ──
function econPlannedYearNav(delta){
  _econPlannedYear+=delta;
  const lbl=$('econPlannedYearLabel');if(lbl)lbl.textContent=_econPlannedYear;
  _econPlannedDirty={};
  if(_econSiteId)econLoadPlanned(_econSiteId,_econPlannedYear);
}

async function econLoadPlanned(apiSiteId,year){
  const el=$('econPlannedTable');if(!el)return;
  try{
    const data=await api.get(`/api/economics/planned-costs/${apiSiteId}?year=${year}`);
    _econPlannedDirty={};
    const months=['Янв','Фев','Мар','Апр','Май','Июн','Июл','Авг','Сен','Окт','Ноя','Дек'];
    let html='<div style="overflow-x:auto"><table class="econ-planned-tbl"><thead><tr><th style="text-align:left;min-width:160px">Категория</th>';
    for(let m=1;m<=12;m++)html+=`<th>${months[m-1]}</th>`;
    html+='<th style="color:var(--g)">Итого</th><th></th></tr></thead><tbody>';
    for(const cat of data.categories){
      const isBase=cat.is_base;
      html+=`<tr><td title="${esc(cat.category)}" style="white-space:nowrap">${esc(cat.category_name)}</td>`;
      for(let m=1;m<=12;m++){
        const v=cat.months[String(m)]||0;
        const key=cat.category+'_'+m;
        html+=`<td><input class="econ-planned-input" type="number" step="1" min="0" value="${v}" data-cat="${esc(cat.category)}" data-catname="${esc(cat.category_name)}" data-month="${m}" onchange="econPlannedMark(this)"></td>`;
      }
      html+=`<td style="font-weight:700;color:var(--g);text-align:right;font-family:var(--m);white-space:nowrap" data-cat-total="${cat.category}">${cat.total.toLocaleString('ru-RU')}</td>`;
      html+=`<td>${isBase?'':'<button class="econ-del" onclick="econDelCategory('+apiSiteId+',\''+cat.category+'\')">🗑</button>'}</td>`;
      html+='</tr>';
    }
    // Totals row
    html+='<tr class="totals"><td>ИТОГО</td>';
    for(let m=1;m<=12;m++){
      const v=data.monthly_totals[String(m)]||0;
      html+=`<td style="font-family:var(--m);font-weight:700">${v.toLocaleString('ru-RU')}</td>`;
    }
    html+=`<td style="font-weight:700;color:var(--g);text-align:right;font-family:var(--m)">${data.grand_total.toLocaleString('ru-RU')}</td><td></td></tr>`;
    html+='</tbody></table></div>';
    el.innerHTML=html;
    // Summary
    const sum=$('econPlannedSummary');
    if(sum){
      const perMonth=data.grand_total/12;
      const perDay=data.grand_total/365;
      sum.innerHTML=`<div class="econ-summary-box">
        <div class="econ-sum-item"><div class="econ-sum-val">${data.grand_total.toLocaleString('ru-RU')}</div><div class="econ-sum-lbl">₽ / год</div></div>
        <div class="econ-sum-item"><div class="econ-sum-val">${Math.round(perMonth).toLocaleString('ru-RU')}</div><div class="econ-sum-lbl">₽ / мес (средн.)</div></div>
        <div class="econ-sum-item"><div class="econ-sum-val">${Math.round(perDay).toLocaleString('ru-RU')}</div><div class="econ-sum-lbl">₽ / день (средн.)</div></div>
      </div>`;
    }
  }catch(e){el.innerHTML='<div class="econ-note">Ошибка загрузки плановых затрат: '+e.message+'</div>'}
}

function econPlannedMark(inp){
  inp.classList.add('dirty');
  const key=inp.dataset.cat+'_'+inp.dataset.month;
  _econPlannedDirty[key]={cat:inp.dataset.cat,catname:inp.dataset.catname,month:inp.dataset.month,value:parseFloat(inp.value)||0};
}

async function econSavePlanned(apiSiteId){
  // Group dirty cells by category
  const byCat={};
  for(const k in _econPlannedDirty){
    const d=_econPlannedDirty[k];
    if(!byCat[d.cat])byCat[d.cat]={category:d.cat,category_name:d.catname,months:{}};
    byCat[d.cat].months[d.month]=d.value;
  }
  const cats=Object.values(byCat);
  if(!cats.length){ae('ℹ Нет изменений для сохранения');return}
  let ok=0,fail=0;
  for(const c of cats){
    try{
      await api.put(`/api/economics/planned-costs/${apiSiteId}`,{year:_econPlannedYear,category:c.category,category_name:c.category_name,months:c.months});
      ok++;
    }catch(e){fail++;console.error('Save planned cost error',c,e)}
  }
  _econPlannedDirty={};
  document.querySelectorAll('.econ-planned-input.dirty').forEach(i=>i.classList.remove('dirty'));
  if(fail)ae('⚠ Сохранено '+ok+', ошибок: '+fail);
  else ae('✅ Плановые затраты сохранены ('+ok+' категорий)');
  econLoadPlanned(apiSiteId,_econPlannedYear);
}

async function econAddCategory(apiSiteId){
  const cat=prompt('Код категории (англ., без пробелов):');
  if(!cat)return;
  const catName=prompt('Название категории (рус.):');
  if(!catName)return;
  const months={};for(let m=1;m<=12;m++)months[String(m)]=0;
  try{
    await api.post(`/api/economics/planned-costs/${apiSiteId}/category`,{year:_econPlannedYear,category:cat,category_name:catName,months});
    ae('✅ Категория "'+catName+'" добавлена');
    econLoadPlanned(apiSiteId,_econPlannedYear);
  }catch(e){ae('⚠ Ошибка: '+e.message)}
}

async function econDelCategory(apiSiteId,cat){
  if(!confirm('Удалить категорию "'+cat+'"?'))return;
  try{
    await api.del(`/api/economics/planned-costs/${apiSiteId}/category?year=${_econPlannedYear}&category=${encodeURIComponent(cat)}`);
    ae('🗑 Категория удалена');
    econLoadPlanned(apiSiteId,_econPlannedYear);
  }catch(e){ae('⚠ Ошибка: '+e.message)}
}

async function econCopyYear(apiSiteId){
  const src=prompt('Копировать из года:',String(_econPlannedYear-1));
  if(!src)return;
  const srcYear=parseInt(src);
  if(isNaN(srcYear)){ae('⚠ Некорректный год');return}
  if(!confirm(`Копировать плановые затраты из ${srcYear} → ${_econPlannedYear}?\nСуществующие данные за ${_econPlannedYear} будут перезаписаны.`))return;
  try{
    await api.post(`/api/economics/planned-costs/${apiSiteId}/copy-year`,{source_year:srcYear,target_year:_econPlannedYear});
    ae('✅ Данные скопированы из '+srcYear+' → '+_econPlannedYear);
    econLoadPlanned(apiSiteId,_econPlannedYear);
  }catch(e){ae('⚠ Ошибка: '+e.message)}
}

async function econLoadPrices(apiSiteId){
  const el=$('econPricesTable');if(!el)return;
  try{
    const prices=await api.get('/api/economics/gas-prices/'+apiSiteId);
    if(!prices.length){el.innerHTML='<div class="econ-note">Нет записей. Добавьте цену на газ.</div>';return}
    let html='<table class="econ-tbl"><thead><tr><th>С даты</th><th>Цена ₽/м³</th><th>Примечание</th><th></th></tr></thead><tbody>';
    for(const p of prices){
      html+=`<tr><td>${p.effective_from}</td><td style="font-weight:600;color:var(--g)">${p.price_per_m3.toFixed(2)}</td><td style="color:var(--t3)">${esc(p.note||'—')}</td><td><button class="econ-del" onclick="econDelPrice(${p.id},${apiSiteId})">🗑</button></td></tr>`;
    }
    html+='</tbody></table>';
    el.innerHTML=html;
  }catch(e){el.innerHTML='<div class="econ-note">Ошибка загрузки цен: '+e.message+'</div>'}
}

async function econAddPrice(apiSiteId){
  const dt=$('econPrDate')?.value;
  const val=parseFloat($('econPrVal')?.value);
  const note=$('econPrNote')?.value||'';
  if(!dt||isNaN(val)||val<=0){ae('⚠ Укажите дату и цену > 0');return}
  try{
    await api.post('/api/economics/gas-prices',{site_id:apiSiteId,effective_from:dt,price_per_m3:val,note:note||null});
    ae('✅ Цена добавлена: '+val+' ₽/м³ с '+dt);
    $('econPrVal').value='';$('econPrNote').value='';
    econLoadPrices(apiSiteId);
    econLoadReport(apiSiteId,_econPeriod);
  }catch(e){ae('⚠ Ошибка: '+e.message)}
}

async function econDelPrice(priceId,apiSiteId){
  if(!confirm('Удалить эту запись цены?'))return;
  try{
    await api.del('/api/economics/gas-prices/'+priceId);
    ae('🗑 Цена удалена');
    econLoadPrices(apiSiteId);
    econLoadReport(apiSiteId,_econPeriod);
  }catch(e){ae('⚠ Ошибка: '+e.message)}
}

function econSetPeriod(apiSiteId,days,btn){
  _econPeriod=days;
  document.querySelectorAll('.econ-pb').forEach(b=>b.classList.remove('on'));
  if(btn)btn.classList.add('on');
  econLoadReport(apiSiteId,days);
  econLoadComparison(days);
}

// Show detail popup for a day row (gas or energy)
function econShowDetail(e,dayIdx,type){
  e.stopPropagation();
  let pop=document.getElementById('econDetailPop');
  if(pop){pop.remove()}
  if(!_econReportData||!_econReportData.days[dayIdx])return;
  const d=_econReportData.days[dayIdx];
  const devs=d.devices||[];
  if(!devs.length)return;
  pop=document.createElement('div');
  pop.id='econDetailPop';
  pop.className='sum-popup';
  pop.style.maxWidth='480px';pop.style.minWidth='380px';
  const isGas=type==='gas';
  const dtSuf=d.last_ts?` (до ${d.last_ts} МСК)`:'';
  const title=isGas?`⛽ Расход газа — ${d.date}${dtSuf}`:`⚡ Выработка — ${d.date}${dtSuf}`;
  let html=`<div class="sum-pop-hdr">${title}</div>`;
  html+='<table style="width:100%;border-collapse:collapse;font-size:11px;font-family:var(--m)">';
  if(isGas){
    html+='<tr style="color:var(--t3);font-size:10px"><td style="padding:4px 6px">Генератор</td><td style="padding:4px 6px;text-align:right">Ср. расход</td><td style="padding:4px 6px;text-align:right">Время</td><td style="padding:4px 6px;text-align:right;font-weight:600">Объём</td></tr>';
    for(const dv of devs){
      const active=dv.avg_gas_m3h>0;
      const c=active?'var(--t)':'var(--t4)';
      html+=`<tr style="color:${c};border-top:1px solid var(--ov)"><td style="padding:5px 6px">${esc(dv.name)}</td><td style="padding:5px 6px;text-align:right">${dv.avg_gas_m3h.toFixed(1)} <span style="color:var(--t3)">м³/ч</span></td><td style="padding:5px 6px;text-align:right">${dv.hours.toFixed(1)} <span style="color:var(--t3)">ч</span></td><td style="padding:5px 6px;text-align:right;font-weight:600;color:${active?'var(--b)':'var(--t4)'}">${dv.gas_m3.toFixed(1)} <span style="color:var(--t3)">м³</span></td></tr>`;
      if(active)html+=`<tr style="font-size:9px;color:var(--t4)"><td colspan="4" style="padding:1px 6px 4px">= ${dv.avg_gas_m3h.toFixed(1)} м³/ч × ${dv.hours.toFixed(1)} ч = ${dv.gas_m3.toFixed(1)} м³</td></tr>`;
    }
    html+=`<tr style="border-top:2px solid var(--bd2);font-weight:700"><td style="padding:6px">ИТОГО</td><td></td><td></td><td style="padding:6px;text-align:right;color:var(--g)">${d.gas_m3.toFixed(1)} м³</td></tr>`;
  }else{
    html+='<tr style="color:var(--t3);font-size:10px"><td style="padding:4px 6px">Генератор</td><td style="padding:4px 6px;text-align:right">Ср. мощность</td><td style="padding:4px 6px;text-align:right">Время</td><td style="padding:4px 6px;text-align:right;font-weight:600">Выработка</td></tr>';
    for(const dv of devs){
      const active=dv.avg_power_kw>0;
      const c=active?'var(--t)':'var(--t4)';
      html+=`<tr style="color:${c};border-top:1px solid var(--ov)"><td style="padding:5px 6px">${esc(dv.name)}</td><td style="padding:5px 6px;text-align:right">${dv.avg_power_kw.toFixed(1)} <span style="color:var(--t3)">кВт</span></td><td style="padding:5px 6px;text-align:right">${dv.hours.toFixed(1)} <span style="color:var(--t3)">ч</span></td><td style="padding:5px 6px;text-align:right;font-weight:600;color:${active?'var(--g)':'var(--t4)'}">${dv.energy_kwh.toFixed(0)} <span style="color:var(--t3)">кВт·ч</span></td></tr>`;
      if(active)html+=`<tr style="font-size:9px;color:var(--t4)"><td colspan="4" style="padding:1px 6px 4px">= ${dv.avg_power_kw.toFixed(1)} кВт × ${dv.hours.toFixed(1)} ч = ${dv.energy_kwh.toFixed(0)} кВт·ч</td></tr>`;
    }
    html+=`<tr style="border-top:2px solid var(--bd2);font-weight:700"><td style="padding:6px">ИТОГО</td><td></td><td></td><td style="padding:6px;text-align:right;color:var(--g)">${d.energy_kwh.toFixed(0)} кВт·ч</td></tr>`;
  }
  html+='</table>';
  pop.innerHTML=html;
  const rect=e.target.getBoundingClientRect();
  pop.style.top=(rect.bottom+6)+'px';
  pop.style.left=Math.max(8,Math.min(rect.left-100,window.innerWidth-500))+'px';
  document.body.appendChild(pop);
  setTimeout(()=>{document.addEventListener('click',function _c(){const p=document.getElementById('econDetailPop');if(p)p.remove();document.removeEventListener('click',_c)},{once:true})},50);
}

async function econLoadReport(apiSiteId,days){
  const el=$('econReport');if(!el)return;
  try{
    const rpt=await api.get(`/api/economics/report/${apiSiteId}?last_days=${days}`);
    _econReportData=rpt;
    const t=rpt.totals;
    const nDays=rpt.days.length;
    const avgSGC=t.energy_kwh>0?(t.gas_m3/t.energy_kwh):0;
    // Top cards: show TOTALS for gas & energy, AVERAGES for SGC & cost
    const el_gas=$('econGas');if(el_gas)el_gas.textContent=t.gas_m3>0?t.gas_m3.toFixed(1):'—';
    const el_gasU=$('econGasUnit');if(el_gasU)el_gasU.textContent=nDays===1?'м³ за день':'м³ итого';
    const el_en=$('econEnergy');if(el_en)el_en.textContent=t.energy_kwh>0?t.energy_kwh.toFixed(0):'—';
    const el_enU=$('econEnergyUnit');if(el_enU)el_enU.textContent=nDays===1?'кВт·ч за день':'кВт·ч итого';
    const el_sgc=$('econSGC');if(el_sgc){el_sgc.textContent=avgSGC>0?avgSGC.toFixed(3):'—';el_sgc.style.color=avgSGC>0.5?'var(--r)':avgSGC>0.35?'var(--y)':'var(--g)'}
    const el_cost=$('econCost');if(el_cost){el_cost.textContent=t.avg_cost_per_kwh!=null?t.avg_cost_per_kwh.toFixed(2):'—';el_cost.style.color=t.avg_cost_per_kwh!=null?(t.avg_cost_per_kwh>5?'var(--r)':t.avg_cost_per_kwh>3?'var(--y)':'var(--g)'):'var(--t3)'}
    // Full cost card
    const el_fc=$('econFullCost');if(el_fc){el_fc.textContent=t.avg_full_cost_per_kwh!=null?t.avg_full_cost_per_kwh.toFixed(2):'—';el_fc.style.color=t.avg_full_cost_per_kwh!=null?(t.avg_full_cost_per_kwh>8?'var(--r)':t.avg_full_cost_per_kwh>5?'var(--y)':'var(--g)'):'var(--t3)'}
    // Grid price card
    const el_gp=$('econGridPrice');if(el_gp){el_gp.textContent=t.avg_grid_price_per_kwh!=null?t.avg_grid_price_per_kwh.toFixed(2):'—';el_gp.style.color=t.avg_grid_price_per_kwh!=null?'var(--b)':'var(--t3)'}
    // Utilization card
    const el_ut=$('econUtil');if(el_ut){el_ut.textContent=t.utilization_pct!=null?t.utilization_pct.toFixed(1):'—';el_ut.style.color=t.utilization_pct!=null?(t.utilization_pct>(t.breakeven_pct||50)?'var(--g)':'var(--r)'):'var(--t3)'}
    const el_utU=$('econUtilUnit');if(el_utU&&t.plan_kwh!=null){el_utU.innerHTML=t.energy_kwh.toFixed(0)+' / '+t.plan_kwh.toFixed(0)+' кВт·ч<br><span style="font-size:9px;color:var(--t4)">факт / план '+t.nominal_kw+' кВт (2×160) × 24ч × '+nDays+'дн.</span>'}
    // Breakeven card
    const el_be=$('econBreakeven');if(el_be){el_be.textContent=t.breakeven_pct!=null?t.breakeven_pct.toFixed(1):'—';el_be.style.color=t.breakeven_pct!=null?(t.utilization_pct>t.breakeven_pct?'var(--g)':'var(--r)'):'var(--t3)'}
    // Period info subtitle
    const el_pi=$('econPeriodInfo');if(el_pi){
      if(nDays===0)el_pi.textContent='Нет данных за выбранный период ('+days+' дн.)';
      else if(nDays===1)el_pi.textContent='Данные за '+rpt.days[0].date;
      else{
        const reqD=rpt.requested_days||days;
        let txt='Данные за '+nDays+' '+(nDays<5&&nDays>1?'дня':'дней')+' (МСК): '+rpt.days[0].date+' — '+rpt.days[nDays-1].date;
        if(nDays<reqD)txt+=' (запрошено '+reqD+')';
        el_pi.textContent=txt;
      }
    }
    // Deviation reason
    const el_dev=$('econDeviation');if(el_dev){
      if(t.deviation_reason){el_dev.style.display='block';el_dev.innerHTML='⚠ <b>Причина отклонения:</b> '+t.deviation_reason}
      else{el_dev.style.display='none'}
    }
    // Data warning banner
    const el_warn=$('econDataWarning');if(el_warn){
      if(rpt.data_warning){el_warn.style.display='block';el_warn.textContent='⚠ '+rpt.data_warning}
      else{el_warn.style.display='none'}
    }
    if(!rpt.days.length){el.innerHTML='<div class="econ-note">Нет данных за выбранный период.</div>';econRenderChart([]);return}
    let html='<div style="overflow-x:auto"><table class="econ-tbl"><thead><tr><th>Дата</th><th style="text-align:right">Газ, м³</th><th style="text-align:right">Энергия, кВт·ч</th><th style="text-align:right">Газ ₽/м³</th><th style="text-align:right">Газ ₽</th><th style="text-align:right">Газ ₽/кВт·ч</th><th style="text-align:right">Пост. ₽</th><th style="text-align:right">Полная ₽/кВт·ч</th><th style="text-align:right">Сеть ₽/кВт·ч</th></tr></thead><tbody>';
    rpt.days.forEach((d,i)=>{
      const cpk=d.cost_per_kwh!=null?d.cost_per_kwh.toFixed(2):'—';
      const cpkC=d.cost_per_kwh!=null?(d.cost_per_kwh>5?'var(--r)':d.cost_per_kwh>3?'var(--y)':'var(--g)'):'var(--t3)';
      const fcpk=d.full_cost_per_kwh!=null?d.full_cost_per_kwh.toFixed(2):'—';
      const fcpkC=d.full_cost_per_kwh!=null?(d.full_cost_per_kwh>8?'var(--r)':d.full_cost_per_kwh>5?'var(--y)':'var(--g)'):'var(--t3)';
      const gpk=d.grid_price_per_kwh!=null?d.grid_price_per_kwh.toFixed(2):'—';
      const plCost=d.planned_costs_rub!=null?d.planned_costs_rub.toFixed(0):'—';
      const dtLabel=d.last_ts?`${d.date} <span style="color:var(--t4);font-size:10px">(до ${d.last_ts})</span>`:d.date;
      html+=`<tr><td>${dtLabel}</td><td class="econ-clickable" style="text-align:right;cursor:pointer" onclick="econShowDetail(event,${i},'gas')">${d.gas_m3.toFixed(1)} 🔍</td><td class="econ-clickable" style="text-align:right;cursor:pointer" onclick="econShowDetail(event,${i},'energy')">${d.energy_kwh.toFixed(0)} 🔍</td><td style="text-align:right">${d.price_per_m3!=null?d.price_per_m3.toFixed(2):'—'}</td><td style="text-align:right">${d.cost_rub!=null?d.cost_rub.toFixed(0):'—'}</td><td style="text-align:right;color:${cpkC}">${cpk}</td><td style="text-align:right;color:var(--t3)">${plCost}</td><td style="text-align:right;color:${fcpkC};font-weight:600">${fcpk}</td><td style="text-align:right;color:var(--b)">${gpk}</td></tr>`;
    });
    html+=`<tr class="totals"><td>Итого (${rpt.days.length} дн.)</td><td style="text-align:right">${t.gas_m3.toFixed(1)}</td><td style="text-align:right">${t.energy_kwh.toFixed(0)}</td><td style="text-align:right">—</td><td style="text-align:right">${t.total_cost!=null?t.total_cost.toFixed(0):'—'}</td><td style="text-align:right;color:var(--g)">${t.avg_cost_per_kwh!=null?t.avg_cost_per_kwh.toFixed(2):'—'}</td><td style="text-align:right">${t.planned_costs!=null?t.planned_costs.toFixed(0):'—'}</td><td style="text-align:right;color:var(--g);font-weight:700">${t.avg_full_cost_per_kwh!=null?t.avg_full_cost_per_kwh.toFixed(2):'—'}</td><td style="text-align:right;color:var(--b)">${t.avg_grid_price_per_kwh!=null?t.avg_grid_price_per_kwh.toFixed(2):'—'}</td></tr>`;
    html+='</tbody></table></div>';
    el.innerHTML=html;
    econRenderChart(rpt.days);
  }catch(e){el.innerHTML='<div class="econ-note">Ошибка загрузки отчёта: '+e.message+'</div>'}
}

function econRenderChart(days){
  const canvas=$('econChartCanvas');if(!canvas)return;
  if(_econChart){_econChart.destroy();_econChart=null}
  if(!days.length)return;
  const labels=days.map(d=>d.date.slice(5));  // MM-DD for shorter labels
  const costData=days.map(d=>d.cost_per_kwh);
  const fullCostData=days.map(d=>d.full_cost_per_kwh);
  const gridPriceData=days.map(d=>d.grid_price_per_kwh);
  const gasData=days.map(d=>d.gas_m3);
  const energyData=days.map(d=>d.energy_kwh);
  // Breakeven line: full_cost at breakeven utilization (= grid price)
  const beVal=_econReportData&&_econReportData.totals.breakeven_pct!=null?_econReportData.totals.avg_grid_price_per_kwh:null;
  const breakevenData=beVal?days.map(()=>beVal):null;
  const style=getComputedStyle(document.documentElement);
  const gridColor=style.getPropertyValue('--bd').trim();
  const txtColor=style.getPropertyValue('--t3').trim();
  _econChart=new Chart(canvas,{
    type:'bar',
    data:{
      labels,
      datasets:[
        {type:'line',label:'Газ ₽/кВт·ч',data:costData,borderColor:'#00e09a',backgroundColor:'rgba(0,224,154,.08)',fill:false,tension:.3,yAxisID:'yCost',pointRadius:3,pointBackgroundColor:'#00e09a',borderWidth:2,borderDash:[4,2],order:0},
        {type:'line',label:'Полная ₽/кВт·ч',data:fullCostData,borderColor:'#ff6b81',backgroundColor:'rgba(255,107,129,.15)',fill:true,tension:.3,yAxisID:'yCost',pointRadius:4,pointBackgroundColor:'#ff6b81',borderWidth:2.5,order:0},
        {type:'line',label:'Сеть ₽/кВт·ч',data:gridPriceData,borderColor:'#4090ff',backgroundColor:'transparent',fill:false,tension:0,yAxisID:'yCost',pointRadius:2,pointBackgroundColor:'#4090ff',borderWidth:2,borderDash:[8,4],order:0},
        ...(breakevenData?[{type:'line',label:'Безубыточность',data:breakevenData,borderColor:'rgba(255,64,96,.5)',backgroundColor:'transparent',fill:false,tension:0,yAxisID:'yCost',pointRadius:0,borderWidth:1.5,borderDash:[3,6],order:0}]:[]),
        {type:'bar',label:'Газ, м³',data:gasData,backgroundColor:'rgba(64,144,255,.4)',borderColor:'#4090ff',borderWidth:1,yAxisID:'yGas',borderRadius:3,order:1},
        {type:'bar',label:'Энергия, кВт·ч',data:energyData,backgroundColor:'rgba(255,176,32,.4)',borderColor:'#ffb020',borderWidth:1,yAxisID:'yEnergy',borderRadius:3,order:2}
      ]
    },
    options:{
      responsive:true,maintainAspectRatio:false,
      interaction:{intersect:false,mode:'index'},
      plugins:{
        legend:{position:'top',labels:{color:txtColor,font:{size:11,family:'Outfit'},usePointStyle:true,padding:16}},
        tooltip:{backgroundColor:'rgba(10,15,26,.95)',titleColor:'#e8edf5',bodyColor:'#94a3b8',borderColor:gridColor,borderWidth:1,padding:10,bodyFont:{family:'JetBrains Mono',size:11},
          callbacks:{label:function(ctx){
            const v=ctx.parsed.y;if(v==null)return '';
            if(ctx.dataset.yAxisID==='yCost')return ctx.dataset.label+': '+v.toFixed(2)+' ₽/кВт·ч';
            if(ctx.dataset.yAxisID==='yGas')return 'Газ: '+v.toFixed(1)+' м³';
            return 'Энергия: '+v.toFixed(0)+' кВт·ч';
          }}
        }
      },
      scales:{
        x:{grid:{color:gridColor,lineWidth:.5},ticks:{color:txtColor,font:{size:10,family:'JetBrains Mono'}}},
        yCost:{position:'left',title:{display:true,text:'₽/кВт·ч',color:'#ff6b81',font:{size:10}},grid:{color:gridColor,lineWidth:.5},ticks:{color:'#00e09a',font:{size:10,family:'JetBrains Mono'}},beginAtZero:true},
        yGas:{position:'right',title:{display:true,text:'Газ, м³',color:'#4090ff',font:{size:10}},grid:{drawOnChartArea:false},ticks:{color:'#4090ff',font:{size:10,family:'JetBrains Mono'}},beginAtZero:true},
        yEnergy:{position:'right',title:{display:true,text:'Энергия, кВт·ч',color:'#ffb020',font:{size:10}},grid:{drawOnChartArea:false},ticks:{color:'#ffb020',font:{size:10,family:'JetBrains Mono'}},beginAtZero:true,
          // Offset third axis to prevent overlap
          afterFit:function(axis){axis.width+=50}}
      }
    }
  });
}

// ── Exports (window globals for onclick handlers) ──
export {
  showEconomics,
  econSwitchTab,
  econSetPeriod,
  econShowDetail,
  econCardInfo,
  econCmpDetail,
  econPlannedYearNav,
  econPlannedMark,
  econCopyYear,
  econAddPrice,
  econDelPrice,
  econAddGridPrice,
  econDelGridPrice,
  econAddCategory,
  econDelCategory,
  econSavePlanned,
  econRenderChart
};
