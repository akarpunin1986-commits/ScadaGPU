// SCADA GPU v5 — Dashboard module
// Extracted from legacy.js: rendering, cards, generators, SPR, summary, flow, demo, sidebar, site CRUD, clock
import { G, sv, ae } from './state.js';
import { $, esc, _v, _f1, _f2, R, RI, now, showM, hideM, fmtAlarmTime, fmtAlarmDuration } from './utils.js';
import { api, API_BASE, getDeviceIdForSlot, getDeviceIdsForSite, getGenSlots, connectWebSocket, loadFromAPI, loadAlarmDefs, decodeAlarms, trackAlarmTimes } from './api.js';
import { getChartColors } from './theme.js';
import { GENSET_ST_TEXT, SW_ST_TEXT, MAINS_ST_TEXT, MAINS_ST_RU, ATS_ST_TEXT, ST, ALARM_CODES, EVT_CAT_LABELS, EVT_CAT_CLS } from './constants.js';

// ===================== SIDEBAR =====================
function renderSB(){const k=Object.keys(G.S);const btn=$('btnTasks');if(btn){if(G.curView==='tasks')btn.classList.add('active');else btn.classList.remove('active')}$('sbSites').innerHTML=k.length?k.map(id=>{const s=G.S[id],exp=G.sbExp.has(id),active=id===G.cur&&G.curView!=='tasks',gpuOpen=exp&&G.curEq[id]==='gpu';const eqActive=active&&gpuOpen;const eqCode=id==='MKZ'||id==='mkz'?'mkz_dgu1':id==='yakz'?'yakz_dgu1':id+'_dgu1';const resp=window._eqResponsible&&window._eqResponsible[eqCode];const respLabel=resp?`<span style="font-size:10px;color:var(--t3);margin-left:4px">👤 ${resp}</span>`:'';return`<div class="sb-tree${exp?' open':''}"><div class="si${active&&!eqActive?' on':''}" onclick="togSite('${id}')"><span class="si-arrow">${exp?'▼':'▶'}</span><span class="si-name">${esc(s.name)}</span><div class="si-acts"><button class="si-btn" onclick="event.stopPropagation();openEdit('${id}')">✏</button><button class="si-btn del" onclick="event.stopPropagation();openDel('${id}')">✕</button></div></div>${exp?`<div class="sb-sub sb-eq-list"><div class="sb-eq-row${gpuOpen&&active?' open':''}" onclick="event.stopPropagation();toggleEq('${id}','gpu')"><span class="sb-eq-arrow">${gpuOpen?'▼':'▶'}</span><span class="sb-eq-name">🔌 ГПУ «Кама Энерго»${respLabel}</span></div>${gpuOpen?`<div class="sb-sub sb-eq-sub"><button class="sb-sub-btn${active&&G.curView==='monitoring'?' on':''}" onclick="event.stopPropagation();selView('${id}','monitoring')">⚡ Мониторинг</button><button class="sb-sub-btn${active&&G.curView==='alarms'?' on':''}" onclick="event.stopPropagation();selView('${id}','alarms')">🚨 Аварии</button><button class="sb-sub-btn${active&&G.curView==='archive'?' on':''}" onclick="event.stopPropagation();selView('${id}','archive')">📊 Архив</button><button class="sb-sub-btn${active&&G.curView==='to'?' on':''}" onclick="event.stopPropagation();selView('${id}','to')">📋 ТО</button><button class="sb-sub-btn${active&&G.curView==='economics'?' on':''}" onclick="event.stopPropagation();selView('${id}','economics')">💰 Экономика</button></div>`:''}</div>`:''}</div>`}).join(''):'<div style="padding:20px;text-align:center;font-size:11px;color:var(--t4)">Нет объектов. Нажмите «+ Объект»</div>'}
function togSite(id){if(G.sbExp.has(id)){G.sbExp.delete(id);renderSB()}else{G.sbExp.add(id);G.curEq[id]=G.curEq[id]||'gpu';sel(id)}}
function sel(id){G.archiveMode=false;G.curView='monitoring';G.cur=id;sv();renderSB();renderDash();if(G._snOpen)window._snUpdateCtxBadge&&window._snUpdateCtxBadge()}
function selView(id,view){G.cur=id;G.curView=view;G.archiveMode=view==='archive';sv();renderSB();if(view==='monitoring')renderDash();else if(view==='alarms')window.showAlarms&&window.showAlarms();else if(view==='archive')window.showArchive&&window.showArchive(id);else if(view==='to')window.openTOTemplates&&window.openTOTemplates();else if(view==='economics')window.showEconomics&&window.showEconomics(id);if(G._snOpen)window._snUpdateCtxBadge&&window._snUpdateCtxBadge()}
function toggleEq(siteId,eqId){G.curEq[siteId]=(G.curEq[siteId]===eqId?null:eqId);renderSB()}
function toggleAdmin(){
    const el=$('sbAdmin');if(!el)return;
    el.classList.toggle('open');
    localStorage.setItem('sbAdminOpen',el.classList.contains('open')?'1':'0');
}
(function(){const st=localStorage.getItem('sbAdminOpen');if(st==='1'){const el=document.getElementById('sbAdmin');if(el)el.classList.add('open')}})();

// ===================== SITE CRUD =====================
function openAddSite(){G.editId=null;$('smT').textContent='Новый объект';$('fN').value='';$('fC').value='';$('fC').disabled=false;$('fD').value='';populateRespSelect('');$('smA').innerHTML='<button class="bp" onclick="saveSite()">Создать</button>';showM('site')}
function openEdit(id){G.editId=id;const s=G.S[id];$('smT').textContent='Редактировать: '+s.name;$('fN').value=s.name;$('fC').value=id;$('fC').disabled=true;$('fD').value=s.desc||'';populateRespSelect(s.responsible||'');$('smA').innerHTML=`<div style="display:flex;gap:8px"><button class="bp" style="flex:1" onclick="saveSite()">Сохранить</button><button class="bdn" style="flex:0;padding:10px 16px" onclick="hideM('site');openDel('${id}')">🗑</button></div>`;showM('site')}
async function saveSite(){const n=$('fN').value.trim(),c=$('fC').value.trim().toLowerCase().replace(/[^a-z0-9_-]/g,''),d=$('fD').value.trim(),resp=$('fResp').value;if(!n||!c){ae('⚠ Укажите название и код');return}if(!G.editId&&G.S[c]){ae('⚠ Объект с кодом «'+c+'» уже существует');return}if(G.editId){G.S[G.editId].name=n;G.S[G.editId].desc=d;G.S[G.editId].responsible=resp;ae('✏ '+n);
// API: update site
if(G.apiAvailable&&G.siteApiIds[G.editId]){try{await api.patch('/api/sites/'+G.siteApiIds[G.editId],{name:n,description:d})}catch(e){console.warn('API update site error:',e)}}
}else{G.S[c]={name:n,desc:d,responsible:resp,g1:{},g2:{},spr:{}};G.cur=c;G.sbExp.add(c);G.curEq[c]='gpu';ae('✅ '+n+' создан');
// API: create site
if(G.apiAvailable){try{const s=await api.post('/api/sites',{name:n,code:c,network:'modbus',description:d});G.siteApiIds[c]=s.id;G.S[c]._apiId=s.id}catch(e){console.warn('API create site error:',e)}}
}$('fC').disabled=false;sv();hideM('site');renderSB();renderDash()}
function populateRespSelect(selectedId){populateRespSelectById('fResp',selectedId)}
async function populateRespSelectById(selId,selectedId){const sel=$(selId);if(!sel)return;sel.innerHTML='<option value="">— выберите сотрудника —</option>';
    try{const r=await fetch(API_BASE+'/api/task-manager/employees',{credentials:'include'});
        if(r.ok){const emps=await r.json();emps.forEach(e=>{const opt=document.createElement('option');opt.value=e.bitrix_id||e.id||'';opt.textContent=e.name+(e.position?' — '+e.position:'');if(String(opt.value)===String(selectedId))opt.selected=true;sel.appendChild(opt)})}}
    catch(e){const users=window.getBxUsers?window.getBxUsers():[];users.forEach(u=>{sel.innerHTML+='<option value="'+u.id+'"'+(u.id===selectedId?' selected':'')+'>'+esc(u.name)+(u.dept?' ('+esc(u.dept)+')':'')+'</option>'})}
    if(sel.options.length<=1)sel.innerHTML+='<option disabled>Нет сотрудников. Переустановите приложение Б24.</option>'}
function openDel(id){G.delId=id;$('delN').textContent=G.S[id]?.name||id;showM('del')}
async function doDel(){if(!G.delId)return;const dName=G.S[G.delId]?.name||G.delId;
// API: delete site (cascade deletes devices)
if(G.apiAvailable&&G.siteApiIds[G.delId]){try{await api.del('/api/sites/'+G.siteApiIds[G.delId]);delete G.siteApiIds[G.delId]}catch(e){console.warn('API delete site error:',e)}}
delete G.S[G.delId];if(G.cur===G.delId)G.cur=Object.keys(G.S)[0]||null;
localStorage.removeItem('s5to_'+G.delId+'_g1');localStorage.removeItem('s5to_'+G.delId+'_g2');
localStorage.removeItem('s5alm_'+G.delId+'_g1');localStorage.removeItem('s5alm_'+G.delId+'_g2');localStorage.removeItem('s5alm_'+G.delId+'_spr');
localStorage.removeItem('s5_spr_backups_'+G.delId);
ae('🗑 '+dName+' удалён');sv();hideM('del');renderSB();renderDash();G.delId=null}
async function testConn(dev){const el=$(dev+'test');el.innerHTML='<div style="padding:6px 10px;background:var(--yd);border:1px solid rgba(255,176,32,.2);border-radius:6px;font-size:11px;color:var(--y);font-family:var(--m);margin-top:6px">⏳ Тест подключения...</div>';
const s=G.S[G.cur];if(!s)return;
let ip='',port=502,slaveId=1,proto='tcp';
if(dev.startsWith('g')){ip=$('c'+dev+'i')?.value||s[dev]?.ip||'';port=+($('c'+dev+'p')?.value)||502;slaveId=+($('c'+dev+'s')?.value)||1;proto=$('c'+dev+'proto')?.value||s[dev]?.proto||'tcp'}
else if(dev==='spr'){ip=$('csi')?.value||s.spr?.ip||'';port=+($('csp')?.value)||26;slaveId=+($('css')?.value)||1;proto='rtu_over_tcp'}
if(!ip){el.innerHTML='<div style="padding:6px 10px;background:var(--rd);border:1px solid rgba(255,64,96,.2);border-radius:6px;font-size:11px;color:var(--r);font-family:var(--m);margin-top:6px">Укажите IP-адрес</div>';return}
try{const ac=new AbortController();const tid=setTimeout(()=>ac.abort(),45000);
el.innerHTML='<div style="padding:6px 10px;background:var(--yd);border:1px solid rgba(255,176,32,.2);border-radius:6px;font-size:11px;color:var(--y);font-family:var(--m);margin-top:6px">⏳ Тест подключения (ожидание до 45с)...</div>';
let r;try{const resp=await fetch(API_BASE+'/api/devices/test-connection',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ip_address:ip,port:port,slave_id:slaveId,protocol:proto}),signal:ac.signal});clearTimeout(tid);if(!resp.ok)throw new Error('HTTP '+resp.status);r=await resp.json()}catch(fe){clearTimeout(tid);if(fe.name==='AbortError')throw new Error('Таймаут 45с — конвертер не отвечает');throw fe}
if(r.success){el.innerHTML=`<div style="padding:6px 10px;background:var(--gd);border:1px solid rgba(0,224,154,.2);border-radius:6px;font-size:11px;color:var(--g);font-family:var(--m);margin-top:6px">✅ ${r.message}</div>`}
else{el.innerHTML=`<div style="padding:6px 10px;background:var(--rd);border:1px solid rgba(255,64,96,.2);border-radius:6px;font-size:11px;color:var(--r);font-family:var(--m);margin-top:6px">❌ ${r.message}</div>`}
}catch(e){el.innerHTML=`<div style="padding:6px 10px;background:var(--rd);border:1px solid rgba(255,64,96,.2);border-radius:6px;font-size:11px;color:var(--r);font-family:var(--m);margin-top:6px">❌ ${e.message}</div>`}}

// ===================== CLOCK =====================
function uCk(){const el=$('ck');if(el)el.textContent=now()}
setInterval(uCk,1000);

// ===================== CARD INTERACTIONS =====================
function tog(id){$(id)?.classList.toggle('op')}
function openAlarms(cardId,alarmTabId){const card=$(cardId);if(!card)return;if(!card.classList.contains('op'))card.classList.add('op');const tabs=card.querySelectorAll('.tb');const panels=card.querySelectorAll('.tp');tabs.forEach(t=>t.classList.remove('on'));panels.forEach(p=>p.classList.remove('on'));tabs.forEach(t=>{if(t.textContent==='Аварии')t.classList.add('on')});const ap=$(alarmTabId);if(ap)ap.classList.add('on');card.scrollIntoView({behavior:'smooth',block:'nearest'})}
function scrollToAlarm(){const cards=['cg1','cg2','cspr'];for(const id of cards){const c=$(id);if(c&&(c.classList.contains('s-wrn')||c.classList.contains('s-alm'))){const sl=id.replace('c','');const aTab=id==='cspr'?'spra':sl+'a';openAlarms(id,aTab);return}}}
function stab(btn,pid){const c=btn.closest('.cc');if(!c)return;c.querySelectorAll('.tb').forEach(b=>b.classList.remove('on'));c.querySelectorAll('.tp').forEach(p=>p.classList.remove('on'));btn.classList.add('on');$(pid)?.classList.add('on')}

