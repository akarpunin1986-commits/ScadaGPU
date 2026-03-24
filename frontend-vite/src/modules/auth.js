// SCADA GPU v5 — Authentication module
import { G } from './state.js';
import { $, esc } from './utils.js';
import { API_BASE, api } from './api.js';

// === AUTH ===

export async function checkAuth() {
    for (let attempt = 0; attempt < 2; attempt++) {
        try {
            const resp = await fetch(API_BASE + '/api/auth/me', {credentials: 'include'});
            if (resp.ok) {
                G.currentUser = await resp.json();
                document.getElementById('login-overlay').classList.add('hidden');
                setTimeout(() => document.getElementById('login-overlay').style.display = 'none', 300);
                applyRoleUI(G.currentUser.role);
                return true;
            }
        } catch(e) {}
        if (attempt === 0) await new Promise(r => setTimeout(r, 500));
    }
    document.getElementById('login-overlay').style.display = 'flex';
    document.getElementById('login-overlay').classList.remove('hidden');
    return false;
}

// Login typing effect + clock
(function(){
    const el=document.getElementById('lo-typed');if(!el)return;
    const phrases=['ИИ-система управления промышленным оборудованием','Генераторы · Печи · Экструдеры · Подстанции','2 завода · Полный контроль · 24/7 мониторинг','Алармы · Экономика · Автоматические задачи'];
    let pi=0,ci=0,del=false,p=0;
    function tick(){const s=phrases[pi];if(!del){el.textContent=s.slice(0,ci+1);ci++;p=ci>=s.length?2600:30+Math.random()*25;if(ci>=s.length)del=true}else{el.textContent=s.slice(0,ci-1);ci--;p=ci<=0?350:16;if(ci<=0){del=false;pi=(pi+1)%phrases.length}}setTimeout(tick,p)}
    setTimeout(tick,700);
    function uc(){const n=new Date();const e=document.getElementById('lo-clock');if(e)e.textContent=[n.getHours(),n.getMinutes(),n.getSeconds()].map(v=>String(v).padStart(2,'0')).join(':')}
    uc();setInterval(uc,1000);
    // Fetch real site status
    fetch(API_BASE+'/api/sites/public-status').then(r=>r.json()).then(function(sites){
        var el=document.getElementById('lo-pills');if(!el)return;
        el.innerHTML=sites.map(function(s){
            var cls=s.online?'lo-pill':'lo-pill offline';
            var label=s.online?'онлайн':'офлайн';
            return '<div class="'+cls+'"><span class="lo-pill-dot"></span> '+esc(s.name)+' — '+label+'</div>';
        }).join('');
    }).catch(function(){});
})();

// Code digit inputs
const loDigits=document.querySelectorAll('.lo-code-digit');
loDigits.forEach(function(el,i){
    el.addEventListener('input',function(e){var v=e.target.value.replace(/\D/g,'');e.target.value=v;if(v){el.classList.add('filled');if(i<5)loDigits[i+1].focus()}else el.classList.remove('filled');loCheckCode()});
    el.addEventListener('keydown',function(e){if(e.key==='Backspace'&&!e.target.value&&i>0){loDigits[i-1].focus();loDigits[i-1].value='';loDigits[i-1].classList.remove('filled')}});
    el.addEventListener('paste',function(e){e.preventDefault();var t=(e.clipboardData.getData('text')||'').replace(/\D/g,'').slice(0,6);t.split('').forEach(function(c,j){if(loDigits[j]){loDigits[j].value=c;loDigits[j].classList.add('filled')}});if(t.length>0)loDigits[Math.min(t.length,5)].focus();loCheckCode()});
});

export function loCheckCode(){var c=loGetCode();document.getElementById('btn-verify-code').disabled=c.length<6;if(c.length===6)setTimeout(verifyAuthCode,200)}
export function loGetCode(){return Array.from(loDigits).map(function(d){return d.value}).join('')}
export function loMaskEmail(e){var p=e.split('@');return p[0].length<=2?e:p[0][0]+'···'+p[0].slice(-1)+'@'+p[1]}
export function loShowMsg(el,type,icon,text){el.className='lo-msg show '+type;el.innerHTML='<span class="lo-msg-icon">'+icon+'</span><span>'+text+'</span>'}
export function loHideMsg(el){el.className='lo-msg'}

export function loStartResend(){G.loResendCD=60;var te=document.getElementById('lo-timer'),rb=document.getElementById('lo-resend-btn');rb.disabled=true;te.style.display='inline';clearInterval(G.loResendTimer);G.loResendTimer=setInterval(function(){G.loResendCD--;te.textContent=' '+G.loResendCD+'с';if(G.loResendCD<=0){clearInterval(G.loResendTimer);rb.disabled=false;te.style.display='none'}},1000)}
export function loResend(){requestAuthCode();loStartResend()}
document.getElementById('login-email').addEventListener('keydown',function(e){if(e.key==='Enter')requestAuthCode()});

