// SCADA GPU v5 — Task Manager & Maintenance/TO Module
// Extracted from legacy.js

import { G, sv, ae } from './state.js';
import { $, esc, showM, hideM } from './utils.js';
import { api, API_BASE, getDeviceIdForSlot, getGenSlots } from './api.js';
import { DEF_TPL, AI_PROVIDERS } from './constants.js';

// ===================== TO/MAINTENANCE TEMPLATES =====================
function getTpl(){try{const raw=localStorage.getItem('s5tpl');return raw?JSON.parse(raw):JSON.parse(JSON.stringify(DEF_TPL))}catch(e){return JSON.parse(JSON.stringify(DEF_TPL))}}
function saveTpl(t){localStorage.setItem('s5tpl',JSON.stringify(t))}
function getTOData(site,dev){try{return JSON.parse(localStorage.getItem('s5to_'+site+'_'+dev))||{hoursAtLastTO:0,lastTOId:null,history:[]}}catch(e){return{hoursAtLastTO:0,lastTOId:null,history:[]}}}
function saveTOData(site,dev,d){localStorage.setItem('s5to_'+site+'_'+dev,JSON.stringify(d))}
function getNextTO(rh,site,dev){
const tpl=getTpl(),td=getTOData(site||'',dev||''),lastH=td.hoursAtLastTO||0;
if(rh<=0&&lastH<=0)return{name:tpl.intervals[0]?.name||'ТО-1',hours:tpl.intervals[0]?.hours||250,remain:tpl.intervals[0]?.hours||250,pct:0,tasks:tpl.intervals[0]?.tasks||[],since:0,dueAt:tpl.intervals[0]?.hours||250,unknown:false};
if(!td.lastTOId&&rh>0)return{name:'ТО-?',hours:0,remain:0,pct:0,tasks:[],since:rh,dueAt:0,unknown:true};
const sorted=[...tpl.intervals].sort((a,b)=>a.hours-b.hours);
function toTypeAtPoint(pt){for(let i=sorted.length-1;i>=0;i--){if(pt>0&&pt%sorted[i].hours===0)return sorted[i]}return sorted[0]}
const minH=sorted[0]?.hours||250;
let nextPoint=minH>0?Math.ceil(Math.max(lastH+1,1)/minH)*minH:250;
if(nextPoint<rh){
const overdueIv=toTypeAtPoint(nextPoint);
const overdueH=rh-nextPoint;
return{...overdueIv,remain:-overdueH,pct:100,since:rh-lastH,_prevP:nextPoint,dueAt:nextPoint,unknown:false}
}
const nextIv=toTypeAtPoint(nextPoint);
const remain=nextPoint-rh;
const totalSpan=nextPoint-lastH;
const progress=totalSpan>0?Math.min(100,Math.max(0,Math.round((rh-lastH)/totalSpan*100))):0;
return{...nextIv,remain,pct:progress,since:rh-lastH,_nextP:nextPoint,dueAt:nextPoint,unknown:false}
}

// ===================== TO PANEL =====================
function openTO(dev){if(!G.cur)return;const s=G.S[G.cur],c=s[dev],rh=c?.runHours||0;const tpl=getTpl(),td=getTOData(G.cur,dev);
const to=getNextTO(rh,G.cur,dev);
const lastName=td.lastTOId?tpl.intervals.find(iv=>iv.id===td.lastTOId)?.name||td.lastTOId:'не указано';
const lastH=td.hoursAtLastTO||0;
const isOverdue=to.remain<0;
const col=isOverdue?'var(--r)':to.remain<=20?'var(--y)':'var(--g)';
const bgd=isOverdue?'var(--rd)':'var(--bg4)';
const brd=isOverdue?'rgba(255,64,96,.2)':'transparent';
const sorted=[...tpl.intervals].sort((a,b)=>a.hours-b.hours);
const minH=sorted[0]?.hours||250;
const maxH=sorted[sorted.length-1]?.hours||2000;
let schedule=[];
for(let h=minH;h<=maxH;h+=minH){let best=sorted[0];for(let i=sorted.length-1;i>=0;i--){if(h%sorted[i].hours===0){best=sorted[i];break}}
schedule.push({name:best.name,hours:h})}
let histH=td.history?.length?td.history.slice(0,8).map(h=>`<div style="display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid var(--bd);font-size:11px"><span>${h.type} · ${h.hours}ч ${h.done?'<span style="color:var(--g)">✓'+h.done+'/'+h.total+'</span>':''}</span><span style="color:var(--t4)">${h.date}</span></div>`).join(''):'<div style="color:var(--t4);font-size:11px;padding:10px;text-align:center">Нет записей</div>';
$('toT').textContent='Генератор '+dev.slice(1)+' — ТО';
$('toBody').innerHTML=`<div style="text-align:center;padding:18px;background:var(--bg4);border-radius:10px;margin-bottom:14px"><div style="font-size:11px;color:var(--t3)">Моточасы</div><div style="font-size:30px;font-weight:700;font-family:var(--m)">${rh} <span style="font-size:14px;color:var(--t3)">ч</span></div><div style="font-size:10px;color:var(--t4)">Последнее ТО: ${lastName}${lastH?' при '+lastH+'ч':''}</div></div>
${to.unknown?`<div style="padding:14px;background:var(--yd);border:1px solid rgba(255,186,0,.2);border-radius:8px;margin-bottom:10px;text-align:center"><div style="font-size:13px;color:var(--y);font-weight:600;margin-bottom:6px">⚠ Укажите последнее ТО</div><div style="font-size:11px;color:var(--t3);margin-bottom:10px">Чтобы рассчитать следующее ТО, нужно указать какое ТО было выполнено последним и при каких моточасах.</div><button class="bp" style="padding:8px 24px" onclick="hideM('to');openSet()">⚙ Открыть настройки</button></div>`:`${isOverdue?`<div style="padding:10px 12px;background:var(--rd);border:1px solid rgba(255,64,96,.2);border-radius:8px;margin-bottom:10px"><div style="font-size:12px;color:var(--r);font-weight:600">⚠ ${to.name} просрочено на ${Math.abs(to.remain)}ч</div><div style="font-size:10px;color:var(--t3);margin-top:2px">Было запланировано при ${to.dueAt||'?'}ч · Текущие: ${rh}ч</div></div>`:''}
<div style="padding:10px 12px;background:${bgd};border:1px solid ${brd};border-radius:8px;margin-bottom:10px">
<div style="display:flex;justify-content:space-between;margin-bottom:6px"><b style="font-size:12px;color:${col}">${isOverdue?'Просрочено: '+to.name:'Следующее: '+to.name}</b><span style="font-size:11px;color:${col};font-family:var(--m)">${isOverdue?'—':to.remain+'ч ост.'}</span></div>
<div class="to-iv-bar"><div class="to-iv-fill" style="width:${to.pct}%;background:${col}"></div></div>
<div style="font-size:10px;color:var(--t3);margin-top:4px">${to.tasks?.slice(0,5).map(t=>'• '+(t.c?'<b>':'')+t.text+(t.c?'</b>':'')).join('<br>')||''}</div>
</div>`}
<div style="font-size:11px;color:var(--t3);margin-bottom:6px">Цикл ТО (каждые ${maxH}ч)</div>
<div style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:10px">${schedule.map(s=>`<span style="font-size:9px;padding:2px 6px;border-radius:4px;background:var(--bg4);color:var(--t3);font-family:var(--m)">${s.name} ${s.hours}ч</span>`).join('')}</div>
<div style="padding:12px;background:var(--gd);border:1px solid rgba(0,224,154,.2);border-radius:10px"><div style="font-size:12px;color:var(--g);font-weight:600;margin-bottom:8px">Провести ТО</div><div style="display:flex;gap:6px"><select class="fi" id="toSel" style="flex:1;padding:7px 8px">${tpl.intervals.map((iv,i)=>`<option value="${i}"${iv.id===to.id?' selected':''}>${iv.name} (${iv.hours}ч)</option>`).join('')}</select><button class="bp" style="width:auto;padding:8px 20px" onclick="openChecklist('${dev}')">Начать</button></div><button class="bs2" style="width:100%;margin-top:6px;padding:7px;font-size:11px;color:var(--b)" onclick="createBxTaskFromTO('${dev}')">📋 Создать задачу в Битрикс24</button></div>
<div style="font-size:11px;color:var(--t3);margin-top:14px;margin-bottom:6px">История</div>${histH}`;showM('to')}

function openChecklist(dev){const tpl=getTpl(),idx=+$('toSel').value,iv=tpl.intervals[idx],rh=G.S[G.cur]?.[dev]?.runHours||0;$('toT').textContent=iv.name+' — Чеклист';
$('toBody').innerHTML=`<div style="display:flex;justify-content:space-between;padding:10px;background:var(--bg4);border-radius:8px;font-size:12px;margin-bottom:12px"><span>Моточасы:</span><b style="font-family:var(--m)">${rh} ч</b></div>
<div style="display:flex;justify-content:space-between;margin-bottom:6px"><span style="font-size:11px;color:var(--t3)">Работы</span><button onclick="document.querySelectorAll('.chk-cb').forEach(c=>c.checked=true)" style="font-size:10px;color:var(--g);background:none;border:none;cursor:pointer">Все</button></div>
<div style="max-height:300px;overflow-y:auto">${iv.tasks.map((t,i)=>`<label class="chk-item ${t.c?'crit':''}"><input type="checkbox" class="chk-cb" id="chk${i}"><span>${t.text}${t.c?'<span style="color:var(--r);font-size:9px;margin-left:4px">обязат.</span>':''}</span></label>`).join('')}</div>
<div style="padding:8px;background:var(--yd);border-radius:6px;font-size:10px;color:var(--y);margin-top:8px">⚠ Счётчик будет сброшен</div>
<div style="display:flex;gap:8px;margin-top:12px"><button class="bp" style="flex:1" onclick="completeTO('${dev}',${idx})">✓ Подтвердить</button><button class="bs2" style="flex:1;padding:10px" onclick="openTO('${dev}')">Назад</button></div>`}

function completeTO(dev,idx){const tpl=getTpl(),iv=tpl.intervals[idx],rh=G.S[G.cur]?.[dev]?.runHours||0;const cbs=document.querySelectorAll('.chk-cb');let done=0;cbs.forEach(c=>{if(c.checked)done++});const td=getTOData(G.cur,dev);td.hoursAtLastTO=rh;td.lastTOId=iv.id;td.history=td.history||[];td.history.unshift({type:iv.name,hours:rh,done,total:cbs.length,date:new Date().toLocaleDateString('ru-RU')});saveTOData(G.cur,dev,td);ae(`✅ ${iv.name} G${dev.slice(1)}: ${done}/${cbs.length}`);hideM('to');renderDash()}

async function openTOTemplates(){G.curView='to';stopB24Poll();const tpl=getTpl();const bxCfg=getBxConfig();const bxOk=!!bxCfg.url;
let aiOk=false;let aiProv='';let aiModel='';if(G.apiAvailable){try{const ah=await api.get('/api/ai/health');aiOk=ah&&ah.available;aiProv=ah?.provider||'';aiModel=ah?.model||''}catch(e){}}
var localAi=getAIConfig();var localProv=localAi.provider||'';var localHasKey=!!(localAi.keys&&localAi.keys[localProv]);
var provName=localProv?((AI_PROVIDERS[localProv]||{}).name||localProv):'';var provIcon=localProv?((AI_PROVIDERS[localProv]||{}).icon||'🤖'):'🤖';
$('tplT').textContent='📋 Регламенты ТО';$('tplBody').innerHTML=`
<div style="padding:10px;background:${bxOk?'rgba(0,224,154,.04)':'rgba(255,176,32,.04)'};border:1px solid ${bxOk?'rgba(0,224,154,.15)':'rgba(255,176,32,.15)'};border-radius:8px;margin-bottom:12px">
<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px">
<span style="font-size:12px;font-weight:600;color:${bxOk?'var(--g)':'var(--y)'}">${bxOk?'🔗 Битрикс24 подключён':'⚠ Битрикс24 не подключён'}</span>
<button class="bs2" style="padding:4px 10px;font-size:10px" onclick="hideM('tpl');initBxModal();showM('bitrix')">${bxOk?'⚙ Настройки':'🔗 Подключить'}</button>
</div>
<div style="font-size:10px;color:var(--t3);line-height:1.5">
${bxOk&&(aiOk||localHasKey)?`<b style="color:var(--p)">${provIcon} AI-импорт доступен (${aiProv?provName+' · '+aiModel:provName})</b> — загрузите мануал ДГУ на Диск Б24, затем нажмите «Импорт из мануала».<br>ИИ-агент автоматически извлечёт интервалы ТО, чеклисты работ и критичность.`:bxOk&&!aiOk?`<b style="color:var(--y)">⚠ AI-агент не настроен</b> — <a href="#" onclick="event.preventDefault();hideM('tpl');initAIModal();showM('aiconf')" style="color:var(--p);text-decoration:underline">настройте провайдера</a> (OpenAI, Claude, Gemini, Grok).`:'Подключите Битрикс24 для загрузки регламентов ТО из мануалов производителя через ИИ-агент.'}
</div>
${bxOk?`<div style="display:flex;gap:6px;margin-top:8px"><button class="bpp" style="flex:1;padding:7px 10px;font-size:11px" onclick="hideM('tpl');initBxModal();showM('bitrix');setTimeout(()=>bxTab(document.querySelectorAll('.set-tab')[2],2),100)">🤖 Импорт из мануала</button></div>`:''}
</div>
<div style="font-size:11px;color:var(--t3);margin-bottom:6px;font-weight:500">Текущие интервалы (${tpl.intervals.length})</div>
<div style="margin-bottom:10px">${tpl.intervals.map((iv,i)=>`<div class="to-iv" style="display:flex;align-items:center;gap:8px"><div style="flex:1"><div style="display:flex;justify-content:space-between"><b>${iv.name}</b><span style="font-size:11px;color:var(--t3);font-family:var(--m)">${iv.hours}ч · ${iv.tasks.length} работ</span></div></div><button class="bk-btn del" onclick="delTOInterval(${i})" title="Удалить">✕</button></div>`).join('')}</div>
<div style="display:flex;gap:8px;margin-bottom:8px"><button class="bp" style="flex:1" onclick="editTemplates()">✏ Редактировать</button><button class="bs2" style="flex:0;padding:10px 16px" onclick="addTOInterval()">+ Добавить</button></div>
<button class="bs2" style="width:100%" onclick="if(confirm('Сбросить все к стандартным?')){localStorage.removeItem('s5tpl');openTOTemplates()}">Сбросить</button>`;showM('tpl')}