// ===================== GENERATOR DISPLAY =====================
function applyGenDetailed(sl, m) {
    if (!m) return;
    const on = m.gen_status === 9 || (m.gen_status >= 1 && m.gen_status <= 8);
    const eT = $(sl + 'e');
    if (eT && on) {
        const p = m.power_total != null ? m.power_total : 0;
        const q = m.reactive_total != null ? m.reactive_total : 0;
        const pf = m.pf_avg != null ? m.pf_avg : 0;
        const uab = m.gen_uab != null ? m.gen_uab : 0;
        const ubc = m.gen_ubc != null ? m.gen_ubc : 0;
        const uca = m.gen_uca != null ? m.gen_uca : 0;
        const ia = m.current_a != null ? m.current_a : 0;
        const ib = m.current_b != null ? m.current_b : 0;
        const ic = m.current_c != null ? m.current_c : 0;
        const freq = m.gen_freq != null ? m.gen_freq : 0;
        const rh = G.S[G.cur]?.[sl]?.runHours || 0;
        const load = m.load_pct != null ? m.load_pct : 0;
        const ekwh = m.energy_kwh != null ? m.energy_kwh : 0;
        const starts = m.start_count != null ? m.start_count : 0;
        const pa = m.power_a != null ? m.power_a : 0;
        const pb = m.power_b != null ? m.power_b : 0;
        const pc = m.power_c != null ? m.power_c : 0;

        eT.innerHTML = `<div class="mg"><div class="mc"><div class="ml">P</div><div class="mv vg">${p.toFixed(1)}<span class="mu">кВт</span></div></div><div class="mc"><div class="ml">Q</div><div class="mv vn">${q.toFixed(1)}<span class="mu">квар</span></div></div><div class="mc"><div class="ml">Cos φ</div><div class="mv vn">${pf.toFixed(3)}</div></div></div><table class="pt"><thead><tr><th>Фаза</th><th>U</th><th>I</th><th>P</th></tr></thead><tbody><tr><td class="ph">A-B</td><td>${uab.toFixed(0)}</td><td>${ia.toFixed(1)}</td><td>${pa.toFixed(1)}</td></tr><tr><td class="ph">B-C</td><td>${ubc.toFixed(0)}</td><td>${ib.toFixed(1)}</td><td>${pb.toFixed(1)}</td></tr><tr><td class="ph">C-A</td><td>${uca.toFixed(0)}</td><td>${ic.toFixed(1)}</td><td>${pc.toFixed(1)}</td></tr></tbody></table><div class="mg mg4" style="margin-top:10px"><div class="mc"><div class="ml">Нагрузка</div><div class="mv vn">${load}%</div></div><div class="mc"><div class="ml">Энергия</div><div class="mv vn">${ekwh}<span class="mu">кВт·ч</span></div></div><div class="mc"><div class="ml">Моточасы</div><div class="mv vn">${rh.toFixed(0)}<span class="mu">ч</span></div></div><div class="mc"><div class="ml">Пусков</div><div class="mv vn">${starts}</div></div></div>`;
    }
    const mT = $(sl + 'm');
    if (mT && on) {
        const ct = m.coolant_temp != null ? m.coolant_temp : '—';
        const op = m.oil_pressure != null ? m.oil_pressure : '—';
        const rpm = m.engine_speed != null ? m.engine_speed : '—';
        const oilT = m.oil_temp != null ? m.oil_temp : '—';
        const gp = m.gas_pressure != null ? m.gas_pressure : (m.fuel_pressure != null ? m.fuel_pressure : '—');
        const fc = m.fuel_consumption != null ? m.fuel_consumption : '—';
        const turbo = m.turbo_pressure != null ? m.turbo_pressure : '—';
        const batt = m.battery_volt != null ? m.battery_volt : '—';
        const ctB = typeof ct==='number'?(ct>=98?'bg-r':ct>=88?'bg-w':ct<70?'bg-b':'bg-g'):'';
        const opB = typeof op==='number'?(op<103?'bg-r':op<200?'bg-w':op>=200?'bg-g':''):'';
        const otB = typeof oilT==='number'?(oilT>=125?'bg-r':oilT>=120?'bg-w':oilT<70?'bg-b':'bg-g'):'';
        const gpC = (typeof gp === 'number' && gp < 50) ? 'vw' : 'vn';
        mT.innerHTML = `<div class="mg"><div class="mc"><div class="ml">Обороты</div><div class="mv vn">${rpm}</div></div><div class="mc ${ctB}"><div class="ml">Темп.ОЖ</div><div class="mv">${ct}°C</div></div><div class="mc ${opB}"><div class="ml">Давл.масла</div><div class="mv">${op} кПа</div></div><div class="mc ${otB}"><div class="ml">Темп.масла</div><div class="mv">${oilT}°C</div></div><div class="mc"><div class="ml">Давл.газа</div><div class="mv ${gpC}">${gp} кПа</div></div><div class="mc"><div class="ml">Расход</div><div class="mv vn">${fc} л/ч</div></div><div class="mc"><div class="ml">Турбо</div><div class="mv vn">${turbo} кПа</div></div><div class="mc"><div class="ml">Батарея</div><div class="mv vn">${typeof batt === 'number' ? batt.toFixed(1) : batt}В</div></div></div>`;
    }
}

