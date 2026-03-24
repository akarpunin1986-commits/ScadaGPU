// settings.js — extracted from legacy.js
// Config, settings, commands, AI, Bitrix24, SPR control, power limit, admin panels

import { G, sv, ae } from './state.js';
import { $, esc, showM, hideM } from './utils.js';
import { api, API_BASE, getDeviceIdForSlot, getGenSlots } from './api.js';
import { AI_PROVIDERS } from './constants.js';

// ===================== MODULE-LEVEL STATE =====================
let _plSlot = null, _plDeviceId = null, _plDeviceType = null;
let b24PollTimer = null;
let b24Filter = { status: null, source_type: null };

// ===================== SETTINGS MODAL =====================
function _genSettingsPanel(sl, s) {
const g = s[sl] || {};
const n = sl.slice(1);
const td = getTOData(G.cur, sl);
return `<div class="cfs"><div class="cft"><span class="dot dot-g"></span>Генератор ${n} — HGM9520N<span class="conn-test" onclick="testConn('${sl}')">🔌 Тест</span></div>
<div class="fr2"><div class="fg"><label class="fl">Протокол</label><select class="fi" id="c${sl}proto" onchange="updGenProtoLabel('${sl}')"><option value="tcp"${(g.proto||'tcp')==='tcp'?' selected':''}>Modbus TCP (напрямую)</option><option value="rtu_over_tcp"${g.proto==='rtu_over_tcp'?' selected':''}>RTU через конвертер</option></select></div><div class="fg"><label class="fl">IP-адрес <span class="req">*</span></label><input class="fi" id="c${sl}i" value="${esc(g.ip||'')}" placeholder="192.168.97.${9+parseInt(n)}"></div></div>
<div class="fr2"><div class="fg"><label class="fl" id="c${sl}plbl">${g.proto==='rtu_over_tcp'?'Порт конвертера':'Порт Modbus TCP'}</label><input class="fi" id="c${sl}p" value="${g.port||(g.proto==='rtu_over_tcp'?26:502)}" type="number"></div><div class="fg"><label class="fl">Slave ID</label><input class="fi" id="c${sl}s" value="${g.slaveId||1}" type="number"></div></div>
<div class="fr2"><div class="fg"><label class="fl">Моточасы</label><input class="fi" id="c${sl}h" value="${g.runHours||0}" type="number"></div><div class="fg"></div></div>
<div class="fr2"><div class="fg"><label class="fl">Последнее ТО</label><select class="fi" id="c${sl}lt"><option value="">Не указано</option>${getTpl().intervals.map(iv=>`<option value="${iv.id}"${(td.lastTOId===iv.id)?' selected':''}>${iv.name}</option>`).join('')}</select></div><div class="fg"><label class="fl">При моточасах</label><input class="fi" id="c${sl}lth" value="${td.hoursAtLastTO||0}" type="number" placeholder="0"></div></div>
<button class="bp" style="margin-top:8px;width:100%;background:var(--bg4);border:1px solid var(--bd);color:var(--t2);font-size:12px;padding:8px 0" onclick="testConn('${sl}')">🔌 Проверить связь с контроллером</button><div id="${sl}test"></div></div>`;
}

function openSet(){if(!G.cur||!G.S[G.cur])return;const s=G.S[G.cur];
const gSlots = getGenSlots(G.cur);
const sprIdx = gSlots.length;
const objIdx = sprIdx + 1;
$('setTitle').textContent='⚙ '+s.name+' — Настройки';
$('setBody').innerHTML=`<div class="set-tabs">${gSlots.map((sl,i)=>`<button class="set-tab${i===0?' on':''}" onclick="setTab(this,${i})">Генератор ${sl.slice(1)}</button>`).join('')}<button class="set-tab" onclick="setTab(this,${sprIdx})">ШПР</button><button class="set-tab" onclick="setTab(this,${objIdx})">Объект</button></div>
${gSlots.map((sl,i)=>`<div class="set-panel${i===0?' on':''}" id="sp${i}">${_genSettingsPanel(sl,s)}</div>`).join('')}
<div class="set-panel" id="sp${sprIdx}"><div class="cfs"><div class="cft"><span class="dot dot-p"></span>ШПР — HGM9560 (RS-485→Ethernet)<span class="conn-test" onclick="testConn('spr')">🔌 Тест</span></div>
<div class="fr2"><div class="fg"><label class="fl">IP конвертера <span class="req">*</span></label><input class="fi" id="csi" value="${esc(s.spr?.ip||'')}" placeholder="10.11.0.2"></div><div class="fg"><label class="fl">Порт</label><input class="fi" id="csp" value="${s.spr?.port||26}" type="number"></div></div>
<div class="fr2"><div class="fg"><label class="fl">Slave ID</label><input class="fi" id="css" value="${s.spr?.slaveId||1}" type="number"></div><div class="fg"><label class="fl">Протокол</label><div style="padding:9px 12px;background:var(--bg);border:1px solid var(--bd);border-radius:var(--rs);font-size:13px;color:var(--t3)">RTU 9600/8N2</div></div></div><button class="bp" style="margin-top:8px;width:100%;background:var(--bg4);border:1px solid var(--bd);color:var(--t2);font-size:12px;padding:8px 0" onclick="testConn('spr')">🔌 Проверить связь с контроллером</button><div id="sprtest"></div></div></div>
<div class="set-panel" id="sp${objIdx}"><div class="cfs"><div class="cft"><span class="dot dot-g"></span>Общие настройки</div>
<div class="fg"><label class="fl">Название</label><input class="fi" id="csn" value="${esc(s.name)}"></div>
<div class="fg"><label class="fl">Описание</label><input class="fi" id="csd" value="${esc(s.desc||'')}"></div>
<div class="fg"><label class="fl">Интервал опроса (мс)</label><input class="fi" id="csi2" value="${s.pollInterval||2000}" type="number"></div>
<div class="fg"><label class="fl">👤 Ответственный за ТО</label><select class="fi" id="csResp" style="padding:8px 10px"></select></div></div></div>
<button class="bp" style="margin-top:4px" onclick="saveSet()">💾 Сохранить</button>`;showM('settings');populateRespSelectById('csResp',s.responsible||'')}

function setTab(btn,idx){btn.closest('.mbd').querySelectorAll('.set-tab').forEach(b=>b.classList.remove('on'));btn.closest('.mbd').querySelectorAll('.set-panel').forEach(p=>p.classList.remove('on'));btn.classList.add('on');$('sp'+idx)?.classList.add('on')}

function updGenProtoLabel(sl){const sel=$('c'+sl+'proto');const lbl=$('c'+sl+'plbl');const pi=$('c'+sl+'p');if(!sel||!lbl)return;if(sel.value==='rtu_over_tcp'){lbl.textContent='Порт конвертера';if(pi&&+pi.value===502)pi.value=26}else{lbl.textContent='Порт Modbus TCP';if(pi&&+pi.value===26)pi.value=502}}