function addTOInterval(){const tpl=getTpl();const num=tpl.intervals.length+1;tpl.intervals.push({id:'to_'+Date.now(),name:'ТО-'+num,hours:num*500,tasks:[{id:1,text:'Осмотр',c:0}]});saveTpl(tpl);ae('+ ТО-'+num+' добавлен');editTemplates()}

function delTOInterval(idx){const tpl=getTpl();if(tpl.intervals.length<=1)return;const name=tpl.intervals[idx].name;if(!confirm('Удалить '+name+'?'))return;tpl.intervals.splice(idx,1);saveTpl(tpl);ae('🗑 '+name+' удалён');openTOTemplates()}

function editTemplates(){const tpl=getTpl();$('tplT').textContent='Редактирование';$('tplBody').innerHTML=tpl.intervals.map((iv,i)=>`<div class="cfs"><div class="cft"><span class="dot dot-g"></span><input class="fi" style="width:80px;padding:4px 6px;font-size:12px;font-weight:600" id="tin${i}" value="${iv.name}"><span class="conn-test del" onclick="delTOInterval(${i})">✕ Удалить</span></div><div class="fg"><label class="fl">Интервал (ч)</label><input class="fi" id="tih${i}" value="${iv.hours}" type="number"></div><div class="fg"><label class="fl">Работы ([!] = критичная)</label><textarea class="ta" id="tit${i}" rows="4">${iv.tasks.map(t=>(t.c?'[!] ':'')+t.text).join('\n')}</textarea></div></div>`).join('')+`<div style="display:flex;gap:8px;margin-top:4px"><button class="bp" style="flex:1" onclick="saveTemplates()">Сохранить</button><button class="bs2" style="padding:10px" onclick="addTOInterval()">+ Добавить</button><button class="bs2" style="flex:1;padding:10px" onclick="openTOTemplates()">Назад</button></div>`}

function saveTemplates(){const tpl=getTpl();tpl.intervals.forEach((iv,i)=>{iv.name=$('tin'+i)?.value||iv.name;iv.hours=parseInt($('tih'+i).value)||iv.hours;const lines=$('tit'+i).value.split('\n').filter(l=>l.trim());if(lines.length===0)lines.push('Осмотр');iv.tasks=lines.map((l,j)=>{const c=l.startsWith('[!]');return{id:j+1,text:l.replace('[!] ','').replace('[!]','').trim(),c:c?1:0}})});saveTpl(tpl);ae('✅ Регламенты обновлены');openTOTemplates()}

// ===================== TASK MANAGER =====================
async function renderTaskManager() {
    G.curView='tasks';
    const btn=$('btnTasks');
    if(btn) btn.classList.add('active');
    const mn=$('mainArea');
    mn.innerHTML=`<div style="padding:4px">
        <div class="tm-hd"><h2>📋 Менеджер задач</h2></div>
        <div class="tm-tabs">
            <button class="tm-tab active" onclick="showTaskTab('tasks',this)">📋 Задачи</button>
            <button class="tm-tab" onclick="showTaskTab('rules',this)">⚙️ Правила</button>
            <button class="tm-tab" onclick="showTaskTab('cards',this)">📄 Карты ТО</button>
        </div>
        <div id="tmTabContent"></div>
    </div>`;
    showTaskTab('tasks');
}

function showTaskTab(tab, btn) {
    document.querySelectorAll('.tm-tab').forEach(t=>t.classList.remove('active'));
    if(btn) btn.classList.add('active');
    else document.querySelector(`.tm-tab:first-child`)?.classList.add('active');
    if(tab==='tasks') renderTasksTab();
    else if(tab==='rules') renderRulesTab();
    else if(tab==='cards') renderCardsTab();
}

async function renderTasksTab() {
    $('tmTabContent').innerHTML=`
        <div class="tm-hd" style="margin-bottom:8px">
            <div class="tm-filters">
                <button class="sb-btn primary" onclick="showCreateTaskForm()" style="padding:6px 14px">+ Создать задачу</button>
                <select id="tmStatus" onchange="loadTasks()"><option value="">Все статусы</option><option value="created">Создана</option><option value="in_progress">В работе</option><option value="escalated">Эскалация</option><option value="completed">Завершена</option></select>
                <select id="tmType" onchange="loadTasks()"><option value="">Все типы</option><option value="maintenance">ТО</option><option value="incident">Инцидент</option><option value="manual">Ручная</option></select>
                <button class="sb-btn" onclick="loadTasks()" style="padding:6px 12px">🔄</button>
            </div>
        </div>
        <div id="tmFormArea"></div>
        <div class="tm-stats" id="tmStats"></div>
        <table class="tm-table"><thead><tr><th>#</th><th>Задача</th><th>Тип</th><th>Объект</th><th>Статус</th><th>Приоритет</th><th>Исполнитель</th><th>Дедлайн</th><th>Эскалация</th></tr></thead><tbody id="tmBody"></tbody></table>`;
    await loadTaskStats();
    await loadTasks();
}

// ===================== RULES =====================
async function renderRulesTab() {
    $('tmTabContent').innerHTML=`
        <div class="tm-hd" style="margin-bottom:8px">
            <div class="tm-filters">
                <button class="sb-btn primary" onclick="showCreateRuleForm()" style="padding:6px 14px">+ Создать правило</button>
                <button class="sb-btn" onclick="renderRulesTab()" style="padding:6px 12px">🔄</button>
            </div>
        </div>
        <div id="ruleFormArea"></div>
        <div id="rulesList">Загрузка...</div>`;
    await loadRules();
}

async function loadRules() {
    try {
        const r=await fetch(API_BASE+'/api/task-manager/rules',{credentials:'include'});
        if(!r.ok){$('rulesList').innerHTML='<div style="color:var(--t3)">Ошибка загрузки</div>';return}
        const rules=await r.json();
        if(!rules.length){$('rulesList').innerHTML='<div style="color:var(--t3);text-align:center;padding:40px">Нет правил. Нажмите "+ Создать правило" или скажите Саньку:<br><br><i>"При ошибках МКЗ создавай задачу на Михайлова"</i></div>';return}
        const triggerIcons={alarm:'🚨',metric_threshold:'📊',schedule:'📅',hours_threshold:'⏱'};
        const triggerNames={alarm:'Аларм/ошибка',metric_threshold:'Порог параметра',schedule:'По расписанию',hours_threshold:'Моточасы'};
        const actionNames={create_task:'→ Задача',notify:'→ Уведомление',create_task_and_notify:'→ Задача + уведомление'};
        $('rulesList').innerHTML=rules.map(r=>`
            <div class="tm-rule">
                <div class="rule-icon">${triggerIcons[r.trigger_type]||'⚙️'}</div>
                <div class="rule-body">
                    <div class="rule-name">${r.name}</div>
                    <div class="rule-desc">${triggerNames[r.trigger_type]||r.trigger_type} ${actionNames[r.action_type]||r.action_type}${r.executor_name?' • '+r.executor_name:''}${r.sanek_control?' • 🤖 Санёк контролирует':''}</div>
                    <div class="rule-meta">
                        <span>${r.equipment_code||'Все объекты'}</span>
                        <span>Сработало: ${r.times_triggered||0}</span>
                        ${r.last_triggered_at?'<span>Последний: '+new Date(r.last_triggered_at).toLocaleDateString('ru')+'</span>':''}
                    </div>
                </div>
                <button class="rule-toggle ${r.is_active?'on':''}" onclick="toggleRule(${r.id},${!r.is_active})" title="${r.is_active?'Выключить':'Включить'}"></button>
            </div>`).join('');
    } catch(e){$('rulesList').innerHTML='<div style="color:var(--r)">Ошибка</div>'}
}

async function toggleRule(id, enable) {
    await fetch(API_BASE+`/api/task-manager/rules/${id}`,{
        method:'PATCH',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({is_active:enable}),credentials:'include'});
    await loadRules();
}

function showCreateRuleForm() {
    $('ruleFormArea').innerHTML=`<div class="tm-detail" style="margin-bottom:16px">
        <h3>⚙️ Новое правило автоматизации</h3>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:10px">
            <div><label style="font-size:11px;color:var(--t2)">Название правила *</label>
                <input type="text" id="rfName" placeholder="При ошибках МКЗ → задача на Михайлова" style="width:100%;padding:8px 10px;border:1px solid var(--bd);border-radius:var(--rs);background:var(--bg3);color:var(--t);font-size:13px;font-family:var(--u);margin-top:4px"></div>
            <div><label style="font-size:11px;color:var(--t2)">Оборудование</label>
                <select id="rfEquip" style="width:100%;padding:8px 10px;border:1px solid var(--bd);border-radius:var(--rs);background:var(--bg3);color:var(--t);font-size:13px;font-family:var(--u);margin-top:4px">
                    <option value="">Все объекты</option><option value="mkz_dgu1">МКЗ ГПУ</option><option value="yakz_dgu1">ЯКЗ ГПУ</option></select></div>
            <div><label style="font-size:11px;color:var(--t2)">Триггер (КОГДА) *</label>
                <select id="rfTrigger" onchange="updateTriggerConfig()" style="width:100%;padding:8px 10px;border:1px solid var(--bd);border-radius:var(--rs);background:var(--bg3);color:var(--t);font-size:13px;font-family:var(--u);margin-top:4px">
                    <option value="alarm">🚨 При ошибке/аларме</option><option value="metric_threshold">📊 Порог параметра</option><option value="schedule">📅 По расписанию</option><option value="hours_threshold">⏱ По моточасам</option></select></div>
            <div><label style="font-size:11px;color:var(--t2)">Действие (ЧТО ДЕЛАТЬ) *</label>
                <select id="rfAction" style="width:100%;padding:8px 10px;border:1px solid var(--bd);border-radius:var(--rs);background:var(--bg3);color:var(--t);font-size:13px;font-family:var(--u);margin-top:4px">
                    <option value="create_task_and_notify">Задача + уведомление</option><option value="create_task">Только задача</option><option value="notify">Только уведомление</option></select></div>
            <div id="rfTriggerConfig" style="grid-column:span 2"></div>
            <div><label style="font-size:11px;color:var(--t2)">Исполнитель</label>
                <div id="rfExecutor" data-employee-select data-field="executor_name"></div></div>
            <div style="display:flex;align-items:center;gap:8px;padding-top:16px">
                <input type="checkbox" id="rfSanekCtrl" checked style="accent-color:var(--g)">
                <label for="rfSanekCtrl" style="font-size:13px;cursor:pointer">🤖 Санёк контролирует исполнение</label></div>
        </div>
        <div style="display:flex;gap:8px;margin-top:14px">
            <button class="sb-btn primary" onclick="submitCreateRule()" style="padding:8px 20px">Создать правило</button>
            <button class="sb-btn" onclick="$('ruleFormArea').innerHTML=''" style="padding:8px 20px">Отмена</button>
        </div>
        <div id="rfError" style="color:var(--r);font-size:12px;margin-top:6px;min-height:16px"></div>
    </div>`;
    updateTriggerConfig();
    loadEmployeeDropdowns();
}

// ===================== SEARCHABLE DROPDOWN =====================
let _employeesCache = null;

async function getEmployees() {
    if (_employeesCache) return _employeesCache;
    try {
        const r = await fetch(API_BASE + '/api/task-manager/employees', {credentials: 'include'});
        if (r.ok) _employeesCache = await r.json();
    } catch(e) {}
    return _employeesCache || [];
}

async function loadEmployeeDropdowns() {
    const emps = await getEmployees();
    document.querySelectorAll('[data-employee-select]').forEach(el => {
        initSearchableDropdown(el, emps);
    });
}

function initSearchableDropdown(container, items) {
    const fieldName = container.getAttribute('data-field') || 'employee';
    const currentVal = container.getAttribute('data-value') || '';

    const wrap = document.createElement('div');
    wrap.className = 'sd-wrap';

    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'sd-input';
    input.placeholder = 'Поиск сотрудника...';
    input.id = container.id + '_search';

    const hidden = document.createElement('input');
    hidden.type = 'hidden';
    hidden.id = container.id;
    hidden.name = fieldName;
    hidden.value = currentVal;

    const dropdown = document.createElement('div');
    dropdown.className = 'sd-dropdown';

    if (currentVal) {
        const found = items.find(e => String(e.bitrix_id) === String(currentVal) || e.name === currentVal);
        if (found) input.value = found.name;
    }

    function renderOptions(filter) {
        const f = (filter || '').toLowerCase();
        const filtered = f ? items.filter(e =>
            (e.name || '').toLowerCase().includes(f) ||
            (e.position || '').toLowerCase().includes(f)
        ) : items;

        if (!filtered.length) {
            dropdown.innerHTML = '<div class="sd-empty">Не найдено</div>';
            return;
        }

        dropdown.innerHTML = filtered.slice(0, 30).map(e =>
            `<div class="sd-option${String(hidden.value) === String(e.bitrix_id) ? ' selected' : ''}"
                 data-id="${e.bitrix_id}" data-name="${e.name}">
                ${e.name}<span class="sd-pos">${e.position || ''}</span>
            </div>`
        ).join('');

        dropdown.querySelectorAll('.sd-option').forEach(opt => {
            opt.addEventListener('click', () => {
                hidden.value = opt.dataset.name || opt.dataset.id;
                input.value = opt.dataset.name;
                dropdown.classList.remove('open');
            });
        });
    }

    input.addEventListener('focus', () => {
        renderOptions(input.value);
        dropdown.classList.add('open');
    });

    input.addEventListener('input', () => {
        renderOptions(input.value);
        dropdown.classList.add('open');
    });

    document.addEventListener('click', (e) => {
        if (!wrap.contains(e.target)) dropdown.classList.remove('open');
    });

    // Option: "Автоматически" at top
    const autoOpt = document.createElement('div');
    autoOpt.className = 'sd-option';
    autoOpt.textContent = 'Автоматически';
    autoOpt.addEventListener('click', () => {
        hidden.value = '';
        input.value = '';
        input.placeholder = 'Автоматически';
        dropdown.classList.remove('open');
    });

    wrap.appendChild(input);
    wrap.appendChild(hidden);
    wrap.appendChild(dropdown);

    container.replaceWith(wrap);
}