function applyGen(sl,status,rh,basePower,isOnline){const card=$('c'+sl);if(!card)return;const st=ST[status],on=status!=='standby',isO=card.classList.contains('op');
card.className='cc '+st.cls+(isO?' op':'');card.querySelector('.cdot').className='cdot '+st.dot;
const bdg=card.querySelector('.bdg');bdg.className='bdg '+st.bdg;bdg.textContent=st.txt;
// Use real WS metrics if available, else random (demo)
const devId=getDeviceIdForSlot(sl),mx=devId?G.latestMetrics[devId]:null;
const p=mx?.power_total!=null?mx.power_total:(basePower?basePower+R(-8,8):R(220,340));
const u=mx?.gen_uab!=null?mx.gen_uab:R(398,406);
const I=mx?.current_a!=null?(mx.current_a+mx.current_b+mx.current_c):(basePower?Math.round(basePower*2.5+R(-20,20)):RI(1100,1350));
const f=mx?.gen_freq!=null?mx.gen_freq:R(49.96,50.04);
const kvs=card.querySelectorAll('.kv');
if(on&&isOnline){kvs[0].className='kv vg';kvs[0].innerHTML=p.toFixed(1)+'<span class="ku">кВт</span>';kvs[1].className='kv vn';kvs[1].innerHTML=u.toFixed(0)+'<span class="ku">В</span>';kvs[2].className='kv vn';kvs[2].innerHTML=Math.round(I)+'<span class="ku">А</span>';kvs[3].className='kv vn';kvs[3].innerHTML=f.toFixed(2)+'<span class="ku">Гц</span>'}else{kvs[0].className='kv vm';kvs[0].textContent='—';kvs[1].className='kv vm';kvs[1].textContent='—';kvs[2].className='kv vm';kvs[2].textContent='—';kvs[3].className='kv vm';kvs[3].textContent='—'}
if(kvs[4]){const ats=mx?.gen_ats_status;if(ats!=null&&isOnline){const hasSd=mx.volt_diff!=null||mx.freq_diff!=null||mx.phase_diff!=null;if(ats===0&&hasSd){const sU=mx.volt_diff!=null&&Math.abs(mx.volt_diff)<5,sF=mx.freq_diff!=null&&Math.abs(mx.freq_diff)<0.3,sP=mx.phase_diff!=null&&Math.abs(mx.phase_diff)<10;const cnt=(sU?1:0)+(sF?1:0)+(sP?1:0);kvs[4].className='kv '+(cnt===3?'vg':cnt>=1?'vw':'va')+' sync-pulse';kvs[4].innerHTML=(sU?'✓':'✗')+(sF?'✓':'✗')+(sP?'✓':'✗')}else if(ats===3){kvs[4].className='kv vg';kvs[4].textContent='✓ Замкн.'}else{const atsTxt=ATS_ST_TEXT[ats]||'?';kvs[4].className='kv '+(ats===7?'vm':ats===0?'vw sync-pulse':'vn');kvs[4].textContent=atsTxt}}else{kvs[4].className='kv vm';kvs[4].textContent='—'}}
const modes=card.querySelectorAll('.mdt');modes.forEach(m=>m.classList.remove('on'));
if(isOnline&&mx){if(mx.mode_auto)modes[0]?.classList.add('on');if(mx.mode_manual)modes[1]?.classList.add('on');if(mx.mode_test)modes[2]?.classList.add('on');if(mx.mode_stop)modes[3]?.classList.add('on')}else if(isOnline){if(on)modes[0]?.classList.add('on');else modes[3]?.classList.add('on')}
if(typeof window.updateQuickButtons==='function')window.updateQuickButtons('c'+sl,mx);
// Power Limit block — always visible when online (disabled placeholder if no data)
const plb=$(sl+'-pl');if(plb){const hasPL=mx&&(mx.current_p_pct!=null||mx.target_p_pct!=null);if(hasPL&&isOnline){plb.style.display='';plb.classList.remove('disabled');const cpP=mx.current_p_pct??0,tpP=mx.target_p_pct,cpQ=mx.current_q_pct??0,tpQ=mx.target_q_pct;const pfEl=$(sl+'-pl-pf'),qfEl=$(sl+'-pl-qf'),pvEl=$(sl+'-pl-pv'),qvEl=$(sl+'-pl-qv');if(pfEl){pfEl.style.width=Math.min(cpP,100)+'%';pfEl.className='pl-fill'+(cpP>80?' pl-crit':cpP>50?' pl-warn':'')}if(qfEl){qfEl.style.width=Math.min(Math.abs(cpQ),100)+'%';qfEl.className='pl-fill pl-q'+(Math.abs(cpQ)>80?' pl-crit':Math.abs(cpQ)>50?' pl-warn':'')}if(pvEl)pvEl.textContent=cpP.toFixed(1)+'%'+(tpP!=null?' → '+tpP.toFixed(1)+'%':'');if(qvEl)qvEl.textContent=cpQ.toFixed(1)+'%'+(tpQ!=null?' → '+tpQ.toFixed(1)+'%':'')}else if(isOnline){plb.style.display='';plb.classList.add('disabled');const pfEl=$(sl+'-pl-pf'),qfEl=$(sl+'-pl-qf'),pvEl=$(sl+'-pl-pv'),qvEl=$(sl+'-pl-qv');if(pfEl)pfEl.style.width='0%';if(qfEl)qfEl.style.width='0%';if(pvEl)pvEl.textContent='—';if(qvEl)qvEl.textContent='—'}else{plb.style.display='none'}}
// Sync panel — always visible when online (disabled placeholder if no data / standby)
const syb=$(sl+'-sy');if(syb){const ats=mx?.gen_ats_status;const hasSync=mx&&(mx.volt_diff!=null||mx.freq_diff!=null||mx.phase_diff!=null);if(isOnline&&on&&hasSync){syb.style.display='';syb.classList.remove('disabled');const isClosed=ats===3;const vD=mx.volt_diff??0,fD=mx.freq_diff??0,pD=mx.phase_diff??0;const uOk=Math.abs(vD)<5,fOk=Math.abs(fD)<0.3,pOk=Math.abs(pD)<10;const allOk=uOk&&fOk&&pOk;syb.className='sy-block'+(isClosed||allOk?' sy-ok':'');syb.querySelector('.sy-hdr').textContent=isClosed?'✓ Синхронизирован':allOk?'✓ Условия совпали':'⟳ Синхронизация';const uEl=$(sl+'-sy-u'),fEl=$(sl+'-sy-f'),pEl=$(sl+'-sy-p');const uB=$(sl+'-sy-ub'),fB=$(sl+'-sy-fb'),pB=$(sl+'-sy-pb');if(uEl){uEl.innerHTML=(uOk?'<span style="color:var(--g)">✓</span> ':'<span style="color:var(--r)">✗</span> ')+(vD>0?'+':'')+vD.toFixed(1)+'В';uEl.style.color=uOk?'var(--g)':Math.abs(vD)<15?'var(--y)':'var(--r)'}if(fEl){fEl.innerHTML=(fOk?'<span style="color:var(--g)">✓</span> ':'<span style="color:var(--r)">✗</span> ')+(fD>0?'+':'')+fD.toFixed(2)+'Гц';fEl.style.color=fOk?'var(--g)':Math.abs(fD)<0.5?'var(--y)':'var(--r)'}if(pEl){pEl.innerHTML=(pOk?'<span style="color:var(--g)">✓</span> ':'<span style="color:var(--r)">✗</span> ')+(pD>0?'+':'')+pD.toFixed(1)+'°';pEl.style.color=pOk?'var(--g)':Math.abs(pD)<15?'var(--y)':'var(--r)'}if(uB){const uPct=50+Math.max(-50,Math.min(50,(vD/30)*50));uB.style.left=uPct+'%';uB.className='sy-bar-c '+(uOk?'sy-bar-ok':Math.abs(vD)<15?'sy-bar-w':'sy-bar-r')}if(fB){const fPct=50+Math.max(-50,Math.min(50,(fD/1)*50));fB.style.left=fPct+'%';fB.className='sy-bar-c '+(fOk?'sy-bar-ok':Math.abs(fD)<0.5?'sy-bar-w':'sy-bar-r')}if(pB){const pPct=50+Math.max(-50,Math.min(50,(pD/30)*50));pB.style.left=pPct+'%';pB.className='sy-bar-c '+(pOk?'sy-bar-ok':Math.abs(pD)<15?'sy-bar-w':'sy-bar-r')}}else if(isOnline){syb.style.display='';syb.className='sy-block disabled';syb.querySelector('.sy-hdr').textContent='⟳ Синхронизация';const uEl=$(sl+'-sy-u'),fEl=$(sl+'-sy-f'),pEl=$(sl+'-sy-p');if(uEl){uEl.textContent='—';uEl.style.color=''}if(fEl){fEl.textContent='—';fEl.style.color=''}if(pEl){pEl.textContent='—';pEl.style.color=''}}else{syb.style.display='none'}}
// Update run hours display in header
const rhEl=$(sl+'-rh');if(rhEl){if(!isOnline){rhEl.textContent='⏱ — ч';rhEl.style.opacity='0.4'}else{const rhVal=mx?.run_hours!=null?mx.run_hours:rh;rhEl.textContent='⏱ '+(typeof rhVal==='number'?rhVal.toFixed(0):rhVal)+' ч';rhEl.style.opacity=''}}
const tob=$(sl+'-to');if(tob){if(!isOnline){tob.querySelector('.to-head').innerHTML=`<span class="to-name" style="color:var(--t3)">⚠ Нет связи — моточасы недоступны</span>`;const bar=tob.querySelector('.to-bar');if(bar)bar.style.display='none';const tasks=tob.querySelector('.to-tasks');if(tasks)tasks.style.display='none';const hint=tob.querySelector('.to-hint');if(hint)hint.style.display='none'}else{const to=window.getNextTO(rh,G.cur,sl);if(to.unknown){tob.querySelector('.to-head').innerHTML=`<span class="to-name to-y">⚠ Укажите последнее ТО</span><span class="to-remain" style="color:var(--y);cursor:pointer" onclick="event.stopPropagation();openSet()">Настройки →</span>`;tob.onclick=function(e){e.stopPropagation();window.openSet()};const bar=tob.querySelector('.to-bar');if(bar)bar.style.display='none';const tasks=tob.querySelector('.to-tasks');if(tasks)tasks.style.display='none';const hint=tob.querySelector('.to-hint');if(hint)hint.style.display='none'}else{const tc2=to.remain<0?'to-r':to.pct>85?'to-r':to.pct>65?'to-y':'to-g';const bc2=to.remain<0?'var(--r)':to.pct>85?'var(--r)':to.pct>65?'var(--y)':'var(--g)';tob.querySelector('.to-head').innerHTML=`<span class="to-name ${tc2}">${to.name} → ${to.dueAt}ч</span><span class="to-remain">${to.remain>0?to.remain+'ч ост.':(to.remain<0?'просроч. '+Math.abs(to.remain)+'ч':'сейчас')} · ${rh}ч</span>`;const fill=tob.querySelector('.to-fill');if(fill){fill.parentElement.style.display='';fill.style.cssText=`width:${to.pct}%;background:${bc2}`}}}}
// online/offline indicator: isOnline=true means WS data arrives, separate from gen running
const connOk=isOnline!==undefined?isOnline:(mx?.online===true);
card.querySelector('.lo').className='lo '+(connOk?'lo-g':'lo-r');card.querySelector('.li span:last-child').textContent=connOk?(on?'live':'standby'):'offline';
// Detailed tabs — use real WS data if available
const ct=mx?.coolant_temp!=null?mx.coolant_temp:(status==='warning'?RI(93,99):(status==='alarm'?RI(100,108):RI(75,88)));
const op=mx?.oil_pressure!=null?mx.oil_pressure:(status==='alarm'?RI(150,250):RI(350,450));
const eT=$(sl+'e');if(eT&&isOnline){const pp=mx?.power_total!=null?mx.power_total:(on?(basePower||p):0);
const q=mx?.reactive_total!=null?mx.reactive_total:R(30,55);
const pf=mx?.pf_avg!=null?mx.pf_avg:R(.97,.999);
const uab=mx?.gen_uab!=null?mx.gen_uab:u;
const ubc=mx?.gen_ubc!=null?mx.gen_ubc:R(397,403);
const uca=mx?.gen_uca!=null?mx.gen_uca:R(399,405);
const ia=mx?.current_a!=null?mx.current_a:Math.round(I/3+R(-15,15));
const ib=mx?.current_b!=null?mx.current_b:Math.round(I/3+R(-15,15));
const ic=mx?.current_c!=null?mx.current_c:Math.round(I/3+R(-15,15));
const pa=mx?.power_a!=null?mx.power_a:(pp/3+R(-5,5));
const pb=mx?.power_b!=null?mx.power_b:(pp/3+R(-5,5));
const pc=mx?.power_c!=null?mx.power_c:(pp/3+R(-5,5));
const ld=mx?.load_pct!=null?mx.load_pct:Math.round(pp/5);
const ekwh=mx?.energy_kwh!=null?mx.energy_kwh:RI(400,500);
const starts=mx?.start_count!=null?mx.start_count:RI(300,400);
const gAts=mx?.gen_ats_status,mAts=mx?.mains_ats_status;
const gAtsTxt=gAts!=null?(ATS_ST_TEXT[gAts]||'?'):'—';const mAtsTxt=mAts!=null?(ATS_ST_TEXT[mAts]||'?'):'—';
const gAtsC=gAts===3?'vg':gAts===0?'vw':'vn';const mAtsC=mAts===3?'vg':mAts===0?'vw':'vn';
const sVd=mx?.volt_diff,sFd=mx?.freq_diff,sPd=mx?.phase_diff;
const hasSy=sVd!=null||sFd!=null||sPd!=null;
const syUok=sVd!=null&&Math.abs(sVd)<5,syFok=sFd!=null&&Math.abs(sFd)<0.3,syPok=sPd!=null&&Math.abs(sPd)<10;
const syVdC=sVd!=null?(syUok?'vg':Math.abs(sVd)<15?'vw':'va'):'vm';
const syFdC=sFd!=null?(syFok?'vg':Math.abs(sFd)<0.5?'vw':'va'):'vm';
const syPdC=sPd!=null?(syPok?'vg':Math.abs(sPd)<15?'vw':'va'):'vm';
eT.innerHTML=`<div class="mg"><div class="mc"><div class="ml">P</div><div class="mv vg">${pp.toFixed?pp.toFixed(1):pp}<span class="mu">кВт</span></div></div><div class="mc"><div class="ml">Q</div><div class="mv vn">${typeof q==='number'?q.toFixed(1):q}<span class="mu">квар</span></div></div><div class="mc"><div class="ml">Cos φ</div><div class="mv vn">${typeof pf==='number'?pf.toFixed(3):pf}</div></div></div><table class="pt"><thead><tr><th>Фаза</th><th>U</th><th>I</th><th>P</th></tr></thead><tbody><tr><td class="ph">A-B</td><td>${typeof uab==='number'?uab.toFixed(0):uab}</td><td>${typeof ia==='number'?ia.toFixed(1):ia}</td><td>${typeof pa==='number'?pa.toFixed(1):pa}</td></tr><tr><td class="ph">B-C</td><td>${typeof ubc==='number'?ubc.toFixed(0):ubc}</td><td>${typeof ib==='number'?ib.toFixed(1):ib}</td><td>${typeof pb==='number'?pb.toFixed(1):pb}</td></tr><tr><td class="ph">C-A</td><td>${typeof uca==='number'?uca.toFixed(0):uca}</td><td>${typeof ic==='number'?ic.toFixed(1):ic}</td><td>${typeof pc==='number'?pc.toFixed(1):pc}</td></tr></tbody></table><div class="mg" style="margin-top:10px"><div class="mc"><div class="ml">АВР ген.</div><div class="mv ${gAtsC}">${gAtsTxt}</div></div><div class="mc"><div class="ml">АВР сети</div><div class="mv ${mAtsC}">${mAtsTxt}</div></div></div>${hasSy?`<div class="mg" style="margin-top:10px"><div class="mc"><div class="ml">${syUok?'✓':'✗'} ΔU</div><div class="mv ${syVdC}">${sVd!=null?(sVd>0?'+':'')+sVd.toFixed(1):'—'}<span class="mu">В</span></div></div><div class="mc"><div class="ml">${syFok?'✓':'✗'} ΔHz</div><div class="mv ${syFdC}">${sFd!=null?(sFd>0?'+':'')+sFd.toFixed(2):'—'}<span class="mu">Гц</span></div></div><div class="mc"><div class="ml">${syPok?'✓':'✗'} Δ°</div><div class="mv ${syPdC}">${sPd!=null?(sPd>0?'+':'')+sPd.toFixed(1):'—'}<span class="mu">°</span></div></div></div>`:''}<div class="mg mg4" style="margin-top:10px"><div class="mc"><div class="ml">Нагрузка</div><div class="mv vn">${ld}%</div></div><div class="mc"><div class="ml">Энергия</div><div class="mv vn">${ekwh}<span class="mu">кВт·ч</span></div></div><div class="mc"><div class="ml">Моточасы</div><div class="mv vn">${typeof rh==='number'?rh.toFixed(0):rh}<span class="mu">ч</span></div></div><div class="mc"><div class="ml">Пусков</div><div class="mv vn">${starts}</div></div></div>`}
else if(eT&&!isOnline)eT.innerHTML=`<div style="color:var(--t3);font-size:12px;text-align:center;padding:20px">Нет связи</div>`;
const mT=$(sl+'m');if(mT&&isOnline){
const rpm=mx?.engine_speed!=null?mx.engine_speed:1500;
const oilT=mx?.oil_temp!=null?mx.oil_temp:RI(70,85);
const gp=mx?.gas_pressure!=null?mx.gas_pressure:(mx?.fuel_pressure!=null?mx.fuel_pressure:RI(100,200));
const fc=mx?.fuel_consumption!=null?mx.fuel_consumption:R(30,45);
const turbo=mx?.turbo_pressure!=null?mx.turbo_pressure:RI(160,200);
const batt=mx?.battery_volt!=null?mx.battery_volt:R(27,28.5);
const ctB=typeof ct==='number'?(ct>=98?'bg-r':ct>=88?'bg-w':ct<70?'bg-b':'bg-g'):'';
const opB=typeof op==='number'?(op<103?'bg-r':op<200?'bg-w':op>=200?'bg-g':''):'';
const otB=typeof oilT==='number'?(oilT>=125?'bg-r':oilT>=120?'bg-w':oilT<70?'bg-b':'bg-g'):'';
const gpC=(typeof gp==='number'&&gp<50)?'vw':'vn';
// Specific gas consumption: fuel_consumption / power_total (м³/кВт·ч)
const sgcPt=mx?.power_total!=null?mx.power_total:0;
const sgcFc=typeof fc==='number'?fc:0;
const sgcVal=(sgcPt>5&&sgcFc>0)?(sgcFc/sgcPt):null;
const sgcTxt=sgcVal!=null?sgcVal.toFixed(3):'---';
const sgcC=sgcVal!=null?(sgcVal>0.5?'bg-r':sgcVal>0.35?'bg-w':'bg-g'):'';
mT.innerHTML=`<div class="mg"><div class="mc mc-click" onclick="openFieldArchive('${sl}','engine_speed')"><div class="ml">Обороты 📈</div><div class="mv vn">${rpm}</div></div><div class="mc mc-click ${ctB}" onclick="openFieldArchive('${sl}','coolant_temp')"><div class="ml">Темп.ОЖ 📈</div><div class="mv">${ct}°C</div></div><div class="mc mc-click ${opB}" onclick="openFieldArchive('${sl}','oil_pressure')"><div class="ml">Давл.масла 📈</div><div class="mv">${op} кПа</div></div><div class="mc mc-click ${otB}" onclick="openFieldArchive('${sl}','oil_temp')"><div class="ml">Темп.масла 📈</div><div class="mv">${oilT}°C</div></div><div class="mc mc-click" onclick="openFieldArchive('${sl}','gas_pressure')"><div class="ml">Давл.газа 📈</div><div class="mv ${gpC}">${gp} кПа</div></div><div class="mc mc-click" onclick="openFieldArchive('${sl}','fuel_consumption')"><div class="ml">Расход 📈</div><div class="mv vn">${typeof fc==='number'?fc.toFixed(1):fc} м³/ч</div></div><div class="mc mc-click ${sgcC}" onclick="openFieldArchive('${sl}',null,'efficiency')"><div class="ml">Уд. расход 📈</div><div class="mv">${sgcTxt}<span class="mu"> м³/кВт·ч</span></div></div><div class="mc mc-click" onclick="openFieldArchive('${sl}','turbo_pressure')"><div class="ml">Турбо 📈</div><div class="mv vn">${turbo} кПа</div></div><div class="mc mc-click" onclick="openFieldArchive('${sl}','battery_volt')"><div class="ml">Батарея 📈</div><div class="mv vn">${typeof batt==='number'?batt.toFixed(1):batt}В</div></div></div>`}
else if(mT&&!isOnline)mT.innerHTML=`<div style="color:var(--t3);font-size:12px;text-align:center;padding:20px">Нет связи</div>`;
// --- Gas quick row (below P/U/I/f/Sync) ---
const gasRow=$(sl+'-gas');if(gasRow){const gp=mx?.gas_pressure,fcRaw=mx?.fuel_consumption,agr=mx?.air_gas_ratio;
const hasGas=gp!=null||agr!=null;
if(hasGas&&isOnline&&on){gasRow.style.display='';const gkvs=gasRow.querySelectorAll('.kv');
if(gp!=null){const gpC=gp<2?'va':gp<5?'vw':'vn';gkvs[0].className='kv '+gpC;gkvs[0].innerHTML=gp.toFixed(1)+'<span class="ku">кПа</span>'}
if(fcRaw!=null){gkvs[1].className='kv vn';gkvs[1].innerHTML=fcRaw.toFixed(1)+'<span class="ku">м³/ч</span>'}
if(agr!=null){const agrC=(agr>=0.95&&agr<=1.05)?'vg':(agr<0.8||agr>1.2)?'va':'vw';gkvs[2].className='kv '+agrC;gkvs[2].innerHTML=agr.toFixed(2)}}
else{gasRow.style.display='none'}}
// --- Gas tab ---
const gT=$(sl+'g');if(gT&&isOnline){
const ign=mx?.ignition_timing,gasT=mx?.gas_temp,ebp=mx?.exhaust_back_pressure,tvp=mx?.throttle_valve_pos,exO2=mx?.exhaust_oxygen,fvp=mx?.fuel_valve_pos,fip=mx?.fuel_inlet_pressure,tvc=mx?.throttle_valve_cmd,ets=mx?.engine_target_speed,accF=mx?.accumulated_fuel;
const gasTempC=(typeof gasT==='number'&&gasT>70)?'va':(typeof gasT==='number'&&gasT>50)?'vw':'vn';
const ebpC=(typeof ebp==='number'&&ebp>25)?'va':(typeof ebp==='number'&&ebp>15)?'vw':'vn';
const exO2C=(typeof exO2==='number'&&(exO2>8||exO2<0.5))?'va':(typeof exO2==='number'&&exO2>5)?'vw':'vn';
gT.innerHTML=`<div class="mg"><div class="mc mc-click" onclick="openFieldArchive('${sl}','ignition_timing')"><div class="ml">Зажигание 📈</div><div class="mv vn">${ign!=null?ign.toFixed(1):'---'}°</div></div><div class="mc mc-click" onclick="openFieldArchive('${sl}','gas_temp')"><div class="ml">Темп. газа 📈</div><div class="mv ${gasTempC}">${gasT!=null?gasT:'---'}°C</div></div><div class="mc mc-click" onclick="openFieldArchive('${sl}','exhaust_back_pressure')"><div class="ml">Противодавл. 📈</div><div class="mv ${ebpC}">${ebp!=null?ebp.toFixed(1):'---'} кПа</div></div><div class="mc mc-click" onclick="openFieldArchive('${sl}','throttle_valve_pos')"><div class="ml">Дроссель 📈</div><div class="mv vn">${tvp!=null?tvp.toFixed(1):'---'}%</div></div><div class="mc mc-click" onclick="openFieldArchive('${sl}','exhaust_oxygen')"><div class="ml">O₂ выхлоп 📈</div><div class="mv ${exO2C}">${exO2!=null?exO2.toFixed(1):'---'}%</div></div><div class="mc mc-click" onclick="openFieldArchive('${sl}','fuel_valve_pos')"><div class="ml">Клап. топлива 📈</div><div class="mv vn">${fvp!=null?fvp.toFixed(1):'---'}%</div></div></div><div class="mg" style="margin-top:10px"><div class="mc"><div class="ml">Давл. на входе</div><div class="mv vn">${fip!=null?fip.toFixed(1):'---'} кПа</div></div><div class="mc"><div class="ml">Цель оборотов</div><div class="mv vn">${ets!=null?ets:'---'} об/мин</div></div><div class="mc"><div class="ml">Накопл. топливо</div><div class="mv vn">${accF!=null?accF.toLocaleString():'---'} л</div></div></div>`}
else if(gT&&!isOnline)gT.innerHTML=`<div style="color:var(--t3);font-size:12px;text-align:center;padding:20px">Нет связи</div>`;
const aT=$(sl+'a-act');if(aT){let ah='';
if(!connOk) ah+=`<div class="ai aa">🔴 <b style="color:var(--r)">CONN_LOST</b> Нет связи с HGM9520N<span style="margin-left:auto;color:var(--t4)">${now()}</span></div>`;
const _did = getDeviceIdForSlot(sl);
const _genAlarms = trackAlarmTimes(_did, decodeAlarms(mx, 'generator'), mx && mx.controller_time);
for (const a of _genAlarms) {
    const _ic = a.severity==='shutdown'?'🔴':a.severity==='warning'?'⚠':'🟠';
    const _cl = a.severity==='shutdown'||a.severity==='block'?'aa':'aw';
    const _co = a.severity==='shutdown'||a.severity==='block'?'var(--r)':'var(--y)';
    const _ts = a._firstSeen ? `<span style="margin-left:auto;color:var(--t4);font-size:10px;font-family:var(--m);white-space:nowrap">⏱ ${fmtAlarmTime(a._firstSeen)} (${fmtAlarmDuration(a._firstSeen)})</span>` : '';
    ah+=`<div class="ai ${_cl}" data-alarm-code="${a.code}" data-device-id="${_did}" data-device-type="generator" style="cursor:pointer;margin-top:2px;display:flex;align-items:center;gap:6px">${_ic} <b style="color:${_co}">${a.code}</b> ${a.name_ru}${_ts}</div>`;
}
aT.innerHTML=ah||'<div style="color:var(--g);font-size:12px;text-align:center;padding:15px">✓ Нет активных аварий</div>'}}