export async function requestAuthCode() {
    var input=document.getElementById('login-email'),email=input.value.trim();
    var msg=document.getElementById('lo-msg-email'),btn=document.getElementById('btn-request-code');
    if(!email||!email.includes('@')){input.classList.add('lo-err');loShowMsg(msg,'error','✕','Введите корректный email');setTimeout(function(){input.classList.remove('lo-err')},600);return}
    btn.disabled=true;btn.innerHTML='<span class="lo-spinner"></span> Отправка...';loHideMsg(msg);
    try {
        var resp = await fetch(API_BASE + '/api/auth/request-code', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({email: email}), credentials: 'include'
        });
        var data = await resp.json();
        if (resp.ok && data.status === 'code_sent') {
            document.getElementById('lo-sent-to').textContent=loMaskEmail(email);
            document.getElementById('lo-step-email').classList.remove('active');
            document.getElementById('lo-step-code').classList.add('active');
            loStartResend();
            setTimeout(function(){loDigits[0].focus()},120);
        } else {
            loShowMsg(msg,'error','✕',data.message||data.detail||'Ошибка');
        }
    } catch(e) { loShowMsg(msg,'error','✕','Сервер недоступен'); }
    btn.disabled=false;btn.textContent='Получить код';
}

export async function verifyAuthCode() {
    var email=document.getElementById('login-email').value.trim();
    var code=loGetCode();
    var msg=document.getElementById('lo-msg-code'),btn=document.getElementById('btn-verify-code');
    if(code.length<6)return;
    btn.disabled=true;btn.innerHTML='<span class="lo-spinner"></span> Проверка...';loHideMsg(msg);
    try {
        var resp = await fetch(API_BASE + '/api/auth/verify-code', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({email: email, code: code}), credentials: 'include'
        });
        var data = await resp.json();
        if (resp.ok && data.status === 'ok') {
            loShowMsg(msg,'success','✓','Авторизация успешна');
            btn.textContent='✓ Готово';
            try{var me=await fetch(API_BASE+'/api/auth/me',{credentials:'include'});if(me.ok)G.currentUser=await me.json()}catch(e){}
            setTimeout(function(){
                document.getElementById('login-overlay').classList.add('hidden');
                setTimeout(function(){document.getElementById('login-overlay').style.display='none'},400);
                applyRoleUI(G.currentUser.role);
                window.initApp();
            },600);
        } else {
            loShowMsg(msg,'error','✕',data.message||data.detail||'Неверный код');
            btn.disabled=false;btn.textContent='Войти';
            loDigits.forEach(function(d){d.value='';d.classList.remove('filled')});loDigits[0].focus();
        }
    } catch(e){loShowMsg(msg,'error','✕','Сервер недоступен');btn.disabled=false;btn.textContent='Войти'}
}

export function showAuthTab(tab) {
    // Toggle tabs
    document.getElementById('tab-b24').classList.toggle('active', tab === 'b24');
    document.getElementById('tab-code').classList.toggle('active', tab === 'code');
    // Toggle content
    var b24 = document.getElementById('lo-step-b24');
    var email = document.getElementById('lo-step-email');
    var code = document.getElementById('lo-step-code');
    if (b24) b24.classList.toggle('active', tab === 'b24');
    if (email) email.classList.toggle('active', tab === 'code');
    if (code) code.classList.remove('active');
}

export function showEmailStep() {
    document.getElementById('lo-step-code').classList.remove('active');
    document.getElementById('lo-step-email').classList.add('active');
    clearInterval(G.loResendTimer);
    loDigits.forEach(function(d){d.value='';d.classList.remove('filled')});
    loHideMsg(document.getElementById('lo-msg-code'));
    var b=document.getElementById('btn-verify-code');b.disabled=true;b.textContent='Войти';
}

export function showLoginTab(tab) {
    document.getElementById('lo-step-email').style.display = tab === 'email' ? 'block' : 'none';
    document.getElementById('lo-step-code').style.display = 'none';
    document.getElementById('login-step-qr').style.display = tab === 'qr' ? 'block' : 'none';
    document.getElementById('tab-email').classList.toggle('active', tab === 'email');
    document.getElementById('tab-qr').classList.toggle('active', tab === 'qr');
    if (tab === 'qr') createQR();
}