function updateTriggerConfig() {
    const type=$('rfTrigger')?.value;
    const area=$('rfTriggerConfig');
    if(!area) return;
    const st='width:100%;padding:8px 10px;border:1px solid var(--bd);border-radius:var(--rs);background:var(--bg3);color:var(--t);font-size:13px;font-family:var(--u);margin-top:4px';
    if(type==='alarm') area.innerHTML=`<label style="font-size:11px;color:var(--t2)">Минимальная серьёзность аларма</label><select id="rfCfgSev" style="${st}"><option value="HIGH">HIGH и выше</option><option value="CRITICAL">Только CRITICAL</option><option value="ANY">Любой аларм</option></select>`;
    else if(type==='metric_threshold') area.innerHTML=`<div style="display:grid;grid-template-columns:1fr auto 1fr;gap:6px"><div><label style="font-size:11px;color:var(--t2)">Параметр</label><select id="rfCfgMetric" style="${st}"><option value="oil_pressure">Давление масла</option><option value="coolant_temp">Температура ОЖ</option><option value="power_total">Мощность</option><option value="frequency">Частота</option></select></div><div><label style="font-size:11px;color:var(--t2)">Условие</label><select id="rfCfgOp" style="${st}"><option value="<">Меньше</option><option value=">">Больше</option></select></div><div><label style="font-size:11px;color:var(--t2)">Значение</label><input type="number" id="rfCfgVal" placeholder="3.0" style="${st}"></div></div>`;
    else if(type==='schedule') area.innerHTML=`<label style="font-size:11px;color:var(--t2)">Интервал (дней)</label><input type="number" id="rfCfgDays" value="30" style="${st}">`;
    else if(type==='hours_threshold') area.innerHTML=`<label style="font-size:11px;color:var(--t2)">Интервал (моточасов)</label><input type="number" id="rfCfgHours" value="250" style="${st}">`;
}

async function submitCreateRule() {
    const name=$('rfName')?.value?.trim();
    if(!name){$('rfError').textContent='Введите название';return}
    const trigger_type=$('rfTrigger')?.value;
    let trigger_config={};
    if(trigger_type==='alarm') trigger_config={severity_min:$('rfCfgSev')?.value||'HIGH',any:$('rfCfgSev')?.value==='ANY'};
    else if(trigger_type==='metric_threshold') trigger_config={metric:$('rfCfgMetric')?.value,operator:$('rfCfgOp')?.value,value:parseFloat($('rfCfgVal')?.value||0)};
    else if(trigger_type==='schedule') trigger_config={interval_days:parseInt($('rfCfgDays')?.value||30)};
    else if(trigger_type==='hours_threshold') trigger_config={interval_hours:parseInt($('rfCfgHours')?.value||250)};
    const body={name,trigger_type,trigger_config,
        action_type:$('rfAction')?.value||'create_task_and_notify',
        equipment_code:$('rfEquip')?.value||null,
        executor_name:$('rfExecutor')?.value?.trim()||null,
        sanek_control:$('rfSanekCtrl')?.checked??true};
    try {
        const r=await fetch(API_BASE+'/api/task-manager/rules',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),credentials:'include'});
        const d=await r.json();
        if(r.ok){$('ruleFormArea').innerHTML=`<div style="background:var(--gd);border:1px solid var(--g);border-radius:var(--rs);padding:10px 14px;margin-bottom:12px;font-size:13px">✅ Правило создано: ${d.name}</div>`;setTimeout(()=>{$('ruleFormArea').innerHTML=''},3000);await loadRules()}
        else{$('rfError').textContent=d.detail||'Ошибка'}
    } catch(e){$('rfError').textContent='Сервер недоступен'}
}

// ===================== MAINTENANCE LIFECYCLE =====================
let _mntEquipData=[];
let _mntCardsData=[];
let _mntFilterSite='all';
let _mntFilterType='all';
let _mntView='equipment';

async function renderCardsTab() {
    $('tmTabContent').innerHTML=`
        <div class="tm-hd" style="margin-bottom:8px">
            <div class="tm-filters">
                <button class="sb-btn${_mntView==='equipment'?' primary':''}" onclick="_mntView='equipment';renderCardsTab()" style="padding:6px 14px">⚙️ Оборудование</button>
                <button class="sb-btn${_mntView==='cards'?' primary':''}" onclick="_mntView='cards';renderCardsTab()" style="padding:6px 14px">📄 Карты ТО</button>
                <button class="sb-btn" onclick="renderCardsTab()" style="padding:6px 12px">🔄</button>
            </div>
        </div>
        <div id="tmFormArea"></div>
        <div id="mntContent">Загрузка...</div>`;
    if(_mntView==='equipment') await _mntLoadEquipment();
    else await _mntLoadCards();
}

function _mntUrgencyColor(score) {
    if(score===null||score===undefined) return 'var(--t3)';
    if(score>5) return 'var(--g)';
    if(score>=1) return 'var(--y)';
    if(score>=0) return '#ff8c00';
    return 'var(--r)';
}
function _mntUrgencyLabel(score) {
    if(score===null||score===undefined) return 'Нет карты';
    if(score>5) return 'Норма';
    if(score>=1) return 'Приближается';
    if(score>=0) return 'Пора делать';
    return 'Просрочено';
}
function _mntProgressPct(hours,threshold) {
    if(!threshold||threshold<=0) return 0;
    return Math.min(100,Math.max(0,(hours/threshold)*100));
}
function _mntTypeName(t) {
    const m={gpu:'ГПУ',extruder:'Экструдер',furnace:'Печь'};
    return m[t]||t||'—';
}
function _mntSiteName(s) {
    if(!s) return '—';
    const u=String(s).toUpperCase();
    if(u==='MKZ'||u==='МКЗ') return 'МКЗ';
    if(u==='YKZ'||u==='ЯКЗ') return 'ЯКЗ';
    return s;
}
function _mntCardStatusBadge(st) {
    const cls={draft:'created',confirmed:'in_progress',active:'completed',archived:'closed'};
    const lbl={draft:'Черновик',confirmed:'Подтверждена',active:'Активна',archived:'Архив'};
    return `<span class="tm-badge ${cls[st]||''}">${lbl[st]||st||'—'}</span>`;
}

async function _mntLoadEquipment() {
    try {
        const r=await fetch(API_BASE+'/api/maintenance/equipment',{credentials:'include'});
        if(!r.ok){$('mntContent').innerHTML='<div style="color:var(--r)">Ошибка загрузки оборудования</div>';return}
        _mntEquipData=await r.json();
        if(Array.isArray(_mntEquipData?.items)) _mntEquipData=_mntEquipData.items;
        if(!Array.isArray(_mntEquipData)) _mntEquipData=[];
        _mntRenderEquipmentView();
    } catch(e){$('mntContent').innerHTML='<div style="color:var(--r)">Сервер недоступен</div>'}
}

var _mntEqSortCol=null,_mntEqSortDir=0;
function _mntRenderEquipmentView() {
    let items=_mntEquipData;
    if(_mntFilterSite!=='all') items=items.filter(e=>{
        const s=String(e.site_name||e.site_code||e.site||'').toUpperCase();
        return s===_mntFilterSite.toUpperCase();
    });
    if(_mntFilterType!=='all') items=items.filter(e=>(e.equipment_type||e.type)===_mntFilterType);

    const total=items.length;
    let cntOk=0,cntWarn=0,cntOver=0,cntNone=0;
    items.forEach(e=>{
        if(e.status==='no_card'){cntNone++;return}
        const nm=e.next_maintenance;
        const sc=nm?nm.urgency_score:(e.urgency_score??null);
        if(sc===null||sc===undefined) cntNone++;
        else if(sc>5) cntOk++;
        else if(sc>=0) cntWarn++;
        else cntOver++;
    });

    const statBox=(label,cnt,bg,fg)=>`<div style="display:flex;align-items:center;gap:6px;padding:6px 12px;border-radius:var(--rs);background:${bg}"><span style="font-size:18px;font-weight:700;color:${fg}">${cnt}</span><span style="font-size:11px;color:var(--t2)">${label}</span></div>`;
    const statsHtml=`<div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px;align-items:center">
        <button class="sb-btn primary" onclick="showUploadCardForm()" style="padding:6px 14px;margin-right:8px" data-role-min="admin">📄 Загрузить карту ТО</button>
        ${statBox('Всего',total,'var(--bg4)','var(--t)')}
        ${statBox('Норма',cntOk,'var(--gd)','var(--g)')}
        ${statBox('Внимание',cntWarn,'var(--yd)','var(--y)')}
        ${statBox('Просрочено',cntOver,'var(--rd)','var(--r)')}
        ${statBox('Нет карты',cntNone,'var(--ov2)','var(--t3)')}
    </div>`;

    const filtersHtml=`<div style="display:flex;gap:6px;margin-bottom:12px;flex-wrap:wrap">
        <select onchange="_mntFilterSite=this.value;_mntRenderEquipmentView()" style="padding:6px 10px;border:1px solid var(--bd);border-radius:var(--rs);background:var(--bg3);color:var(--t);font-size:12px;font-family:var(--u)">
            <option value="all"${_mntFilterSite==='all'?' selected':''}>Все площадки</option>
            <option value="MKZ"${_mntFilterSite==='MKZ'?' selected':''}>МКЗ</option>
            <option value="YKZ"${_mntFilterSite==='YKZ'?' selected':''}>ЯКЗ</option>
        </select>
        <select onchange="_mntFilterType=this.value;_mntRenderEquipmentView()" style="padding:6px 10px;border:1px solid var(--bd);border-radius:var(--rs);background:var(--bg3);color:var(--t);font-size:12px;font-family:var(--u)">
            <option value="all"${_mntFilterType==='all'?' selected':''}>Все типы</option>
            <option value="gpu"${_mntFilterType==='gpu'?' selected':''}>ГПУ</option>
            <option value="extruder"${_mntFilterType==='extruder'?' selected':''}>Экструдер</option>
            <option value="furnace"${_mntFilterType==='furnace'?' selected':''}>Печь</option>
        </select>
    </div>`;

    if(!items.length){
        $('mntContent').innerHTML=statsHtml+filtersHtml+`<div style="color:var(--t3);text-align:center;padding:40px">Нет оборудования по выбранным фильтрам</div>`;
        return;
    }

    // Sort
    if(_mntEqSortCol&&_mntEqSortDir){
        var sc=_mntEqSortCol,sd=_mntEqSortDir;
        items=[...items].sort(function(a,b){
            var va,vb;
            if(sc==='name'){va=a.name||a.equipment_name||'';vb=b.name||b.equipment_name||''}
            else if(sc==='type'){va=a.equipment_type||'';vb=b.equipment_type||''}
            else if(sc==='site'){va=a.site_name||'';vb=b.site_name||''}
            else if(sc==='next'){va=(a.next_maintenance?a.next_maintenance.interval_name:'');vb=(b.next_maintenance?b.next_maintenance.interval_name:'')}
            else if(sc==='resp'){va=a.responsible_name||'';vb=b.responsible_name||''}
            else if(sc==='status'){va=a.status||'';vb=b.status||''}
            else{va='';vb=''}
            if(typeof va==='string'){va=va.toLowerCase();vb=vb.toLowerCase()}
            return va<vb?-sd:va>vb?sd:0;
        });
    }

    // Group by site
    var groups={};
    items.forEach(function(e){
        var sk=e.site_name||e.site_code||e.site||'Без площадки';
        if(!groups[sk])groups[sk]=[];
        groups[sk].push(e);
    });
    var siteKeys=Object.keys(groups).sort(function(a,b){return a.localeCompare(b)});

    function eqSortArrow(c){if(_mntEqSortCol!==c)return '';return _mntEqSortDir===1?' ▲':_mntEqSortDir===-1?' ▼':''}
    var thStyle='cursor:pointer;user-select:none';

    var html=statsHtml+filtersHtml;
    html+='<table class="tm-table"><thead><tr>';
    html+='<th style="'+thStyle+'" onclick="_mntEqToggleSort(\'name\')">Оборудование'+eqSortArrow('name')+'</th>';
    html+='<th style="'+thStyle+'" onclick="_mntEqToggleSort(\'type\')">Тип'+eqSortArrow('type')+'</th>';
    html+='<th>Прогресс</th>';
    html+='<th style="'+thStyle+'" onclick="_mntEqToggleSort(\'next\')">Следующее ТО'+eqSortArrow('next')+'</th>';
    html+='<th style="'+thStyle+'" onclick="_mntEqToggleSort(\'resp\')">Ответственный'+eqSortArrow('resp')+'</th>';
    html+='<th style="'+thStyle+'" onclick="_mntEqToggleSort(\'status\')">Статус'+eqSortArrow('status')+'</th>';
    html+='<th>Карта ТО</th>';
    html+='</tr></thead><tbody>';

    siteKeys.forEach(function(site){
        html+='<tr><td colspan="7" style="background:var(--bg3);font-weight:600;font-size:12px;padding:6px 10px;color:var(--t)">🏭 '+esc(_mntSiteName(site))+'</td></tr>';
        groups[site].forEach(function(e){
            var nm=e.next_maintenance;
            var sc2=nm?nm.urgency_score:(e.urgency_score??e.urgency??null);
            var col=_mntUrgencyColor(sc2);
            var opHrs=e.operating_hours??e.current_hours??0;
            var nextThr=nm?nm.target_value:(e.next_threshold??0);
            var pct=sc2!==null?_mntProgressPct(opHrs,nextThr||1):0;
            var nextName=nm?nm.interval_name:(e.next_maintenance_name||'—');
            var remaining=nm?(nm.remaining_hours??nm.remaining_days):(e.remaining_hours??e.hours_remaining);
            var remainTxt=remaining!==null&&remaining!==undefined?remaining+' '+(nm&&nm.remaining_days!==null&&nm.remaining_hours===null?'дн':'ч'):'—';
            var resp=e.responsible_name||e.responsible||'—';
            var statusTxt=e.status==='no_card'?'Нет карты':_mntUrgencyLabel(sc2);
            var eqType=e.equipment_type||e.type||'';
            var eqId=e.id||e.equipment_id||'';

            var cardObj=e.card;
            var cardHtml='<span style="color:var(--t4)">—</span>';
            if(cardObj){
                var fileLink=cardObj.source_file_url?'<a href="'+cardObj.source_file_url+'" title="Скачать: '+esc(cardObj.source_file_name||'')+'" style="color:var(--g);text-decoration:none;margin-left:4px" onclick="event.stopPropagation()">📎</a>':'';
                cardHtml='<span style="font-size:11px;cursor:pointer;color:var(--link,#4ea8de)" onclick="event.stopPropagation();_mntShowCardDetail('+cardObj.id+')">'+esc(cardObj.name||'Карта')+'</span>'+fileLink;
            }

            html+='<tr style="cursor:pointer" onclick="_mntShowEquipDetail(\''+eqId+'\')">';
            html+='<td style="font-weight:500">'+esc(e.name||e.equipment_name||'—')+'</td>';
            html+='<td>'+_mntTypeName(eqType)+'</td>';
            html+='<td style="min-width:120px"><div style="display:flex;align-items:center;gap:8px"><div style="flex:1;height:6px;border-radius:3px;background:var(--bg4);overflow:hidden"><div style="height:100%;width:'+pct+'%;border-radius:3px;background:'+col+';transition:width .3s"></div></div><span style="font-size:10px;color:var(--t2);white-space:nowrap">'+Math.round(opHrs)+'/'+(nextThr||'—')+'</span></div></td>';
            html+='<td><span style="font-size:12px">'+esc(nextName)+'</span><br><span style="font-size:10px;color:var(--t2)">'+remainTxt+'</span></td>';
            html+='<td style="font-size:12px">'+esc(resp)+'</td>';
            html+='<td><span class="tm-badge" style="background:'+col+'20;color:'+col+'">'+statusTxt+'</span></td>';
            html+='<td>'+cardHtml+'</td>';
            html+='</tr>';
        });
    });
    html+='</tbody></table>';
    $('mntContent').innerHTML=html;
}