// ===================== SPR DISPLAY =====================
function applySprDetailed(m) {
    if (!m) return;
    // SPR offline — show offline placeholder in all tabs
    if (m.online === false) {
        const offHtml = '<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;padding:32px 10px;color:var(--t4)"><div style="font-size:32px;margin-bottom:8px;opacity:.4">⚡</div><div style="font-size:13px;font-weight:600;color:var(--r)">ШПР ОФЛАЙН</div><div style="font-size:11px;margin-top:4px">Нет связи с контроллером</div></div>';
        ['sprov','sprb','sprm','sprs'].forEach(id => { const el=$(id); if(el) el.innerHTML=offHtml; });
        updateSprControlMode(m);
        return;
    }
    const mN = (m.mains_status === 0);
    const bC = (m.busbar_switch === 3);
    const mC = (m.mains_switch === 3);
    const gOn = (m.genset_status === 9);
    // Get G1 & G2 data for overview
    const g1id = getDeviceIdForSlot('g1');
    const g2id = getDeviceIdForSlot('g2');
    const g1 = g1id ? G.latestMetrics[g1id] : null;
    const g2 = g2id ? G.latestMetrics[g2id] : null;
    const g1on = g1 && g1.online !== false;
    const g2on = g2 && g2.online !== false;

    // === ОБЗОР TAB ===
    const sprov=$('sprov');
    if(sprov){
    // -- Helper: build gen panel HTML for a generator --
    function _genPanel(gx, gxon, label, gxid) {
        let st, stT, stC;
        if (!gxon) {
            st = -1; stT = 'Нет связи'; stC = 'background:rgba(255,64,96,.12);color:var(--r)';
        } else {
            st = gx.gen_status != null ? gx.gen_status : (m.genset_status != null ? m.genset_status : -1);
            stT = GENSET_ST_TEXT[st] || '—';
            stC = st === 9 ? 'background:rgba(0,224,154,.15);color:#00e09a' : 'background:var(--bg);color:var(--t3)';
        }
        let body;
        if (gxon) {
            const P=_f1(gx.power_total), Q=_f1(gx.reactive_total);
            const Uab=Math.round(_v(gx.gen_uab,0)), Ubc=Math.round(_v(gx.gen_ubc,0)), Uca=Math.round(_v(gx.gen_uca,0));
            const Ia=_f1(gx.current_a), Ib=_f1(gx.current_b), Ic=_f1(gx.current_c);
            const F=_f2(gx.gen_freq);
            body = `<div class="ov-pq"><span style="color:var(--g)"><small>P:</small>${P} кВт</span><span style="color:var(--t3)"><small>Q:</small>${Q} квар</span></div>
<table class="pt"><thead><tr><th>Фаза</th><th>U лин, В</th><th>I, А</th></tr></thead><tbody>
<tr><td class="ph">A</td><td>${Uab}</td><td>${Ia}</td></tr>
<tr><td class="ph">B</td><td>${Ubc}</td><td>${Ib}</td></tr>
<tr><td class="ph">C</td><td>${Uca}</td><td>${Ic}</td></tr></tbody></table>
<div style="text-align:center;margin-top:6px;font-family:var(--m)"><span style="color:var(--g);font-size:13px;font-weight:600">f: ${F} Гц</span></div>`;
        } else {
            body = `<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;padding:16px 10px;color:var(--t4)">
<div style="font-size:22px;margin-bottom:6px;opacity:.4">⚡</div>
<div style="font-size:11px;font-weight:500;color:var(--t3)">${label} офлайн</div>
<div style="font-size:10px">Нет связи с контроллером</div></div>`;
        }
        const dotC = gxon ? 'var(--g)' : 'var(--r)';
        return `<div class="ov-panel"><div class="ov-hdr"><div class="ov-lbl"><span style="color:${dotC}">●</span> ${label}</div><span class="ov-bdg" style="${stC}">${stT}</span></div>${body}</div>`;
    }
    const g1Html = g1id ? _genPanel(g1, g1on, 'Г1', g1id) : '';
    const g2Html = g2id ? _genPanel(g2, g2on, 'Г2', g2id) : '';
    // -- Mains panel --
    const mStR=MAINS_ST_RU[m.mains_status]||'—';
    const mStC=mN?'background:rgba(0,188,212,.15);color:#00bcd4':'background:rgba(255,64,96,.15);color:#ff4060';
    const mP=_f1(m.mains_total_p);
    const mQ=_f1(m.mains_total_q);
    const mUab=_v(m.mains_uab,'—');const mUbc=_v(m.mains_ubc,'—');const mUca=_v(m.mains_uca,'—');
    const mUa=_v(m.mains_ua,'—');const mUb=_v(m.mains_ub,'—');const mUc=_v(m.mains_uc,'—');
    const mIa=_f1(m.mains_ia);const mIb=_f1(m.mains_ib);const mIc=_f1(m.mains_ic);
    const mF=_f2(m.mains_freq);
    // -- Busbar --
    const bp=_v(m.busbar_p,0);const bq=_v(m.busbar_q,0);const bi=_v(m.busbar_current,0);
    const bU=_v(m.busbar_uab,0);const bF=_v(m.busbar_freq,0);
    // -- Running --
    const rh=_v(m.running_hours_a,_v(m.maint_hours,0));
    const rst=_v(m.start_times_a,0);
    const kwh=_v(m.accum_kwh,0);
    const batV=_f1(m.battery_volt);
    const maintH=_v(m.maint_hours,0);
    // -- Switches --
    const bSwC=bC?'var(--g)':'var(--r)';const mSwC=mC?'var(--g)':'var(--r)';
    const bSwT=bC?'ЗАМКНУТ':'РАЗОМКН';const mSwT=mC?'ЗАМКНУТ':'РАЗОМКН';
    const lineOn=bC||mC;
    // Grid: if 2 gens + mains = 3 columns, if 1 gen + mains = 2 columns
    const genCount = (g1id?1:0)+(g2id?1:0);
    const gridCols = genCount + 1; // +1 for mains
    sprov.innerHTML=`<div class="ov-grid" style="grid-template-columns:repeat(${gridCols},1fr)">
${g1Html}${g2Html}
<div class="ov-panel"><div class="ov-hdr"><div class="ov-lbl"><span style="color:var(--b)">●</span> Сеть</div><span class="ov-bdg" style="${mStC}">${mStR}</span></div>
<div class="ov-pq"><span style="color:var(--b)"><small>P:</small>${mP} кВт</span><span style="color:var(--t3)"><small>Q:</small>${mQ} квар</span></div>
<table class="pt"><thead><tr><th>Фаза</th><th>U лин, В</th><th>U фаз, В</th><th>I, А</th></tr></thead><tbody>
<tr><td class="ph">A</td><td>${mUab}</td><td>${mUa}</td><td>${mIa}</td></tr>
<tr><td class="ph">B</td><td>${mUbc}</td><td>${mUb}</td><td>${mIb}</td></tr>
<tr><td class="ph">C</td><td>${mUca}</td><td>${mUc}</td><td>${mIc}</td></tr></tbody></table>
<div style="text-align:center;margin-top:6px;font-family:var(--m)"><span style="color:var(--b);font-size:13px;font-weight:600">f: ${mF} Гц</span></div></div></div>
<div class="ov-bus"><div style="display:flex;align-items:center;gap:6px;margin-bottom:8px"><span style="color:var(--y)">●</span><span style="font-size:12px;font-weight:600">ШИНА</span><span style="margin-left:auto;font-size:10px;color:var(--t3)">→ Нагрузка</span></div>
<div class="ov-bus-grid"><div><div class="ov-bv" style="color:var(--y)">${((typeof m.multiset_total_p==='number'?m.multiset_total_p:0)+(typeof m.mains_total_p==='number'?m.mains_total_p:0)).toFixed(1)}</div><div class="ov-bl">P нагр.</div></div><div><div class="ov-bv">${(typeof bq==='number'?bq:0).toFixed(1)}</div><div class="ov-bl">Q, квар</div></div><div><div class="ov-bv">${(typeof bi==='number'?bi:0).toFixed(0)}</div><div class="ov-bl">I, А</div></div><div><div class="ov-bv">${bU}</div><div class="ov-bl">U, В</div></div><div><div class="ov-bv">${(typeof bF==='number'?bF:0).toFixed(2)}</div><div class="ov-bl">f, Гц</div></div></div></div>
<div class="ov-sw"><div class="ov-sw-item"><div class="ov-sw-lbl">Авт. шины</div><div style="font-family:var(--m);font-size:11px;font-weight:600;color:${bSwC}">${bSwT}</div></div>
<div class="ov-sw-line${lineOn?' on':''}"></div>
<div style="font-size:10px;font-weight:600;color:var(--y)">ШИНА</div>
<div class="ov-sw-line${lineOn?' on':''}"></div>
<div class="ov-sw-item"><div class="ov-sw-lbl">Авт. сети</div><div style="font-family:var(--m);font-size:11px;font-weight:600;color:${mSwC}">${mSwT}</div></div></div>
<div class="ov-stats"><div class="ov-st"><div class="ov-stv" style="color:var(--g)">${(typeof kwh==='number'?kwh:0).toLocaleString('ru-RU')}</div><div class="ov-stl">кВт·ч</div></div>
<div class="ov-st"><div class="ov-stv" style="color:var(--t)">${rh} ч</div><div class="ov-stl">Наработка · Пусков: ${rst}</div></div>
<div class="ov-st"><div class="ov-stv" style="color:var(--y)">${maintH} ч</div><div class="ov-stl">ТО осталось</div></div>
<div class="ov-st"><div class="ov-stv" style="color:var(--g)">${batV} В</div><div class="ov-stl">Батарея</div></div></div>`;
    }

    // === ШИНА TAB (sprb) - unchanged ===
    const sprb = $('sprb');
    if (sprb) {
        const bp2=_v(m.busbar_p,0);const bq2=_v(m.busbar_q,0);const bi2=_v(m.busbar_current,0);
        const bpN=typeof bp2==='number'?bp2:0;const bpC=bpN>0?'vg':bpN<0?'vw':'vn';
        const mstP=_v(m.multiset_total_p,0);const mainsTp=_v(m.mains_total_p,0);
        const totalLoad=(typeof mstP==='number'?mstP:0)+(typeof mainsTp==='number'?mainsTp:0);
        sprb.innerHTML=`<div class="mg mg4"><div class="mc"><div class="ml">P нагр.</div><div class="mv vw">${totalLoad.toFixed(1)}<span class="mu">кВт</span></div></div><div class="mc"><div class="ml">P ТТ шин</div><div class="mv ${bpC}">${bpN.toFixed(1)}<span class="mu">кВт</span></div>${bpN<0?'<div class="ms2" style="color:var(--y)">⚠ инверсия ТТ</div>':''}</div><div class="mc"><div class="ml">Q</div><div class="mv vn">${(typeof bq2==='number'?bq2:0).toFixed(1)}<span class="mu">квар</span></div></div><div class="mc"><div class="ml">I</div><div class="mv vn">${(typeof bi2==='number'?bi2:0).toFixed(0)}<span class="mu">А</span></div></div></div><table class="pt"><thead><tr><th>Фаза</th><th>U лин</th><th>U фаз</th></tr></thead><tbody><tr><td class="ph">A-B</td><td>${_v(m.busbar_uab,0)}</td><td>${_v(m.busbar_ua,0)}</td></tr><tr><td class="ph">B-C</td><td>${_v(m.busbar_ubc,0)}</td><td>${_v(m.busbar_ub,0)}</td></tr><tr><td class="ph">C-A</td><td>${_v(m.busbar_uca,0)}</td><td>${_v(m.busbar_uc,0)}</td></tr></tbody></table>`;
    }

    // === СЕТЬ TAB (sprm) - enhanced with per-phase table ===
    const sprm = $('sprm');
    if (sprm) {
        const mStR2=MAINS_ST_RU[m.mains_status]||'—';
        const stCls=mN?'vg':'va';
        const mPt=_f1(m.mains_total_p);const mQt=_f1(m.mains_total_q);const mPf=m.mains_pf_avg!=null?m.mains_pf_avg.toFixed(2):'—';
        sprm.innerHTML=`<div class="mg"><div class="mc"><div class="ml">P сети</div><div class="mv vb">${mPt}<span class="mu">кВт</span></div></div><div class="mc"><div class="ml">Q сети</div><div class="mv vn">${mQt}<span class="mu">квар</span></div></div><div class="mc"><div class="ml">cos φ</div><div class="mv vn">${mPf}</div></div></div>
<table class="pt"><thead><tr><th>Фаза</th><th>U лин, В</th><th>U фаз, В</th><th>I, А</th><th>P, кВт</th><th>cos φ</th></tr></thead><tbody>
<tr><td class="ph">A</td><td>${_v(m.mains_uab,'—')}</td><td>${_v(m.mains_ua,'—')}</td><td>${_f1(m.mains_ia)}</td><td>${_f1(m.mains_p_a)}</td><td>${m.mains_pf_a!=null?m.mains_pf_a.toFixed(2):'—'}</td></tr>
<tr><td class="ph">B</td><td>${_v(m.mains_ubc,'—')}</td><td>${_v(m.mains_ub,'—')}</td><td>${_f1(m.mains_ib)}</td><td>${_f1(m.mains_p_b)}</td><td>${m.mains_pf_b!=null?m.mains_pf_b.toFixed(2):'—'}</td></tr>
<tr><td class="ph">C</td><td>${_v(m.mains_uca,'—')}</td><td>${_v(m.mains_uc,'—')}</td><td>${_f1(m.mains_ic)}</td><td>${_f1(m.mains_p_c)}</td><td>${m.mains_pf_c!=null?m.mains_pf_c.toFixed(2):'—'}</td></tr></tbody></table>
<div style="text-align:center;margin-top:6px;font-family:var(--m)"><span style="color:var(--b);font-size:13px;font-weight:600">f: ${_f2(m.mains_freq)} Гц</span> <span style="margin-left:12px;font-size:11px;color:var(--t3)">Статус:</span> <span class="mv ${stCls}" style="font-size:11px">${mStR2}</span></div>`;
    }

    // === КОММУТАЦИЯ TAB (sprs) - enhanced ===
    const sprs = $('sprs');
    if (sprs) {
        const bSwV=m.busbar_switch!=null?m.busbar_switch:-1;
        const mSwV=m.mains_switch!=null?m.mains_switch:-1;
        const bSwT2=SW_ST_TEXT[bSwV]||'—';
        const mSwT2=SW_ST_TEXT[mSwV]||'—';
        const bSwC2=bSwV===3?'var(--g)':bSwV===7?'var(--r)':'var(--y)';
        const mSwC2=mSwV===3?'var(--g)':mSwV===7?'var(--r)':'var(--y)';
        const gStV=m.genset_status!=null?m.genset_status:-1;
        const gStT2=GENSET_ST_TEXT[gStV]||'—';
        const gStC2=gStV===9?'var(--g)':gStV===0?'var(--t3)':'var(--y)';
        const mStV=m.mains_status!=null?m.mains_status:-1;
        const mStT2=MAINS_ST_TEXT[mStV]||'—';
        const mStC2=mStV===0?'var(--g)':mStV===2||mStV===3?'var(--r)':'var(--y)';
        const ind=m.indicators!=null?m.indicators:0;
        const lineOn2=bC||mC;
        sprs.innerHTML=`<div class="ov-sw" style="margin-bottom:12px"><div class="ov-sw-item"><div class="ov-sw-lbl">Авт. шины</div><div style="font-family:var(--m);font-size:11px;font-weight:600;color:${bSwC2}">${bSwT2}</div></div>
<div class="ov-sw-line${lineOn2?' on':''}"></div><div style="font-size:10px;font-weight:600;color:var(--y)">ШИНА</div><div class="ov-sw-line${lineOn2?' on':''}"></div>
<div class="ov-sw-item"><div class="ov-sw-lbl">Авт. сети</div><div style="font-family:var(--m);font-size:11px;font-weight:600;color:${mSwC2}">${mSwT2}</div></div></div>
<div class="mg mg2"><div class="mc"><div class="ml">Статус генератора</div><div class="mv" style="color:${gStC2}">${gStT2}</div></div><div class="mc"><div class="ml">Статус сети</div><div class="mv" style="color:${mStC2}">${mStT2}</div></div></div>
<div class="ind-grid">
<div class="ind-item"><div class="ind-dot" style="background:${ind&1?'var(--g)':'var(--t4)'}"></div>Сеть норма</div>
<div class="ind-item"><div class="ind-dot" style="background:${ind&2?'var(--g)':'var(--t4)'}"></div>Сеть замкн.</div>
<div class="ind-item"><div class="ind-dot" style="background:${ind&4?'var(--g)':'var(--t4)'}"></div>Шина норма</div>
<div class="ind-item"><div class="ind-dot" style="background:${ind&8?'var(--g)':'var(--t4)'}"></div>Шина замкн.</div>
<div class="ind-item"><div class="ind-dot" style="background:${ind&16?'var(--r)':'var(--t4)'}"></div>Авария</div>
<div class="ind-item"><div class="ind-dot" style="background:${ind&32?'var(--g)':'var(--t4)'}"></div>Работа</div></div>`;
    }

    // === UPDATE CONTROL TAB BUTTONS ===
    updateSprControlMode(m);
}