export async function createQR() {
    if (G.qrPollInterval) { clearInterval(G.qrPollInterval); G.qrPollInterval = null; }
    const errEl = document.getElementById('login-error-qr');
    errEl.textContent = '';
    try {
        const resp = await fetch(API_BASE + '/api/auth/qr/create', {method: 'POST', credentials: 'include'});
        const data = await resp.json();
        G.qrToken = data.session_token;

        // Generate QR on canvas
        const canvas = document.getElementById('qr-canvas');
        renderQR(canvas, data.qr_url);

        // Timer
        let remaining = 180;
        const timerEl = document.getElementById('qr-timer');
        const tick = () => {
            const m = Math.floor(remaining / 60);
            const s = remaining % 60;
            timerEl.textContent = `QR обновится через ${m}:${s.toString().padStart(2,'0')}`;
            if (remaining <= 0) { clearInterval(timerInterval); timerEl.textContent = 'QR истёк'; }
            remaining--;
        };
        tick();
        const timerInterval = setInterval(tick, 1000);

        // Poll for status
        G.qrPollInterval = setInterval(async () => {
            try {
                const r = await fetch(API_BASE + `/api/auth/qr/status?token=${G.qrToken}`, {credentials: 'include'});
                const d = await r.json();
                if (d.status === 'ready') {
                    clearInterval(G.qrPollInterval);
                    clearInterval(timerInterval);
                    G.currentUser = {name: d.user_name};
                    location.reload();
                } else if (d.status === 'expired') {
                    clearInterval(G.qrPollInterval);
                    clearInterval(timerInterval);
                    timerEl.textContent = 'QR истёк — нажмите "Обновить"';
                }
            } catch(e) {}
        }, 2000);

    } catch(e) { errEl.textContent = 'Ошибка создания QR'; }
}

export function renderQR(canvas, text) {
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#fff';
    ctx.fillRect(0, 0, 200, 200);
    ctx.fillStyle = '#000';
    ctx.font = '11px monospace';
    ctx.textAlign = 'center';

    if (typeof QRCode !== 'undefined') {
        ctx.fillStyle = '#fff';
        ctx.fillRect(0, 0, 200, 200);
        new QRCode(canvas.parentElement, {text: text, width: 180, height: 180, correctLevel: QRCode.CorrectLevel.M});
    } else {
        const script = document.createElement('script');
        script.src = 'https://cdn.jsdelivr.net/npm/qrcode-generator@1.4.4/qrcode.min.js';
        script.onload = () => {
            const qr = qrcode(0, 'M');
            qr.addData(text);
            qr.make();
            const size = qr.getModuleCount();
            const cellSize = Math.floor(180 / size);
            const offset = Math.floor((200 - size * cellSize) / 2);
            ctx.fillStyle = '#fff';
            ctx.fillRect(0, 0, 200, 200);
            for (let r = 0; r < size; r++) {
                for (let c = 0; c < size; c++) {
                    if (qr.isDark(r, c)) {
                        ctx.fillStyle = '#000';
                        ctx.fillRect(offset + c * cellSize, offset + r * cellSize, cellSize, cellSize);
                    }
                }
            }
        };
        document.head.appendChild(script);
    }
}

export function showUserProfile() {
    if (!G.currentUser) return;
    const old = document.getElementById('user-profile');
    if (old) old.remove();
    const header = document.querySelector('.dh');
    if (!header) return;
    const p = document.createElement('div');
    p.id = 'user-profile';
    p.onclick = function(e) {
        e.stopPropagation();
        const pp = p.querySelector('.up-popup');
        if (pp) pp.classList.toggle('open');
    };
    const av = G.currentUser.avatar_url || '';
    const rn = {admin:'Администратор',operator:'Оператор',viewer:'Наблюдатель'};
    const shortName = (G.currentUser.name||'').split(' ').slice(0,2).join(' ');
    const firstName = (G.currentUser.name||'').split(' ')[1] || shortName;
    var pos = G.currentUser.position || G.currentUser.department || '';
    p.innerHTML = `${av ? '<img class="up-av" src="'+esc(av)+'">' : ''}<span class="up-name">${esc(firstName)}</span>`
        + `<div class="up-popup" onclick="event.stopPropagation()">`
        + `<div class="up-popup-hd">${av ? '<img src="'+esc(av)+'">' : ''}<div class="up-details">`
        + `<div class="up-fn">${esc(G.currentUser.name||'')}</div>`
        + `<div class="up-pos">${esc(pos)}</div>`
        + `</div></div>`
        + `<div class="up-popup-body">`
        + `<button class="up-item danger" onclick="doLogout()">⏻ Выйти из системы</button>`
        + `</div></div>`;
    header.appendChild(p);
}
document.addEventListener('click', function() {
    const pp = document.querySelector('.up-popup.open');
    if (pp) pp.classList.remove('open');
});

export function applyRoleUI(role) {
    if (role === 'viewer') {
        document.querySelectorAll('.cmd-buttons, .modbus-cmd, [data-role-min="operator"]').forEach(function(el) { el.style.display = 'none'; });
    }
    if (role !== 'admin') {
        document.querySelectorAll('.admin-only, [data-role-min="admin"]').forEach(function(el) { el.style.display = 'none'; });
    }
}

export async function doLogout() {
    await fetch(API_BASE + '/api/auth/logout', {method: 'POST', credentials: 'include'});
    G.currentUser = null;
    location.reload();
}

export function toggleMobileSidebar() {
    const sb = document.querySelector('.sb');
    const ov = document.getElementById('sbOverlay');
    if (sb && ov) {
        sb.classList.toggle('open');
        ov.classList.toggle('open');
    }
}