function _mntEqToggleSort(col){
    if(_mntEqSortCol===col){_mntEqSortDir=_mntEqSortDir===1?-1:_mntEqSortDir===-1?0:1;}
    else{_mntEqSortCol=col;_mntEqSortDir=1;}
    if(!_mntEqSortDir)_mntEqSortCol=null;
    _mntRenderEquipmentView();
}

async function _mntShowEquipDetail(eqId) {
    if(!eqId) return;
    $('tmFormArea').innerHTML=`<div class="tm-detail"><div style="color:var(--t2);font-size:12px">Загрузка...</div></div>`;
    try {
        const [rSt,rHist]=await Promise.all([
            fetch(API_BASE+'/api/maintenance/equipment/'+eqId+'/status',{credentials:'include'}),
            fetch(API_BASE+'/api/maintenance/equipment/'+eqId+'/history',{credentials:'include'})
        ]);
        const eq=rSt.ok?await rSt.json():{};
        const hist=rHist.ok?await rHist.json():[];
        const histItems=Array.isArray(hist)?hist:(hist.items||[]);

        const sc=eq.urgency_score??eq.urgency??null;
        const col=_mntUrgencyColor(sc);
        const opHrs=eq.operating_hours??eq.current_hours??0;
        const upcoming=Array.isArray(eq.upcoming)?eq.upcoming:[];
        const cards=Array.isArray(eq.cards)?eq.cards:[];
        const isManual=(eq.hours_source||'')=='manual';
        const eqType=eq.equipment_type||eq.type||'';

        let upcomingHtml='<div style="color:var(--t3);font-size:12px">Нет запланированных ТО</div>';
        if(upcoming.length) {
            upcomingHtml=`<table class="tm-table" style="font-size:11px"><thead><tr><th>ТО</th><th>Порог (ч)</th><th>Осталось</th><th>Срочность</th></tr></thead><tbody>`+
                upcoming.map(u=>{
                    const uc=_mntUrgencyColor(u.urgency_score??u.urgency??null);
                    return `<tr>
                        <td>${u.name||u.maintenance_name||'—'}</td>
                        <td>${u.threshold_hours??u.interval_hours??'—'}</td>
                        <td>${u.remaining_hours??u.hours_remaining??'—'} ч</td>
                        <td><span class="tm-badge" style="background:${uc}20;color:${uc}">${_mntUrgencyLabel(u.urgency_score??u.urgency??null)}</span></td>
                    </tr>`;
                }).join('')+`</tbody></table>`;
        }

        let histHtml='<div style="color:var(--t3);font-size:12px">Нет записей</div>';
        if(histItems.length) {
            histHtml=`<table class="tm-table" style="font-size:11px"><thead><tr><th>Дата</th><th>ТО</th><th>Моточасы</th><th>Кем</th></tr></thead><tbody>`+
                histItems.slice(0,10).map(h=>`<tr>
                    <td>${h.performed_at||h.date?new Date(h.performed_at||h.date).toLocaleDateString('ru'):'—'}</td>
                    <td>${h.maintenance_name||h.name||'—'}</td>
                    <td>${h.hours_at??h.operating_hours??'—'}</td>
                    <td>${h.performed_by||h.user||'—'}</td>
                </tr>`).join('')+`</tbody></table>`;
        }

        let cardsHtml='';
        if(cards.length) {
            cardsHtml=`<div style="margin-top:12px"><div style="font-size:12px;font-weight:600;margin-bottom:6px">Привязанные карты</div>`+
                cards.map(c=>`<div style="padding:4px 0;font-size:12px;border-bottom:1px solid var(--bd)">
                    ${c.name||c.card_name||'Карта'} — ${_mntCardStatusBadge(c.status)}
                </div>`).join('')+`</div>`;
        }

        $('tmFormArea').innerHTML=`<div class="tm-detail">
            <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:12px">
                <div>
                    <h3 style="margin-bottom:4px">⚙️ ${eq.name||eq.equipment_name||'Оборудование'}</h3>
                    <div style="font-size:11px;color:var(--t2)">${_mntTypeName(eqType)} · ${_mntSiteName(eq.site_code||eq.site||'')}${eq.manufacturer?' · '+eq.manufacturer:''}${eq.model?' '+eq.model:''}</div>
                    ${eq.hours_source?`<div style="font-size:10px;color:var(--t3);margin-top:2px">Источник часов: ${eq.hours_source}${eq.epoch!==undefined?' · epoch: '+eq.epoch:''}</div>`:''}
                </div>
                <button class="sb-btn" onclick="$('tmFormArea').innerHTML=''" style="padding:4px 10px;font-size:11px">✕ Закрыть</button>
            </div>
            <div style="display:flex;gap:12px;margin-bottom:14px;flex-wrap:wrap">
                <div style="padding:8px 14px;border-radius:var(--rs);background:var(--bg4)">
                    <div style="font-size:10px;color:var(--t2)">Моточасы</div>
                    <div style="font-size:20px;font-weight:700;color:${col}">${Math.round(opHrs)}</div>
                </div>
                <div style="padding:8px 14px;border-radius:var(--rs);background:var(--bg4)">
                    <div style="font-size:10px;color:var(--t2)">Статус</div>
                    <div style="font-size:14px;font-weight:600;color:${col}">${_mntUrgencyLabel(sc)}</div>
                </div>
            </div>
            <div style="margin-bottom:14px">
                <div style="font-size:12px;font-weight:600;margin-bottom:6px">Предстоящие ТО</div>
                ${upcomingHtml}
            </div>
            <div style="margin-bottom:14px">
                <div style="font-size:12px;font-weight:600;margin-bottom:6px">История обслуживания</div>
                ${histHtml}
            </div>
            ${cardsHtml}
            <div style="display:flex;gap:8px;margin-top:14px;flex-wrap:wrap">
                <button class="sb-btn primary" onclick="_mntShowRecordForm('${eqId}')" style="padding:6px 14px" data-role-min="operator">📝 Записать ТО</button>
                <button class="sb-btn" onclick="_mntResetEpoch('${eqId}')" style="padding:6px 14px" data-role-min="admin">🔄 Обнулить epoch</button>
                ${isManual?`<button class="sb-btn" onclick="_mntShowHoursForm('${eqId}')" style="padding:6px 14px" data-role-min="operator">⏱ Ввести часы</button>`:''}
            </div>
            <div id="mntEqAction" style="margin-top:8px"></div>
        </div>`;
    } catch(e){$('tmFormArea').innerHTML=`<div class="tm-detail"><div style="color:var(--r)">Ошибка загрузки: ${e.message}</div></div>`}
}

function _mntShowRecordForm(eqId) {
    $('mntEqAction').innerHTML=`<div style="margin-top:8px;padding:10px;background:var(--bg4);border-radius:var(--rs)">
        <div style="font-size:12px;font-weight:600;margin-bottom:8px">Записать выполненное ТО</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
            <div>
                <label style="font-size:10px;color:var(--t2)">Название ТО</label>
                <input type="text" id="mntRecName" placeholder="ТО-500" style="width:100%;padding:6px 8px;border:1px solid var(--bd);border-radius:var(--rs);background:var(--bg3);color:var(--t);font-size:12px;font-family:var(--u);margin-top:2px">
            </div>
            <div>
                <label style="font-size:10px;color:var(--t2)">Моточасы на момент ТО</label>
                <input type="number" id="mntRecHours" placeholder="500" style="width:100%;padding:6px 8px;border:1px solid var(--bd);border-radius:var(--rs);background:var(--bg3);color:var(--t);font-size:12px;font-family:var(--u);margin-top:2px">
            </div>
            <div style="grid-column:span 2">
                <label style="font-size:10px;color:var(--t2)">Комментарий</label>
                <input type="text" id="mntRecNote" placeholder="Замена масла, фильтров..." style="width:100%;padding:6px 8px;border:1px solid var(--bd);border-radius:var(--rs);background:var(--bg3);color:var(--t);font-size:12px;font-family:var(--u);margin-top:2px">
            </div>
        </div>
        <div style="display:flex;gap:8px;margin-top:10px">
            <button class="sb-btn primary" onclick="_mntSubmitRecord('${eqId}')" style="padding:6px 14px">Сохранить</button>
            <button class="sb-btn" onclick="$('mntEqAction').innerHTML=''" style="padding:6px 14px">Отмена</button>
        </div>
        <div id="mntRecResult" style="font-size:12px;margin-top:6px"></div>
    </div>`;
}
async function _mntSubmitRecord(eqId) {
    const name=$('mntRecName')?.value?.trim();
    if(!name){$('mntRecResult').innerHTML='<span style="color:var(--r)">Укажите название ТО</span>';return}
    const body={maintenance_name:name,hours_at:parseFloat($('mntRecHours')?.value)||undefined,note:$('mntRecNote')?.value?.trim()||undefined};
    try {
        const r=await fetch(API_BASE+'/api/maintenance/equipment/'+eqId+'/record',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),credentials:'include'});
        if(r.ok){$('mntRecResult').innerHTML='<span style="color:var(--g)">ТО записано</span>';setTimeout(()=>{_mntShowEquipDetail(eqId);renderCardsTab()},1000)}
        else{const d=await r.json();$('mntRecResult').innerHTML=`<span style="color:var(--r)">${d.detail||'Ошибка'}</span>`}
    } catch(e){$('mntRecResult').innerHTML='<span style="color:var(--r)">Сервер недоступен</span>'}
}