function applySpr(gOn,mN,bC,mC,isOnline){const card=$('cspr');if(!card)return;const isO=card.classList.contains('op'),active=gOn||mN;
// Status: alarm (mains abnormal), running (active), standby (online but idle), offline
let cls='s-stb',dot='cd-x',bcls='bdg-off',btxt='СТОП';
if(!isOnline){cls='s-alm';dot='cd-r';bcls='bdg-a';btxt='АВАРИЯ'}
else if(!mN&&!active){cls='s-alm';dot='cd-r';bcls='bdg-a';btxt='АВАРИЯ'}
else if(active){cls='s-run';dot='cd-g';bcls='bdg-run';btxt='РАБОТА'}
else{cls='s-run';dot='cd-g';bcls='bdg-ok';btxt='НОРМА'}
card.className='cc '+cls+(isO?' op':'');card.querySelector('.cdot').className='cdot '+dot;
const bdg=card.querySelector('.bdg');bdg.className='bdg '+bcls;bdg.textContent=btxt;
const kvs=card.querySelectorAll('.kv'),bp=R(400,520),bu=RI(398,405),bf=R(49.98,50.04);
if(isOnline){
const m3=G.latestMetrics[getDeviceIdForSlot('spr')];
const rGenP=m3?.multiset_total_p||0;
const rMainsP=m3?.mains_total_p||0;
const rLoadP=rGenP+rMainsP;
const rBu=m3?.busbar_uab!=null?m3.busbar_uab:0;
const rBf=m3?.busbar_freq!=null?m3.busbar_freq:0;
kvs[0].className='kv '+(rLoadP>0?'vw':'vn');kvs[0].innerHTML=(rLoadP||0).toFixed(1)+'<span class="ku">кВт</span>';
kvs[1].className='kv vn';kvs[1].innerHTML=(rBu||0)+'<span class="ku">В</span>';
kvs[2].className='kv vn';kvs[2].innerHTML=(rBf||0).toFixed(2)+'<span class="ku">Гц</span>';
kvs[3].className=mN?'kv vg':'kv va';kvs[3].textContent=mN?'НОРМ':'АВАР';
const mode=gOn&&!mC?'ГЕН':mC&&!gOn?'СЕТЬ':gOn&&mC?'ПАРАЛ':'—';
kvs[4].className='kv '+(gOn&&mC?'vp':gOn?'vg':mN?'vb':'vm');kvs[4].textContent=mN&&!gOn?'СЕТЬ':mode;
}else kvs.forEach(k=>{k.className='kv vm';k.textContent='—'});
card.querySelector('.lo').className='lo '+(isOnline?'lo-g':'lo-r');card.querySelector('.li span:last-child').textContent=isOnline?'live':'offline';
// Tabs (Обзор/Шина/Сеть/Коммутация) are rendered by applySprDetailed() via WS updates
if(isOnline){const m3=G.latestMetrics[getDeviceIdForSlot('spr')];if(m3)applySprDetailed(m3)}
const sprAct=$('spra-act');if(sprAct){const sprMx=G.latestMetrics[getDeviceIdForSlot('spr')];let sah='';
if(!isOnline) sah+=`<div class="ai aa">🔴 <b style="color:var(--r)">CONN_LOST</b> Нет связи с HGM9560<span style="margin-left:auto;color:var(--t4)">${now()}</span></div>`;
if(isOnline&&!mN) sah+=`<div class="ai aa"${sah?' style="margin-top:2px"':''}>🔴 <b style="color:var(--r)">M001</b> Авария сети<span style="margin-left:auto;color:var(--t4)">${now()}</span></div>`;
const _sprDid = getDeviceIdForSlot('spr');
const _sprAlarms = trackAlarmTimes(_sprDid, decodeAlarms(sprMx, 'ats'), sprMx && sprMx.controller_time);
for (const a of _sprAlarms) {
    const _ic = a.severity==='shutdown'?'🔴':a.severity==='warning'?'⚠':'🟠';
    const _cl = a.severity==='shutdown'||a.severity==='block'?'aa':'aw';
    const _co = a.severity==='shutdown'||a.severity==='block'?'var(--r)':'var(--y)';
    const _ts = a._firstSeen ? `<span style="margin-left:auto;color:var(--t4);font-size:10px;font-family:var(--m);white-space:nowrap">⏱ ${fmtAlarmTime(a._firstSeen)} (${fmtAlarmDuration(a._firstSeen)})</span>` : '';
    sah+=`<div class="ai ${_cl}" data-alarm-code="${a.code}" data-device-id="${_sprDid}" data-device-type="ats" style="cursor:pointer;margin-top:2px;display:flex;align-items:center;gap:6px">${_ic} <b style="color:${_co}">${a.code}</b> ${a.name_ru}${_ts}</div>`;
}
sprAct.innerHTML=sah||'<div style="color:var(--g);font-size:12px;text-align:center;padding:15px">✓ Нет активных аварий</div>'}}

function updateSprControlMode(mx){
    if(!mx)return;
    const isOffline=mx.online===false;
    // --- Quick buttons (top row) ---
    if(typeof window.updateQuickButtons==='function')window.updateQuickButtons('cspr',mx);
    // --- Command buttons: Авто / Ручн. / Стоп ---
    const cmdMap=[
        {id:'sprCmdAuto',flag:'mode_auto',cls:'act-g'},
        {id:'sprCmdManual',flag:'mode_manual',cls:'act-y'},
        {id:'sprCmdStop',flag:'mode_stop',cls:'act-r'},
        {id:'sprCmdStart',flag:null,cls:'act-g'}, // start = genset running (status 9)
    ];
    const isRunning = mx.genset_status===9;
    cmdMap.forEach(c=>{
        const btn=$(c.id);if(!btn)return;
        btn.classList.remove('act-g','act-r','act-b','act-y');
        if(isOffline){btn.disabled=true;btn.style.opacity='.3';btn.style.pointerEvents='none';return}
        btn.disabled=false;btn.style.opacity='';btn.style.pointerEvents='';
        let active=false;
        if(c.id==='sprCmdStart') active=isRunning;
        else if(c.flag) active=!!mx[c.flag];
        if(active) btn.classList.add(c.cls);
    });
    // --- Switch buttons: Авт.сети / Авт.шины ---
    const mSwBtn=$('sprCmdMains'), bSwBtn=$('sprCmdBusbar');
    if(mSwBtn){mSwBtn.classList.remove('act-g','act-r','act-b','act-y');if(isOffline){mSwBtn.disabled=true;mSwBtn.style.opacity='.3';mSwBtn.style.pointerEvents='none'}else{mSwBtn.disabled=false;mSwBtn.style.opacity='';mSwBtn.style.pointerEvents='';if(mx.mains_switch===3)mSwBtn.classList.add('act-g');else if(mx.mains_switch===7)mSwBtn.classList.add('act-r')}}
    if(bSwBtn){bSwBtn.classList.remove('act-g','act-r','act-b','act-y');if(isOffline){bSwBtn.disabled=true;bSwBtn.style.opacity='.3';bSwBtn.style.pointerEvents='none'}else{bSwBtn.disabled=false;bSwBtn.style.opacity='';bSwBtn.style.pointerEvents='';if(mx.busbar_switch===3)bSwBtn.classList.add('act-g');else if(mx.busbar_switch===7)bSwBtn.classList.add('act-r')}}
}

// ===================== SUMMARY =====================
let _summaryIssues = []; // shared for popup
function updateSummary() {
    const s = G.S[G.cur];
    if (!s) return;

    // Collect powers and issues from latestMetrics
    let totalP = 0, genP = 0, mainsP = 0, mainsU = null, hasAlarm = false, hasWarning = false, running = 0;
    let allOffline = true, deviceCount = 0, anyOffline = false, onlineCount = 0;
    const issues = [];

    // Dynamic slot names: g1→Генератор 1, g2→Генератор 2, ... spr→ШПР
    const _slotName = (sl) => sl === 'spr' ? 'ШПР' : sl.startsWith('g') ? 'Генератор ' + sl.slice(1) : 'Устройство';

    for (const [devId, m] of Object.entries(G.latestMetrics)) {
        const info = G.deviceSlotIndex[devId];
        if (!info || info.siteKey !== G.cur) continue;
        deviceCount++;
        const devName = _slotName(info.slot);

        if (m.online === false) {
            anyOffline = true;
            issues.push({severity: 'error', text: devName + ' — нет связи'});
        } else {
            allOffline = false;
            onlineCount++;
        }

        if (info.slot.startsWith('g')) {
            const p = m.power_total || 0;
            if (m.online !== false && m.gen_status === 9) { genP += p; running++; }
            if (m.online !== false && (m.alarm_common || m.alarm_shutdown)) {
                hasAlarm = true;
                issues.push({severity: 'error', text: devName + ' — авария'});
            }
            if (m.online !== false && m.alarm_warning) {
                hasWarning = true;
                issues.push({severity: 'warn', text: devName + ' — предупреждение'});
            }
        }
        if (info.slot === 'spr') {
            if (m.online !== false) {
                mainsP = m.mains_total_p || 0;
                mainsU = m.mains_uab;
                if (m.alarm_common) {
                    hasAlarm = true;
                    issues.push({severity: 'error', text: devName + ' — авария'});
                }
                // Mains lost
                if (m.mains_status != null && m.mains_status !== 0) {
                    issues.push({severity: 'warn', text: 'Сеть — аварийная'});
                }
            }
        }
    }
    totalP = genP + mainsP;
    _summaryIssues = issues;

    const el = n => document.getElementById(n);
    if (el('sP')) el('sP').innerHTML = allOffline ? '—<span class="su">кВт</span>' : `${totalP.toFixed(1)}<span class="su">кВт</span>`;
    if (el('sPg')) el('sPg').innerHTML = allOffline ? '—<span class="su">кВт</span>' : `${genP.toFixed(1)}<span class="su">кВт</span>`;
    if (el('sU')) el('sU').innerHTML = mainsU != null ? `${mainsU.toFixed(0)}<span class="su">В</span>` : '—<span class="su">В</span>';
    if (el('sG')) el('sG').innerHTML = `${onlineCount}<span class="su">/${deviceCount}</span>`;
    if (el('sSt')) {
        const hasIssues = issues.length > 0;
        const clk = hasIssues ? ' onclick="showSummaryIssues(event)" style="cursor:pointer"' : '';
        if (deviceCount > 0 && allOffline) {
            el('sSt').innerHTML = `<span class="bdg bdg-a"${clk}>● Нет связи (${issues.length})</span>`;
        } else if (hasAlarm || anyOffline) {
            const lbl = hasAlarm ? 'Авария' : 'Ошибка';
            el('sSt').innerHTML = `<span class="bdg bdg-a"${clk}>● ${lbl} (${issues.length})</span>`;
        } else if (hasWarning) {
            el('sSt').innerHTML = `<span class="bdg bdg-w"${clk}>● Предупр. (${issues.length})</span>`;
        } else if (running > 0 || totalP > 0) {
            el('sSt').innerHTML = '<span class="bdg bdg-ok">● Норма</span>';
        } else {
            el('sSt').innerHTML = '<span class="bdg bdg-off">● Стоп</span>';
        }
    }
}

function showSummaryIssues(e) {
    e.stopPropagation();
    // Remove existing popup
    let pop = document.getElementById('summaryPopup');
    if (pop) { pop.remove(); return; }
    if (!_summaryIssues.length) return;
    pop = document.createElement('div');
    pop.id = 'summaryPopup';
    pop.className = 'sum-popup';
    let html = '<div class="sum-pop-hdr">Проблемы объекта</div>';
    for (const iss of _summaryIssues) {
        const ic = iss.severity === 'error' ? '🔴' : '🟡';
        html += `<div class="sum-pop-row">${ic} ${iss.text}</div>`;
    }
    pop.innerHTML = html;
    // Position near the badge
    const rect = e.target.getBoundingClientRect();
    pop.style.top = (rect.bottom + 8) + 'px';
    pop.style.left = Math.max(8, rect.left - 60) + 'px';
    document.body.appendChild(pop);
    // Close on click outside
    setTimeout(() => {
        document.addEventListener('click', function _closePop() {
            const p = document.getElementById('summaryPopup');
            if (p) p.remove();
            document.removeEventListener('click', _closePop);
        }, {once: true});
    }, 50);
}

function updateFlowFromMetrics() {
    const pf = $('pflow');
    if (!pf || !G.cur || !G.S[G.cur]) return;

    let g1on = false, g2on = false, mN = false, bC = false, mC = false, p1 = 0, p2 = 0, mP = 0, busP = 0;
    // g1st/g2st: 0=не настроен, 1=офлайн, 2=онлайн; sprSt: 0=не настроен, 1=офлайн, 2=онлайн
    const g1id = getDeviceIdForSlot('g1'), g2id = getDeviceIdForSlot('g2'), sprId = getDeviceIdForSlot('spr');
    let g1st = g1id ? 1 : 0, g2st = g2id ? 1 : 0, sprSt = sprId ? 1 : 0;

    for (const [devId, m] of Object.entries(G.latestMetrics)) {
        const info = G.deviceSlotIndex[devId];
        if (!info || info.siteKey !== G.cur) continue;
        if (info.slot === 'g1') { g1on = m.gen_status === 9; p1 = (m.online !== false) ? (m.power_total || 0) : 0; if(m.online !== false) g1st = 2; }
        else if (info.slot === 'g2') { g2on = m.gen_status === 9; p2 = (m.online !== false) ? (m.power_total || 0) : 0; if(m.online !== false) g2st = 2; }
        else if (info.slot.startsWith('g')) {
            // g3+ generators: aggregate power into p2 for flow display
            const gp = (m.online !== false) ? (m.power_total || 0) : 0;
            if (m.gen_status === 9) { g2on = true; p2 += gp; }
            if(m.online !== false) g2st = 2;
        }
        if (info.slot === 'spr') {
            if(m.online !== false) { sprSt = 2; }
            mN = (m.online !== false) ? (m.mains_status === 0) : false;
            bC = (m.online !== false) ? (m.busbar_switch === 3) : false;
            mC = (m.online !== false) ? (m.mains_switch === 3) : false;
            mP = (m.online !== false) ? (m.mains_total_p || 0) : 0;
            busP = (m.online !== false) ? (m.busbar_p || 0) : 0;
        }
    }

    pf.innerHTML = flowSvg(g1on, g2on, mN, bC, mC, p1, p2, mP, busP, g1st, g2st, sprSt);
}