async function saveSet(){const s=G.S[G.cur];
// Save generator settings dynamically
const gSlots=getGenSlots(G.cur);
for(const sl of gSlots){s[sl]={...s[sl],ip:$('c'+sl+'i').value.trim(),port:+$('c'+sl+'p').value||502,slaveId:+$('c'+sl+'s').value||1,proto:$('c'+sl+'proto')?.value||s[sl]?.proto||'tcp',runHours:+$('c'+sl+'h').value||0}}
s.spr={...s.spr,ip:$('csi').value.trim(),port:+$('csp').value||26,slaveId:+$('css').value||1};s.name=$('csn')?.value.trim()||s.name;s.desc=$('csd')?.value.trim()||'';s.responsible=$('csResp')?.value||s.responsible||'';s.pollInterval=+$('csi2')?.value||2000;
// Save last TO data for all generators + sync to equipment_units epoch
for(const sl of gSlots){const ltSel=$('c'+sl+'lt'),lthInp=$('c'+sl+'lth');if(ltSel){const td=getTOData(G.cur,sl);const newId=ltSel.value||null;const newH=+(lthInp?.value)||0;if(newId!==td.lastTOId||newH!==td.hoursAtLastTO){td.lastTOId=newId;td.hoursAtLastTO=newH;saveTOData(G.cur,sl,td);
// Sync epoch to equipment_units (maintenance lifecycle)
if(newH>0&&G.apiAvailable){try{
const eqList=await(await fetch(API_BASE+'/api/maintenance/equipment',{credentials:'include'})).json();
const motorNum=sl==='g1'?'Мотор 1':'Мотор 2';
const eq=eqList.find(e=>(e.equipment_name||'').includes(motorNum)&&(e.site_name||'').toUpperCase().includes(G.cur.toUpperCase().replace('mkz','МКЗ').replace('yakz','ЯКЗ').replace('ykz','ЯКЗ')));
if(eq){await fetch(API_BASE+'/api/maintenance/equipment/'+(eq.equipment_id||eq.id)+'/set-epoch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({epoch_value:newH,reason:'Последнее ТО из настроек',changed_by:'UI'}),credentials:'include'});
console.log('Epoch set for',eq.equipment_name,'=',newH,'ч')}
}catch(e){console.warn('Epoch sync error:',e)}}
}}}
sv();
// API: sync devices
if(G.apiAvailable&&G.siteApiIds[G.cur]){const siteId=G.siteApiIds[G.cur];try{
// Update site name/desc
await api.patch('/api/sites/'+siteId,{name:s.name,description:s.desc});
// Sync generator slots
for(const sl of gSlots){
const d=s[sl];if(!d?.ip)continue;
const proto=d.proto||'tcp';const nm='Генератор '+sl.slice(1);
if(d._deviceId){await api.patch('/api/devices/'+d._deviceId,{ip_address:d.ip,port:d.port,slave_id:d.slaveId||1,protocol:proto,name:nm})}
else{const created=await api.post('/api/devices',{site_id:siteId,name:nm,device_type:'generator',ip_address:d.ip,port:d.port,slave_id:d.slaveId||1,protocol:proto});
d._deviceId=created.id;G.deviceSlotIndex[created.id]={siteKey:G.cur,slot:sl}}}
// Sync SPR slot
{const d=s.spr;if(d?.ip){const proto='rtu_over_tcp';
if(d._deviceId){await api.patch('/api/devices/'+d._deviceId,{ip_address:d.ip,port:d.port,slave_id:d.slaveId||1,protocol:proto,name:'ШПР'})}
else{const created=await api.post('/api/devices',{site_id:siteId,name:'ШПР',device_type:'ats',ip_address:d.ip,port:d.port,slave_id:d.slaveId||1,protocol:proto});
d._deviceId=created.id;G.deviceSlotIndex[created.id]={siteKey:G.cur,slot:'spr'}}}}
}catch(e){console.warn('API sync devices error:',e)}}
ae('✅ Настройки сохранены');hideM('settings');renderSB();renderDash()}

// ===================== SMART RESET =====================
async function smartReset(slot,name){
if(!confirm(`Сбросить аварию на ${name}?\n\nСистема пробует несколько методов сброса и проверяет результат.`))return;
const devId=getDeviceIdForSlot(slot);if(!devId){ae('❌ Устройство не найдено');return}
const cs=$('cs-'+name.replace(/[\s\/]/g,''));
if(cs){cs.textContent='⏳ Сброс...';cs.classList.add('sh')}
try{
const resp=await api.post(`/api/commands/reset/${devId}`,{});
if(resp.cleared){
ae(`✅ Авария на ${name} сброшена!`);
if(cs){cs.textContent='✅ Сброшено';setTimeout(()=>cs.classList.remove('sh'),3000)}
}else{
ae(`⚠ ${name}: авария НЕ сбросилась. Проверьте режим контроллера (LOCAL/REMOTE)`);
if(cs){cs.textContent='⚠ Не сброшено';cs.style.color='var(--y)';setTimeout(()=>{cs.classList.remove('sh');cs.style.color=''},5000)}
}
}catch(e){ae(`❌ Ошибка сброса: ${e.message}`);if(cs){cs.textContent='❌ Ошибка';cs.classList.add('sh');setTimeout(()=>cs.classList.remove('sh'),3000)}}
}

// ===================== COMMAND SYSTEM =====================
function cmdConfirm(target,cmd,label,info){$('cmdT').textContent='Подтверждение: '+label;$('cmdTxt').innerHTML=`Команда <b>${label}</b> → <b>${target}</b>`;$('cmdInfo').textContent=info||'Modbus FC05';$('cmdOk').onclick=async()=>{hideM('cmd');
const cs=$('cs-'+target.replace(/[\s\/]/g,''));
// Resolve device_id and command params
let deviceId=null,fc=5,addr=0,val=1;
const _gm=target.match(/Генератор\s+(\d+)/);
if(_gm)deviceId=getDeviceIdForSlot('g'+_gm[1]);
else if(target==='ШПР')deviceId=getDeviceIdForSlot('spr');
// Parse FC and address from info string
const fcMatch=info?.match(/FC0?(\d)/);if(fcMatch)fc=parseInt(fcMatch[1]);
const addrMatch=info?.match(/0x([0-9A-Fa-f]+)/);if(addrMatch)addr=parseInt(addrMatch[1],16);
const regMatch=info?.match(/reg\s+(\d+)/);if(regMatch)addr=parseInt(regMatch[1]);
// For FC06, parse value from cmd or info
if(fc===6){
const valMatch=info?.match(/←\s*(\d+)/);if(valMatch)val=parseInt(valMatch[1]);
else if(cmd.includes('LoadMode=')){val=parseInt(cmd.split('=')[1])||0}
else if(cmd==='SetPQ'){
// Send P and Q as separate commands
const pv=+($('sprPslider')?.value||500),qv=+($('sprQslider')?.value||500);
if(G.apiAvailable&&deviceId){try{
await api.post('/api/commands',{device_id:deviceId,function_code:6,address:4352,value:pv});
await api.post('/api/commands',{device_id:deviceId,function_code:6,address:4354,value:qv});
if(cs){cs.textContent='✅ P/Q записаны';cs.classList.add('sh');setTimeout(()=>cs.classList.remove('sh'),3000)}
ae(`⚡ FC06 P=${pv/10}% Q=${qv/10}% → ${target}`);return}catch(e){ae(`❌ Ошибка: ${e.message}`);if(cs){cs.textContent='❌ Ошибка';cs.classList.add('sh');setTimeout(()=>cs.classList.remove('sh'),3000)}return}}}
}
if(cmd.startsWith('Preset:')){
// Preset: send 3 commands (LoadMode, P, Q)
const P={island:{m:0,p:1000,q:500},genres:{m:0,p:800,q:500},peak:{m:1,p:300,q:500},parallel:{m:2,p:500,q:500},export:{m:0,p:800,q:300},mains:{m:1,p:0,q:0},test:{m:0,p:200,q:200}};
const pn=cmd.split(':')[1],pr=P[pn];
if(G.apiAvailable&&deviceId&&pr){try{
await api.post('/api/commands',{device_id:deviceId,function_code:6,address:4351,value:pr.m});
await api.post('/api/commands',{device_id:deviceId,function_code:6,address:4352,value:pr.p});
await api.post('/api/commands',{device_id:deviceId,function_code:6,address:4354,value:pr.q});
if(cs){cs.textContent='✅ Пресет применён';cs.classList.add('sh');setTimeout(()=>cs.classList.remove('sh'),3000)}
ae(`⚡ Пресет ${pn} → ${target}`);return}catch(e){ae(`❌ Ошибка: ${e.message}`)}}
}
// Standard FC05 or FC06 command
if(G.apiAvailable&&deviceId){try{
const resp=await api.post('/api/commands',{device_id:deviceId,function_code:fc,address:addr,value:fc===5?1:val});
ae(`⚡ ${cmd} → ${target}`);if(cs){cs.textContent='✅ '+label+' отправлено';cs.classList.add('sh');setTimeout(()=>cs.classList.remove('sh'),3000)}
}catch(e){ae(`❌ ${cmd} → ${target}: ${e.message}`);if(cs){cs.textContent='❌ Ошибка';cs.classList.add('sh');setTimeout(()=>cs.classList.remove('sh'),3000)}}}
else{ae(`⚡ ${cmd} → ${target}`);if(cs){cs.textContent='✅ '+label+' отправлено';cs.classList.add('sh');setTimeout(()=>cs.classList.remove('sh'),3000)}}
};showM('cmd')}

// ===================== PRESETS =====================
function applyPreset(btn,name){
const P={island:{m:0,p:1000,q:500,l:'🏝 Островной'},genres:{m:0,p:800,q:500,l:'🔋 Ген+Резерв сети'},peak:{m:1,p:300,q:500,l:'⚡ Пик-шейвинг'},parallel:{m:2,p:500,q:500,l:'🔀 Параллель'},export:{m:0,p:800,q:300,l:'📤 Экспорт'},mains:{m:1,p:0,q:0,l:'🔌 Только сеть'},test:{m:0,p:200,q:200,l:'🔧 Тест'}};
const pr=P[name];if(!pr)return;
// Apply preset to control tab UI
G.sprSelectedLoadMode=pr.m;G.sprCfgDirty=true;
applySprConfigToUI(pr.m, pr.p, pr.q);
const cp=$('currentPreset');if(cp)cp.innerHTML=`<b>${pr.l}</b> · Mode=${pr.m} P=${(pr.p/10).toFixed(1)}% Q=${(pr.q/10).toFixed(1)}%`;
document.querySelectorAll('.preset-btn').forEach(b=>b.classList.remove('active'));btn.classList.add('active');
ae(`🎛 Пресет: ${pr.l}`);
// Prompt to save to controller
if(confirm('Применить пресет «'+pr.l+'» и записать в контроллер?\n\nLoadMode='+pr.m+' P='+(pr.p/10).toFixed(1)+'% Q='+(pr.q/10).toFixed(1)+'%')){saveSprConfig()}
else{const banner=$('sprCfgBanner');if(banner)banner.innerHTML='<span style="color:var(--y)">⚠ Пресет загружен, но НЕ записан в контроллер. Нажмите «Сохранить» на вкладке Управление.</span>'}}

// ===================== ADMIN PANELS =====================
async function renderAdminComms() {
    if(!G.currentUser||G.currentUser.role!=='admin'){alert('Доступ только для администратора');return}
    G.curView='admin-comms';
    const mn=$('mainArea');
    mn.innerHTML=`<div style="padding:4px">
        <div class="tm-hd"><h2>💬 Переписка Санька</h2>
            <div class="tm-filters">
                <select id="commUserFilter" onchange="loadAdminComms()" style="padding:6px 10px;border:1px solid var(--bd);border-radius:var(--rs);background:var(--bg3);color:var(--t);font-size:12px;font-family:var(--u)"><option value="">Все сотрудники</option></select>
                <select id="commSessionFilter" onchange="loadAdminComms()" style="padding:6px 10px;border:1px solid var(--bd);border-radius:var(--rs);background:var(--bg3);color:var(--t);font-size:12px;font-family:var(--u)"><option value="">Все сессии</option></select>
                <button class="sb-btn" onclick="loadAdminComms()">🔄</button>
            </div>
        </div>
        <div id="adminCommsBody" style="font-size:12px">Загрузка...</div>
    </div>`;
    await loadAdminSessions();
    await loadAdminUserFilter();
    await loadAdminComms();
}

async function loadAdminUserFilter() {
    try {
        const r=await fetch(API_BASE+'/api/task-manager/employees',{credentials:'include'});
        if(!r.ok) return;
        const emps=await r.json();
        const sel=$('commUserFilter');
        if(sel) emps.forEach(e=>{
            if(!e.bitrix_id) return;
            const opt=document.createElement('option');
            opt.value=e.bitrix_id;
            opt.textContent=e.name+(e.position?' — '+e.position:'');
            sel.appendChild(opt);
        });
    } catch(e){}
}

async function loadAdminSessions() {
    try {
        const r=await fetch(API_BASE+'/api/dev-console/communications/sessions',{credentials:'include'});
        if(!r.ok) return;
        const sessions=await r.json();
        const sel=$('commSessionFilter');
        if(sel) sessions.forEach(s=>{
            const dt=new Date(s.last_at).toLocaleString('ru',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'});
            const opt=document.createElement('option');
            opt.value=s.session_id;
            opt.textContent=`${s.user_name||'Аноним'} — ${s.msg_count} сообщ. (${dt})${s.source==='bitrix_chat'?' 📱':''}`;
            sel.appendChild(opt);
        });
    } catch(e){}
}

async function loadAdminComms() {
    try {
        const sid=$('commSessionFilter')?.value||'';
        const uid=$('commUserFilter')?.value||'';
        let url=API_BASE+'/api/dev-console/communications?limit=100';
        if(sid) url+=`&session_id=${sid}`;
        if(uid) url+=`&user_id=${uid}`;
        const r=await fetch(url,{credentials:'include'});
        if(!r.ok){$('adminCommsBody').innerHTML='<div style="color:var(--t3)">Нет данных</div>';return}
        const msgs=await r.json();
        if(!msgs.length){$('adminCommsBody').innerHTML='<div style="color:var(--t3)">Нет сообщений</div>';return}
        $('adminCommsBody').innerHTML=msgs.map(m=>{
            const dt=new Date(m.created_at).toLocaleString('ru',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'});
            const isUser=m.role==='user';
            const src=m.source==='bitrix_chat'?' 📱Б24':' 🖥️СКАДА';
            return `<div class="tm-comm ${isUser?'incoming':'outgoing'}" style="margin-bottom:6px">
                <div class="tm-comm-meta">${isUser?'👤 '+(m.user_name||'Пользователь'):'🤖 Санёк'}${src} | ${dt} | сессия: ${(m.session_id||'').substring(0,8)}</div>
                <div class="tm-comm-text">${m.content||'—'}</div>
            </div>`;
        }).join('');
    } catch(e){$('adminCommsBody').innerHTML='<div style="color:var(--r)">Ошибка загрузки</div>'}
}

async function renderAdminDecisions() {
    if(!G.currentUser||G.currentUser.role!=='admin'){alert('Доступ только для администратора');return}
    G.curView='admin-decisions';
    const mn=$('mainArea');
    mn.innerHTML='<div style="padding:4px"><div class="tm-hd"><h2>🧠 Решения AI (Dev Console)</h2><button class="sb-btn" onclick="loadAdminDecisions()">🔄</button></div><table class="tm-table"><thead><tr><th>ID</th><th>Задача</th><th>Тип решения</th><th>Причина</th><th>Триггер</th><th>Дата</th></tr></thead><tbody id="adminDecBody"></tbody></table></div>';
    await loadAdminDecisions();
}

async function loadAdminDecisions() {
    try {
        const r=await fetch(API_BASE+'/api/dev-console/decisions?limit=50',{credentials:'include'});
        if(!r.ok) return;
        const decs=await r.json();
        $('adminDecBody').innerHTML=decs.map(d=>{
            const dt=new Date(d.created_at).toLocaleString('ru',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'});
            return `<tr><td>${d.id}</td><td>${d.task_id||'—'}</td><td><span class="tm-badge">${d.decision_type}</span></td><td style="max-width:300px;overflow:hidden;text-overflow:ellipsis">${d.reasoning||'—'}</td><td>${d.triggered_by||'—'}</td><td>${dt}</td></tr>`;
        }).join('')||'<tr><td colspan="6" style="color:var(--t3)">Нет решений</td></tr>';
    } catch(e){}
}

async function renderAdminOfflineQueue() {
    if(!G.currentUser||G.currentUser.role!=='admin'){alert('Доступ только для администратора');return}
    G.curView='admin-queue';
    const mn=$('mainArea');
    try {
        const r=await fetch(API_BASE+'/api/dev-console/offline-queue',{credentials:'include'});
        const d=r.ok?await r.json():{pending:0,processing:0,failed:0,completed:0};
        mn.innerHTML=`<div style="padding:4px"><div class="tm-hd"><h2>📡 Очередь API (Offline Mode)</h2></div>
            <div class="tm-stats">
                <div class="tm-stat"><div class="val">${d.pending||0}</div><div class="lbl">В очереди</div></div>
                <div class="tm-stat"><div class="val">${d.processing||0}</div><div class="lbl">Обработка</div></div>
                <div class="tm-stat overdue"><div class="val">${d.failed||0}</div><div class="lbl">Ошибки</div></div>
                <div class="tm-stat done"><div class="val">${d.completed||0}</div><div class="lbl">Выполнено</div></div>
            </div></div>`;
    } catch(e){mn.innerHTML='<div style="padding:20px;color:var(--r)">Ошибка</div>'}
}

function toggleAdmin(){
    const el=$('sbAdmin');if(!el)return;
    el.classList.toggle('open');
    localStorage.setItem('sbAdminOpen',el.classList.contains('open')?'1':'0');
}

// ===================== BITRIX24 INTEGRATION =====================
function getBxConfig(){try{return JSON.parse(localStorage.getItem('s5bx'))||{}}catch(e){return{}}}
function saveBxCfg(c){localStorage.setItem('s5bx',JSON.stringify(c))}
function getBxUsers(){try{return JSON.parse(localStorage.getItem('s5bx_users'))||[]}catch(e){return[]}}
function saveBxUsers(u){localStorage.setItem('s5bx_users',JSON.stringify(u))}
async function getBxWebhookUrl(){
  const cfg=getBxConfig();
  if(cfg.url)return cfg.url;
  if(G.apiAvailable){try{const s=await api.get('/api/bitrix24/status');if(s.webhook_url){cfg.url=s.webhook_url;saveBxCfg(cfg);return s.webhook_url}}catch(e){}}
  return '';
}
async function initBxModal(){
  let cfg=getBxConfig();
  if(G.apiAvailable){
    try{const r=await api.get('/api/bitrix24/config');if(r.group_id)cfg.groupId=String(r.group_id);if(r.task_title_template)cfg.taskTitle=r.task_title_template;if(r.deadline_days)cfg.deadlineDays=r.deadline_days;if(r.priority)cfg.priority=String(r.priority);if(r.auto_create!==undefined)cfg.autoCreate=r.auto_create;if(r.add_checklist!==undefined)cfg.addChecklist=r.add_checklist;if(r.auditor_id)cfg.auditor=String(r.auditor_id)}catch(e){}
    try{const s=await api.get('/api/bitrix24/status');if(s.webhook_url)cfg.url=s.webhook_url}catch(e){}
    saveBxCfg(cfg);
  }
  if($('bxUrl'))$('bxUrl').value=cfg.url||'';
  if($('bxFolderId'))$('bxFolderId').value=cfg.folderId||'';
  if($('bxGroupId'))$('bxGroupId').value=cfg.groupId||'46';
  if($('bxTaskTitle'))$('bxTaskTitle').value=cfg.taskTitle||'{TO_NAME} — {SITE_NAME} — {GEN_NAME}';
  if($('bxDeadlineDays'))$('bxDeadlineDays').value=cfg.deadlineDays||3;
  if($('bxPriority'))$('bxPriority').value=cfg.priority||'1';
  if($('bxAutoCreate'))$('bxAutoCreate').checked=cfg.autoCreate||false;
  if($('bxAddChecklist'))$('bxAddChecklist').checked=cfg.addChecklist!==false;
  if($('bxDescBBCode'))$('bxDescBBCode').checked=cfg.descBBCode!==false;
  const aud=$('bxAuditor');
  if(aud){const users=getBxUsers();aud.innerHTML='<option value="">— нет —</option>'+users.map(u=>`<option value="${u.id||u.ID}"${String(u.id||u.ID)===String(cfg.auditor)?' selected':''}>${u.name||(u.LAST_NAME||'')+' '+(u.NAME||'')}</option>`).join('')}
}
function bxTab(btn,idx){btn.closest('.mbd').querySelectorAll('.set-tab').forEach(b=>b.classList.remove('on'));btn.closest('.mbd').querySelectorAll('.set-panel').forEach(p=>p.classList.remove('on'));btn.classList.add('on');$('bxp'+idx)?.classList.add('on');if(idx===1){const ul=$('bxUserList');if(ul&&(!ul.innerHTML||ul.innerHTML.includes('Загрузите')||ul.innerHTML.includes('демо')))loadBxUsers()}}
async function saveBxConfig(){const cfg=getBxConfig();cfg.url=($('bxUrl')?.value||'').trim();cfg.folderId=$('bxFolderId')?.value||'';cfg.groupId=$('bxGroupId')?.value||'';cfg.taskTitle=$('bxTaskTitle')?.value||'{TO_NAME} — {SITE_NAME} — {GEN_NAME}';cfg.deadlineDays=+($('bxDeadlineDays')?.value)||3;cfg.priority=$('bxPriority')?.value||'1';cfg.auditor=$('bxAuditor')?.value||'';cfg.autoCreate=$('bxAutoCreate')?.checked||false;cfg.addChecklist=$('bxAddChecklist')?.checked!==false;cfg.descBBCode=$('bxDescBBCode')?.checked!==false;saveBxCfg(cfg);
if(G.apiAvailable){try{await api.put('/api/bitrix24/config',{group_id:+cfg.groupId||46,deadline_days:cfg.deadlineDays,priority:+cfg.priority,auto_create:cfg.autoCreate,add_checklist:cfg.addChecklist,auditor_id:+cfg.auditor||null,task_title_template:cfg.taskTitle})}catch(e){}}
ae('✅ Битрикс24 настройки сохранены')}
async function testBxConnection(){const el=$('bxConnResult');const url=($('bxUrl')?.value||'').trim();if(!url){el.innerHTML='<div style="padding:6px 10px;background:var(--rd);border:1px solid rgba(255,64,96,.2);border-radius:6px;font-size:11px;color:var(--r)">Укажите Webhook URL</div>';return}
el.innerHTML='<div style="padding:6px 10px;background:var(--yd);border:1px solid rgba(255,176,32,.2);border-radius:6px;font-size:11px;color:var(--y);font-family:var(--m)">⏳ Проверка подключения...</div>';
if(G.apiAvailable){try{const r=await api.post('/api/bitrix/test',{webhook_url:url});
if(r.success){el.innerHTML='<div style="padding:6px 10px;background:var(--gd);border:1px solid rgba(0,224,154,.2);border-radius:6px;font-size:11px;color:var(--g);font-family:var(--m)">✅ '+r.message+'</div>';ae('✅ Б24 подключение OK')}
else{el.innerHTML='<div style="padding:6px 10px;background:var(--rd);border:1px solid rgba(255,64,96,.2);border-radius:6px;font-size:11px;color:var(--r)">❌ '+r.message+'</div>'}
}catch(e){el.innerHTML='<div style="padding:6px 10px;background:var(--rd);border:1px solid rgba(255,64,96,.2);border-radius:6px;font-size:11px;color:var(--r)">❌ '+e.message+'</div>'}}
else{setTimeout(function(){el.innerHTML='<div style="padding:6px 10px;background:var(--bb);border:1px solid rgba(64,144,255,.2);border-radius:6px;font-size:11px;color:var(--b);font-family:var(--m)">ℹ Backend недоступен. URL: '+esc(url.substring(0,40))+'...</div>'},800)}}
async function loadBxUsers(){const el=$('bxUserList');el.innerHTML='<div style="color:var(--y);font-size:12px;text-align:center;padding:15px">⏳ Загрузка user.get...</div>';
const url=await getBxWebhookUrl();
if(G.apiAvailable&&url){try{const r=await api.post('/api/bitrix/users/sync',{webhook_url:url});
if(r.success&&r.users&&r.users.length>0){saveBxUsers(r.users);var h='';for(var i=0;i<r.users.length;i++){var u=r.users[i];h+='<div class="bk-item"><div><b style="color:var(--t)">'+esc(u.name)+'</b><br><span style="color:var(--t3);font-size:10px">'+esc(u.pos||'—')+' · '+esc(u.dept||'—')+'</span></div><span style="font-size:10px;color:var(--t4);font-family:var(--m)">ID: '+u.id+'</span></div>'}
el.innerHTML=h+'<div style="padding:6px;text-align:center;font-size:10px;color:var(--t4)">'+r.users.length+' сотрудников из Б24</div>';ae('👥 Загружено '+r.users.length+' сотрудников');return}
}catch(e){console.warn('Bitrix users error:',e)}}
el.innerHTML='<div style="padding:10px;text-align:center;font-size:11px;color:var(--r)">❌ Не удалось загрузить сотрудников. Проверьте Webhook URL на вкладке «Подключение».</div>'}
function formatSize(b){if(b<1024)return b+' Б';if(b<1048576)return(b/1024).toFixed(0)+' КБ';return(b/1048576).toFixed(1)+' МБ'}
async function scanBxFolder(){var el=$('bxFileList');var fid=$('bxFolderId')?.value;if(!fid){el.innerHTML='<div style="padding:6px;background:var(--rd);border-radius:6px;font-size:11px;color:var(--r)">Укажите ID папки</div>';return}
el.innerHTML='<div style="padding:10px;color:var(--y);font-size:12px;text-align:center">⏳ Сканирование disk.folder.getchildren...</div>';
var url=await getBxWebhookUrl();
if(G.apiAvailable&&url){try{var r=await api.post('/api/bitrix/folder/scan',{webhook_url:url,folder_id:parseInt(fid)});
if(r.success&&r.files&&r.files.length>0){var h='<div style="font-size:11px;color:var(--t3);margin-bottom:6px">Найдено файлов: '+r.files.length+'</div>';
for(var i=0;i<r.files.length;i++){var f=r.files[i];var ext=(f.name||'').split('.').pop().toLowerCase();var canParse=(ext==='pdf'||ext==='docx');
h+='<div class="bk-item"><div><b style="color:var(--t)">'+esc(f.name)+'</b><br><span style="color:var(--t3);font-size:10px">'+ext.toUpperCase()+' · '+formatSize(f.size||0)+' · '+(f.updated||'')+'</span></div>';
if(canParse){h+='<button class="bk-btn" onclick="importBxFile('+f.id+',\''+esc(f.name).replace(/'/g,"\\'")+'\')" style="color:var(--p)">🤖 AI Import</button>'}
h+='</div>'}
el.innerHTML=h;ae('📂 Найдено '+r.files.length+' файлов в папке Б24')}
else if(r.success){el.innerHTML='<div style="padding:10px;font-size:11px;color:var(--t3);text-align:center">Папка пуста</div>'}
else{el.innerHTML='<div style="padding:6px;background:var(--rd);border-radius:6px;font-size:11px;color:var(--r)">❌ '+(r.message||'Ошибка')+'</div>'}}
catch(e){el.innerHTML='<div style="padding:6px;background:var(--rd);border-radius:6px;font-size:11px;color:var(--r)">❌ '+e.message+'</div>'}}
else{el.innerHTML='<div style="padding:10px;text-align:center;font-size:11px;color:var(--r)">❌ Webhook URL не настроен. Укажите URL на вкладке «Подключение».</div>'}}
async function importBxFile(fileId,filename){var el=$('bxFileList');var bxUrl=await getBxWebhookUrl();
el.innerHTML+='<div id="aiProgress" style="padding:10px;background:var(--pd);border:1px solid rgba(160,112,255,.2);border-radius:8px;margin-top:8px"><div style="font-size:12px;color:var(--p);font-weight:600;margin-bottom:6px">🤖 AI-агент обработки</div><div id="aiStep" style="font-size:11px;color:var(--t2)">⏳ Скачивание файла из Битрикс24...</div><div style="margin-top:6px;height:3px;background:rgba(160,112,255,.1);border-radius:2px;overflow:hidden"><div id="aiBar" style="width:10%;height:100%;background:var(--p);transition:width .5s"></div></div></div>';
ae('🤖 AI-импорт: '+(filename||'file#'+fileId));
var t1=setTimeout(function(){var b=$('aiBar'),s=$('aiStep');if(b)b.style.width='30%';if(s)s.textContent='⏳ Извлечение текста из документа...'},2000);
var aiCfgName=((AI_PROVIDERS[(getAIConfig().provider||'openai')])||{}).name||'AI';
var t2=setTimeout(function(){var b=$('aiBar'),s=$('aiStep');if(b)b.style.width='50%';if(s)s.textContent='⏳ Отправка в '+aiCfgName+' для анализа...'},5000);
var t3=setTimeout(function(){var b=$('aiBar'),s=$('aiStep');if(b)b.style.width='80%';if(s)s.textContent='⏳ Парсинг интервалов ТО и работ...'},15000);
if(G.apiAvailable&&bxUrl){try{var r=await api.post('/api/ai/parse',{webhook_url:bxUrl,file_id:fileId,filename:filename||''});
clearTimeout(t1);clearTimeout(t2);clearTimeout(t3);
var bar=$('aiBar');if(bar)bar.style.width='100%';
if(r.success&&r.intervals&&r.intervals.length>0){window._aiParsedResult=r;
var prog=$('aiProgress');if(prog)prog.remove();
var h='<div id="aiResult" style="padding:10px;background:var(--gd);border:1px solid rgba(0,224,154,.2);border-radius:8px;margin-top:8px">';
h+='<div style="font-size:12px;color:var(--g);font-weight:600;margin-bottom:6px">✅ AI-агент завершил анализ</div>';
h+='<div style="font-size:11px;color:var(--t2);margin-bottom:8px">'+esc(r.template_name)+' — '+r.intervals.length+' интервалов</div>';
for(var i=0;i<r.intervals.length;i++){var iv=r.intervals[i];h+='<div style="padding:5px 8px;background:var(--ov);border:1px solid var(--bd);border-radius:4px;margin-bottom:3px"><div style="display:flex;justify-content:space-between"><b style="font-size:11px">'+esc(iv.name)+'</b><span style="font-size:10px;color:var(--t3);font-family:var(--m)">'+iv.hours+'ч · '+iv.tasks.length+' работ</span></div></div>'}
h+='<div style="display:flex;gap:8px;margin-top:10px"><button class="bp" style="flex:1" onclick="applyAIResult()">✅ Применить к регламенту</button><button class="bs2" style="padding:10px" onclick="var e=document.getElementById(\'aiResult\');if(e)e.remove()">✕</button></div></div>';
el.innerHTML+=h;ae('✅ AI: найдено '+r.intervals.length+' интервалов ТО')}
else{var step=$('aiStep');if(step){step.textContent='❌ '+(r.error||'Не удалось извлечь данные');step.style.color='var(--r)'}ae('❌ AI: '+(r.error||'пусто'))}}
catch(e){clearTimeout(t1);clearTimeout(t2);clearTimeout(t3);var step=$('aiStep');if(step){step.textContent='❌ Ошибка: '+e.message;step.style.color='var(--r)'}ae('❌ AI ошибка: '+e.message)}}
else{clearTimeout(t1);clearTimeout(t2);clearTimeout(t3);var step=$('aiStep');if(step){step.textContent='ℹ Backend недоступен — AI-импорт требует подключение к серверу';step.style.color='var(--b)'}}}
function applyAIResult(){var r=window._aiParsedResult;if(!r||!r.intervals){ae('⚠ Нет данных AI');return}
var tpl=getTpl();var newIvs=[];
for(var i=0;i<r.intervals.length;i++){var iv=r.intervals[i];var tasks=[];
for(var j=0;j<iv.tasks.length;j++){tasks.push({id:j+1,text:iv.tasks[j].text,c:iv.tasks[j].is_critical?1:0})}
newIvs.push({id:iv.code,name:iv.name,hours:iv.hours,tasks:tasks})}
if(confirm('Заменить текущий регламент ('+tpl.intervals.length+' интервалов) на импортированный ('+newIvs.length+' интервалов)?')){
tpl.name=r.template_name||tpl.name;tpl.intervals=newIvs;saveTpl(tpl);
ae('✅ Регламент обновлён из AI: '+newIvs.length+' интервалов');hideM('bitrix');openTOTemplates()}}
function createBxTaskFromTO(dev){var tpl=getTpl();var idx=+($('toSel')?.value||0);var iv=tpl.intervals[idx];if(!iv){ae('⚠ Выберите интервал ТО');return}createBxTask(dev,iv.name,iv.tasks)}
function createBxTask(dev,toName,tasks){var cfg=getBxConfig();var s=G.S[G.cur];if(!s)return;var users=getBxUsers();var respId=s.responsible||'';var respName='Не назначен';for(var i=0;i<users.length;i++){if(users[i].id===respId)respName=users[i].name}
var genName=dev==='g1'?'Генератор 1':'Генератор 2';var title=cfg.taskTitle||'{TO_NAME} — {SITE_NAME} — {GEN_NAME}';title=title.replace('{TO_NAME}',toName).replace('{SITE_NAME}',s.name).replace('{GEN_NAME}',genName).replace('{HOURS}',s[dev]?.runHours||0).replace('{RESPONSIBLE}',respName);
var dl=new Date();dl.setDate(dl.getDate()+(+cfg.deadlineDays||3));var dlStr=dl.toISOString().replace('Z','+03:00');
var desc='[B]Объект:[/B] '+s.name+'\n[B]Генератор:[/B] '+genName+'\n[B]Моточасы:[/B] '+(s[dev]?.runHours||0)+'\n[B]Ответственный:[/B] '+respName+'\n\n[B]Работы ТО:[/B]\n';
for(var ti=0;ti<tasks.length;ti++){desc+=(ti+1)+'. '+tasks[ti].text+(tasks[ti].c?' [COLOR=red][!] ОБЯЗАТЕЛЬНО[/COLOR]':'')+'\n'}
var auditors=cfg.auditor?'['+cfg.auditor+']':'[]';
var payload=JSON.stringify({fields:{TITLE:title,DESCRIPTION:desc,DESCRIPTION_IN_BBCODE:"Y",RESPONSIBLE_ID:+respId||null,GROUP_ID:cfg.groupId?+cfg.groupId:null,DEADLINE:dlStr,PRIORITY:+(cfg.priority||1),AUDITORS:cfg.auditor?[+cfg.auditor]:[],ALLOW_CHANGE_DEADLINE:"N"}},null,2);
var chkPayload='// Для каждой работы:\ntask.checklistitem.add\n[TASK_ID, {"TITLE": "текст работы"}]';
$('toBody').innerHTML+='<div style="padding:10px;background:var(--gd);border:1px solid rgba(0,224,154,.2);border-radius:8px;margin-top:10px"><div style="font-size:12px;color:var(--g);font-weight:600;margin-bottom:8px">📋 Задача для Битрикс24</div><div style="font-size:11px;color:var(--t2);line-height:1.5"><b>TITLE:</b> '+esc(title)+'<br><b>RESPONSIBLE_ID:</b> '+respId+' ('+esc(respName)+')<br><b>GROUP_ID:</b> '+(cfg.groupId||'—')+'<br><b>DEADLINE:</b> '+dlStr+'<br><b>PRIORITY:</b> '+(cfg.priority||1)+'<br><b>AUDITORS:</b> '+auditors+'<br><b>Чеклист:</b> '+tasks.length+' пунктов'+(cfg.addChecklist!==false?' (task.checklistitem.add)':' (отключён)')+'</div><details style="margin-top:8px"><summary style="cursor:pointer;font-size:10px;color:var(--t3)">Показать JSON payload</summary><pre style="font-size:9px;color:var(--t3);background:var(--bg);padding:8px;border-radius:4px;margin-top:4px;overflow-x:auto;white-space:pre-wrap">POST {webhook}/tasks.task.add\n'+esc(payload)+'</pre></details><div style="margin-top:8px;font-size:9px;color:var(--t4)">Требуется backend для отправки. URL: '+esc((cfg.url||'https://...').substring(0,35))+'...</div></div>';ae('📋 Б24 задача: '+title)}

// ===================== AI PROVIDER CONFIG =====================
function getAIConfig(){try{return JSON.parse(localStorage.getItem('s5ai'))||{}}catch(e){return{}}}
function saveAICfg(c){localStorage.setItem('s5ai',JSON.stringify(c))}
async function initAIModal(){
var cfg=getAIConfig();G._aiDbData=null;
if(G.apiAvailable){try{G._aiDbData=await api.get('/api/ai/providers')}catch(e){console.warn('AI providers fetch:',e)}}
var cards=$('aiProviderCards');if(!cards)return;var h='';
for(var k in AI_PROVIDERS){var p=AI_PROVIDERS[k];
var isActive=G._aiDbData?(G._aiDbData.active_provider===k):(cfg.provider===k);
var isCfg=false;
if(G._aiDbData){var dp=G._aiDbData.providers.find(function(x){return x.provider===k});isCfg=dp?dp.is_configured:false}
else{isCfg=!!(cfg.keys&&cfg.keys[k])}
h+='<div onclick="selectAIProvider(\''+k+'\')" style="padding:10px;border:2px solid '+(isActive?p.color:isCfg?'var(--g)':'var(--bd)')+';border-radius:var(--rad);cursor:pointer;background:'+(isActive?p.color+'15':'var(--ov)')+';transition:all .2s;text-align:center;position:relative" id="aip_'+k+'">';
h+='<div style="font-size:22px;margin-bottom:4px">'+p.icon+'</div>';
h+='<div style="font-size:13px;font-weight:600;color:'+(isActive?p.color:'var(--t)')+'">'+p.name+'</div>';
h+='<div style="font-size:9px;margin-top:2px;color:'+(isCfg?'var(--g)':'var(--t4)')+'">'+
(isCfg?'● Настроен':'○ Нет ключа')+'</div>';
if(isActive)h+='<div style="font-size:8px;color:'+p.color+';font-weight:700;margin-top:2px">★ АКТИВНЫЙ</div>';
h+='</div>'}
cards.innerHTML=h;
var showPid=G._aiDbData?G._aiDbData.active_provider:cfg.provider;
if(showPid){showAIKeySection(showPid)}else{$('aiKeySection').style.display='none'}
updateAIStatus()}
function selectAIProvider(pid){
for(var k in AI_PROVIDERS){var el=$('aip_'+k);if(!el)continue;var p=AI_PROVIDERS[k];
var isActive=G._aiDbData?(G._aiDbData.active_provider===k):false;
var isCfg=false;if(G._aiDbData){var dp=G._aiDbData.providers.find(function(x){return x.provider===k});isCfg=dp?dp.is_configured:false}
var editing=k===pid;
el.style.borderColor=editing?p.color:isActive?p.color:isCfg?'var(--g)':'var(--bd)';
el.style.background=editing?p.color+'15':'var(--ov)'}
showAIKeySection(pid)}
function showAIKeySection(pid){var p=AI_PROVIDERS[pid];if(!p)return;
G._aiEditPid=pid;var cfg=getAIConfig();
$('aiKeySection').style.display='block';
$('aiKeyLabel').textContent=p.name+' API Key';$('aiKeyLabel').style.color=p.color;
$('aiKeyInput').placeholder=p.keyPlaceholder;$('aiKeyInput').type='password';
// Load key from localStorage (DB never returns full key)
$('aiKeyInput').value=cfg.keys?.[pid]||'';
var sel=$('aiModelSelect');sel.innerHTML='';
var savedModel=null;
if(G._aiDbData){var dp=G._aiDbData.providers.find(function(x){return x.provider===pid});if(dp&&dp.model)savedModel=dp.model}
if(!savedModel)savedModel=cfg.models?.[pid];
for(var i=0;i<p.models.length;i++){var o=document.createElement('option');o.value=p.models[i];o.textContent=p.models[i];sel.appendChild(o)}
if(savedModel)sel.value=savedModel;
$('aiTestResult').innerHTML='';
// Update activate button
var abtn=$('aiActivateBtn');if(abtn){
var isActive=G._aiDbData?(G._aiDbData.active_provider===pid):cfg.provider===pid;
abtn.textContent=isActive?'★ Активный':'☆ Активировать';
abtn.style.background=isActive?'var(--gd)':'';abtn.style.color=isActive?'var(--g)':'';
abtn.style.borderColor=isActive?'rgba(0,224,154,.3)':'';
abtn.disabled=isActive}}
function toggleAIKeyVis(){var inp=$('aiKeyInput');inp.type=inp.type==='password'?'text':'password'}
async function saveAIConfig(){var pid=G._aiEditPid;if(!pid){ae('⚠ Выберите провайдера');return}
var key=$('aiKeyInput').value.trim();var model=$('aiModelSelect').value;
if(!key){ae('⚠ Введите API ключ');return}
// Save to localStorage
var cfg=getAIConfig();if(!cfg.keys)cfg.keys={};if(!cfg.models)cfg.models={};
cfg.keys[pid]=key;cfg.models[pid]=model;saveAICfg(cfg);
// Save to DB via backend
if(G.apiAvailable){try{var r=await api.post('/api/ai/provider/save',{provider:pid,api_key:key,model:model});
if(r.success){ae('💾 '+AI_PROVIDERS[pid].name+' сохранён в БД')}
else{ae('⚠ '+r.message)}}catch(e){ae('⚠ '+e.message);console.warn('AI save error:',e)}}
else{ae('✅ '+AI_PROVIDERS[pid].name+' сохранён (локально)')}
await initAIModal()}
async function activateAIProvider(){var pid=G._aiEditPid;if(!pid)return;
if(!G.apiAvailable){ae('⚠ Backend недоступен');return}
try{var r=await api.post('/api/ai/provider/activate',{provider:pid});
if(r.success){ae('★ '+AI_PROVIDERS[pid].name+' активирован');
var cfg=getAIConfig();cfg.provider=pid;saveAICfg(cfg);await initAIModal()}
else{ae('⚠ '+r.message)}}catch(e){ae('⚠ '+e.message)}}
async function testAIProvider(){var pid=G._aiEditPid;if(!pid)return;
var key=$('aiKeyInput').value.trim();var model=$('aiModelSelect').value;
if(!key){$('aiTestResult').innerHTML='<div style="padding:6px 10px;background:var(--rd);border:1px solid rgba(255,64,96,.2);border-radius:6px;font-size:11px;color:var(--r)">Введите API ключ</div>';return}
var el=$('aiTestResult');el.innerHTML='<div style="padding:6px 10px;background:var(--yd);border:1px solid rgba(255,176,32,.2);border-radius:6px;font-size:11px;color:var(--y);font-family:var(--m)">⏳ Проверка '+AI_PROVIDERS[pid].name+'...</div>';
if(G.apiAvailable){try{var r=await api.post('/api/ai/test',{provider:pid,api_key:key,model:model});
if(r.success){el.innerHTML='<div style="padding:6px 10px;background:var(--gd);border:1px solid rgba(0,224,154,.2);border-radius:6px;font-size:11px;color:var(--g);font-family:var(--m)">✅ '+r.message+'</div>';ae('✅ '+AI_PROVIDERS[pid].name+' OK')}
else{el.innerHTML='<div style="padding:6px 10px;background:var(--rd);border:1px solid rgba(255,64,96,.2);border-radius:6px;font-size:11px;color:var(--r)">❌ '+(r.error||'Ошибка подключения')+'</div>'}}
catch(e){el.innerHTML='<div style="padding:6px 10px;background:var(--rd);border:1px solid rgba(255,64,96,.2);border-radius:6px;font-size:11px;color:var(--r)">❌ '+e.message+'</div>'}}
else{setTimeout(function(){el.innerHTML='<div style="padding:6px 10px;background:var(--bb);border:1px solid rgba(64,144,255,.2);border-radius:6px;font-size:11px;color:var(--b);font-family:var(--m)">ℹ Backend недоступен — тест требует подключение к серверу</div>'},800)}}
function updateAIStatus(){var el=$('aiStatus');if(!el)return;
if(G._aiDbData){
var cfgCount=G._aiDbData.providers.filter(function(p){return p.is_configured}).length;
var ap=G._aiDbData.active_provider;var apInfo=ap?AI_PROVIDERS[ap]:null;
el.innerHTML='<b>Провайдеры:</b> '+cfgCount+'/4 настроено'+
(apInfo?' · <b>Активный:</b> '+apInfo.icon+' <span style="color:'+apInfo.color+';font-weight:600">'+apInfo.name+'</span>':
' · <span style="color:var(--y)">⚠ активный не выбран</span>');
// Show configured providers list
var cfgList=G._aiDbData.providers.filter(function(p){return p.is_configured});
if(cfgList.length>0){var det='';cfgList.forEach(function(dp){var pi=AI_PROVIDERS[dp.provider];
det+='<br>'+pi.icon+' '+pi.name+': <span style="font-family:var(--m);font-size:9px">'+esc(dp.model)+'</span>'+(dp.is_active?' <span style="color:var(--g)">★</span>':'')});
el.innerHTML+=det}}
else{var cfg=getAIConfig();
if(!cfg.provider){el.innerHTML='<b>Статус:</b> провайдер не выбран';return}
var p=AI_PROVIDERS[cfg.provider];var hasKey=cfg.keys?.[cfg.provider];var model=cfg.models?.[cfg.provider]||p.models[0];
el.innerHTML='<b>Статус:</b> '+p.icon+' <span style="color:'+p.color+';font-weight:600">'+p.name+'</span>'+(hasKey?' · <span style="color:var(--g)">🔑 ключ сохранён</span>':' · <span style="color:var(--y)">⚠ нет ключа</span>')+'<br><b>Модель:</b> <span style="font-family:var(--m)">'+model+'</span>'}}

// ===================== SPR CONTROL =====================
function getSprBackups(){try{return JSON.parse(localStorage.getItem('s5_spr_backups_'+(G.cur||'')))||[]}catch(e){return[]}}
function saveSprBackups(list){localStorage.setItem('s5_spr_backups_'+(G.cur||''),JSON.stringify(list))}

// Called when "Управление" tab is opened
async function onSprControlTabOpen(){
    if(G.sprCfgReading)return;
    await readSprConfig();
}

// Read current config from controller via API
async function readSprConfig(){
    const banner=$('sprCfgBanner'),status=$('sprConfigStatus');
    const devId=getDeviceIdForSlot('spr');
    if(!devId||!G.apiAvailable){
        if(banner)banner.innerHTML='<span style="color:var(--y)">⚠ ШПР не подключён к API</span>';
        return;
    }
    G.sprCfgReading=true;
    if(banner)banner.innerHTML='<span style="color:var(--y)">⏳ Считывание конфигурации с контроллера (ожидание опроса до 40с)...</span>';
    if(status)status.innerHTML='';
    try{
        const ac=new AbortController();
        const tid=setTimeout(()=>ac.abort(),40000);
        let cfg;
        try{
            const r=await fetch(API_BASE+'/api/commands/spr-config/'+devId,{signal:ac.signal});
            clearTimeout(tid);
            if(!r.ok)throw new Error('HTTP '+r.status);
            cfg=await r.json();
        }catch(fe){
            clearTimeout(tid);
            if(fe.name==='AbortError')throw new Error('Таймаут 40с — контроллер не ответил (идёт опрос)');
            throw fe;
        }
        if(!cfg.success)throw new Error(cfg.message);
        G.sprCurrentConfig={loadMode:cfg.load_mode,pRaw:cfg.p_raw,qRaw:cfg.q_raw,readAt:Date.now()};
        G.sprSelectedLoadMode=cfg.load_mode;
        G.sprCfgDirty=false;
        // Populate UI from real controller values
        applySprConfigToUI(cfg.load_mode, cfg.p_raw, cfg.q_raw);
        if(banner)banner.innerHTML='<span style="color:var(--g)">✓ Конфигурация считана с контроллера</span>'+
            '<span style="color:var(--t4);font-size:10px;margin-left:8px">'+new Date().toLocaleTimeString('ru-RU')+'</span>';
        ae('📖 Конфиг ШПР считан: Mode='+cfg.load_mode+' P='+(cfg.p_raw/10).toFixed(1)+'% Q='+(cfg.q_raw/10).toFixed(1)+'%');
    }catch(e){
        console.error('SPR config read error:',e);
        if(banner)banner.innerHTML='<span style="color:var(--r)">❌ Ошибка чтения: '+(e.message||e)+'</span>';
    }finally{G.sprCfgReading=false}
}

function applySprConfigToUI(loadMode, pRaw, qRaw){
    // LoadMode buttons
    highlightLoadMode(loadMode);
    // P/Q sliders
    const ps=$('sprPslider'),qs=$('sprQslider');
    if(ps){ps.value=pRaw;$('sprPval').textContent=(pRaw/10).toFixed(1)+'%'}
    if(qs){qs.value=qRaw;$('sprQval').textContent=(qRaw/10).toFixed(1)+'%'}
    // Current label
    const lbl=$('sprLmCurrent');
    if(lbl)lbl.textContent='(текущий: '+(loadMode===0?'Генератор':loadMode===1?'Сеть':loadMode===2?'Приём нагрузки':'?')+')';
}

function highlightLoadMode(mode){
    const colors=['var(--g)','var(--b)','var(--p)'];
    const bgs=['var(--gd)','var(--bb)','var(--pd)'];
    ['sprLm0','sprLm1','sprLm2'].forEach((id,i)=>{
        const btn=$(id);if(!btn)return;
        if(i===mode){btn.style.background=bgs[i]||'var(--gd)';btn.style.color=colors[i]||'var(--g)';btn.style.borderColor=colors[i]||'var(--g)';btn.style.fontWeight='600'}
        else{btn.style.background='';btn.style.color='';btn.style.borderColor='';btn.style.fontWeight=''}
    });
}

function setSprLoadMode(mode){
    G.sprSelectedLoadMode=mode;
    G.sprCfgDirty=true;
    highlightLoadMode(mode);
}

// Update control tab buttons to reflect current controller mode (called from applySprDetailed)
function updateQuickButtons(cardId, mx){
    if(!mx)return;
    const card=$(cardId);if(!card)return;
    const isOffline=mx.online===false;
    const isRunning=mx.gen_status===9||mx.genset_status===9;
    const qbs=card.querySelectorAll('.qb,.cb2.q-start,.cb2.q-stop,.cb2.q-auto,.cb2.q-manual');
    let hasOn=false;
    qbs.forEach(b=>{
        b.classList.remove('on','dim');
        if(isOffline){b.disabled=true;b.style.opacity='.3';b.style.pointerEvents='none';return}
        b.disabled=false;b.style.opacity='';b.style.pointerEvents='';
        if(b.classList.contains('q-start')&&isRunning){b.classList.add('on');hasOn=true}
        else if(b.classList.contains('q-auto')&&mx.mode_auto){b.classList.add('on');hasOn=true}
        else if(b.classList.contains('q-manual')&&mx.mode_manual){b.classList.add('on');hasOn=true}
        else if(b.classList.contains('q-stop')&&mx.mode_stop){b.classList.add('on');hasOn=true}
    });
    if(hasOn)qbs.forEach(b=>{if(!b.classList.contains('on')&&b.classList.contains('cb2'))b.classList.add('dim')});
}
function updateSprControlMode(mx){
    if(!mx)return;
    const isOffline=mx.online===false;
    // --- Quick buttons (top row) ---
    updateQuickButtons('cspr',mx);
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

// Save current configuration to controller (LoadMode + P% + Q%)
async function saveSprConfig(){
    const devId=getDeviceIdForSlot('spr');
    if(!devId||!G.apiAvailable){ae('⚠ ШПР не подключён');return}
    const lm=G.sprSelectedLoadMode!=null?G.sprSelectedLoadMode:(G.sprCurrentConfig?.loadMode??0);
    const pv=+($('sprPslider')?.value||500);
    const qv=+($('sprQslider')?.value||500);
    const desc='LoadMode='+lm+' P='+(pv/10).toFixed(1)+'% Q='+(qv/10).toFixed(1)+'%';
    // Confirm before writing
    if(!confirm('Записать конфигурацию в контроллер ШПР?\n\n'+desc))return;
    const banner=$('sprCfgBanner');
    if(banner)banner.innerHTML='<span style="color:var(--y)">⏳ Запись конфигурации (FC06 × 3 + verify)...</span>';
    try{
        // Atomic write: 3 config registers → verify read-back
        const res=await api.post('/api/commands/spr-config/'+devId,{
            load_mode:lm, p_raw:pv, q_raw:qv
        });
        G.sprCfgDirty=false;
        if(res.verified){
            G.sprCurrentConfig={loadMode:lm,pRaw:pv,qRaw:qv,readAt:Date.now()};
            if(banner)banner.innerHTML='<span style="color:var(--g)">✓ Конфигурация записана и верифицирована</span>'+
                '<span style="color:var(--t4);font-size:10px;margin-left:8px">'+new Date().toLocaleTimeString('ru-RU')+'</span>';
            ae('⚡ ШПР конфиг записан (verified): '+desc);
        }else{
            // Echo OK but verify-read returned old values
            if(banner)banner.innerHTML='<span style="color:var(--y)">⚠ Команды FC06 отправлены (echo OK), но при перечитывании — старые значения.</span>'+
                '<span style="display:block;font-size:10px;color:var(--t4);margin-top:2px">Запись reg 4351-4354 требует прошивку HGM9560 ≥ V1.1 (2023). Проверьте версию прошивки контроллера.</span>';
            ae('⚠ ШПР конфиг: echo OK, verify mismatch (firmware V1.1+ needed?): '+desc);
        }
    }catch(e){
        console.error('SPR config write error:',e);
        const msg=(e.message||e).toString();
        if(banner)banner.innerHTML='<span style="color:var(--r)">❌ Ошибка записи: '+msg+'</span>';
        ae('❌ Ошибка записи конфига ШПР: '+msg);
    }
}

function backupSprConfig(){
    if(!G.sprCurrentConfig){ae('⚠ Сначала считайте конфигурацию с контроллера');readSprConfig();return}
    const backups=getSprBackups();
    const backup={id:'bk_'+Date.now(),date:new Date().toLocaleString('ru-RU'),site:G.cur,name:G.S[G.cur]?.name||'',
        loadMode:G.sprCurrentConfig.loadMode,pPercent:G.sprCurrentConfig.pRaw,qPercent:G.sprCurrentConfig.qRaw,
        readAt:G.sprCurrentConfig.readAt,note:''};
    backups.unshift(backup);if(backups.length>20)backups.pop();saveSprBackups(backups);
    ae('💾 Бэкап ШПР создан (из контроллера)');renderBackupList();
    const el=$('sprConfigStatus');if(el)el.innerHTML='<div style="padding:6px 10px;background:var(--gd);border:1px solid rgba(0,224,154,.2);border-radius:6px;font-size:11px;color:var(--g);font-family:var(--m);margin-bottom:6px">✓ Бэкап сохранён: '+backup.date+' (LoadMode='+backup.loadMode+' P='+(backup.pPercent/10).toFixed(1)+'% Q='+(backup.qPercent/10).toFixed(1)+'%)</div>';
}
function openRestoreBackup(){const backups=getSprBackups();if(!backups.length){const el=$('sprConfigStatus');if(el)el.innerHTML='<div style="padding:6px 10px;background:var(--rd);border:1px solid rgba(255,64,96,.2);border-radius:6px;font-size:11px;color:var(--r);font-family:var(--m);margin-bottom:6px">Нет сохранённых бэкапов</div>';return}
renderBackupList()}
function renderBackupList(){const backups=getSprBackups();const el=$('sprBackupList');if(!el)return;
const lmNames={0:'GenCtrl',1:'MainsCtrl',2:'LoadRec'};
el.innerHTML='<div style="font-size:10px;color:var(--t3);margin:6px 0 4px">Сохранённые бэкапы ('+backups.length+'):</div><div style="max-height:160px;overflow-y:auto">'+backups.map((b,i)=>`<div class="bk-item"><div><span style="color:var(--t)">${b.date}</span><br><span style="color:var(--t3);font-size:10px">${lmNames[b.loadMode]||'?'} P=${(b.pPercent/10).toFixed(1)}% Q=${(b.qPercent/10).toFixed(1)}%</span></div><div class="bk-acts"><button class="bk-btn" onclick="restoreBackup(${i})" title="Восстановить в контроллер">📂</button><button class="bk-btn" onclick="downloadBackup(${i})" title="Скачать JSON">⬇</button><button class="bk-btn del" onclick="deleteBackup(${i})" title="Удалить">✕</button></div></div>`).join('')+'</div>'}
function restoreBackup(idx){const backups=getSprBackups();const b=backups[idx];if(!b)return;
// Apply backup values to UI
G.sprSelectedLoadMode=b.loadMode;G.sprCfgDirty=true;
applySprConfigToUI(b.loadMode, b.pPercent, b.qPercent);
// Prompt to save to controller
const desc='LoadMode='+b.loadMode+' P='+(b.pPercent/10).toFixed(1)+'% Q='+(b.qPercent/10).toFixed(1)+'%';
if(confirm('Применить бэкап от '+b.date+' и записать в контроллер?\n\n'+desc)){saveSprConfig()}
else{ae('📂 Бэкап загружен в UI (не записан в контроллер)')}}
function downloadBackup(idx){const backups=getSprBackups();const b=backups[idx];if(!b)return;
const json=JSON.stringify(b,null,2);const blob=new Blob([json],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='spr_backup_'+b.date.replace(/[\s:.,]/g,'_')+'.json';a.click();URL.revokeObjectURL(url);ae('⬇ Бэкап скачан')}
function deleteBackup(idx){const backups=getSprBackups();backups.splice(idx,1);saveSprBackups(backups);renderBackupList();ae('🗑 Бэкап удалён')}

// ===================== POWER LIMIT =====================
function openPowerLimitModal(slot){
_plSlot=slot;_plDeviceId=getDeviceIdForSlot(slot);_plDeviceType=null;
if(!_plDeviceId){ae('⚠ Устройство не найдено');return}
const isGen=slot.startsWith('g');
const m=$('plModal');if(!m)return;m.classList.add('sh');
const nm=slot.startsWith('g')?'Генератор '+slot.slice(1):'ШПР';
$('plTitle').textContent=(isGen?'📊 Мощность — ':'⚡ Ограничение мощности — ')+nm;
// Show correct section
$('plReadOnly').style.display=isGen?'':'none';
$('plWriteSection').style.display=isGen?'none':'';
if(isGen){
// Read-only mode for generators
$('plRoCurrentP').textContent='—';$('plRoTargetP').textContent='—';
$('plRoCurrentQ').textContent='—';$('plRoTargetQ').textContent='—';
$('plRoConfigP').textContent='—';$('plRoConfigQ').textContent='—';
$('plStatus').innerHTML='';
if(G.apiAvailable){
fetch(API_BASE+'/api/devices/'+_plDeviceId+'/power-limit').then(r=>{if(!r.ok)throw new Error('HTTP '+r.status);return r.json()}).then(d=>{
if(d.success){
_plDeviceType=d.device_type;
if(d.current_p_pct!=null)$('plRoCurrentP').textContent=d.current_p_pct.toFixed(1)+'%';
if(d.target_p_pct!=null)$('plRoTargetP').textContent=d.target_p_pct.toFixed(1)+'%';
if(d.current_q_pct!=null)$('plRoCurrentQ').textContent=d.current_q_pct.toFixed(1)+'%';
if(d.target_q_pct!=null)$('plRoTargetQ').textContent=d.target_q_pct.toFixed(1)+'%';
if(d.config_p_raw!=null)$('plRoConfigP').textContent=d.config_p_raw;
if(d.config_q_raw!=null)$('plRoConfigQ').textContent=d.config_q_raw;
}}).catch(e=>{console.warn('PL read error:',e);$('plStatus').innerHTML='<div style="padding:6px 10px;background:var(--yd);border:1px solid rgba(255,176,32,.2);border-radius:6px;font-size:11px;color:var(--y)">⚠ Не удалось считать: '+e.message+'</div>'})}
else{const mx=G.latestMetrics[_plDeviceId];if(mx){
if(mx.current_p_pct!=null)$('plRoCurrentP').textContent=mx.current_p_pct.toFixed(1)+'%';
if(mx.target_p_pct!=null)$('plRoTargetP').textContent=mx.target_p_pct.toFixed(1)+'%';
if(mx.current_q_pct!=null)$('plRoCurrentQ').textContent=mx.current_q_pct.toFixed(1)+'%';
if(mx.target_q_pct!=null)$('plRoTargetQ').textContent=mx.target_q_pct.toFixed(1)+'%';
}}}else{
// Write mode for SPR
$('plLiveP').textContent='—';$('plLiveQ').textContent='—';
$('plSliderP').value=75;$('plNumP').textContent='75.0%';
$('plSliderQ').value=50;$('plNumQ').textContent='50.0%';
$('plLoadModeWrap').style.display='none';
$('plStatusW').innerHTML='';
if(G.apiAvailable){
fetch(API_BASE+'/api/devices/'+_plDeviceId+'/power-limit').then(r=>{if(!r.ok)throw new Error('HTTP '+r.status);return r.json()}).then(d=>{
if(d.success){
_plDeviceType=d.device_type;
if(d.current_p_pct!=null)$('plLiveP').textContent=d.current_p_pct.toFixed(1)+'%';
if(d.current_q_pct!=null)$('plLiveQ').textContent=d.current_q_pct.toFixed(1)+'%';
if(d.config_p_raw!=null){$('plSliderP').value=Math.round(d.config_p_raw/10);$('plNumP').textContent=(d.config_p_raw/10).toFixed(1)+'%'}
if(d.config_q_raw!=null){$('plSliderQ').value=Math.round(d.config_q_raw/10);$('plNumQ').textContent=(d.config_q_raw/10).toFixed(1)+'%'}
if(d.device_type==='ats'){$('plLoadModeWrap').style.display='';document.querySelectorAll('input[name=plMode]').forEach(r=>{r.checked=d.load_mode!=null&&+r.value===d.load_mode})}
}}).catch(e=>{console.warn('PL read error:',e);$('plStatusW').innerHTML='<div style="padding:6px 10px;background:var(--yd);border:1px solid rgba(255,176,32,.2);border-radius:6px;font-size:11px;color:var(--y)">⚠ Не удалось считать конфиг: '+e.message+'</div>'})}
else{const mx=G.latestMetrics[_plDeviceId];if(mx){
if(mx.current_p_pct!=null)$('plLiveP').textContent=mx.current_p_pct.toFixed(1)+'%';
if(mx.current_q_pct!=null)$('plLiveQ').textContent=mx.current_q_pct.toFixed(1)+'%';
if(mx.target_p_pct!=null){$('plSliderP').value=Math.round(mx.target_p_pct);$('plNumP').textContent=mx.target_p_pct.toFixed(1)+'%'}
if(mx.target_q_pct!=null){$('plSliderQ').value=Math.round(mx.target_q_pct);$('plNumQ').textContent=mx.target_q_pct.toFixed(1)+'%'}
}}}}
function closePowerLimitModal(){const m=$('plModal');if(m)m.classList.remove('sh');_plSlot=null}
function goToSprControl(){
// Open SPR card → Управление tab
const sprCard=$('cspr');if(!sprCard)return;
if(!sprCard.classList.contains('op'))tog('cspr');
// Switch to Управление tab
const tabs=sprCard.querySelectorAll('.tbs .tb');
tabs.forEach(t=>{if(t.textContent.includes('Управление')){t.click()}});
sprCard.scrollIntoView({behavior:'smooth',block:'start'});
}
function plSliderUpdate(which){
const sl=$('plSlider'+which),num=$('plNum'+which);
if(sl&&num)num.textContent=parseFloat(sl.value).toFixed(1)+'%'}
function plQuickP(p,q){$('plSliderP').value=p;$('plNumP').textContent=p.toFixed(1)+'%';$('plSliderQ').value=q;$('plNumQ').textContent=q.toFixed(1)+'%'}
async function savePowerLimit(){
if(!_plDeviceId){ae('⚠ Нет устройства');return}
const pVal=parseInt($('plSliderP').value),qVal=parseInt($('plSliderQ').value);
const pRaw=pVal*10,qRaw=qVal*10;
const st=$('plStatusW');
if(!confirm('Записать P='+pVal+'%, Q='+qVal+'% в контроллер?\n\n⚠ Это изменит реальное распределение электрической нагрузки!')){return}
const body={p_raw:pRaw,q_raw:qRaw};
const modeEl=document.querySelector('input[name=plMode]:checked');
if(modeEl)body.load_mode=parseInt(modeEl.value);
st.innerHTML='<div style="padding:6px 10px;background:var(--yd);border:1px solid rgba(255,176,32,.2);border-radius:6px;font-size:11px;color:var(--y);font-family:var(--m)">⏳ Запись в контроллер...</div>';
if(!G.apiAvailable){st.innerHTML='<div style="padding:6px 10px;background:var(--rd);border:1px solid rgba(255,64,96,.2);border-radius:6px;font-size:11px;color:var(--r)">❌ Backend недоступен</div>';return}
try{
const r=await fetch(API_BASE+'/api/devices/'+_plDeviceId+'/power-limit',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
const d=await r.json();
if(d.success&&d.verified){st.innerHTML='<div style="padding:6px 10px;background:var(--gd);border:1px solid rgba(0,224,154,.2);border-radius:6px;font-size:11px;color:var(--g);font-family:var(--m)">✅ '+d.message+'</div>';ae('⚡ P='+pVal+'% Q='+qVal+'% записано')}
else if(d.success){st.innerHTML='<div style="padding:6px 10px;background:var(--yd);border:1px solid rgba(255,176,32,.2);border-radius:6px;font-size:11px;color:var(--y);font-family:var(--m)">⚠ '+d.message+'</div>';ae('⚠ PL записано, но не верифицировано')}
else{st.innerHTML='<div style="padding:6px 10px;background:var(--rd);border:1px solid rgba(255,64,96,.2);border-radius:6px;font-size:11px;color:var(--r)">❌ '+(d.detail||d.message||'Ошибка')+'</div>'}
}catch(e){st.innerHTML='<div style="padding:6px 10px;background:var(--rd);border:1px solid rgba(255,64,96,.2);border-radius:6px;font-size:11px;color:var(--r)">❌ '+e.message+'</div>'}}

// ===================== B24 DASHBOARD =====================
function stopB24Poll(){if(b24PollTimer){clearInterval(b24PollTimer);b24PollTimer=null}}
function showB24Dashboard(){
G.archiveMode=false;stopB24Poll();
const mn=$('mainArea');
mn.innerHTML=`<div class="dh"><div class="dt"><h1 style="font-size:16px;font-weight:700;color:var(--t)">🔗 Битрикс24</h1></div>
<div class="da"><button class="bs2" style="padding:6px 14px" onclick="stopB24Poll();if(cur&&S[cur])renderDash()">← Мониторинг</button>
<button class="bs2" style="padding:6px 14px" onclick="b24ForceSync()">⚡ Синхронизация</button>
<button class="bs2" style="padding:6px 14px" onclick="b24TestTask()">🧪 Тест</button>
<button class="bs2" style="padding:6px 14px" onclick="initBxModal();showM('bitrix')">⚙ Настройки</button></div></div>
<div id="b24Status" style="margin-bottom:10px"></div>
<div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:8px;margin-bottom:12px">
<div id="b24StatOpen" class="cc" style="padding:14px;text-align:center"></div>
<div id="b24StatClosed" class="cc" style="padding:14px;text-align:center"></div>
<div id="b24StatMaint" class="cc" style="padding:14px;text-align:center"></div>
<div id="b24StatAlarm" class="cc" style="padding:14px;text-align:center"></div></div>
<div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:12px">
<div><h3 style="font-size:13px;color:var(--t2);margin-bottom:8px">📋 Активные задачи</h3><div id="b24Tasks"></div></div>
<div><h3 style="font-size:13px;color:var(--t2);margin-bottom:8px">👥 Оборудование и роли</h3><div id="b24Equip"></div></div></div>
<div><h3 style="font-size:13px;color:var(--t2);margin-bottom:8px">🔧 Привязка устройств к оборудованию Б24</h3><div id="b24Mapping"></div></div>`;
b24Refresh();
b24LoadMapping();
b24PollTimer=setInterval(b24Refresh,15000);
}
async function b24Refresh(){await Promise.all([b24LoadStatus(),b24LoadStats(),b24LoadTasks(),b24LoadEquip()])}
async function b24LoadStatus(){
const el=$('b24Status');if(!el)return;
try{const s=await api.get('/api/bitrix24/status');
const c=s.connected;const domain=s.webhook_url?new URL(s.webhook_url).origin:'';
el.innerHTML=`<div style="padding:10px 14px;background:${c?'var(--gd)':'var(--rd)'};border:1px solid var(--bd);border-radius:var(--rad);display:flex;align-items:center;gap:10px;cursor:pointer" onclick="b24ForceSync()" title="Нажмите для синхронизации">
<span style="font-size:14px">${c?'🟢':'🔴'}</span>
<b style="font-size:12px;color:${c?'var(--g)':'var(--r)'}">${c?'Подключено':'Нет связи'}</b>
<span style="font-size:10px;color:var(--t3);font-family:var(--m)">Оборудование: ${s.equipment_count||0} ед.</span>
${domain?`<a href="${domain}" target="_blank" onclick="event.stopPropagation()" style="font-size:10px;color:var(--b);text-decoration:underline;margin-left:4px">${domain.replace('https://','')}</a>`:''}
<span style="font-size:10px;color:var(--t4);margin-left:auto">${s.last_sync?'Синхр: '+new Date(s.last_sync).toLocaleTimeString():''} 🔄</span></div>`;
}catch(e){el.innerHTML=`<div style="padding:10px;background:var(--bg3);border:1px solid var(--bd);border-radius:var(--rad);font-size:11px;color:var(--t3)">Модуль Б24 не активен (BITRIX24_ENABLED=false)</div>`}}
async function b24LoadStats(){
try{const s=await api.get('/api/bitrix24/stats');
const mk=(id,val,lbl,clr,flt)=>{const el=$(id);if(el){const act=JSON.stringify(b24Filter)===JSON.stringify(flt);el.innerHTML=`<div style="font-size:22px;font-weight:700;color:var(--${clr})">${val}</div><div style="font-size:10px;color:var(--t3);margin-top:2px">${lbl}</div>`;el.style.cursor='pointer';el.style.border=act?'2px solid var(--'+clr+')':'';el.onclick=()=>{b24Filter=act?{status:null,source_type:null}:flt;b24LoadTasks();b24LoadStats()}}};
mk('b24StatOpen',s.open,'Открытых','y',{status:'open',source_type:null});
mk('b24StatClosed',s.closed,'Закрытых','g',{status:'closed',source_type:null});
mk('b24StatMaint',s.by_type?.maintenance||0,'ТО','b',{status:null,source_type:'maintenance'});
mk('b24StatAlarm',s.by_type?.alarm||0,'Аварий','r',{status:null,source_type:'alarm'});
}catch(e){}}
function b24TaskUrl(taskId){const cfg=getBxConfig();if(!cfg.url)return'';try{const u=new URL(cfg.url);return u.origin+'/company/personal/user/102/tasks/task/view/'+taskId+'/'}catch(e){return''}}
async function b24LoadTasks(){
const el=$('b24Tasks');if(!el)return;
try{let q='/api/bitrix24/tasks?limit=20';if(b24Filter.status)q+='&status='+b24Filter.status;if(b24Filter.source_type)q+='&source_type='+b24Filter.source_type;
const r=await api.get(q);
if(!r.tasks||!r.tasks.length){el.innerHTML='<div style="padding:16px;background:var(--bg3);border:1px solid var(--bd);border-radius:var(--rad);font-size:11px;color:var(--t3);text-align:center">Нет задач'+(b24Filter.status||b24Filter.source_type?' по фильтру · <a href="#" onclick="b24Filter={status:null,source_type:null};b24LoadTasks();b24LoadStats();return false" style="color:var(--g)">сбросить</a>':'')+'</div>';return}
const fBadge=(b24Filter.status||b24Filter.source_type)?`<div style="display:flex;align-items:center;gap:6px;margin-bottom:6px;font-size:10px;color:var(--t3)"><span>Фильтр: ${b24Filter.status||''} ${b24Filter.source_type||''}</span><a href="#" onclick="b24Filter={status:null,source_type:null};b24LoadTasks();b24LoadStats();return false" style="color:var(--g);text-decoration:none">✕ сбросить</a></div>`:'';
el.innerHTML=fBadge+r.tasks.map(t=>{
const isAlarm=t.source_type==='alarm';
const ico=isAlarm?'🔴':'🟡';
const cls=t.status==='closed'?'opacity:.5':'';
const pr=t.priority>=2?'<span style="color:var(--r);font-size:9px;font-weight:700"> HIGH</span>':'';
const href=b24TaskUrl(t.bitrix_task_id);
return`<div class="cc b24-task" style="padding:10px 12px;margin-bottom:6px;${cls};cursor:pointer" onclick="${href?`window.open('${href}','_blank')`:''}" title="${href?'Открыть в Битрикс24':''}">
<div style="display:flex;align-items:center;gap:6px;margin-bottom:4px">
<span style="font-size:12px">${ico}</span>
<span style="font-size:11px;font-weight:600;color:var(--t)">${esc(t.task_title)}</span>${pr}
<span style="margin-left:auto;font-size:9px;padding:2px 6px;border-radius:10px;background:${t.status==='open'?'var(--yd)':'var(--gd)'};color:${t.status==='open'?'var(--y)':'var(--g)'}">${t.status}</span></div>
<div style="font-size:10px;color:var(--t3)">
→ ${esc(t.responsible_name||'—')} · <span style="color:var(--b);text-decoration:underline">#${t.bitrix_task_id}</span> · ${t.created_at?new Date(t.created_at).toLocaleDateString():''}</div></div>`}).join('')}
catch(e){el.innerHTML=`<div style="padding:10px;font-size:11px;color:var(--r)">Ошибка: ${esc(e.message)}</div>`}}
async function b24LoadEquip(){
const el=$('b24Equip');if(!el)return;
try{const r=await api.get('/api/bitrix24/equipment');
if(!r.items||!r.items.length){el.innerHTML='<div style="padding:16px;background:var(--bg3);border:1px solid var(--bd);border-radius:var(--rad);font-size:11px;color:var(--t3);text-align:center">Нет оборудования</div>';return}
el.innerHTML=r.items.map((eq,i)=>`<div class="cc b24-eq" style="padding:10px 12px;margin-bottom:6px;cursor:pointer" onclick="b24ToggleEq(this,'${esc(eq.system_code)}')">
<div style="display:flex;align-items:center;gap:6px;margin-bottom:4px">
<span class="b24-eq-arrow" style="font-size:9px;color:var(--t3);width:12px">▶</span>
<span style="font-size:12px;font-weight:600;color:var(--t)">${esc(eq.name)}</span>
<span style="font-size:9px;color:var(--t4);font-family:var(--m)">(${esc(eq.system_code)})</span>
<span style="margin-left:auto;font-size:9px;padding:2px 6px;border-radius:10px;background:var(--gd);color:var(--g)">ID: ${eq.responsible_id||'—'}</span></div>
<div style="font-size:10px;color:var(--t3);line-height:1.6">
<div>👤 Ответственный: <b style="color:var(--t2)">${esc(eq.responsible_name||'—')}</b></div>
${eq.accomplice_names?.length?`<div>👥 Соисполнители: ${eq.accomplice_names.map(n=>esc(n)).join(', ')}</div>`:''}
${eq.auditor_names?.length?`<div>👁 Наблюдатели: ${eq.auditor_names.map(n=>esc(n)).join(', ')}</div>`:''}
</div>
<div class="b24-eq-detail" style="display:none;margin-top:8px;padding-top:8px;border-top:1px solid var(--bd)">
<div style="font-size:10px;color:var(--t4)">⏳ Загрузка задач...</div></div>
</div>`).join('')}
catch(e){el.innerHTML=`<div style="padding:10px;font-size:11px;color:var(--r)">Ошибка: ${esc(e.message)}</div>`}}
async function b24ToggleEq(card,sysCode){
const det=card.querySelector('.b24-eq-detail');const arr=card.querySelector('.b24-eq-arrow');
if(det.style.display!=='none'){det.style.display='none';arr.textContent='▶';return}
det.style.display='block';arr.textContent='▼';
try{const r=await api.get('/api/bitrix24/tasks?limit=10');
const tasks=(r.tasks||[]).filter(t=>t.system_code===sysCode);
if(!tasks.length){det.innerHTML='<div style="font-size:10px;color:var(--t4)">Нет задач для этого оборудования</div>';return}
det.innerHTML='<div style="font-size:10px;font-weight:600;color:var(--t2);margin-bottom:4px">Задачи ('+tasks.length+'):</div>'+tasks.map(t=>{
const href=b24TaskUrl(t.bitrix_task_id);
return`<div style="padding:4px 8px;background:var(--ov);border-radius:4px;margin-bottom:3px;font-size:10px;cursor:pointer" onclick="event.stopPropagation();${href?`window.open('${href}','_blank')`:''}">
<span style="color:${t.status==='open'?'var(--y)':'var(--g)'}">${t.status==='open'?'🟡':'🟢'}</span>
${esc(t.task_title)} <span style="color:var(--b)">#${t.bitrix_task_id}</span></div>`}).join('')}
catch(e){det.innerHTML='<div style="font-size:10px;color:var(--r)">'+e.message+'</div>'}}
async function b24LoadMapping(){
const el=$('b24Mapping');if(!el)return;
try{const r=await api.get('/api/bitrix24/device-mapping');
const devs=r.devices||[];const eqs=r.equipment||[];
if(!devs.length){el.innerHTML='<div style="padding:10px;font-size:11px;color:var(--t3)">Нет устройств</div>';return}
el.innerHTML=`<div class="cc" style="padding:12px"><table style="width:100%;border-collapse:collapse;font-size:11px">
<tr style="border-bottom:1px solid var(--bd)"><th style="text-align:left;padding:6px;color:var(--t2)">Устройство</th><th style="text-align:left;padding:6px;color:var(--t2)">Тип</th><th style="text-align:left;padding:6px;color:var(--t2)">Оборудование Б24</th><th style="padding:6px"></th></tr>
${devs.map(d=>{
const opts=eqs.map(eq=>`<option value="${esc(eq.system_code)}"${d.system_code===eq.system_code?' selected':''}>${esc(eq.name)} (${esc(eq.system_code)})</option>`).join('');
const linked=d.system_code?true:false;
return`<tr style="border-bottom:1px solid var(--bd)">
<td style="padding:6px;color:var(--t)">${esc(d.name)}</td>
<td style="padding:6px;color:var(--t3)">${esc(d.device_type)}</td>
<td style="padding:6px"><select id="b24map_${d.id}" style="padding:4px 8px;font-size:11px;border:1px solid var(--bd);border-radius:4px;background:var(--bg);color:var(--t)">
<option value="">— не привязан —</option>${opts}</select></td>
<td style="padding:6px"><button class="bs2" style="padding:4px 10px;font-size:10px" onclick="b24SaveMapping(${d.id})">${linked?'✅':'💾'}</button></td></tr>`}).join('')}
</table></div>`;
}catch(e){el.innerHTML=`<div style="padding:10px;font-size:11px;color:var(--r)">Ошибка: ${esc(e.message)}</div>`}}
async function b24SaveMapping(deviceId){
const sel=$('b24map_'+deviceId);if(!sel)return;
const sc=sel.value||null;
try{await api.put('/api/bitrix24/device-mapping',{device_id:deviceId,system_code:sc});
ae(sc?'✅ Привязано: '+sc:'✅ Привязка снята');b24LoadMapping()}
catch(e){ae('❌ '+e.message)}}
async function b24ForceSync(){
try{const r=await api.post('/api/bitrix24/equipment/sync');ae('✅ Синхронизация: '+r.cached+' ед.');b24Refresh();b24LoadMapping()}
catch(e){ae('❌ Ошибка синхронизации: '+e.message)}}
async function b24TestTask(){
try{const r=await api.post('/api/bitrix24/tasks/test');
if(r.success){ae('✅ Тестовая задача создана: #'+r.task_id);b24Refresh()}
else ae('❌ Ошибка: '+(r.error||'unknown'))}
catch(e){ae('❌ '+e.message)}}

// ===================== KNOWLEDGE BASE =====================
async function kbDeleteDoc(filename){
  if(!confirm('Удалить «'+filename+'» из базы знаний?'))return;
  try{
    await fetch(API_BASE+'/api/ai/knowledge/'+encodeURIComponent(filename),{method:'DELETE'});
    kbLoadDocs();
  }catch(e){
    alert('Ошибка удаления: '+e.message);
  }
}

// ===================== EXPORTS =====================
export {
  // Settings modal
  openSet, setTab, saveSet, _genSettingsPanel,
  // Generator settings
  updGenProtoLabel,
  // Smart reset
  smartReset,
  // Command system
  cmdConfirm, applyPreset,
  // AI config
  getAIConfig, saveAICfg, initAIModal, selectAIProvider, showAIKeySection,
  toggleAIKeyVis, saveAIConfig, activateAIProvider, testAIProvider, updateAIStatus,
  // Bitrix24
  getBxConfig, saveBxCfg, getBxUsers, saveBxUsers, getBxWebhookUrl,
  initBxModal, bxTab, saveBxConfig, testBxConnection, loadBxUsers,
  scanBxFolder, importBxFile, applyAIResult, createBxTaskFromTO, createBxTask,
  formatSize, b24TaskUrl, b24SaveMapping, b24TestTask, b24ForceSync,
  b24ToggleEq, stopB24Poll, showB24Dashboard, b24LoadStats, b24LoadTasks,
  // SPR control
  onSprControlTabOpen, readSprConfig, saveSprConfig, setSprLoadMode,
  backupSprConfig, openRestoreBackup, restoreBackup, downloadBackup,
  deleteBackup, getSprBackups, saveSprBackups, updateQuickButtons,
  updateSprControlMode, applySprConfigToUI, highlightLoadMode, renderBackupList,
  // Power limit
  openPowerLimitModal, closePowerLimitModal, savePowerLimit,
  plSliderUpdate, plQuickP, goToSprControl,
  // Admin
  renderAdminComms, loadAdminComms, loadAdminDecisions, renderAdminDecisions,
  renderAdminOfflineQueue, toggleAdmin, loadAdminUserFilter, loadAdminSessions,
  // Knowledge base
  kbDeleteDoc,
};