function _mntShowHoursForm(eqId) {
    $('mntEqAction').innerHTML=`<div style="margin-top:8px;padding:10px;background:var(--bg4);border-radius:var(--rs)">
        <div style="font-size:12px;font-weight:600;margin-bottom:8px">Ввести моточасы вручную</div>
        <div style="display:flex;gap:8px;align-items:flex-end">
            <div>
                <label style="font-size:10px;color:var(--t2)">Текущие моточасы</label>
                <input type="number" id="mntHoursVal" placeholder="1234" style="width:120px;padding:6px 8px;border:1px solid var(--bd);border-radius:var(--rs);background:var(--bg3);color:var(--t);font-size:12px;font-family:var(--u);margin-top:2px">
            </div>
            <button class="sb-btn primary" onclick="_mntSubmitHours('${eqId}')" style="padding:6px 14px">Сохранить</button>
            <button class="sb-btn" onclick="$('mntEqAction').innerHTML=''" style="padding:6px 14px">Отмена</button>
        </div>
        <div id="mntHoursResult" style="font-size:12px;margin-top:6px"></div>
    </div>`;
}
async function _mntSubmitHours(eqId) {
    const val=parseFloat($('mntHoursVal')?.value);
    if(isNaN(val)||val<0){$('mntHoursResult').innerHTML='<span style="color:var(--r)">Введите корректное значение</span>';return}
    try {
        const r=await fetch(API_BASE+'/api/maintenance/equipment/'+eqId+'/hours',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({hours:val}),credentials:'include'});
        if(r.ok){$('mntHoursResult').innerHTML='<span style="color:var(--g)">Часы обновлены</span>';setTimeout(()=>{_mntShowEquipDetail(eqId);renderCardsTab()},1000)}
        else{const d=await r.json();$('mntHoursResult').innerHTML=`<span style="color:var(--r)">${d.detail||'Ошибка'}</span>`}
    } catch(e){$('mntHoursResult').innerHTML='<span style="color:var(--r)">Сервер недоступен</span>'}
}

async function _mntResetEpoch(eqId) {
    if(!confirm('Обнулить epoch для этого оборудования? Счетчик моточасов начнет отсчет заново.')) return;
    try {
        const r=await fetch(API_BASE+'/api/maintenance/equipment/'+eqId+'/record',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({maintenance_name:'Epoch reset',reset_epoch:true}),credentials:'include'});
        if(r.ok){_mntShowEquipDetail(eqId);renderCardsTab()}
        else{const d=await r.json();alert(d.detail||'Ошибка')}
    } catch(e){alert('Сервер недоступен')}
}

// ===================== CARDS SECTION =====================
async function _mntLoadCards() {
    try {
        const r=await fetch(API_BASE+'/api/maintenance/cards?t='+Date.now(),{credentials:'include'});
        if(!r.ok){$('mntContent').innerHTML='<div style="color:var(--r)">Ошибка загрузки карт</div>';return}
        _mntCardsData=await r.json();
        if(Array.isArray(_mntCardsData?.items)) _mntCardsData=_mntCardsData.items;
        if(!Array.isArray(_mntCardsData)) _mntCardsData=[];
        _mntRenderCardsView();
    } catch(e){console.error('_mntLoadCards error:',e);$('mntContent').innerHTML='<div style="color:var(--r)">Ошибка: '+e.message+'</div>'}
}

var _mntSortCol=null, _mntSortDir=0;
function _mntRenderCardsView() {
    const uploadBtn=`<div style="margin-bottom:12px"><button class="sb-btn primary" onclick="showUploadCardForm()" style="padding:6px 14px" data-role-min="admin">📄 Загрузить карту ТО</button></div>`;
    if(!_mntCardsData.length){
        $('mntContent').innerHTML=uploadBtn+`<div style="color:var(--t3);text-align:center;padding:40px">Нет карт ТО. Загрузите файл Word/PDF с картой обслуживания.</div>`;
        return;
    }
    var cards=_mntCardsData.map(function(c){
        var intervals=Array.isArray(c.intervals)?c.intervals:[];
        var intTxt=intervals.length?intervals.map(function(i){return (i.name||'?')+': '+(i.interval_hours?i.interval_hours+'ч':i.interval_days?i.interval_days+'д':'—')}).join(', '):'—';
        var workCount=c.work_items_count??0;
        var spareCount=c.spare_parts_count??0;
        var eq=Array.isArray(c.linked_equipment)&&c.linked_equipment.length?c.linked_equipment[0]:null;
        return {id:c.id,name:c.name||'—',intTxt:intTxt,workCount:workCount,spareCount:spareCount,
            status:c.status,siteName:eq?eq.site_name:'',eqName:eq?eq.equipment_name:'',
            sourceFile:c.source_file_name,sourceUrl:c.source_file_url,intervals:intervals};
    });
    if(_mntSortCol&&_mntSortDir){
        var col=_mntSortCol,dir=_mntSortDir;
        cards.sort(function(a,b){
            var va=col==='name'?a.name:col==='intervals'?a.intervals.length:col==='works'?a.workCount:col==='spares'?a.spareCount:col==='status'?a.status:'';
            var vb=col==='name'?b.name:col==='intervals'?b.intervals.length:col==='works'?b.workCount:col==='spares'?b.spareCount:col==='status'?b.status:'';
            if(typeof va==='string')va=va.toLowerCase();
            if(typeof vb==='string')vb=vb.toLowerCase();
            return va<vb?-dir:va>vb?dir:0;
        });
    }
    var groups={};
    cards.forEach(function(c){
        var sKey=c.siteName||'Не привязано';
        var eKey=c.eqName||'Без оборудования';
        if(!groups[sKey])groups[sKey]={};
        if(!groups[sKey][eKey])groups[sKey][eKey]=[];
        groups[sKey][eKey].push(c);
    });
    var siteKeys=Object.keys(groups).sort(function(a,b){
        if(a==='Не привязано')return 1;if(b==='Не привязано')return -1;return a.localeCompare(b);
    });
    function sortArrow(col){
        if(_mntSortCol!==col)return '';
        return _mntSortDir===1?' ▲':_mntSortDir===-1?' ▼':'';
    }
    var html=uploadBtn;
    html+='<table class="tm-table"><thead><tr>';
    html+='<th style="cursor:pointer;user-select:none" onclick="_mntToggleSort(\'name\')">Карта'+sortArrow('name')+'</th>';
    html+='<th>Оборудование</th>';
    html+='<th style="cursor:pointer;user-select:none" onclick="_mntToggleSort(\'intervals\')">Интервалы'+sortArrow('intervals')+'</th>';
    html+='<th style="cursor:pointer;user-select:none" onclick="_mntToggleSort(\'works\')">Работы'+sortArrow('works')+'</th>';
    html+='<th style="cursor:pointer;user-select:none" onclick="_mntToggleSort(\'spares\')">Запчасти'+sortArrow('spares')+'</th>';
    html+='<th style="cursor:pointer;user-select:none" onclick="_mntToggleSort(\'status\')">Статус'+sortArrow('status')+'</th>';
    html+='<th>Файл</th></tr></thead><tbody>';
    siteKeys.forEach(function(site){
        html+='<tr class="tm-group-row"><td colspan="7" style="background:var(--bg3);font-weight:600;font-size:12px;padding:6px 10px;color:var(--t)">🏭 '+esc(site)+'</td></tr>';
        var eqKeys=Object.keys(groups[site]).sort();
        eqKeys.forEach(function(eq){
            if(eq!=='Без оборудования')html+='<tr><td colspan="7" style="background:var(--bg4);font-size:11px;padding:4px 10px 4px 24px;color:var(--t2)">⚙ '+esc(eq)+'</td></tr>';
            groups[site][eq].forEach(function(c){
                var fileLink=c.sourceUrl?'<a href="'+c.sourceUrl+'" title="'+esc(c.sourceFile||'')+'" style="color:var(--g);text-decoration:none" onclick="event.stopPropagation()">📎</a>':'—';
                html+='<tr style="cursor:pointer" onclick="_mntShowCardDetail('+c.id+')">';
                html+='<td style="font-weight:500">'+esc(c.name)+'</td>';
                html+='<td style="font-size:11px;color:var(--t3)">'+esc(c.eqName||'—')+'</td>';
                html+='<td style="font-size:11px;max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">'+esc(c.intTxt)+'</td>';
                html+='<td>'+c.workCount+'</td><td>'+c.spareCount+'</td>';
                html+='<td>'+_mntCardStatusBadge(c.status)+'</td>';
                html+='<td>'+fileLink+'</td></tr>';
            });
        });
    });
    html+='</tbody></table>';
    $('mntContent').innerHTML=html;
}

function _mntToggleSort(col){
    if(_mntSortCol===col){_mntSortDir=_mntSortDir===1?-1:_mntSortDir===-1?0:1;}
    else{_mntSortCol=col;_mntSortDir=1;}
    if(!_mntSortDir)_mntSortCol=null;
    _mntRenderCardsView();
}

async function _mntShowCardDetail(cardId) {
    const card=_mntCardsData.find(c=>c.id===cardId);
    if(card && (card.status==='draft'||card.status==='confirmed')) {
        _mntOpenCardEditor(cardId);
        return;
    }
    _mntOpenCardEditor(cardId);
}

// ===================== CARD EDITOR =====================
let _mntEditCardId=null;
let _mntEditCardData=null;

async function _mntOpenCardEditor(cardId) {
    _mntEditCardId=cardId;
    try {
        const [rCard, rEquip] = await Promise.all([
            fetch(API_BASE+'/api/maintenance/cards/'+cardId,{credentials:'include'}),
            fetch(API_BASE+'/api/maintenance/equipment',{credentials:'include'}),
        ]);
        if(!rCard.ok){alert('Ошибка загрузки карты');return}
        _mntEditCardData=await rCard.json();
        if(rEquip.ok){
            let eq=await rEquip.json();
            if(Array.isArray(eq?.items)) eq=eq.items;
            if(Array.isArray(eq)) _mntEquipData=eq;
            console.log('Card editor: loaded',_mntEquipData.length,'equipment items');
        } else {
            console.error('Card editor: equipment load failed',rEquip.status);
        }
    } catch(e){alert('Сервер недоступен');return}
    _mntRenderEditor();
}