// ===================== FLOW SVG =====================
function _gc(st,on){
    if(st===0)return{fill:'var(--ov)',stroke:'var(--t4)',txt:'var(--t4)',sub:'var(--t4)',lbl:'—'};
    if(st===1)return{fill:'rgba(255,64,96,.06)',stroke:'#ff4060',txt:'#ff4060',sub:'rgba(255,64,96,.5)',lbl:'ОФЛАЙН'};
    return on
        ?{fill:'rgba(0,224,154,.1)',stroke:'var(--g)',txt:'var(--g)',sub:'rgba(0,224,154,.6)',lbl:null}
        :{fill:'rgba(0,224,154,.04)',stroke:'rgba(0,224,154,.5)',txt:'rgba(0,224,154,.7)',sub:'rgba(0,224,154,.4)',lbl:'СТОП'};
}

function flowSvg(g1on,g2on,mN,bC,mC,p1,p2,mP,busP,g1st,g2st,sprSt){
p1=p1||0;p2=p2||0;mP=mP||0;busP=busP||0;
g1st=g1st||0;g2st=g2st||0;sprSt=sprSt===undefined?2:sprSt; // 0=не настроен, 1=офлайн, 2=онлайн
const sprOff=sprSt===1;
const gAct=(g1on||g2on)&&bC&&!sprOff,mAct=mN&&mC&&!sprOff,busAct=gAct||mAct;
const g1act=g1on&&bC&&!sprOff,g2act=g2on&&bC&&!sprOff;
const genTotal=p1+p2;
// P нагрузки = P генераторов + P сети (через замкнутые автоматы)
const loadP=(bC?genTotal:0)+(mC?mP:0);
// Line thickness proportional to power (2-5px range)
const g1w=g1act?Math.max(2,Math.min(5,p1/100)):2.5;
const g2w=g2act?Math.max(2,Math.min(5,p2/100)):2.5;
const mw=mAct?Math.max(2,Math.min(5,mP/100)):2.5;
// Line class for offline segments
const g1line=g1st===1?'off':(g1act?'on':'');
const g2line=g2st===1?'off':(g2act?'on':'');
const sprBusL=sprOff?'off':(gAct?'on':(busAct?'on':''));
const sprBusR=sprOff?'off':(mAct?'monR':(busAct?'on':''));
const sprLoad=sprOff?'off':(busAct?'lon':'');
const sprMainsLine=sprOff?'off':(mAct?'monR':'');
// Power label formatting
const _pw=v=>Math.abs(v)>=1000?(v/1000).toFixed(1)+' МВт':v.toFixed(1)+' кВт';
const c1=_gc(g1st,g1on),c2=_gc(g2st,g2on);
const _pws=v=>Math.abs(v)>=1000?(v/1000).toFixed(0)+'М':Math.round(v)+'';
return`<svg viewBox="0 0 740 96" style="width:100%">
<!-- G1 (source, top-left) -->
<circle cx="38" cy="16" r="16" fill="${c1.fill}" stroke="${c1.stroke}" stroke-width="1.5"/>
<text x="38" y="12" fill="${c1.txt}" font-size="8" text-anchor="middle" font-family="var(--m)" font-weight="700">Г1</text>
<text x="38" y="21" fill="${c1.sub}" font-size="6.5" text-anchor="middle" font-family="var(--m)" font-weight="600">${c1.lbl||(p1>0?_pws(p1)+' кВт':'РАБ')}</text>
<!-- G1 → Y-join -->
<line x1="54" y1="16" x2="100" y2="16" class="pline ${g1line}" stroke-width="${g1w}"/>
<line x1="100" y1="16" x2="100" y2="38" class="pline ${g1line}" stroke-width="${g1w}"/>
<!-- G2 (source, bottom-left) -->
<circle cx="38" cy="60" r="16" fill="${c2.fill}" stroke="${c2.stroke}" stroke-width="1.5"/>
<text x="38" y="56" fill="${c2.txt}" font-size="8" text-anchor="middle" font-family="var(--m)" font-weight="700">Г2</text>
<text x="38" y="65" fill="${c2.sub}" font-size="6.5" text-anchor="middle" font-family="var(--m)" font-weight="600">${c2.lbl||(p2>0?_pws(p2)+' кВт':'РАБ')}</text>
<!-- G2 → Y-join -->
<line x1="54" y1="60" x2="100" y2="60" class="pline ${g2line}" stroke-width="${g2w}"/>
<line x1="100" y1="60" x2="100" y2="38" class="pline ${g2line}" stroke-width="${g2w}"/>
<!-- Y-join → Busbar Switch -->
<line x1="100" y1="38" x2="150" y2="38" class="pline ${(g1st===1&&g2st===1)?'off':(gAct?'on':'')}"/>
<!-- GEN POWER LABEL: P генераторов (сумма G1+G2) — над линией авт.шины→шина -->
${gAct&&genTotal>0&&!sprOff?`<text x="270" y="34" fill="var(--g)" font-size="7.5" text-anchor="middle" font-family="var(--m)" font-weight="700" style="cursor:pointer" onclick="showPwChart('bus')">${_pw(genTotal)}</text>`:''}
<!-- Busbar Switch -->
<rect x="150" y="28" width="48" height="20" rx="4" fill="${sprOff?'rgba(255,64,96,.06)':(bC?'rgba(0,224,154,.08)':'var(--ov)')}" stroke="${sprOff?'#ff4060':(bC?'var(--g)':'var(--t4)')}" stroke-width="1.5"/>
<text x="174" y="41" fill="${sprOff?'#ff4060':(bC?'var(--g)':'var(--t3)')}" font-size="6.5" text-anchor="middle" font-family="var(--m)" font-weight="600">${sprOff?'ОФЛАЙН':(bC?'ЗАМКН':'РАЗОМК')}</text>
<text x="174" y="23" fill="${sprOff?'rgba(255,64,96,.5)':'var(--t3)'}" font-size="5.5" text-anchor="middle" font-family="var(--m)">Авт. шины</text>
<!-- Busbar Switch → BUS LEFT -->
<line x1="198" y1="38" x2="340" y2="38" class="pline bus ${sprBusL}" stroke-width="4"/>
<!-- BUS CENTER LABEL -->
<rect x="340" y="29" width="64" height="18" rx="4" fill="${sprOff?'rgba(255,64,96,.06)':'var(--bg3)'}" stroke="${sprOff?'#ff4060':(busAct?'var(--g)':'var(--t4)')}" stroke-width="1"/>
<text x="372" y="41" fill="${sprOff?'#ff4060':(busAct?'var(--g)':'var(--t3)')}" font-size="8" text-anchor="middle" font-family="var(--m)" font-weight="700">${sprOff?'ОФЛАЙН':'ШИНА'}</text>
<text x="372" y="24" fill="${sprOff?'rgba(255,64,96,.5)':'var(--p)'}" font-size="5.5" text-anchor="middle" font-family="var(--m)" font-weight="600">ШПР</text>
<!-- BUS RIGHT → Mains Switch -->
<line x1="404" y1="38" x2="520" y2="38" class="pline bus ${sprBusR}" stroke-width="4"/>
<!-- MAINS POWER LABEL: P сети (ТТ сетевого ввода) — над линией шина→авт.сети -->
${mC&&mP>0&&!sprOff?`<text x="462" y="34" fill="#4090ff" font-size="7.5" text-anchor="middle" font-family="var(--m)" font-weight="700" style="cursor:pointer" onclick="showPwChart('mains')">${_pw(mP)}</text>`:''}
<!-- Mains Switch -->
<rect x="520" y="28" width="48" height="20" rx="4" fill="${sprOff?'rgba(255,64,96,.06)':(mC?'rgba(64,144,255,.1)':'var(--ov)')}" stroke="${sprOff?'#ff4060':(mC?'#4090ff':'var(--t4)')}" stroke-width="1.5"/>
<text x="544" y="41" fill="${sprOff?'#ff4060':(mC?'#4090ff':'var(--t3)')}" font-size="6.5" text-anchor="middle" font-family="var(--m)" font-weight="600">${sprOff?'ОФЛАЙН':(mC?'ЗАМКН':'РАЗОМК')}</text>
<text x="544" y="23" fill="${sprOff?'rgba(255,64,96,.5)':'var(--t3)'}" font-size="5.5" text-anchor="middle" font-family="var(--m)">Авт. сети</text>
<!-- Mains Switch → MAINS -->
<line x1="568" y1="38" x2="630" y2="38" class="pline ${sprMainsLine}" stroke-width="${mw}"/>
<!-- MAINS (source, right) -->
<rect x="630" y="26" width="56" height="24" rx="5" fill="${sprOff?'var(--ov)':(mN?'rgba(64,144,255,.1)':'rgba(255,64,96,.06)')}" stroke="${sprOff?'var(--t4)':(mN?'#4090ff':'#ff4060')}" stroke-width="1.5"/>
<text x="658" y="42" fill="${sprOff?'var(--t3)':(mN?'#4090ff':'#ff4060')}" font-size="8.5" text-anchor="middle" font-family="var(--m)" font-weight="600">СЕТЬ</text>
<text x="658" y="20" fill="${sprOff?'var(--t4)':(mN?'rgba(64,144,255,.6)':'rgba(255,64,96,.5)')}" font-size="5.5" text-anchor="middle" font-family="var(--m)">${sprOff?'—':(mN?'НОРМА':'АВАРИЯ')}</text>
<!-- BUS → LOAD -->
<line x1="372" y1="47" x2="372" y2="68" class="pline ${sprLoad}" stroke-width="3.5"/>
<!-- LOAD POWER LABEL: P нагрузки = P шины + P сети -->
${busAct&&loadP>0&&!sprOff?`<text x="398" y="60" fill="var(--y)" font-size="7.5" text-anchor="start" font-family="var(--m)" font-weight="700" style="cursor:pointer" onclick="showPwChart('load')">${_pw(loadP)}</text>`:''}
<rect x="342" y="68" width="60" height="22" rx="5" fill="${sprOff?'rgba(255,64,96,.06)':(busAct?'rgba(255,176,32,.06)':'var(--ov)')}" stroke="${sprOff?'#ff4060':(busAct?'var(--y)':'var(--t4)')}" stroke-width="1.5"/>
<text x="372" y="82" fill="${sprOff?'#ff4060':(busAct?'var(--y)':'var(--t3)')}" font-size="7.5" text-anchor="middle" font-family="var(--m)" font-weight="600">${sprOff?'—':'НАГРУЗКА'}</text>
</svg>`}

// ===================== DEMO MODE =====================
// Demo scenario: [g1state, g2state, mainsNormal, busbarClosed, mainsClosed, g1power, g2power]
const SC=[
['standby','standby',true,false,true, 0,0],       // 1: нормально, сеть питает, генераторы стоят
['standby','standby',true,false,true, 0,0],       // 2: нормально
['standby','standby',false,false,true, 0,0],      // 3: АВАРИЯ СЕТИ! mains fail
['running','standby',false,false,false, 180,0],   // 4: G1 запустился, G2 ещё стоит
['running','running',false,false,false, 280,200],  // 5: оба запустились, набирают обороты
['running','running',false,true,false, 320,240],   // 6: авт.шины замкнут, генераторы под нагрузкой
['running','running',false,true,false, 340,220],   // 7: работают, G1 больше мощности чем G2
['warning','running',false,true,false, 350,260],   // 8: предупреждение G1 (темп.ОЖ)
['running','running',false,true,false, 300,280],   // 9: G1 снизил нагрузку, G2 компенсирует
['running','running',true,true,false, 280,260],    // 10: сеть вернулась! но ещё на генераторах
['running','running',true,true,true, 200,180],     // 11: параллельная работа с сетью, плавный переход
['standby','standby',true,false,true, 0,0]         // 12: генераторы остановлены, вернулись на сеть
];

function togDemo(){G.demo=!G.demo;
if(G.demo){if(G.cur&&G.S[G.cur]){const s=G.S[G.cur];if(!s.g1?.ip){s.g1={ip:'192.168.97.10',port:502,slaveId:1,runHours:1227};s.g2={ip:'192.168.97.11',port:502,slaveId:1,runHours:489};s.spr={ip:'10.11.0.2',port:26,slaveId:1};sv();renderDash()}}G.dStep=0;ae('▶ Демо');demoTick();G.demoIv=setInterval(demoTick,2500)}
else{clearInterval(G.demoIv);G.demoIv=null;
// Clean up demo power_limit data from latestMetrics
for(const did of Object.keys(G.latestMetrics)){const mx=G.latestMetrics[did];if(mx){delete mx.current_p_pct;delete mx.target_p_pct;delete mx.current_q_pct;delete mx.target_q_pct}}
ae('⏹ Стоп');renderDash()}
const b=$('demoBtn');if(b){b.textContent=G.demo?'⏹ Стоп':'▶ Демо';b.classList.toggle('demo-on',G.demo)}}

function demoTick(){if(!G.cur||!G.S[G.cur])return;G.dStep++;const sc=SC[(G.dStep-1)%SC.length],s1=sc[0],s2=sc[1],mN=sc[2],bC=sc[3],mC=sc[4],p1base=sc[5],p2base=sc[6];
const on1=s1!=='standby',on2=s2!=='standby';
// Inject ONLY power_limit fields for demo (do NOT touch online/power_total/modes — that breaks real WS data)
const _g1id=getDeviceIdForSlot('g1'),_g2id=getDeviceIdForSlot('g2');
if(_g1id){if(!G.latestMetrics[_g1id])G.latestMetrics[_g1id]={};G.latestMetrics[_g1id].current_p_pct=on1?75+R(-2,2):null;G.latestMetrics[_g1id].target_p_pct=on1?75:null;G.latestMetrics[_g1id].current_q_pct=on1?50+R(-1.5,1.5):null;G.latestMetrics[_g1id].target_q_pct=on1?50:null}
if(_g2id){if(!G.latestMetrics[_g2id])G.latestMetrics[_g2id]={};G.latestMetrics[_g2id].current_p_pct=on2?80+R(-3,3):null;G.latestMetrics[_g2id].target_p_pct=on2?80:null;G.latestMetrics[_g2id].current_q_pct=on2?45+R(-2,2):null;G.latestMetrics[_g2id].target_q_pct=on2?45:null}
// Pass actual power values to applyGen for display
applyGen('g1',s1,G.S[G.cur].g1?.runHours||1227,p1base,true);applyGen('g2',s2,G.S[G.cur].g2?.runHours||489,p2base,true);applySpr(on1||on2,mN,bC,mC,true);
const p1=on1?p1base+R(-10,10):0,p2=on2?p2base+R(-10,10):0,mP=mN&&mC?R(100,200):0;const busP2=p1+p2+(mN&&mC?mP:0);const el=n=>document.getElementById(n);
const pf=$('pflow');if(pf)pf.innerHTML=flowSvg(on1,on2,mN,bC,mC,p1,p2,mP,busP2,2,2,2);
if(el('sP'))el('sP').innerHTML=`${(p1+p2+mP).toFixed(1)}<span class="su">кВт</span>`;
if(el('sPg'))el('sPg').innerHTML=`${(p1+p2).toFixed(1)}<span class="su">кВт</span>`;
if(el('sU')){if(mN)el('sU').innerHTML=`${RI(398,406)}<span class="su">В</span>`;else el('sU').innerHTML='<span style="color:var(--r)">АВАР</span>'}
if(el('sG'))el('sG').innerHTML=`${(on1?1:0)+(on2?1:0)}<span class="su">/2</span>`;
const w=s1==='alarm'||s2==='alarm'?'a':s1==='warning'||s2==='warning'?'w':(!mN&&!on1&&!on2)?'a':'ok';
if(el('sSt'))el('sSt').innerHTML=w==='a'?'<span class="bdg bdg-a" onclick="scrollToAlarm()" style="cursor:pointer">● Авария</span>':w==='w'?'<span class="bdg bdg-w" onclick="scrollToAlarm()" style="cursor:pointer">● Предупр.</span>':'<span class="bdg bdg-ok">● Норма</span>';
if(el('sResp')){var rid=G.S[G.cur]?.responsible||'';var users=window.getBxUsers?window.getBxUsers():[];var rn='—';for(var ui=0;ui<users.length;ui++){if(users[ui].id===rid)rn=users[ui].name}el('sResp').textContent=rn}
if(el('evL'))el('evL').innerHTML=G.evts.slice(0,10).map(e=>`<div class="er"><span class="et">${e.t}</span>${esc(e.m)}</div>`).join('')}

// ===================== DASHBOARD RENDERING =====================
function renderDash(){window.stopB24Poll&&window.stopB24Poll();G.curView='monitoring';const mn=$('mainArea');setTimeout(window.showUserProfile,0);
if(!G.cur||!G.S[G.cur]){mn.innerHTML='<div class="empty-dash" style="height:100%"><div style="font-size:48px;margin-bottom:16px;opacity:.4">🏭</div><p style="font-size:14px">Выберите объект или <span style="color:var(--g);cursor:pointer" onclick="openAddSite()">создайте новый</span></p></div>';return}
const s=G.S[G.cur],genSlots=getGenSlots(G.cur),hs=!!s.spr?.ip,cfg=genSlots.filter(sl=>!!s[sl]?.ip).length+(hs?1:0),totalSlots=genSlots.length+(hs?1:0);
mn.innerHTML=`<div class="dh"><div class="dt"><div class="ld"></div><h1>${esc(s.name)}${s.desc?' — '+esc(s.desc):''}</h1></div><div style="display:flex;align-items:center;gap:16px"><div class="da"><button onclick="openSet()">⚙ Настройки</button><button id="demoBtn" class="${G.demo?'demo-on':''}" onclick="togDemo()">${G.demo?'⏹ Стоп':'▶ Демо'}</button></div><span class="ck" id="ck"></span></div></div>
<div class="ss"><div class="sc"><div class="sl2">P нагр.</div><div class="sv" style="color:var(--y)" id="sP">—<span class="su">кВт</span></div></div><div class="sc"><div class="sl2">P генераторов</div><div class="sv" style="color:var(--g)" id="sPg">—<span class="su">кВт</span></div></div><div class="sc"><div class="sl2">U сети</div><div class="sv" id="sU">—<span class="su">В</span></div></div><div class="sc"><div class="sl2">Устройства</div><div class="sv" id="sG">${cfg}<span class="su">/${totalSlots||3}</span></div></div><div class="sc"><div class="sl2">Состояние</div><div id="sSt"><span class="bdg bdg-off">${cfg?'Ожидание':'—'}</span></div></div><div class="sc"><div class="sl2">Ответственный</div><div class="sv" id="sResp" style="font-size:12px">—</div></div></div>
${cfg===0?'<div class="empty-dash" style="padding:40px"><div style="font-size:32px;margin-bottom:10px;opacity:.4">⚙</div><p>Нажмите <b>Настройки</b></p></div>':`
<div class="gg">${genSlots.map(sl=>genCard(sl,'Генератор '+sl.slice(1),s[sl])).join('')}</div>
<div class="pflow" id="pflow">${flowSvg(false,false,false,false,false,0,0,0,0,genSlots.length>=1&&s.g1?.ip?1:0,genSlots.length>=2&&s.g2?.ip?1:0,hs?1:0)}</div>
${hs?sprCard(s.spr):''}
`}<div class="ev${localStorage.getItem('evCollapsed')==='1'?' collapsed':''}" id="evPanel"><div class="ev-t" onclick="toggleEvPanel()">📋 Журнал событий <span class="ev-badge" id="evBadge"></span><span class="ev-arrow" id="evArrow">▼</span></div><div class="ev-body" id="evBody"><div id="evL"><div style="color:var(--t4);font-size:11px">Загрузка...</div></div></div></div>`;uCk();if(G.demo)demoTick();window.loadServerEvents&&window.loadServerEvents()}
function genCard(sl,nm,c){
if(!c?.ip)return`<div class="cc s-stb"><div style="padding:24px;text-align:center;color:var(--t3);font-size:12px">${nm} — не настроен<br><span style="color:var(--g);cursor:pointer" onclick="openSet()">Настроить →</span></div></div>`;
const rh=c.runHours||0,to=window.getNextTO(rh,G.cur,sl),tc=to.remain<0?'to-r':to.pct>85?'to-r':to.pct>65?'to-y':'to-g',bc=to.remain<0?'var(--r)':to.pct>85?'var(--r)':to.pct>65?'var(--y)':'var(--g)';
return`<div class="cc s-stb" id="c${sl}"><div class="ch" onclick="tog('c${sl}')">
<div class="cr1"><div class="cid"><div class="cdot cd-x"></div><div><div class="cn">${nm}</div><div class="csb">HGM9520N${c.proto==='rtu_over_tcp'?' (RTU)':''} · ${esc(c.ip)}:${c.port||(c.proto==='rtu_over_tcp'?26:502)} <span id="${sl}-rh" style="color:var(--t);font-weight:600;margin-left:6px">⏱ ${rh} ч</span></div></div></div><span class="bdg bdg-off" onclick="event.stopPropagation();openAlarms('c${sl}','${sl}a')" title="Нажми для просмотра аварий">ОЖИДАНИЕ</span></div>
<div class="kr kr5"><div class="kp"><div class="kl">P</div><div class="kv vm">—</div></div><div class="kp"><div class="kl">U</div><div class="kv vm">—</div></div><div class="kp"><div class="kl">I</div><div class="kv vm">—</div></div><div class="kp"><div class="kl">f</div><div class="kv vm">—</div></div><div class="kp"><div class="kl">Синхр.</div><div class="kv vm">—</div></div></div>
<div class="kr kr3" id="${sl}-gas" style="display:none"><div class="kp"><div class="kl">Газ</div><div class="kv vm">— кПа</div></div><div class="kp"><div class="kl">Расход</div><div class="kv vm">— м³/ч</div></div><div class="kp"><div class="kl">λ</div><div class="kv vm">—</div></div></div>
<div class="to-block" id="${sl}-to" onclick="event.stopPropagation();${to.unknown?'openSet()':'this.classList.toggle(&quot;exp&quot;)'}"><div class="to-head"><span class="to-name ${to.unknown?'to-y':tc}">${to.unknown?'⚠ Укажите последнее ТО':to.name+' → '+to.dueAt+'ч'}</span><span class="to-remain">${to.unknown?'<span style=&quot;color:var(--y);cursor:pointer&quot;>Настройки →</span>':(to.remain>0?to.remain+'ч ост.':(to.remain<0?'просроч. '+Math.abs(to.remain)+'ч':'сейчас'))+' · '+rh+'ч'}</span></div>${to.unknown?'':`<div class="to-bar"><div class="to-fill" style="width:${to.pct}%;background:${bc}"></div></div><div class="to-tasks">${to.tasks?.slice(0,5).map(t=>'• '+(t.c?'<b>':'')+t.text+(t.c?'</b>':'')).join('<br>')||''}</div><div class="to-hint">▼ работы · <span style="color:var(--g);cursor:pointer" onclick="event.stopPropagation();openTO('${sl}')">ТО</span></div>`}</div>
<div class="mds"><span class="mdt">AUTO</span><span class="mdt">MAN</span><span class="mdt">TEST</span><span class="mdt">STOP</span></div>
<div class="pl-block" id="${sl}-pl" style="display:none">
<div class="pl-hdr">⚡ Огр. мощности</div>
<div class="pl-rows">
<div class="pl-row"><span class="pl-lbl">P</span><div class="pl-bar"><div class="pl-fill" id="${sl}-pl-pf"></div></div><span class="pl-val" id="${sl}-pl-pv">—</span></div>
<div class="pl-row"><span class="pl-lbl">Q</span><div class="pl-bar"><div class="pl-fill pl-q" id="${sl}-pl-qf"></div></div><span class="pl-val" id="${sl}-pl-qv">—</span></div>
</div>
<button class="pl-btn" onclick="event.stopPropagation();openPowerLimitModal('${sl}')">📊 Подробнее</button>
</div>
<div class="sy-block" id="${sl}-sy" style="display:none">
<div class="sy-hdr">⟳ Синхронизация</div>
<div class="sy-rows">
<div class="sy-col"><div class="sy-lbl">ΔU</div><div class="sy-val" id="${sl}-sy-u">—</div><div class="sy-bar"><div class="sy-bar-c" id="${sl}-sy-ub"></div></div></div>
<div class="sy-col"><div class="sy-lbl">ΔHz</div><div class="sy-val" id="${sl}-sy-f">—</div><div class="sy-bar"><div class="sy-bar-c" id="${sl}-sy-fb"></div></div></div>
<div class="sy-col"><div class="sy-lbl">Δ°</div><div class="sy-val" id="${sl}-sy-p">—</div><div class="sy-bar"><div class="sy-bar-c" id="${sl}-sy-pb"></div></div></div>
</div>
</div></div>
<!-- QUICK CONTROLS always visible -->
<div style="padding:0 10px 5px"><div class="qc">
<button class="qb q-start" onclick="event.stopPropagation();cmdConfirm('${nm}','Start','▶ Пуск','FC05 coil 0x0000: Remote Start')">▶ Пуск</button>
<button class="qb q-stop" onclick="event.stopPropagation();cmdConfirm('${nm}','Stop','⏹ Стоп','FC05 coil 0x0001: Remote Stop')">⏹ Стоп</button>
<button class="qb q-auto" onclick="event.stopPropagation();cmdConfirm('${nm}','Auto','🅰 Авто','FC05 coil 0x0003: Remote Auto')">🅰 Авто</button>
<button class="qb q-manual" onclick="event.stopPropagation();cmdConfirm('${nm}','Manual','🔧 Ручной','FC05 coil 0x0004: Remote Manual')">🔧 Руч.</button>
</div><div class="cmd-st" id="cs-${nm.replace(/[\s\/]/g,'')}"></div></div>
<div class="cv" onclick="tog('c${sl}')"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9l6 6 6-6"/></svg></div>
<div class="ce"><div class="ei">
<div class="tbs"><button class="tb on" onclick="stab(this,'${sl}e')">Электрика</button><button class="tb" onclick="stab(this,'${sl}m')">Двигатель</button><button class="tb" onclick="stab(this,'${sl}g')">Газ</button><button class="tb" onclick="stab(this,'${sl}a')">Аварии</button><button class="tb" onclick="stab(this,'${sl}c')">Все команды</button></div>
<div class="tp on" id="${sl}e"><div style="color:var(--t3);font-size:12px;text-align:center;padding:20px">Ожидание данных...</div></div>
<div class="tp" id="${sl}m"><div style="color:var(--t3);font-size:12px;text-align:center;padding:20px">Ожидание...</div></div>
<div class="tp" id="${sl}g"><div style="color:var(--t3);font-size:12px;text-align:center;padding:20px">Ожидание данных ECU...</div></div>
<div class="tp" id="${sl}a">
<div style="display:flex;gap:4px;margin-bottom:8px"><button class="spr-b" style="flex:1;font-weight:600;color:var(--r)" id="${sl}a-act-btn" onclick="showAlarmSub('${sl}','act')">🔴 Активные</button><button class="spr-b" style="flex:1" id="${sl}a-arc-btn" onclick="showAlarmSub('${sl}','arc')">📋 Архив</button></div>
<div id="${sl}a-act"><div style="color:var(--t3);font-size:12px;text-align:center;padding:20px">Нет аварий ✓</div></div>
<div id="${sl}a-arc" style="display:none"><div style="color:var(--t3);font-size:12px;text-align:center;padding:15px">Архив пуст</div></div>
</div>
<div class="tp" id="${sl}c"><div style="font-size:11px;color:var(--t3);margin-bottom:8px">Все команды HGM9520N (FC05)</div>
<div class="cg">
<button class="cb2 cgo q-start" onclick="event.stopPropagation();cmdConfirm('${nm}','Start','▶ Пуск','FC05 0x0000')"><span class="ci2">▶</span>Пуск</button>
<button class="cb2 cst q-stop" onclick="event.stopPropagation();cmdConfirm('${nm}','Stop','⏹ Стоп','FC05 0x0001')"><span class="ci2">⏹</span>Стоп</button>
<button class="cb2 q-auto" onclick="event.stopPropagation();cmdConfirm('${nm}','Auto','🅰 Авто','FC05 0x0003')"><span class="ci2">🅰</span>Авто</button>
<button class="cb2 q-manual" onclick="event.stopPropagation();cmdConfirm('${nm}','Manual','🔧 Ручной','FC05 0x0004')"><span class="ci2">🔧</span>Ручной</button>
<button class="cb2" onclick="event.stopPropagation();cmdConfirm('${nm}','GenClose','⚡ ВКЛ ген.','FC05 0x0006: Remote Gen Close')"><span class="ci2">⚡</span>ВКЛ ген.</button>
<button class="cb2" onclick="event.stopPropagation();cmdConfirm('${nm}','GenOpen','⚡ ОТКЛ ген.','FC05 0x0007: Remote Gen Open')"><span class="ci2">⚡</span>ОТКЛ ген.</button>
<button class="cb2" onclick="event.stopPropagation();cmdConfirm('${nm}','MainsClose','🔌 Авт.сети','FC05 0x0005: Mains Close/Open')"><span class="ci2">🔌</span>Авт.сети</button>
<button class="cb2" onclick="event.stopPropagation();cmdConfirm('${nm}','Mute','🔇 Тишина','FC05 addr 0x000C (12): Remote Mute Key')"><span class="ci2">🔇</span>Тишина</button>
<button class="cb2" onclick="event.stopPropagation();smartReset('${sl}','${nm}')"><span class="ci2">🔄</span>Сброс</button>
</div><div style="margin-top:8px"><button class="cb2 q-danger" style="width:100%;flex-direction:row;justify-content:center;gap:8px;padding:10px" onclick="event.stopPropagation();cmdConfirm('${nm}','FastStop','🛑 Экстренный стоп','FC05 addr 0x000F (15): Remote Diesel Engine Fast Stop')"><span>🛑</span>Экстренный стоп</button></div>
</div></div></div>
<div class="cf"><div class="li"><span class="lo lo-r"></span><span>ожидание</span></div><span>${c.proto==='rtu_over_tcp'?'rtu':'tcp'}:${c.port||(c.proto==='rtu_over_tcp'?26:502)} · id:${c.slaveId||1}</span></div></div>`}
function sprCard(c){return`<div class="sr2"><div class="cc s-stb" id="cspr"><div class="ch" onclick="tog('cspr')">
<div class="cr1"><div class="cid"><div class="cdot cd-x"></div><div><div class="cn" style="color:var(--p)">ШПР</div><div class="csb">HGM9560 · ${esc(c.ip)}:${c.port||26} · RTU</div></div></div><span class="bdg bdg-off" onclick="event.stopPropagation();openAlarms('cspr','spra')" title="Нажми для просмотра аварий">ОЖИДАНИЕ</span></div>
<div class="kr kr5"><div class="kp"><div class="kl">P нагр.</div><div class="kv vm">—</div></div><div class="kp"><div class="kl">U</div><div class="kv vm">—</div></div><div class="kp"><div class="kl">f</div><div class="kv vm">—</div></div><div class="kp"><div class="kl">Сеть</div><div class="kv vm">—</div></div><div class="kp"><div class="kl">Режим</div><div class="kv vm">—</div></div></div></div>
<!-- SPR QUICK CONTROLS -->
<div style="padding:0 10px 5px"><div class="qc">
<button class="qb q-start" onclick="event.stopPropagation();cmdConfirm('ШПР','Start','▶ Пуск','FC05 0x0000')">▶ Пуск</button>
<button class="qb q-stop" onclick="event.stopPropagation();cmdConfirm('ШПР','Stop','⏹ Стоп','FC05 0x0001')">⏹ Стоп</button>
<button class="qb q-auto" onclick="event.stopPropagation();cmdConfirm('ШПР','Auto','🅰 Авто','FC05 0x0003')">🅰 Авто</button>
<button class="qb q-manual" onclick="event.stopPropagation();cmdConfirm('ШПР','Manual','🔧 Ручной','FC05 0x0004')">🔧 Руч.</button>
</div><div class="cmd-st" id="cs-ШПР"></div></div>
<div class="cv" onclick="tog('cspr')"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9l6 6 6-6"/></svg></div>
<div class="ce"><div class="ei">
<div class="tbs"><button class="tb on" onclick="stab(this,'sprov')">Обзор</button><button class="tb" onclick="stab(this,'sprb')">Шина</button><button class="tb" onclick="stab(this,'sprm')">Сеть</button><button class="tb" onclick="stab(this,'sprs')">Коммутация</button><button class="tb" onclick="stab(this,'spra')">Аварии</button><button class="tb" onclick="stab(this,'sprc');onSprControlTabOpen()">Управление</button><button class="tb" onclick="stab(this,'sprp')">Пресеты</button></div>
<div class="tp on" id="sprov"><div style="color:var(--t3);font-size:12px;text-align:center;padding:20px">Ожидание...</div></div>
<div class="tp" id="sprb"><div style="color:var(--t3);font-size:12px;text-align:center;padding:20px">Ожидание...</div></div>
<div class="tp" id="sprm"><div style="color:var(--t3);font-size:12px;text-align:center;padding:20px">Ожидание...</div></div>
<div class="tp" id="sprs"><div style="color:var(--t3);font-size:12px;text-align:center;padding:20px">Ожидание...</div></div>
<div class="tp" id="spra">
<div style="display:flex;gap:4px;margin-bottom:8px"><button class="spr-b" style="flex:1;font-weight:600;color:var(--r)" id="spra-act-btn" onclick="showAlarmSub('spr','act')">🔴 Активные</button><button class="spr-b" style="flex:1" id="spra-arc-btn" onclick="showAlarmSub('spr','arc')">📋 Архив</button></div>
<div id="spra-act"><div style="color:var(--t3);font-size:12px;text-align:center;padding:15px">Ожидание данных ШПР...</div></div>
<div id="spra-arc" style="display:none"><div style="color:var(--t3);font-size:12px;text-align:center;padding:15px">Архив пуст</div></div>
</div>
<div class="tp" id="sprc">
<div id="sprCfgBanner" style="padding:8px 10px;background:var(--bg3);border:1px solid var(--bd);border-radius:6px;margin-bottom:10px;font-size:11px;color:var(--t3);font-family:var(--m);text-align:center">Откройте вкладку — конфигурация будет считана автоматически</div>
<div style="font-size:11px;color:var(--t3);margin-bottom:8px">Команды HGM9560 (FC05)</div>
<div class="spr-cg">
<button class="spr-b" id="sprCmdStart" onclick="cmdConfirm('ШПР','Start','▶ Пуск','FC05 0x0000')"><span class="si2">▶</span>Пуск</button>
<button class="spr-b" id="sprCmdStop" onclick="cmdConfirm('ШПР','Stop','⏹ Стоп','FC05 0x0001')"><span class="si2">⏹</span>Стоп</button>
<button class="spr-b" id="sprCmdAuto" onclick="cmdConfirm('ШПР','Auto','🅰 Авто','FC05 0x0003')"><span class="si2">🅰</span>Авто</button>
<button class="spr-b" id="sprCmdManual" onclick="cmdConfirm('ШПР','Manual','🔧 Ручн.','FC05 0x0004')"><span class="si2">🔧</span>Ручн.</button>
</div><div class="spr-cg">
<button class="spr-b" id="sprCmdMains" onclick="cmdConfirm('ШПР','MainsSwitch','🔌 Авт.сети','FC05 0x0005: Mains Close/Open')"><span class="si2">🔌</span>Авт.сети</button>
<button class="spr-b" id="sprCmdBusbar" onclick="cmdConfirm('ШПР','BusbarSwitch','⚡ Авт.шины','FC05 0x0006: Busbar Close/Open')"><span class="si2">⚡</span>Авт.шины</button>
<button class="spr-b" onclick="cmdConfirm('ШПР','Mute','🔇 Тишина','FC05 0x000C: Mute')"><span class="si2">🔇</span>Тишина</button>
<button class="spr-b" onclick="cmdConfirm('ШПР','Confirm','✓ Подтв.','FC05 0x000B: Confirm')"><span class="si2">✓</span>Подтв.</button>
</div>
<div style="font-size:11px;color:var(--t3);margin-top:12px;margin-bottom:6px">Режим нагрузки (FC06 reg 4351) <span id="sprLmCurrent" style="font-size:10px;color:var(--t4)"></span></div>
<div style="padding:8px 10px;background:var(--ov);border:1px solid var(--bd);border-radius:6px;margin-bottom:8px;font-size:10px;color:var(--t2);line-height:1.5;font-family:var(--m)">
<b style="color:var(--g)">Gen Control (0)</b> — генераторы управляют мощностью. P% задаёт, сколько от номинала выдаёт генератор. Сеть компенсирует остаток.<br>
<b style="color:var(--b)">Mains Control (1)</b> — сеть основная. P% задаёт порог «срезания пиков» (peak clipping). Генераторы включаются когда нагрузка сети превышает этот %.<br>
<b style="color:var(--p)">Load Reception (2)</b> — приём нагрузки. Генераторы плавно принимают на себя нагрузку от сети.
</div>
<div style="display:flex;gap:6px;margin-bottom:10px">
<button class="spr-b" id="sprLm0" style="flex:1" onclick="setSprLoadMode(0)">Генератор</button>
<button class="spr-b" id="sprLm1" style="flex:1" onclick="setSprLoadMode(1)">Сеть</button>
<button class="spr-b" id="sprLm2" style="flex:1" onclick="setSprLoadMode(2)">Приём нагр.</button>
</div>
<div class="slider-group">
<div style="font-size:10px;color:var(--t3);margin-bottom:6px;line-height:1.4">P% и Q% — уставки для ШПР. В режиме <b style="color:var(--g)">Gen Ctrl</b>: P% = выходная мощность генераторов от номинала. В режиме <b style="color:var(--b)">Mains Ctrl</b>: P% = порог пик-шейвинга сети.</div>
<div class="slider-row"><span class="slider-label">P%</span><input type="range" id="sprPslider" min="0" max="1000" value="500" oninput="sprCfgDirty=true;$('sprPval').textContent=((+this.value)/10).toFixed(1)+'%'"><span class="slider-val" id="sprPval">50.0%</span></div>
<div class="slider-row"><span class="slider-label">Q%</span><input type="range" id="sprQslider" min="0" max="1000" value="500" oninput="sprCfgDirty=true;$('sprQval').textContent=((+this.value)/10).toFixed(1)+'%'"><span class="slider-val" id="sprQval">50.0%</span></div>
<button class="bp" id="sprSaveBtn" style="margin-top:6px;padding:7px;font-size:11px" onclick="saveSprConfig()">💾 Сохранить конфигурацию в контроллер</button>
<div style="font-size:9px;color:var(--t4);margin-top:4px">FC06: LoadMode → reg 4351, P% → reg 4352, Q% → reg 4354. Значения записываются в контроллер и применяются немедленно.</div></div>
<div style="font-size:11px;color:var(--t3);margin-top:14px;margin-bottom:6px">Бэкап / восстановление</div>
<div style="display:flex;gap:6px;margin-bottom:8px">
<button class="spr-b" style="flex:1" onclick="readSprConfig()"><span class="si2">🔄</span>Перечитать</button>
<button class="spr-b" style="flex:1" onclick="backupSprConfig()"><span class="si2">💾</span>Бэкап</button>
<button class="spr-b" style="flex:1" onclick="openRestoreBackup()"><span class="si2">📂</span>Восстановить</button>
</div>
<div id="sprConfigStatus"></div>
<div id="sprBackupList"></div>
</div>
<!-- PRESETS TAB -->
<div class="tp" id="sprp">
<div style="font-size:11px;color:var(--t3);margin-bottom:10px">Быстрые пресеты режимов ШПР (HGM9560)</div>
<div style="padding:10px;background:rgba(160,112,255,.04);border:1px solid rgba(160,112,255,.15);border-radius:8px;margin-bottom:12px;font-size:11px;color:var(--t2);line-height:1.5">
<b style="color:var(--p)">Что такое пресеты?</b><br>
Пресет — это готовая комбинация из трёх параметров: <b>режим нагрузки</b> (LoadMode), <b>% активной мощности</b> (P) и <b>% реактивной мощности</b> (Q), которые отправляются в ШПР через FC06.<br>
Вместо ручной установки каждого параметра — один клик.
</div>
<div class="preset-grid">
<button class="preset-btn" onclick="applyPreset(this,'island')"><div class="preset-name">🏝 Островной</div><div class="preset-desc">Gen Ctrl · P100% Q50%</div></button>
<button class="preset-btn" onclick="applyPreset(this,'genres')"><div class="preset-name">🔋 Ген+Резерв</div><div class="preset-desc">Gen Ctrl · P80% Q50%</div></button>
<button class="preset-btn" onclick="applyPreset(this,'peak')"><div class="preset-name">⚡ Пик-шейвинг</div><div class="preset-desc">Mains Ctrl · P30% Q50%</div></button>
<button class="preset-btn" onclick="applyPreset(this,'parallel')"><div class="preset-name">🔀 Параллель</div><div class="preset-desc">Load Rec · P50% Q50%</div></button>
<button class="preset-btn" onclick="applyPreset(this,'export')"><div class="preset-name">📤 Экспорт</div><div class="preset-desc">Gen Ctrl · P80% Q30%</div></button>
<button class="preset-btn" onclick="applyPreset(this,'mains')"><div class="preset-name">🔌 Только сеть</div><div class="preset-desc">Mains Ctrl · P0% Q0%</div></button>
<button class="preset-btn" onclick="applyPreset(this,'test')"><div class="preset-name">🔧 Тест</div><div class="preset-desc">Gen Ctrl · P20% Q20%</div></button>
</div>
<div id="presetExplain" style="padding:10px;background:var(--ov);border:1px solid var(--bd);border-radius:8px;margin-top:6px">
<div style="font-size:10px;color:var(--t3);margin-bottom:6px">Описание режимов:</div>
<div style="font-size:10px;color:var(--t2);line-height:1.6;font-family:var(--m)">
<b style="color:var(--g)">🏝 Островной</b> — генераторы единственный источник, сеть отключена. P=100%<br>
<b style="color:#00c8ff">🔋 Ген+Резерв</b> — генератор основной (80%), сеть компенсирует остаток. При пропадании сети генератор продолжает питать нагрузку автоматически<br>
<b style="color:var(--y)">⚡ Пик-шейвинг</b> — сеть основная, генераторы срезают пики нагрузки. P=30%<br>
<b style="color:var(--p)">🔀 Параллель</b> — приём нагрузки, генераторы и сеть работают параллельно<br>
<b style="color:var(--b)">📤 Экспорт</b> — генераторы выдают 80% в сеть (обратная продажа)<br>
<b style="color:var(--t)">🔌 Только сеть</b> — генераторы отключены, питание только от сети<br>
<b style="color:var(--t3)">🔧 Тест</b> — 20% нагрузки для проверки работоспособности генераторов
</div>
</div>
<div style="padding:10px;background:var(--ov);border:1px solid var(--bd);border-radius:8px;margin-top:8px"><div style="font-size:10px;color:var(--t3);margin-bottom:4px">Текущий:</div><div id="currentPreset" style="font-family:var(--m);font-size:12px;color:var(--t2)">Не выбран</div></div>
</div></div></div>
<div class="cf"><div class="li"><span class="lo lo-r"></span><span>ожидание</span></div><span>rtu:9600/8N2 · id:${c.slaveId||1}</span></div></div></div>`}