async function _mntRenderEditor() {
    const c=_mntEditCardData;
    if(!c) return;
    const intervals=c.intervals||[];

    let intAccHtml='';
    intervals.forEach((iv,idx)=>{
        const wiList=(iv.work_items||[]).map(wi=>`<div style="display:flex;align-items:center;gap:6px;padding:4px 0;border-bottom:1px solid var(--bd)" id="mce-wi-${wi.id}">
            <span style="flex:1;font-size:12px">${wi.work_description||'—'}</span>
            <button class="sb-btn" style="padding:2px 8px;font-size:10px" onclick="_mceEditWI(${wi.id})">✏️</button>
            <button class="sb-btn" style="padding:2px 8px;font-size:10px;color:var(--r)" onclick="_mceDelWI(${wi.id})">🗑️</button>
        </div>`).join('');
        const spList=(iv.spare_parts||[]).map(sp=>`<div style="display:flex;align-items:center;gap:6px;padding:4px 0;border-bottom:1px solid var(--bd)" id="mce-sp-${sp.id}">
            <span style="flex:1;font-size:12px">${sp.name||sp.part_name||'—'} ${sp.part_number?'('+sp.part_number+')':''} — ${sp.quantity||1} ${sp.unit||'шт.'}</span>
            <button class="sb-btn" style="padding:2px 8px;font-size:10px" onclick="_mceEditSP(${sp.id})">✏️</button>
            <button class="sb-btn" style="padding:2px 8px;font-size:10px;color:var(--r)" onclick="_mceDelSP(${sp.id})">🗑️</button>
        </div>`).join('');

        const typeLabel={'hours':'Моточасы','calendar_days':'Календарные дни','hours_or_days':'Часы или дни','once':'Однократно'};
        intAccHtml+=`<div style="border:1px solid var(--bd);border-radius:var(--rs);margin-bottom:8px;overflow:hidden" id="mce-iv-${iv.id}">
            <div style="display:flex;align-items:center;gap:6px;padding:10px 12px;background:var(--bg4);cursor:pointer;flex-wrap:wrap" onclick="this.nextElementSibling.style.display=this.nextElementSibling.style.display==='none'?'block':'none'">
                <span style="font-weight:600;font-size:13px;min-width:120px">${iv.code}</span>
                <span style="flex:1;font-size:12px;color:var(--t)">${iv.name}</span>
                <span style="font-size:11px;color:var(--g);font-weight:600;white-space:nowrap">${iv.interval_hours?iv.interval_hours+' ч':''}${iv.interval_hours&&iv.interval_days?' / ':''}${iv.interval_days?iv.interval_days+' дн':''}</span>
                <span style="font-size:10px;color:var(--t3);white-space:nowrap">${iv.labor_hours?iv.labor_hours+' н/ч':''}</span>
                <span style="font-size:10px;color:var(--t3);white-space:nowrap">работ:${(iv.work_items||[]).length} зч:${(iv.spare_parts||[]).length}</span>
                <button class="sb-btn" style="padding:2px 6px;font-size:10px" onclick="event.stopPropagation();_mceEditIV(${iv.id})">✏️</button>
                <button class="sb-btn" style="padding:2px 6px;font-size:10px;color:var(--r)" onclick="event.stopPropagation();_mceDelIV(${iv.id})">🗑️</button>
            </div>
            <div style="padding:10px 12px;display:${idx===0?'block':'none'}">
                <div style="margin-bottom:8px">
                    <div style="font-size:11px;font-weight:600;color:var(--t2);margin-bottom:4px">Работы (${(iv.work_items||[]).length})</div>
                    ${wiList||'<div style="font-size:11px;color:var(--t3)">Нет работ</div>'}
                    <button class="sb-btn" style="padding:4px 10px;font-size:11px;margin-top:6px" onclick="_mceAddWI(${iv.id})">+ Работа</button>
                </div>
                <div>
                    <div style="font-size:11px;font-weight:600;color:var(--t2);margin-bottom:4px">Запчасти (${(iv.spare_parts||[]).length})</div>
                    ${spList||'<div style="font-size:11px;color:var(--t3)">Нет запчастей</div>'}
                    <button class="sb-btn" style="padding:4px 10px;font-size:11px;margin-top:6px" onclick="_mceAddSP(${iv.id})">+ Запчасть</button>
                </div>
            </div>
        </div>`;
    });

    if(!_mntEquipData.length){
        try{const r=await fetch(API_BASE+'/api/maintenance/equipment',{credentials:'include'});if(r.ok){let d=await r.json();if(Array.isArray(d))_mntEquipData=d;}}catch(e){}
    }
    let eqOptions='';
    _mntEquipData.forEach(eq=>{
        const eqId=eq.equipment_id||eq.id;
        const eqName=eq.equipment_name||eq.name||'—';
        const site=eq.site_name||eq.site_code||eq.site||'';
        const sel=(c.linked_equipment||[]).some(lk=>lk.equipment_id===eqId&&lk.is_active);
        eqOptions+=`<option value="${eqId}"${sel?' selected':''}>${eqName} (${_mntSiteName(site)})</option>`;
    });
    if(!eqOptions) eqOptions='<option value="">Нет оборудования</option>';

    const confBadge=c.parse_confidence?`<span style="font-size:11px;color:var(--t2);margin-left:8px">AI confidence: ${Math.round(c.parse_confidence*100)}%</span>`:'';

    $('tmFormArea').innerHTML=`<div class="tm-detail" style="margin-bottom:16px;max-width:960px">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
            <div><h3 style="display:inline">📄 Редактор карты ТО</h3>${confBadge}</div>
            <button class="sb-btn" onclick="$('tmFormArea').innerHTML='';_mntLoadCards()" style="padding:4px 10px;font-size:11px">✕ Закрыть</button>
        </div>

        <!-- Card Info -->
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:14px">
            <div>
                <label style="font-size:10px;color:var(--t2)">Название карты</label>
                <input type="text" id="mceCardName" value="${(c.name||'').replace(/"/g,'&quot;')}" style="width:100%;padding:6px 8px;border:1px solid var(--bd);border-radius:var(--rs);background:var(--bg3);color:var(--t);font-size:12px;font-family:var(--u);margin-top:2px">
            </div>
            <div>
                <label style="font-size:10px;color:var(--t2)">Производитель</label>
                <input type="text" id="mceCardMfr" value="${(c.manufacturer||'').replace(/"/g,'&quot;')}" style="width:100%;padding:6px 8px;border:1px solid var(--bd);border-radius:var(--rs);background:var(--bg3);color:var(--t);font-size:12px;font-family:var(--u);margin-top:2px">
            </div>
            <div>
                <label style="font-size:10px;color:var(--t2)">Тип оборудования</label>
                <input type="text" id="mceCardType" value="${(c.equipment_type||'').replace(/"/g,'&quot;')}" style="width:100%;padding:6px 8px;border:1px solid var(--bd);border-radius:var(--rs);background:var(--bg3);color:var(--t);font-size:12px;font-family:var(--u);margin-top:2px">
            </div>
            <div>
                <label style="font-size:10px;color:var(--t2)">Примечания</label>
                <input type="text" id="mceCardNotes" value="${(c.notes||'').replace(/"/g,'&quot;')}" style="width:100%;padding:6px 8px;border:1px solid var(--bd);border-radius:var(--rs);background:var(--bg3);color:var(--t);font-size:12px;font-family:var(--u);margin-top:2px">
            </div>
        </div>
        <button class="sb-btn" onclick="_mceSaveCardInfo()" style="padding:4px 14px;font-size:11px;margin-bottom:14px">💾 Сохранить информацию</button>
        <div id="mceCardInfoMsg" style="font-size:11px;margin-bottom:8px"></div>

        <!-- Intervals Accordion -->
        <div style="font-size:13px;font-weight:600;margin-bottom:8px">Интервалы обслуживания (${intervals.length})</div>
        <div id="mceIntervalsArea">${intAccHtml||'<div style="color:var(--t3);font-size:12px">Нет интервалов</div>'}</div>
        <button class="sb-btn" onclick="_mceAddIV()" style="padding:6px 14px;font-size:12px;margin-top:8px">+ Новый интервал</button>

        <!-- Equipment Linking -->
        <div style="margin-top:16px;padding-top:14px;border-top:1px solid var(--bd)">
            <div style="font-size:13px;font-weight:600;margin-bottom:8px">Привязка к оборудованию</div>
            <div style="display:flex;gap:8px;align-items:flex-end">
                <div style="flex:1">
                    <select id="mceEqSelect" style="width:100%;padding:8px 10px;border:1px solid var(--bd);border-radius:var(--rs);background:var(--bg3);color:var(--t);font-size:13px;font-family:var(--u)">${eqOptions}</select>
                    <div style="font-size:10px;color:var(--t3);margin-top:4px">Для привязки к нескольким ГПУ — повторите операцию</div>
                </div>
                <button class="sb-btn primary" onclick="_mceLinkEquip()" style="padding:6px 14px;font-size:12px">🔗 Привязать</button>
            </div>
            <div id="mceLinkMsg" style="font-size:11px;margin-top:4px"></div>
        </div>

        <!-- Actions -->
        <div style="display:flex;gap:8px;margin-top:16px;padding-top:14px;border-top:1px solid var(--bd)">
            ${c.status==='draft'?`<button class="bp" onclick="_mceConfirm()" style="padding:8px 20px">✓ Подтвердить карту</button>`:''}
            <button class="sb-btn" onclick="_mceReparse()" style="padding:8px 14px">🔄 Перепарсить</button>
            ${_mntCardStatusBadge(c.status)}
        </div>
        <div id="mceActionMsg" style="font-size:12px;margin-top:6px"></div>
    </div>`;
}

// ===================== CARD EDITOR CRUD =====================
async function _mceSaveCardInfo() {
    const body={};
    const name=$('mceCardName')?.value?.trim();
    if(name) body.name=name;
    const mfr=$('mceCardMfr')?.value?.trim();
    if(mfr!==undefined) body.manufacturer=mfr||null;
    const tp=$('mceCardType')?.value?.trim();
    if(tp!==undefined) body.equipment_type=tp||null;
    const notes=$('mceCardNotes')?.value?.trim();
    if(notes!==undefined) body.notes=notes||null;
    try {
        const r=await fetch(API_BASE+'/api/maintenance/cards/'+_mntEditCardId,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),credentials:'include'});
        if(r.ok) $('mceCardInfoMsg').innerHTML='<span style="color:var(--g)">Сохранено</span>';
        else{const d=await r.json();$('mceCardInfoMsg').innerHTML=`<span style="color:var(--r)">${d.detail||'Ошибка'}</span>`}
    } catch(e){$('mceCardInfoMsg').innerHTML='<span style="color:var(--r)">Сервер недоступен</span>'}
}

async function _mceEditIV(ivId) {
    const iv=(_mntEditCardData?.intervals||[]).find(i=>i.id===ivId);
    if(!iv) return;
    const html=`<div style="padding:10px;background:var(--bg4);border-radius:var(--rs);margin-top:6px" id="mce-iv-form">
        <div style="font-size:12px;font-weight:600;margin-bottom:8px">Редактирование интервала</div>
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px">
            <div><label style="font-size:10px;color:var(--t2)">Название</label><input type="text" id="mceIvName" value="${(iv.name||'').replace(/"/g,'&quot;')}" class="fi" style="font-size:12px;padding:4px 6px;margin-top:2px"></div>
            <div><label style="font-size:10px;color:var(--t2)">Код</label><input type="text" id="mceIvCode" value="${iv.code||''}" class="fi" style="font-size:12px;padding:4px 6px;margin-top:2px"></div>
            <div><label style="font-size:10px;color:var(--t2)">Тип</label><select id="mceIvType" class="fi" style="font-size:12px;padding:4px 6px;margin-top:2px">
                <option value="hours"${iv.interval_type==='hours'?' selected':''}>Моточасы</option>
                <option value="calendar_days"${iv.interval_type==='calendar_days'?' selected':''}>Календарные дни</option>
                <option value="hours_or_days"${iv.interval_type==='hours_or_days'?' selected':''}>Часы или дни</option>
                <option value="once"${iv.interval_type==='once'?' selected':''}>Однократно</option>
            </select></div>
            <div><label style="font-size:10px;color:var(--t2)">Часы</label><input type="number" id="mceIvHours" value="${iv.interval_hours||''}" class="fi" style="font-size:12px;padding:4px 6px;margin-top:2px"></div>
            <div><label style="font-size:10px;color:var(--t2)">Дни</label><input type="number" id="mceIvDays" value="${iv.interval_days||''}" class="fi" style="font-size:12px;padding:4px 6px;margin-top:2px"></div>
            <div><label style="font-size:10px;color:var(--t2)">Нормочасы</label><input type="number" step="0.5" id="mceIvLabor" value="${iv.labor_hours||''}" class="fi" style="font-size:12px;padding:4px 6px;margin-top:2px"></div>
        </div>
        <div style="display:flex;gap:6px;margin-top:8px">
            <button class="sb-btn primary" onclick="_mceSaveIV(${ivId})" style="padding:4px 14px;font-size:11px">Сохранить</button>
            <button class="sb-btn" onclick="_mntOpenCardEditor(_mntEditCardId)" style="padding:4px 14px;font-size:11px">Отмена</button>
        </div>
    </div>`;
    const el=$('mce-iv-'+ivId);
    if(el) el.insertAdjacentHTML('afterend',html);
}

async function _mceSaveIV(ivId) {
    const body={};
    const name=$('mceIvName')?.value?.trim();if(name) body.name=name;
    const code=$('mceIvCode')?.value?.trim();if(code) body.code=code;
    const type=$('mceIvType')?.value;if(type) body.interval_type=type;
    const hrs=$('mceIvHours')?.value;if(hrs) body.interval_hours=parseInt(hrs);
    const days=$('mceIvDays')?.value;if(days) body.interval_days=parseInt(days);
    const labor=$('mceIvLabor')?.value;if(labor) body.labor_hours=parseFloat(labor);
    try {
        const r=await fetch(API_BASE+'/api/maintenance/intervals/'+ivId,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),credentials:'include'});
        if(r.ok) _mntOpenCardEditor(_mntEditCardId);
        else alert('Ошибка сохранения');
    } catch(e){alert('Сервер недоступен')}
}

async function _mceDelIV(ivId) {
    if(!confirm('Удалить интервал и все его работы/запчасти?')) return;
    try {
        const r=await fetch(API_BASE+'/api/maintenance/intervals/'+ivId,{method:'DELETE',credentials:'include'});
        if(r.ok) _mntOpenCardEditor(_mntEditCardId);
        else alert('Ошибка удаления');
    } catch(e){alert('Сервер недоступен')}
}

async function _mceAddIV() {
    const code='TO-'+((_mntEditCardData?.intervals||[]).length+1);
    try {
        const r=await fetch(API_BASE+'/api/maintenance/cards/'+_mntEditCardId+'/intervals',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:'Новый интервал',code,interval_type:'hours'}),credentials:'include'});
        if(r.ok) _mntOpenCardEditor(_mntEditCardId);
        else alert('Ошибка создания');
    } catch(e){alert('Сервер недоступен')}
}

function _mceEditWI(wiId) {
    const allWI=(_mntEditCardData?.intervals||[]).flatMap(iv=>iv.work_items||[]);
    const wi=allWI.find(w=>w.id===wiId);
    if(!wi) return;
    const el=$('mce-wi-'+wiId);
    if(!el) return;
    el.innerHTML=`<input type="text" id="mceWIDesc-${wiId}" value="${(wi.work_description||'').replace(/"/g,'&quot;')}" class="fi" style="flex:1;font-size:12px;padding:4px 6px">
        <button class="sb-btn primary" style="padding:2px 8px;font-size:10px" onclick="_mceSaveWI(${wiId})">💾</button>
        <button class="sb-btn" style="padding:2px 8px;font-size:10px" onclick="_mntOpenCardEditor(_mntEditCardId)">✕</button>`;
}

async function _mceSaveWI(wiId) {
    const desc=$('mceWIDesc-'+wiId)?.value?.trim();
    if(!desc) return;
    try {
        const r=await fetch(API_BASE+'/api/maintenance/work-items/'+wiId,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({work_description:desc}),credentials:'include'});
        if(r.ok) _mntOpenCardEditor(_mntEditCardId);
        else alert('Ошибка');
    } catch(e){alert('Сервер недоступен')}
}

async function _mceDelWI(wiId) {
    if(!confirm('Удалить работу?')) return;
    try {
        const r=await fetch(API_BASE+'/api/maintenance/work-items/'+wiId,{method:'DELETE',credentials:'include'});
        if(r.ok) _mntOpenCardEditor(_mntEditCardId);
        else alert('Ошибка');
    } catch(e){alert('Сервер недоступен')}
}

async function _mceAddWI(ivId) {
    const desc=prompt('Описание работы:');
    if(!desc) return;
    try {
        const r=await fetch(API_BASE+'/api/maintenance/intervals/'+ivId+'/work-items',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({work_description:desc}),credentials:'include'});
        if(r.ok) _mntOpenCardEditor(_mntEditCardId);
        else alert('Ошибка');
    } catch(e){alert('Сервер недоступен')}
}

function _mceEditSP(spId) {
    const allSP=(_mntEditCardData?.intervals||[]).flatMap(iv=>iv.spare_parts||[]);
    const sp=allSP.find(s=>s.id===spId);
    if(!sp) return;
    const el=$('mce-sp-'+spId);
    if(!el) return;
    el.innerHTML=`<input type="text" id="mceSPName-${spId}" value="${(sp.name||sp.part_name||'').replace(/"/g,'&quot;')}" placeholder="Название" class="fi" style="flex:1;font-size:11px;padding:3px 6px">
        <input type="text" id="mceSPNum-${spId}" value="${(sp.part_number||'').replace(/"/g,'&quot;')}" placeholder="Артикул" class="fi" style="width:80px;font-size:11px;padding:3px 6px">
        <input type="number" id="mceSPQty-${spId}" value="${sp.quantity||1}" step="0.5" class="fi" style="width:50px;font-size:11px;padding:3px 6px">
        <button class="sb-btn primary" style="padding:2px 8px;font-size:10px" onclick="_mceSaveSP(${spId})">💾</button>
        <button class="sb-btn" style="padding:2px 8px;font-size:10px" onclick="_mntOpenCardEditor(_mntEditCardId)">✕</button>`;
}