// ===================== _onMetricsUpdate hook =====================
// Called by api.js handleMetricsUpdate after updating latestMetrics
window._onMetricsUpdate = function(m, siteKey, slot) {
    if (!m || !siteKey || !slot) return;
    // Only update if this site is currently displayed
    if (siteKey !== G.cur) return;

    if (slot.startsWith('g')) {
        // Update runHours in S from WS data
        if (m.run_hours != null && G.S[siteKey]?.[slot]) {
            G.S[siteKey][slot].runHours = m.run_hours + (m.run_minutes ? m.run_minutes / 60 : 0);
        }
        // Determine status
        let status = 'standby';
        if (m.online === false) status = 'alarm';
        else if (m.alarm_common || m.alarm_shutdown) status = 'alarm';
        else if (m.alarm_warning) status = 'warning';
        else if (m.gen_status === 9 || m.gen_status_text === 'running') status = 'running';
        else if (m.gen_status >= 1 && m.gen_status <= 8) status = 'running';
        else if (m.gen_status >= 10 && m.gen_status <= 14) status = 'standby';

        const rh = G.S[siteKey]?.[slot]?.runHours || 0;
        const basePower = m.power_total != null ? m.power_total : 0;

        applyGen(slot, status, rh, basePower, m.online !== false);
        updateSummary();
        updateFlowFromMetrics();
    }
    else if (slot === 'spr') {
        const gOn = (m.genset_status === 9);
        const mN = (m.mains_status === 0);
        const bC = (m.busbar_switch === 3);
        const mC = (m.mains_switch === 3);

        applySpr(gOn, mN, bC, mC, m.online !== false);
        applySprDetailed(m);

        updateSummary();
        updateFlowFromMetrics();
    }
};

// ===================== initApp (called after auth) =====================
async function initApp() {
    /* TODO: extract full initialization logic from legacy */
    try {
        await loadFromAPI();
        renderSB();
        renderDash();
        connectWebSocket();
        uCk();
    } catch (e) {
        console.error('[initApp]', e);
    }
}

// ===================== EXPORTS =====================
export {
    // Dashboard rendering
    renderDash, genCard, sprCard,
    // Card interactions
    tog, stab, scrollToAlarm, openAlarms,
    // Generator display
    applyGen, applyGenDetailed,
    // SPR display
    applySpr, applySprDetailed, updateSprControlMode,
    // Summary
    updateSummary, showSummaryIssues, updateFlowFromMetrics,
    // Flow SVG
    flowSvg, _gc,
    // Demo mode
    togDemo, demoTick, SC,
    // Sidebar
    renderSB, togSite, sel, selView, toggleEq, toggleAdmin,
    // Site CRUD
    openAddSite, openEdit, openDel, saveSite, doDel, populateRespSelect, testConn,
    // Clock
    uCk,
    // App init
    initApp,
};