async function _mceSaveSP(spId) {
    const body={};
    const name=$('mceSPName-'+spId)?.value?.trim();if(name) body.part_name=name;
    const num=$('mceSPNum-'+spId)?.value?.trim();if(num!==undefined) body.part_number=num||null;
    const qty=$('mceSPQty-'+spId)?.value;if(qty) body.quantity=parseFloat(qty);
    try {
        const r=await fetch(API_BASE+'/api/maintenance/spare-parts/'+spId,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),credentials:'include'});
        if(r.ok) _mntOpenCardEditor(_mntEditCardId);
        else alert('Ошибка');
    } catch(e){alert('Сервер недоступен')}
}

async function _mceDelSP(spId) {
    if(!confirm('Удалить запчасть?')) return;
    try {
        const r=await fetch(API_BASE+'/api/maintenance/spare-parts/'+spId,{method:'DELETE',credentials:'include'});
        if(r.ok) _mntOpenCardEditor(_mntEditCardId);
        else alert('Ошибка');
    } catch(e){alert('Сервер недоступен')}
}

async function _mceAddSP(ivId) {
    const name=prompt('Название запчасти:');
    if(!name) return;
    try {
        const r=await fetch(API_BASE+'/api/maintenance/intervals/'+ivId+'/spare-parts',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({part_name:name}),credentials:'include'});
        if(r.ok) _mntOpenCardEditor(_mntEditCardId);
        else alert('Ошибка');
    } catch(e){alert('Сервер недоступен')}
}

async function _mceConfirm() {
    try {
        const r=await fetch(API_BASE+'/api/maintenance/cards/'+_mntEditCardId+'/confirm',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({confirmed_by:'UI'}),credentials:'include'});
        if(r.ok){$('mceActionMsg').innerHTML='<span style="color:var(--g)">Карта подтверждена!</span>';_mntLoadEquipment();setTimeout(()=>_mntOpenCardEditor(_mntEditCardId),800)}
        else{const d=await r.json();$('mceActionMsg').innerHTML=`<span style="color:var(--r)">${d.detail||'Ошибка'}</span>`}
    } catch(e){$('mceActionMsg').innerHTML='<span style="color:var(--r)">Сервер недоступен</span>'}
}

async function _mceLinkEquip() {
    const sel=$('mceEqSelect');
    if(!sel) return;
    const ids=[...sel.selectedOptions].map(o=>parseInt(o.value)).filter(v=>v);
    if(!ids.length){$('mceLinkMsg').innerHTML='<span style="color:var(--r)">Выберите оборудование</span>';return}
    try {
        const r=await fetch(API_BASE+'/api/maintenance/cards/'+_mntEditCardId+'/link',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({equipment_ids:ids,linked_by:'UI'}),credentials:'include'});
        if(r.ok){$('mceLinkMsg').innerHTML='<span style="color:var(--g)">Привязано!</span>';_mntLoadEquipment();setTimeout(()=>_mntOpenCardEditor(_mntEditCardId),800)}
        else{const d=await r.json();$('mceLinkMsg').innerHTML=`<span style="color:var(--r)">${d.detail||'Ошибка'}</span>`}
    } catch(e){$('mceLinkMsg').innerHTML='<span style="color:var(--r)">Сервер недоступен</span>'}
}

async function _mceReparse() {
    if(!confirm('Перепарсить карту? Текущие данные будут заменены.')) return;
    $('mceActionMsg').innerHTML='<span style="color:var(--y)">⏳ Парсинг...</span>';
    try {
        const r=await fetch(API_BASE+'/api/maintenance/cards/'+_mntEditCardId+'/reparse',{method:'POST',credentials:'include'});
        if(r.ok){$('mceActionMsg').innerHTML='<span style="color:var(--g)">Перепарсено!</span>';setTimeout(()=>_mntOpenCardEditor(_mntEditCardId),800)}
        else{const d=await r.json();$('mceActionMsg').innerHTML=`<span style="color:var(--r)">${d.detail||'Ошибка'}</span>`}
    } catch(e){$('mceActionMsg').innerHTML='<span style="color:var(--r)">Сервер недоступен</span>'}
}

// ===================== CREATE TASK =====================
function showCreateTaskForm() {
    $('tmFormArea').innerHTML=`<div class="tm-detail" style="margin-bottom:16px">
        <h3>➕ Новая задача</h3>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:10px">
            <div>
                <label style="font-size:11px;color:var(--t2)">Название задачи *</label>
                <input type="text" id="tfTitle" placeholder="Проверка масла МКЗ Gen1" style="width:100%;padding:8px 10px;border:1px solid var(--bd);border-radius:var(--rs);background:var(--bg3);color:var(--t);font-size:13px;font-family:var(--u);margin-top:4px">
            </div>
            <div>
                <label style="font-size:11px;color:var(--t2)">Оборудование</label>
                <select id="tfEquip" style="width:100%;padding:8px 10px;border:1px solid var(--bd);border-radius:var(--rs);background:var(--bg3);color:var(--t);font-size:13px;font-family:var(--u);margin-top:4px">
                    <option value="">Не привязано</option>
                    <option value="mkz_dgu1">МКЗ ГПУ</option>
                    <option value="yakz_dgu1">ЯКЗ ГПУ</option>
                </select>
            </div>
            <div style="grid-column:span 2">
                <label style="font-size:11px;color:var(--t2)">Описание</label>
                <textarea id="tfDesc" rows="3" placeholder="Подробности задачи..." style="width:100%;padding:8px 10px;border:1px solid var(--bd);border-radius:var(--rs);background:var(--bg3);color:var(--t);font-size:13px;font-family:var(--u);margin-top:4px;resize:vertical"></textarea>
            </div>
            <div>
                <label style="font-size:11px;color:var(--t2)">Приоритет</label>
                <select id="tfPri" style="width:100%;padding:8px 10px;border:1px solid var(--bd);border-radius:var(--rs);background:var(--bg3);color:var(--t);font-size:13px;font-family:var(--u);margin-top:4px">
                    <option value="2">⚪ Обычный (7 дней)</option>
                    <option value="1">🟡 Высокий (24 часа)</option>
                    <option value="0">🔴 Критический (4 часа)</option>
                </select>
            </div>
            <div>
                <label style="font-size:11px;color:var(--t2)">Тип задачи</label>
                <select id="tfType" style="width:100%;padding:8px 10px;border:1px solid var(--bd);border-radius:var(--rs);background:var(--bg3);color:var(--t);font-size:13px;font-family:var(--u);margin-top:4px">
                    <option value="manual">Ручная</option>
                    <option value="maintenance">ТО</option>
                    <option value="incident">Инцидент</option>
                </select>
            </div>
            <div>
                <label style="font-size:11px;color:var(--t2)">Исполнитель</label>
                <div id="tfExecutor" data-employee-select data-field="executor_name"></div>
            </div>
            <div style="display:flex;align-items:center;gap:8px;padding-top:16px">
                <input type="checkbox" id="tfSanekCtrl" checked style="accent-color:var(--g)">
                <label for="tfSanekCtrl" style="font-size:13px;cursor:pointer">🤖 Санёк контролирует исполнение</label>
            </div>
        </div>
        <div style="display:flex;gap:8px;margin-top:14px">
            <button class="sb-btn primary" onclick="submitCreateTask()" style="padding:8px 20px">Создать</button>
            <button class="sb-btn" onclick="$('tmFormArea').innerHTML=''" style="padding:8px 20px">Отмена</button>
        </div>
        <div id="tfError" style="color:var(--r);font-size:12px;margin-top:6px;min-height:16px"></div>
    </div>`;
    loadEmployeeDropdowns();
}

async function submitCreateTask() {
    const title=$('tfTitle')?.value?.trim();
    if(!title){$('tfError').textContent='Введите название задачи';return}
    const body={
        title,
        equipment_code:$('tfEquip')?.value||null,
        description:$('tfDesc')?.value?.trim()||'',
        priority:parseInt($('tfPri')?.value||'2'),
        task_type:$('tfType')?.value||'manual',
    };
    try {
        const r=await fetch(API_BASE+'/api/task-manager/tasks',{
            method:'POST',headers:{'Content-Type':'application/json'},
            body:JSON.stringify(body),credentials:'include'
        });
        const d=await r.json();
        if(r.ok){
            $('tmFormArea').innerHTML=`<div style="background:var(--gd);border:1px solid var(--g);border-radius:var(--rs);padding:10px 14px;margin-bottom:12px;font-size:13px">✅ Задача #${d.id||''} создана: ${d.title||title}</div>`;
            setTimeout(()=>{$('tmFormArea').innerHTML=''},3000);
            await loadTaskStats();
            await loadTasks();
        } else {
            $('tfError').textContent=d.detail||d.message||'Ошибка создания';
        }
    } catch(e){$('tfError').textContent='Сервер недоступен'}
}

// ===================== UPLOAD CARD =====================
function showUploadCardForm() {
    $('tmFormArea').innerHTML=`<div class="tm-detail" style="margin-bottom:16px">
        <h3>📄 Загрузка карты ТО</h3>
        <p style="font-size:12px;color:var(--t2);margin:8px 0">Загрузите файл Word (.docx) или PDF с картой технического обслуживания. Санёк распарсит его и создаст чек-лист работ.</p>
        <div style="margin-top:10px">
            <input type="file" id="tfCardFile" accept=".docx,.pdf,.xlsx" style="font-size:12px;font-family:var(--u)">
        </div>
        <div style="display:flex;gap:8px;margin-top:14px">
            <button class="sb-btn primary" onclick="submitUploadCard()" style="padding:8px 20px">📤 Загрузить и распарсить</button>
            <button class="sb-btn" onclick="$('tmFormArea').innerHTML=''" style="padding:8px 20px">Отмена</button>
        </div>
        <div id="tfCardResult" style="font-size:12px;margin-top:8px;min-height:16px"></div>
    </div>`;
}

let _parseProgressTimer=null;
function _startParseProgress() {
    const stages=[
        {pct:3,text:'📤 Загрузка файла на сервер...'},
        {pct:8,text:'📄 Извлечение текста из PDF...'},
        {pct:15,text:'🔍 Извлечение таблиц и структуры...'},
        {pct:25,text:'🤖 AI анализирует документ (GPT-5.4)...'},
        {pct:35,text:'🤖 Распознавание интервалов ТО...'},
        {pct:45,text:'📋 Извлечение работ из чек-листов...'},
        {pct:55,text:'🔧 Извлечение запчастей и артикулов...'},
        {pct:65,text:'📊 Обработка результатов AI...'},
        {pct:72,text:'🔬 Проверка качества парсинга...'},
        {pct:80,text:'💾 Сохранение интервалов в базу...'},
        {pct:88,text:'💾 Сохранение работ и запчастей...'},
        {pct:95,text:'✅ Финализация карты ТО...'},
    ];
    let idx=0;
    const el=$('tfCardResult');
    const startTime=Date.now();
    const render=()=>{
        const s=stages[Math.min(idx,stages.length-1)];
        const elapsed=Math.round((Date.now()-startTime)/1000);
        el.innerHTML=`<div style="margin-top:8px">
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
                <div style="flex:1;height:8px;border-radius:4px;background:var(--bg4);overflow:hidden">
                    <div style="height:100%;width:${s.pct}%;border-radius:4px;background:var(--g);transition:width 2s ease"></div>
                </div>
                <span style="font-size:11px;color:var(--t2);white-space:nowrap;min-width:55px">${s.pct}% · ${elapsed}с</span>
            </div>
            <div style="font-size:12px;color:var(--y)">${s.text}</div>
        </div>`;
        idx++;
    };
    render();
    _parseProgressTimer=setInterval(()=>{if(idx<stages.length)render()},15000);
}
function _stopParseProgress(){if(_parseProgressTimer){clearInterval(_parseProgressTimer);_parseProgressTimer=null}}

async function submitUploadCard() {
    const file=$('tfCardFile')?.files?.[0];
    if(!file){$('tfCardResult').innerHTML='<span style="color:var(--r)">Выберите файл</span>';return}
    _startParseProgress();
    const fd=new FormData();
    fd.append('file',file);
    try {
        const ctrl=new AbortController();
        const timer=setTimeout(()=>ctrl.abort(),300000);
        const r=await fetch(API_BASE+'/api/maintenance/cards/upload',{
            method:'POST',body:fd,credentials:'include',signal:ctrl.signal
        });
        clearTimeout(timer);
        _stopParseProgress();
        const contentType=r.headers.get('content-type')||'';
        if(!contentType.includes('application/json')){
            if(r.status>=500) $('tfCardResult').innerHTML='<span style="color:var(--r)">Сервер вернул ошибку '+r.status+'. AI парсинг занял слишком долго — попробуйте ещё раз.</span>';
            else $('tfCardResult').innerHTML='<span style="color:var(--r)">Неожиданный ответ сервера ('+r.status+')</span>';
            return;
        }
        const d=await r.json();
        if(r.ok){
            const iv=d.intervals_count||0;
            if(iv>0){
                $('tfCardResult').innerHTML=`<div style="color:var(--g)">✅ Карта ТО распарсена! Интервалов: ${iv}, работ: ${d.work_items_count||0}, запчастей: ${d.spare_parts_count||0}. Открываю редактор...</div>`;
                setTimeout(()=>_mntOpenCardEditor(d.card_id),800);
            } else {
                $('tfCardResult').innerHTML=`<div style="color:var(--y)">⚠️ AI не нашёл интервалов ТО. Карта создана — добавьте интервалы вручную в редакторе.</div>`;
                if(d.card_id) setTimeout(()=>_mntOpenCardEditor(d.card_id),800);
            }
            _mntLoadEquipment();
        } else {
            $('tfCardResult').innerHTML=`<span style="color:var(--r)">${d.detail||d.message||'Ошибка парсинга'}</span>`;
        }
    } catch(e){
        _stopParseProgress();
        if(e.name==='AbortError') $('tfCardResult').innerHTML='<span style="color:var(--r)">⏳ Парсинг занял больше 3 минут. Проверьте файл — нужен PDF/Word с таблицей регламента ТО.</span>';
        else $('tfCardResult').innerHTML='<span style="color:var(--r)">Ошибка: '+e.message+'</span>';
    }
}

// ===================== TASK LIST & STATS =====================
async function loadTaskStats() {
    try {
        const r = await fetch(API_BASE+'/api/task-manager/stats/overview',{credentials:'include'});
        if(!r.ok) return;
        const d = await r.json();
        $('tmStats').innerHTML=`
            <div class="tm-stat"><div class="val">${d.total||0}</div><div class="lbl">Всего</div></div>
            <div class="tm-stat open"><div class="val">${d.open||0}</div><div class="lbl">Открытых</div></div>
            <div class="tm-stat overdue"><div class="val">${d.overdue||0}</div><div class="lbl">Просрочено</div></div>
            <div class="tm-stat done"><div class="val">${d.completed_week||0}</div><div class="lbl">За неделю</div></div>`;
    } catch(e){}
}

async function loadTasks() {
    const status=$('tmStatus')?.value||'';
    const type=$('tmType')?.value||'';
    let url=API_BASE+'/api/task-manager/tasks?limit=50';
    if(status)url+=`&status=${status}`;
    if(type)url+=`&task_type=${type}`;
    try {
        const r=await fetch(url,{credentials:'include'});
        if(!r.ok){$('tmBody').innerHTML='<tr><td colspan="9" style="text-align:center;color:var(--t3)">Нет задач</td></tr>';return}
        const tasks=await r.json();
        if(!tasks.length){$('tmBody').innerHTML='<tr><td colspan="9" style="text-align:center;color:var(--t3)">Нет задач</td></tr>';return}
        $('tmBody').innerHTML=tasks.map(t=>{
            const pri=['🔴 Критич.','🟡 Высокий','⚪ Обычный'][t.priority]||'⚪';
            const priCls=['p0','p1','p2'][t.priority]||'p2';
            const statusMap={created:'Создана',in_progress:'В работе',escalated:'⚠ Эскалация',completed:'Завершена',closed:'Закрыта',pending_review:'На проверке'};
            const dl=t.deadline?new Date(t.deadline).toLocaleDateString('ru',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'}):'—';
            const overdue=t.deadline&&new Date(t.deadline)<new Date()&&!['completed','closed'].includes(t.status);
            return `<tr onclick="showTaskDetail(${t.id})" style="cursor:pointer">
                <td style="color:var(--t3)">${t.id}</td>
                <td style="max-width:250px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${t.title||'—'}${(t.trigger_source==='rule_engine'||String(t.creator||'').startsWith('rule:'))?' <span style="font-size:9px;padding:1px 5px;border-radius:4px;background:var(--pd);color:var(--p)">от правила</span>':''}</td>
                <td><span class="tm-badge">${t.task_type||'—'}</span></td>
                <td>${t.equipment_code||'—'}</td>
                <td><span class="tm-badge ${t.status}">${statusMap[t.status]||t.status}</span></td>
                <td><span class="tm-pri ${priCls}">${pri}</span></td>
                <td>${t.responsible_name||'—'}</td>
                <td style="${overdue?'color:var(--r);font-weight:600':''}">${dl}</td>
                <td>${t.escalation_level>0?'L'+t.escalation_level:'—'}</td>
            </tr>`;
        }).join('');
    } catch(e){$('tmBody').innerHTML='<tr><td colspan="9" style="color:var(--r)">Ошибка загрузки</td></tr>'}
}

async function changeTaskStatus(taskId, newStatus) {
    try {
        const r=await fetch(API_BASE+`/api/task-manager/tasks/${taskId}/status`,{
            method:'PATCH',headers:{'Content-Type':'application/json'},
            body:JSON.stringify({status:newStatus}),credentials:'include'
        });
        if(r.ok){
            await showTaskDetail(taskId);
        } else {
            const d=await r.json();
            alert(d.detail||d.message||'Ошибка');
        }
    } catch(e){alert('Ошибка сервера')}
}

function _showCloseTaskForm(taskId, equipCode) {
    const eqCode=decodeURIComponent(equipCode||'');
    const el=$('closeTaskForm');
    if(!el) return;
    el.innerHTML=`<div style="margin-top:12px;padding:12px;background:var(--bg4);border-radius:var(--rs);border:1px solid var(--bd)">
        <div style="font-size:13px;font-weight:600;margin-bottom:10px">Завершение задачи #${taskId}</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px">
            <div>
                <label style="font-size:10px;color:var(--t2)">Код интервала ТО (если применимо)</label>
                <input type="text" id="ctfCode" placeholder="ТО-500, ТО-1000..." value="" style="width:100%;padding:6px 8px;border:1px solid var(--bd);border-radius:var(--rs);background:var(--bg3);color:var(--t);font-size:12px;font-family:var(--u);margin-top:2px">
            </div>
            <div>
                <label style="font-size:10px;color:var(--t2)">Выполнил</label>
                <input type="text" id="ctfPerf" placeholder="ФИО исполнителя" value="" style="width:100%;padding:6px 8px;border:1px solid var(--bd);border-radius:var(--rs);background:var(--bg3);color:var(--t);font-size:12px;font-family:var(--u);margin-top:2px">
            </div>
            <div style="grid-column:span 2">
                <label style="font-size:10px;color:var(--t2)">Комментарий</label>
                <textarea id="ctfNotes" rows="2" placeholder="Что было сделано..." style="width:100%;padding:6px 8px;border:1px solid var(--bd);border-radius:var(--rs);background:var(--bg3);color:var(--t);font-size:12px;font-family:var(--u);margin-top:2px;resize:vertical"></textarea>
            </div>
        </div>
        <div style="display:flex;gap:8px;margin-top:10px">
            <button class="sb-btn primary" onclick="_submitCloseTask(${taskId})" style="padding:6px 14px">✅ Завершить и записать ТО</button>
            <button class="sb-btn" onclick="$('closeTaskForm').innerHTML=''" style="padding:6px 14px">Отмена</button>
        </div>
        <div id="ctfResult" style="font-size:12px;margin-top:6px"></div>
    </div>`;
}

async function _submitCloseTask(taskId) {
    const body={};
    const code=$('ctfCode')?.value?.trim();if(code) body.interval_code=code;
    const perf=$('ctfPerf')?.value?.trim();if(perf) body.performed_by=perf;
    const notes=$('ctfNotes')?.value?.trim();if(notes) body.notes=notes;
    $('ctfResult').innerHTML='<span style="color:var(--y)">Обработка...</span>';
    try {
        const r=await fetch(API_BASE+`/api/task-manager/tasks/${taskId}/close`,{
            method:'POST',headers:{'Content-Type':'application/json'},
            body:JSON.stringify(body),credentials:'include'
        });
        const d=await r.json();
        if(r.ok){
            $('ctfResult').innerHTML=`<span style="color:var(--g)">Задача завершена!${d.maintenance_log_id?' ТО записано (log #'+d.maintenance_log_id+')':''} ${d.quality_status?'Качество: '+d.quality_status:''}</span>`;
            setTimeout(()=>showTaskDetail(taskId),1500);
        } else {
            $('ctfResult').innerHTML=`<span style="color:var(--r)">${d.detail||'Ошибка'}</span>`;
        }
    } catch(e){$('ctfResult').innerHTML='<span style="color:var(--r)">Сервер недоступен</span>'}
}

// ===================== TASK DETAIL =====================
async function showTaskDetail(id) {
    try {
        const r=await fetch(API_BASE+`/api/task-manager/tasks/${id}`,{credentials:'include'});
        if(!r.ok) return;
        const t=await r.json();
        const mn=$('mainArea');
        const statusMap={created:'Создана',in_progress:'В работе',escalated:'⚠ Эскалация',completed:'✅ Завершена',closed:'Закрыта',pending_review:'На проверке'};
        const priMap=['🔴 Критический','🟡 Высокий','⚪ Обычный'];

        let html=`<div style="padding:4px"><div class="tm-hd"><h2>Задача #${t.id}</h2><button class="sb-btn" onclick="renderTaskManager()">← Назад</button></div>`;
        html+=`<div class="tm-detail"><h3>${t.title||'Без названия'}</h3>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:12px;margin-top:10px">
            <div><b>Тип:</b> ${t.task_type}</div><div><b>Статус:</b> <span class="tm-badge ${t.status}">${statusMap[t.status]||t.status}</span></div>
            <div><b>Приоритет:</b> ${priMap[t.priority]||'—'}</div><div><b>Объект:</b> ${t.equipment_code||'—'}</div>
            <div><b>Исполнитель:</b> ${t.responsible_name||'—'}</div><div><b>Дедлайн:</b> ${t.deadline?new Date(t.deadline).toLocaleString('ru'):'—'}</div>
            <div><b>Эскалация:</b> L${t.escalation_level||0}</div><div><b>Б24:</b> ${t.bitrix_task_id?'#'+t.bitrix_task_id:'—'}</div>
            </div>
            ${t.description?`<div style="margin-top:10px;font-size:12px;color:var(--t2)">${t.description}</div>`:''}
            <div style="display:flex;gap:6px;margin-top:14px;flex-wrap:wrap" id="taskActions">
                ${!['completed','closed'].includes(t.status)?`
                    ${t.status==='created'?'<button class="sb-btn" onclick="changeTaskStatus('+t.id+',\'in_progress\')" style="padding:6px 14px">▶ В работу</button>':''}
                    ${['in_progress','escalated'].includes(t.status)?'<button class="sb-btn primary" onclick="_showCloseTaskForm('+t.id+',\''+encodeURIComponent(t.equipment_code||'')+'\')" style="padding:6px 14px">✅ Завершить</button>':''}
                    <button class="sb-btn" onclick="changeTaskStatus(${t.id},'closed')" style="padding:6px 14px;color:var(--t3)">✕ Закрыть без ТО</button>
                `:'<span style="font-size:12px;color:var(--g)">Задача завершена</span>'}
            </div>
            <div id="closeTaskForm"></div>
        </div>`;

        // Communications
        const cr=await fetch(API_BASE+`/api/task-manager/tasks/${id}/communications`,{credentials:'include'});
        if(cr.ok){
            const comms=await cr.json();
            if(comms.length){
                html+=`<div class="tm-detail"><h3>💬 Переписка (${comms.length})</h3>`;
                comms.forEach(c=>{
                    const dt=new Date(c.created_at).toLocaleString('ru',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'});
                    html+=`<div class="tm-comm ${c.direction}"><div class="tm-comm-meta">${c.sender} → ${c.recipient_name||'—'} | ${dt} | ${c.message_type}</div><div class="tm-comm-text">${c.message_text}</div></div>`;
                });
                html+=`</div>`;
            }
        }

        // Quality
        const qr=await fetch(API_BASE+`/api/task-manager/tasks/${id}/quality`,{credentials:'include'});
        if(qr.ok){
            const checks=await qr.json();
            if(checks.length){
                html+=`<div class="tm-detail"><h3>✅ Проверки качества</h3>`;
                checks.forEach(q=>{
                    html+=`<div style="font-size:12px;padding:4px 0"><span class="tm-badge ${q.passed?'completed':'escalated'}">${q.check_type}</span> ${q.passed?'Пройдено':'Не пройдено'} ${q.details?JSON.stringify(q.details):''}</div>`;
                });
                html+=`</div>`;
            }
        }

        html+=`</div>`;
        mn.innerHTML=html;
    } catch(e){console.error('Task detail error:',e)}
}

// ===================== B24 TASK FROM TO =====================
function createBxTaskFromTO(dev){var tpl=getTpl();var idx=+($('toSel')?.value||0);var iv=tpl.intervals[idx];if(!iv){ae('⚠ Выберите интервал ТО');return}createBxTask(dev,iv.name,iv.tasks)}

export {
  renderTaskManager, showTaskTab, showCreateTaskForm, submitCreateTask,
  changeTaskStatus, loadTasks, _showCloseTaskForm, _submitCloseTask,
  renderCardsTab, showUploadCardForm, submitUploadCard,
  _mntShowCardDetail, _mntShowEquipDetail, _mntShowRecordForm,
  _mntSubmitRecord, _mntShowHoursForm, _mntSubmitHours, _mntResetEpoch,
  _mntToggleSort, _mntEqToggleSort, _mntOpenCardEditor, _mntLoadCards,
  _mntRenderEquipmentView,
  _mceConfirm, _mceSaveCardInfo, _mceAddIV, _mceSaveIV,
  _mceAddWI, _mceSaveWI, _mceEditWI, _mceDelWI,
  _mceAddSP, _mceSaveSP, _mceEditSP, _mceDelSP,
  _mceLinkEquip, _mceReparse, _mceDelIV, _mceEditIV,
  showCreateRuleForm, submitCreateRule, renderRulesTab, toggleRule,
  updateTriggerConfig,
  getTpl, saveTpl, getTOData, saveTOData, getNextTO,
  openTO, openTOTemplates, editTemplates, saveTemplates,
  addTOInterval, delTOInterval, completeTO, openChecklist,
  createBxTaskFromTO,
  initSearchableDropdown,
  showTaskDetail, loadTaskStats, renderTasksTab, loadRules,
  getEmployees, loadEmployeeDropdowns,
};
