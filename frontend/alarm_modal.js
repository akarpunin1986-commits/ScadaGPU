/**
 * Alarm Analytics Modal — autonomous JS module.
 *
 * Attaches click handlers to alarm items (.ai elements) on the page.
 * On click: fetches detailed alarm data from /api/alarm-analytics/events
 * and shows a modal with 4 sections: Header, Description, Metrics, Analysis.
 *
 * Self-contained: CSS injected via JS, no external dependencies.
 * Removal of this file does NOT affect SCADA operation.
 */
(function() {
    'use strict';

    // ---------------------------------------------------------------------------
    // CSS Injection
    // ---------------------------------------------------------------------------
    const style = document.createElement('style');
    style.textContent = `
        .alm-overlay {
            position: fixed; inset: 0; z-index: 9999;
            background: rgba(0,0,0,0.6); backdrop-filter: blur(4px);
            display: flex; align-items: center; justify-content: center;
            opacity: 0; transition: opacity 0.2s ease;
        }
        .alm-overlay.alm-show { opacity: 1; }
        .alm-modal {
            background: var(--bg2, #1e2430); color: var(--t, #e0e6ed);
            border-radius: 12px; max-width: 720px; width: 95%;
            max-height: 85vh; overflow-y: auto;
            box-shadow: 0 20px 60px rgba(0,0,0,0.5);
            transform: translateY(20px); transition: transform 0.2s ease;
            border: 1px solid var(--bd, rgba(255,255,255,0.08));
        }
        .alm-overlay.alm-show .alm-modal { transform: translateY(0); }
        .alm-header {
            padding: 20px 24px 16px; border-bottom: 1px solid var(--bd, rgba(255,255,255,0.06));
            position: relative;
        }
        .alm-close {
            position: absolute; top: 12px; right: 16px; background: none; border: none;
            color: var(--t3, #6c7a8d); font-size: 22px; cursor: pointer;
            width: 32px; height: 32px; display: flex; align-items: center; justify-content: center;
            border-radius: 6px; transition: all 0.15s;
        }
        .alm-close:hover { background: var(--bg4, rgba(255,255,255,0.08)); color: var(--t, #e0e6ed); }
        .alm-title {
            font-size: 16px; font-weight: 600; margin: 0 0 8px;
            display: flex; align-items: center; gap: 8px;
        }
        .alm-meta {
            font-size: 11px; color: var(--t3, #6c7a8d);
            display: flex; gap: 12px; flex-wrap: wrap;
        }
        .alm-badge {
            display: inline-flex; padding: 2px 8px; border-radius: 4px;
            font-size: 10px; font-weight: 600; text-transform: uppercase;
        }
        .alm-badge-shutdown { background: rgba(239,68,68,0.15); color: #f87171; }
        .alm-badge-trip { background: rgba(249,115,22,0.15); color: #fb923c; }
        .alm-badge-warning { background: rgba(234,179,8,0.15); color: #fbbf24; }
        .alm-badge-indication { background: rgba(96,165,250,0.15); color: #93c5fd; }
        .alm-badge-mains_trip { background: rgba(239,68,68,0.15); color: #f87171; }
        .alm-badge-block { background: rgba(239,68,68,0.15); color: #f87171; }
        .alm-badge-active { background: rgba(239,68,68,0.2); color: #f87171; }
        .alm-badge-cleared { background: rgba(34,197,94,0.15); color: #4ade80; }
        .alm-section {
            padding: 16px 24px; border-bottom: 1px solid var(--bd, rgba(255,255,255,0.04));
        }
        .alm-section:last-child { border-bottom: none; }
        .alm-section-title {
            font-size: 12px; font-weight: 600; color: var(--t2, #a0aec0);
            margin: 0 0 10px; display: flex; align-items: center; gap: 6px;
        }
        .alm-desc { font-size: 13px; line-height: 1.6; color: var(--t2, #a0aec0); }
        .alm-danger {
            margin-top: 10px; padding: 10px 14px; border-radius: 8px;
            background: rgba(239,68,68,0.08); border-left: 3px solid #f87171;
            font-size: 12px; color: #fca5a5;
        }
        .alm-metrics-grid {
            display: grid; grid-template-columns: 1fr 1fr; gap: 12px;
        }
        @media (max-width: 600px) { .alm-metrics-grid { grid-template-columns: 1fr; } }
        .alm-mg {
            background: var(--bg3, rgba(255,255,255,0.03)); border-radius: 8px; padding: 12px;
            border: 1px solid var(--bd, rgba(255,255,255,0.05));
        }
        .alm-mg-title {
            font-size: 10px; text-transform: uppercase; font-weight: 600;
            color: var(--t3, #6c7a8d); margin-bottom: 8px; letter-spacing: 0.5px;
        }
        .alm-mg-row {
            font-size: 12px; color: var(--t2, #a0aec0); padding: 2px 0;
            display: flex; justify-content: space-between;
        }
        .alm-mg-val { font-family: 'JetBrains Mono', monospace; color: var(--t, #e0e6ed); }
        .alm-mg-warn { color: #fbbf24; }
        .alm-mg-err { color: #f87171; }
        .alm-evidence {
            list-style: none; padding: 0; margin: 8px 0;
        }
        .alm-evidence li {
            font-size: 12px; color: var(--t2, #a0aec0); padding: 4px 0;
            padding-left: 16px; position: relative;
        }
        .alm-evidence li::before {
            content: ''; position: absolute; left: 0; top: 10px;
            width: 6px; height: 6px; border-radius: 50%; background: var(--p, #60a5fa);
        }
        .alm-cause {
            font-size: 13px; line-height: 1.6; color: var(--t, #e0e6ed);
            padding: 12px 16px; background: rgba(96,165,250,0.06);
            border-radius: 8px; border-left: 3px solid var(--p, #60a5fa);
        }
        .alm-rec {
            margin-top: 12px; font-size: 12px; color: var(--t2, #a0aec0);
            padding: 10px 14px; background: rgba(34,197,94,0.06);
            border-radius: 8px; border-left: 3px solid #4ade80;
        }
        .alm-loading {
            text-align: center; padding: 40px; color: var(--t3, #6c7a8d);
            font-size: 13px;
        }
        .alm-error {
            text-align: center; padding: 40px; color: #f87171;
            font-size: 13px;
        }
        .alm-llm-btn {
            width: 100%; padding: 12px 20px; border: 1px solid rgba(96,165,250,0.3);
            border-radius: 8px; background: rgba(96,165,250,0.08); color: #93c5fd;
            font-size: 13px; font-weight: 600; cursor: pointer; transition: all 0.15s;
            display: flex; align-items: center; justify-content: center; gap: 8px;
        }
        .alm-llm-btn:hover { background: rgba(96,165,250,0.15); border-color: rgba(96,165,250,0.5); }
        .alm-llm-btn:disabled { opacity: 0.5; cursor: not-allowed; }
        .alm-llm-result {
            margin-top: 12px; padding: 16px; background: rgba(96,165,250,0.04);
            border-radius: 8px; border: 1px solid rgba(96,165,250,0.1);
            font-size: 13px; line-height: 1.7; color: var(--t, #e0e6ed);
            white-space: pre-wrap;
        }
        .alm-llm-spinner {
            display: inline-block; width: 16px; height: 16px;
            border: 2px solid rgba(147,197,253,0.3); border-top-color: #93c5fd;
            border-radius: 50%; animation: almSpin 0.8s linear infinite;
        }
        @keyframes almSpin { to { transform: rotate(360deg); } }
    `;
    document.head.appendChild(style);

    // ---------------------------------------------------------------------------
    // Device name resolution
    // ---------------------------------------------------------------------------
    function resolveDeviceName(deviceId, deviceType) {
        // Try to use existing SCADA deviceSlotIndex if available
        if (typeof window.deviceSlotIndex !== 'undefined') {
            const slot = window.deviceSlotIndex[deviceId];
            if (slot) return slot;
        }
        if (deviceType === 'ats') return 'SPR (HGM9560)';
        if (deviceType === 'generator') return 'Generator (HGM9520N)';
        return 'Device #' + deviceId;
    }

    function severityEmoji(sev) {
        switch(sev) {
            case 'shutdown': return '\u{1F534}';
            case 'trip': case 'trip_stop': case 'mains_trip': case 'block': return '\u{1F7E0}';
            case 'warning': return '\u26A0\uFE0F';
            case 'indication': return '\u{1F535}';
            default: return '\u26A0\uFE0F';
        }
    }

    function severityLabel(sev) {
        switch(sev) {
            case 'shutdown': return 'Shutdown';
            case 'trip': return 'Trip';
            case 'trip_stop': return 'Trip & Stop';
            case 'mains_trip': return 'Mains Trip';
            case 'warning': return 'Warning';
            case 'indication': return 'Indication';
            case 'block': return 'Block';
            default: return sev;
        }
    }

    function fmtDt(iso) {
        if (!iso) return '—';
        const d = new Date(iso);
        return d.toLocaleString('ru-RU', {day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit',second:'2-digit'});
    }

    // ---------------------------------------------------------------------------
    // Metrics rendering
    // ---------------------------------------------------------------------------
    function renderMetricsHGM9560(snap) {
        if (!snap) return '<div class="alm-desc" style="color:var(--t3)">Снимок метрик недоступен</div>';
        const m = snap.mains || {};
        const b = snap.busbar || {};
        const sw = snap.switches || {};

        return `<div class="alm-metrics-grid">
            <div class="alm-mg">
                <div class="alm-mg-title">Сеть (Mains)</div>
                <div class="alm-mg-row"><span>UA</span><span class="alm-mg-val">${m.ua ?? '—'}V</span></div>
                <div class="alm-mg-row"><span>UB</span><span class="alm-mg-val">${m.ub ?? '—'}V</span></div>
                <div class="alm-mg-row"><span>UC</span><span class="alm-mg-val">${m.uc ?? '—'}V</span></div>
                <div class="alm-mg-row"><span>F</span><span class="alm-mg-val">${m.freq ?? '—'} Гц</span></div>
                <div class="alm-mg-row"><span>IA</span><span class="alm-mg-val">${m.ia ?? '—'}A</span></div>
                <div class="alm-mg-row"><span>IB</span><span class="alm-mg-val">${m.ib ?? '—'}A</span></div>
                <div class="alm-mg-row"><span>IC</span><span class="alm-mg-val">${m.ic ?? '—'}A</span></div>
                <div class="alm-mg-row"><span>P</span><span class="alm-mg-val">${m.total_p ?? '—'} кВт</span></div>
                <div class="alm-mg-row"><span>Q</span><span class="alm-mg-val">${m.total_q ?? '—'} квар</span></div>
            </div>
            <div class="alm-mg">
                <div class="alm-mg-title">Шина (Busbar)</div>
                <div class="alm-mg-row"><span>UAB</span><span class="alm-mg-val">${b.uab ?? '—'}V</span></div>
                <div class="alm-mg-row"><span>F</span><span class="alm-mg-val">${b.freq ?? '—'} Гц</span></div>
                <div class="alm-mg-row"><span>I</span><span class="alm-mg-val">${b.current ?? '—'}A</span></div>
                <div class="alm-mg-row"><span>P</span><span class="alm-mg-val">${b.total_p ?? '—'} кВт</span></div>
                <div class="alm-mg-row"><span>Q</span><span class="alm-mg-val">${b.total_q ?? '—'} квар</span></div>
                <div class="alm-mg-title" style="margin-top:12px">Коммутация</div>
                <div class="alm-mg-row"><span>Авт. шины</span><span class="alm-mg-val">${sw.busbar_switch_text ?? '—'}</span></div>
                <div class="alm-mg-row"><span>Авт. сети</span><span class="alm-mg-val">${sw.mains_switch_text ?? '—'}</span></div>
                <div class="alm-mg-row"><span>Статус сети</span><span class="alm-mg-val">${sw.mains_status_text ?? '—'}</span></div>
            </div>
        </div>
        <div style="margin-top:10px;font-size:11px;color:var(--t3)">
            Генератор: ${snap.genset_status_text ?? '—'} | Батарея: ${snap.battery_voltage ?? '—'}V | Режим: ${snap.mode ?? '—'}
        </div>`;
    }

    function renderMetricsHGM9520N(snap) {
        if (!snap) return '<div class="alm-desc" style="color:var(--t3)">Снимок метрик недоступен</div>';
        const g = snap.gen || {};
        const m = snap.mains || {};

        return `<div class="alm-metrics-grid">
            <div class="alm-mg">
                <div class="alm-mg-title">Генератор</div>
                <div class="alm-mg-row"><span>UAB</span><span class="alm-mg-val">${g.uab ?? '—'}V</span></div>
                <div class="alm-mg-row"><span>UBC</span><span class="alm-mg-val">${g.ubc ?? '—'}V</span></div>
                <div class="alm-mg-row"><span>UCA</span><span class="alm-mg-val">${g.uca ?? '—'}V</span></div>
                <div class="alm-mg-row"><span>IA</span><span class="alm-mg-val">${g.ia ?? '—'}A</span></div>
                <div class="alm-mg-row"><span>IB</span><span class="alm-mg-val">${g.ib ?? '—'}A</span></div>
                <div class="alm-mg-row"><span>IC</span><span class="alm-mg-val">${g.ic ?? '—'}A</span></div>
                <div class="alm-mg-row"><span>F</span><span class="alm-mg-val">${g.freq ?? '—'} Гц</span></div>
                <div class="alm-mg-row"><span>P</span><span class="alm-mg-val">${g.total_p ?? '—'} кВт</span></div>
                <div class="alm-mg-row"><span>Q</span><span class="alm-mg-val">${g.total_q ?? '—'} квар</span></div>
                <div class="alm-mg-row"><span>Обороты</span><span class="alm-mg-val">${g.engine_speed ?? '—'} об/мин</span></div>
            </div>
            <div class="alm-mg">
                <div class="alm-mg-title">Сеть (Mains)</div>
                <div class="alm-mg-row"><span>UAB</span><span class="alm-mg-val">${m.uab ?? '—'}V</span></div>
                <div class="alm-mg-row"><span>F</span><span class="alm-mg-val">${m.freq ?? '—'} Гц</span></div>
                <div class="alm-mg-row"><span>Статус</span><span class="alm-mg-val">${m.status_text ?? '—'}</span></div>
                <div class="alm-mg-title" style="margin-top:12px">Двигатель</div>
                <div class="alm-mg-row"><span>Батарея</span><span class="alm-mg-val">${snap.battery_voltage ?? '—'}V</span></div>
                <div class="alm-mg-row"><span>Зарядка</span><span class="alm-mg-val">${snap.charger_voltage ?? '—'}V</span></div>
                <div class="alm-mg-row"><span>Давл. масла</span><span class="alm-mg-val">${snap.oil_pressure ?? '—'}</span></div>
                <div class="alm-mg-row"><span>Темп. ОЖ</span><span class="alm-mg-val">${snap.coolant_temp ?? '—'}°C</span></div>
                <div class="alm-mg-row"><span>Топливо</span><span class="alm-mg-val">${snap.fuel_level ?? '—'}%</span></div>
            </div>
        </div>
        <div style="margin-top:10px;font-size:11px;color:var(--t3)">
            Генератор: ${snap.genset_status_text ?? '—'} | Режим: ${snap.mode ?? '—'}
        </div>`;
    }

    function renderMetrics(snap, deviceType) {
        if (deviceType === 'ats') return renderMetricsHGM9560(snap);
        if (deviceType === 'generator') return renderMetricsHGM9520N(snap);
        return '<div class="alm-desc" style="color:var(--t3)">Неизвестный тип устройства</div>';
    }

    // ---------------------------------------------------------------------------
    // Analysis rendering
    // ---------------------------------------------------------------------------
    function renderAnalysis(analysis) {
        if (!analysis) return '<div class="alm-desc" style="color:var(--t3)">Анализ недоступен</div>';

        let html = '';

        if (analysis.probable_cause) {
            html += `<div class="alm-cause"><b>Вероятная причина:</b><br>${analysis.probable_cause}</div>`;
        }

        if (analysis.evidence && analysis.evidence.length > 0) {
            html += `<ul class="alm-evidence">`;
            for (const e of analysis.evidence) {
                html += `<li>${e}</li>`;
            }
            html += `</ul>`;
        }

        if (analysis.recommendation) {
            html += `<div class="alm-rec"><b>Рекомендация:</b><br>${analysis.recommendation}</div>`;
        }

        return html || '<div class="alm-desc" style="color:var(--t3)">Нет данных для анализа</div>';
    }

    // ---------------------------------------------------------------------------
    // Modal
    // ---------------------------------------------------------------------------
    let overlayEl = null;

    function createOverlay() {
        if (overlayEl) return overlayEl;
        overlayEl = document.createElement('div');
        overlayEl.className = 'alm-overlay';
        overlayEl.addEventListener('click', function(e) {
            if (e.target === overlayEl) closeModal();
        });
        document.body.appendChild(overlayEl);
        return overlayEl;
    }

    function closeModal() {
        if (!overlayEl) return;
        overlayEl.classList.remove('alm-show');
        setTimeout(() => {
            if (overlayEl) { overlayEl.remove(); overlayEl = null; }
        }, 200);
    }

    function showModal(html) {
        const overlay = createOverlay();
        overlay.innerHTML = `<div class="alm-modal">${html}</div>`;
        requestAnimationFrame(() => overlay.classList.add('alm-show'));
    }

    function showLoading() {
        showModal('<div class="alm-loading">Загрузка данных аварии...</div>');
    }

    function showError(msg) {
        showModal(`<div class="alm-error">${msg}</div>`);
    }

    function renderFullModal(ev) {
        const sev = ev.alarm_severity || 'warning';
        const sevBadge = `<span class="alm-badge alm-badge-${sev}">${severityLabel(sev)}</span>`;
        const activeBadge = ev.is_active
            ? '<span class="alm-badge alm-badge-active">Активна</span>'
            : '<span class="alm-badge alm-badge-cleared">Снята</span>';
        const deviceName = resolveDeviceName(ev.device_id, ev.device_type);
        const controllerType = ev.device_type === 'ats' ? 'HGM9560' : 'HGM9520N';

        let html = `
            <div class="alm-header">
                <button class="alm-close" onclick="document.querySelector('.alm-overlay').click()">&times;</button>
                <div class="alm-title">
                    ${severityEmoji(sev)} ${ev.alarm_code} ${ev.alarm_name_ru}
                </div>
                <div class="alm-meta">
                    <span>${fmtDt(ev.occurred_at)}</span>
                    <span>${deviceName}</span>
                    <span>${controllerType}</span>
                    ${sevBadge} ${activeBadge}
                </div>
                ${ev.cleared_at ? `<div class="alm-meta" style="margin-top:4px"><span>Снята: ${fmtDt(ev.cleared_at)}</span></div>` : ''}
            </div>`;

        // Section: Description — use analysis.manual_description or description_ru from alarmDefs
        const analysis = ev.analysis_result || {};
        let descText = analysis.manual_description || '';
        if (!descText && typeof window.alarmDefs !== 'undefined') {
            // Lookup description_ru from definitions loaded in scada-v5.html
            const regField = ev.alarm_register !== undefined ? Object.keys(window.alarmDefs).find(f => {
                const bits = window.alarmDefs[f] || {};
                return bits[ev.alarm_bit] && bits[ev.alarm_bit].code === ev.alarm_code;
            }) : null;
            if (regField && window.alarmDefs[regField] && window.alarmDefs[regField][ev.alarm_bit]) {
                descText = window.alarmDefs[regField][ev.alarm_bit].description_ru || '';
            }
        }
        if (descText) {
            html += `<div class="alm-section">
                <div class="alm-section-title">\u{1F4D6} Описание</div>
                <div class="alm-desc">${descText}</div>
                ${analysis.manual_danger ? `<div class="alm-danger">\u26A0\uFE0F <b>Опасность:</b> ${analysis.manual_danger}</div>` : ''}
            </div>`;
        }

        // Section: Metrics
        html += `<div class="alm-section">
            <div class="alm-section-title">\u{1F4CA} Метрики в момент аварии</div>
            ${renderMetrics(ev.metrics_snapshot, ev.device_type)}
        </div>`;

        // Section: Analysis
        html += `<div class="alm-section">
            <div class="alm-section-title">\u{1F50D} Анализ причины</div>
            ${renderAnalysis(analysis)}
        </div>`;

        // Section: LLM (Sanek) — Ask AI for detailed analysis
        const _devType = ev.device_type || 'generator';
        html += `<div class="alm-section">
            <button class="alm-llm-btn" id="alm-llm-btn" onclick="window._almAskLLM('${ev.alarm_code}', ${ev.device_id || 0}, '${_devType}')">
                \u{1F916} Спросить Санька — подробный анализ
            </button>
            <div id="alm-llm-result"></div>
        </div>`;

        showModal(html);
    }

    // ---------------------------------------------------------------------------
    // Fetch + show
    // ---------------------------------------------------------------------------
    async function fetchAndShowEvent(eventId) {
        showLoading();
        try {
            const resp = await fetch(`/api/alarm-analytics/events/${eventId}`);
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const ev = await resp.json();
            renderFullModal(ev);
        } catch (err) {
            showError('Не удалось загрузить данные аварии: ' + err.message);
        }
    }

    async function fetchAndShowByCode(alarmCode, deviceId) {
        showLoading();
        try {
            // Try to find the most recent event for this alarm code + device
            let url = `/api/alarm-analytics/events?alarm_code=${encodeURIComponent(alarmCode)}&limit=1`;
            if (deviceId) url += `&device_id=${deviceId}`;
            const resp = await fetch(url);
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const events = await resp.json();
            if (events.length > 0) {
                // Found event — fetch full details
                await fetchAndShowEvent(events[0].id);
            } else {
                // No event in DB — show definition + active alarms for the device
                await showDefinitionWithContext(alarmCode, deviceId);
            }
        } catch (err) {
            showError('\u041D\u0435 \u0443\u0434\u0430\u043B\u043E\u0441\u044C \u0437\u0430\u0433\u0440\u0443\u0437\u0438\u0442\u044C \u0434\u0430\u043D\u043D\u044B\u0435 \u0430\u0432\u0430\u0440\u0438\u0438: ' + err.message);
        }
    }

    async function showDefinitionWithContext(alarmCode, deviceId) {
        // Show definition for THIS specific alarm only — no list of all active alarms
        try {
            const defResp = await fetch('/api/alarm-analytics/definitions');
            const defs = defResp.ok ? await defResp.json() : [];
            const defn = defs.find(d => d.code === alarmCode);

            // Header
            const title = defn ? defn.name_ru : alarmCode;
            const severity = defn ? defn.severity : 'warning';
            const engName = defn ? defn.name : '';
            const deviceName = deviceId ? resolveDeviceName(deviceId, defn ? (defn.register_field.startsWith('alarm_reg') ? 'ats' : 'generator') : null) : '';

            let html = '<div class="alm-header">' +
                '<button class="alm-close" onclick="document.querySelector(\'.alm-overlay\').click()">&times;</button>' +
                '<div class="alm-title">' + severityEmoji(severity) + ' ' + alarmCode + ' ' + title + '</div>' +
                '<div class="alm-meta">' +
                    (engName ? '<span>' + engName + '</span>' : '') +
                    (deviceName ? '<span>' + deviceName + '</span>' : '') +
                    '<span class="alm-badge alm-badge-' + severity + '">' + severityLabel(severity) + '</span>' +
                '</div>' +
            '</div>';

            // Description section — show description_ru if available, else title
            const descRu = defn ? (defn.description_ru || '') : '';
            html += '<div class="alm-section">' +
                '<div class="alm-section-title">\uD83D\uDCD6 \u041E\u043F\u0438\u0441\u0430\u043D\u0438\u0435</div>' +
                '<div class="alm-desc">' + (descRu || title) + '</div>' +
                (engName && engName !== title ? '<div class="alm-desc" style="margin-top:4px;color:var(--t3,#6c7a8d);font-size:12px">' + engName + '</div>' : '') +
            '</div>';

            // Severity explanation
            const sevExplanations = {
                'shutdown': '\u0410\u0432\u0430\u0440\u0438\u044F \u043A\u0430\u0442\u0435\u0433\u043E\u0440\u0438\u0438 SHUTDOWN \u2014 \u043A\u0440\u0438\u0442\u0438\u0447\u0435\u0441\u043A\u0430\u044F. \u041F\u0440\u0438\u0432\u043E\u0434\u0438\u0442 \u043A \u043D\u0435\u043C\u0435\u0434\u043B\u0435\u043D\u043D\u043E\u0439 \u043E\u0441\u0442\u0430\u043D\u043E\u0432\u043A\u0435 \u043E\u0431\u043E\u0440\u0443\u0434\u043E\u0432\u0430\u043D\u0438\u044F.',
                'trip': '\u0410\u0432\u0430\u0440\u0438\u044F \u043A\u0430\u0442\u0435\u0433\u043E\u0440\u0438\u0438 TRIP \u2014 \u043E\u0442\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u0435 \u0430\u0432\u0442\u043E\u043C\u0430\u0442\u0430/\u043A\u043E\u043D\u0442\u0430\u043A\u0442\u043E\u0440\u0430.',
                'trip_stop': '\u0410\u0432\u0430\u0440\u0438\u044F \u043A\u0430\u0442\u0435\u0433\u043E\u0440\u0438\u0438 TRIP & STOP \u2014 \u043E\u0442\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u0435 \u0441 \u043E\u0441\u0442\u0430\u043D\u043E\u0432\u043A\u043E\u0439.',
                'mains_trip': '\u0410\u0432\u0430\u0440\u0438\u044F \u043A\u0430\u0442\u0435\u0433\u043E\u0440\u0438\u0438 MAINS TRIP \u2014 \u043E\u0442\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u0435 \u0430\u0432\u0442\u043E\u043C\u0430\u0442\u0430 \u0441\u0435\u0442\u0438.',
                'warning': '\u041F\u0440\u0435\u0434\u0443\u043F\u0440\u0435\u0436\u0434\u0435\u043D\u0438\u0435 \u2014 \u043D\u0435 \u043F\u0440\u0438\u0432\u043E\u0434\u0438\u0442 \u043A \u043E\u0442\u043A\u043B\u044E\u0447\u0435\u043D\u0438\u044E, \u043D\u043E \u0442\u0440\u0435\u0431\u0443\u0435\u0442 \u0432\u043D\u0438\u043C\u0430\u043D\u0438\u044F.',
                'indication': '\u0418\u043D\u0434\u0438\u043A\u0430\u0446\u0438\u044F \u2014 \u0438\u043D\u0444\u043E\u0440\u043C\u0430\u0446\u0438\u043E\u043D\u043D\u043E\u0435 \u0441\u043E\u043E\u0431\u0449\u0435\u043D\u0438\u0435.',
                'block': '\u0411\u043B\u043E\u043A\u0438\u0440\u043E\u0432\u043A\u0430 \u2014 \u0437\u0430\u043F\u0440\u0435\u0442 \u043E\u043F\u0435\u0440\u0430\u0446\u0438\u0438 \u0434\u043E \u0443\u0441\u0442\u0440\u0430\u043D\u0435\u043D\u0438\u044F \u043F\u0440\u0438\u0447\u0438\u043D\u044B.'
            };

            html += '<div class="alm-section">' +
                '<div class="alm-section-title">\u2139\uFE0F \u0418\u043D\u0444\u043E\u0440\u043C\u0430\u0446\u0438\u044F</div>' +
                '<div class="alm-desc" style="font-size:12px">' +
                    (sevExplanations[severity] || '\u0410\u0432\u0430\u0440\u0438\u044F \u043A\u043E\u043D\u0442\u0440\u043E\u043B\u043B\u0435\u0440\u0430.') +
                '</div>' +
                '<div class="alm-desc" style="margin-top:10px;font-size:12px;color:var(--t3,#6c7a8d)">' +
                    '\u0414\u0435\u0442\u0430\u043B\u044C\u043D\u044B\u0439 \u0441\u043D\u0438\u043C\u043E\u043A \u043C\u0435\u0442\u0440\u0438\u043A \u0431\u0443\u0434\u0435\u0442 \u0434\u043E\u0441\u0442\u0443\u043F\u0435\u043D \u043F\u0440\u0438 \u0441\u043B\u0435\u0434\u0443\u044E\u0449\u0435\u043C \u0441\u0440\u0430\u0431\u0430\u0442\u044B\u0432\u0430\u043D\u0438\u0438 \u043C\u043E\u0434\u0443\u043B\u044F \u0430\u043D\u0430\u043B\u0438\u0442\u0438\u043A\u0438.' +
                '</div>' +
            '</div>';

            // LLM button
            const _dType = defn ? (defn.register_field.startsWith('alarm_reg') ? 'ats' : 'generator') : 'generator';
            html += '<div class="alm-section">' +
                '<button class="alm-llm-btn" id="alm-llm-btn" onclick="window._almAskLLM(\'' + alarmCode + '\',' + (deviceId || 0) + ',\'' + _dType + '\')">' +
                '\uD83E\uDD16 \u0421\u043F\u0440\u043E\u0441\u0438\u0442\u044C \u0421\u0430\u043D\u044C\u043A\u0430 \u2014 \u043F\u043E\u0434\u0440\u043E\u0431\u043D\u044B\u0439 \u0430\u043D\u0430\u043B\u0438\u0437</button>' +
                '<div id="alm-llm-result"></div>' +
            '</div>';

            showModal(html);
        } catch(err) {
            showError('\u041E\u0448\u0438\u0431\u043A\u0430 \u0437\u0430\u0433\u0440\u0443\u0437\u043A\u0438 \u0434\u0430\u043D\u043D\u044B\u0445: ' + err.message);
        }
    }

    // ---------------------------------------------------------------------------
    // Click handler attachment
    // ---------------------------------------------------------------------------
    function extractAlarmCode(el) {
        // Try to extract alarm code from element text content
        // Patterns: "CONN_LOST", "M001", "COMMON", "SHUTDOWN", "WARNING", "BLOCK", "TRIP_STOP"
        const text = el.textContent || '';
        const boldEl = el.querySelector('b');
        if (boldEl) {
            return boldEl.textContent.trim();
        }
        // Fallback: first word after emoji
        const match = text.match(/(?:[\u{1F534}\u26A0\uFE0F\u{1F7E0}\u{1F535}])\s*(\S+)/u);
        return match ? match[1] : null;
    }

    function extractDeviceId(el) {
        // Walk up to find card with device ID
        let node = el;
        while (node) {
            // Check data attribute
            if (node.dataset && node.dataset.deviceId) {
                return parseInt(node.dataset.deviceId, 10);
            }
            // Check id pattern like 'cg1', 'cg2', 'cspr'
            if (node.id) {
                if (typeof window.getDeviceIdForSlot === 'function') {
                    const slot = node.id.replace(/^c/, '');
                    const did = window.getDeviceIdForSlot(slot);
                    if (did) return did;
                }
            }
            node = node.parentElement;
        }
        return null;
    }

    function handleAlarmClick(e) {
        const el = e.currentTarget;

        // Prefer data attributes (set by decodeAlarms in scada-v5.html)
        let code = el.dataset.alarmCode || extractAlarmCode(el);
        if (!code) return;

        // Skip CONN_LOST — handled by base AlarmDetector, not alarm_analytics
        if (code === 'CONN_LOST') return;

        // Summary flags (COMMON, SHUTDOWN, WARNING, BLOCK, TRIP_STOP) —
        // show list of active alarms for the device
        const summaryFlags = ['COMMON', 'SHUTDOWN', 'WARNING', 'BLOCK', 'TRIP_STOP'];
        if (summaryFlags.includes(code)) {
            const deviceId = el.dataset.deviceId ? parseInt(el.dataset.deviceId, 10) : extractDeviceId(el);
            showSummaryFlagModal(code, deviceId);
            return;
        }

        const deviceId = el.dataset.deviceId ? parseInt(el.dataset.deviceId, 10) : extractDeviceId(el);
        fetchAndShowByCode(code, deviceId);
    }

    async function showSummaryFlagModal(code, deviceId) {
        // Summary flags (COMMON, SHUTDOWN, etc.) — show compact info with limited alarm preview
        showLoading();
        try {
            const MAX_PREVIEW = 5; // Show max 5 alarms in preview
            let url = '/api/alarm-analytics/active';
            if (deviceId) url += '?device_id=' + deviceId;
            const resp = await fetch(url);
            let events = [];
            if (resp.ok) events = await resp.json();

            const codeLabels = {
                'COMMON': '\u041E\u0431\u0449\u0430\u044F \u0430\u0432\u0430\u0440\u0438\u044F (COMMON)',
                'SHUTDOWN': '\u0410\u0432\u0430\u0440\u0438\u0439\u043D\u044B\u0439 \u043E\u0441\u0442\u0430\u043D\u043E\u0432 (SHUTDOWN)',
                'WARNING': '\u041F\u0440\u0435\u0434\u0443\u043F\u0440\u0435\u0436\u0434\u0435\u043D\u0438\u0435 (WARNING)',
                'BLOCK': '\u0411\u043B\u043E\u043A\u0438\u0440\u043E\u0432\u043A\u0430 (BLOCK)',
                'TRIP_STOP': '\u0410\u0432\u0430\u0440\u0438\u0439\u043D\u044B\u0439 \u0441\u0442\u043E\u043F (TRIP_STOP)'
            };
            const codeDescriptions = {
                'COMMON': '\u0421\u0443\u043C\u043C\u0430\u0440\u043D\u044B\u0439 \u0431\u0438\u0442 \u0430\u0432\u0430\u0440\u0438\u0438 \u043A\u043E\u043D\u0442\u0440\u043E\u043B\u043B\u0435\u0440\u0430. \u0410\u043A\u0442\u0438\u0432\u0438\u0440\u0443\u0435\u0442\u0441\u044F \u043A\u043E\u0433\u0434\u0430 \u0435\u0441\u0442\u044C \u0445\u043E\u0442\u044F \u0431\u044B \u043E\u0434\u043D\u0430 \u0430\u043A\u0442\u0438\u0432\u043D\u0430\u044F \u0430\u0432\u0430\u0440\u0438\u044F \u043B\u044E\u0431\u043E\u0433\u043E \u0442\u0438\u043F\u0430.',
                'SHUTDOWN': '\u0421\u0443\u043C\u043C\u0430\u0440\u043D\u044B\u0439 \u0431\u0438\u0442 \u043A\u0440\u0438\u0442\u0438\u0447\u0435\u0441\u043A\u0438\u0445 \u0430\u0432\u0430\u0440\u0438\u0439. \u0410\u043A\u0442\u0438\u0432\u0438\u0440\u0443\u0435\u0442\u0441\u044F \u043F\u0440\u0438 \u043D\u0430\u043B\u0438\u0447\u0438\u0438 \u0430\u0432\u0430\u0440\u0438\u0439 \u043A\u0430\u0442\u0435\u0433\u043E\u0440\u0438\u0438 Shutdown.',
                'WARNING': '\u0421\u0443\u043C\u043C\u0430\u0440\u043D\u044B\u0439 \u0431\u0438\u0442 \u043F\u0440\u0435\u0434\u0443\u043F\u0440\u0435\u0436\u0434\u0435\u043D\u0438\u0439. \u0410\u043A\u0442\u0438\u0432\u0438\u0440\u0443\u0435\u0442\u0441\u044F \u043F\u0440\u0438 \u043D\u0430\u043B\u0438\u0447\u0438\u0438 \u043F\u0440\u0435\u0434\u0443\u043F\u0440\u0435\u0436\u0434\u0435\u043D\u0438\u0439.',
                'BLOCK': '\u0421\u0443\u043C\u043C\u0430\u0440\u043D\u044B\u0439 \u0431\u0438\u0442 \u0431\u043B\u043E\u043A\u0438\u0440\u043E\u0432\u043E\u043A. \u0410\u043A\u0442\u0438\u0432\u0438\u0440\u0443\u0435\u0442\u0441\u044F \u043F\u0440\u0438 \u043D\u0430\u043B\u0438\u0447\u0438\u0438 \u0430\u043A\u0442\u0438\u0432\u043D\u044B\u0445 \u0431\u043B\u043E\u043A\u0438\u0440\u043E\u0432\u043E\u043A.',
                'TRIP_STOP': '\u0421\u0443\u043C\u043C\u0430\u0440\u043D\u044B\u0439 \u0431\u0438\u0442 \u0430\u0432\u0430\u0440\u0438\u0439\u043D\u043E\u0433\u043E \u0441\u0442\u043E\u043F\u0430. \u0410\u043A\u0442\u0438\u0432\u0438\u0440\u0443\u0435\u0442\u0441\u044F \u043F\u0440\u0438 \u043D\u0430\u043B\u0438\u0447\u0438\u0438 \u0430\u0432\u0430\u0440\u0438\u0439 \u043A\u0430\u0442\u0435\u0433\u043E\u0440\u0438\u0438 Trip & Stop.'
            };
            const codeSeverity = {
                'COMMON': 'warning', 'SHUTDOWN': 'shutdown', 'WARNING': 'warning',
                'BLOCK': 'block', 'TRIP_STOP': 'trip_stop'
            };

            const severity = codeSeverity[code] || 'warning';
            let html = '<div class="alm-header">' +
                '<button class="alm-close" onclick="document.querySelector(\'.alm-overlay\').click()">&times;</button>' +
                '<div class="alm-title">' + severityEmoji(severity) + ' ' +
                (codeLabels[code] || code) + '</div>' +
                '<div class="alm-meta">' +
                    '<span>\u0421\u0443\u043C\u043C\u0430\u0440\u043D\u044B\u0439 \u0444\u043B\u0430\u0433 \u0430\u0432\u0430\u0440\u0438\u0438</span>' +
                    '<span class="alm-badge alm-badge-' + severity + '">' + severityLabel(severity) + '</span>' +
                '</div>' +
            '</div>';

            // Description
            html += '<div class="alm-section">' +
                '<div class="alm-section-title">\uD83D\uDCD6 \u041E\u043F\u0438\u0441\u0430\u043D\u0438\u0435</div>' +
                '<div class="alm-desc">' + (codeDescriptions[code] || '\u0421\u0443\u043C\u043C\u0430\u0440\u043D\u044B\u0439 \u0431\u0438\u0442 \u0430\u0432\u0430\u0440\u0438\u0438 \u043A\u043E\u043D\u0442\u0440\u043E\u043B\u043B\u0435\u0440\u0430.') + '</div>' +
            '</div>';

            // Compact summary: count + limited preview
            if (events.length > 0) {
                const preview = events.slice(0, MAX_PREVIEW);
                const remaining = events.length - preview.length;

                html += '<div class="alm-section">' +
                    '<div class="alm-section-title">\uD83D\uDD0D \u0410\u043A\u0442\u0438\u0432\u043D\u044B\u0435 \u0430\u0432\u0430\u0440\u0438\u0438: ' + events.length + '</div>';
                for (const ev of preview) {
                    const sev = ev.alarm_severity || 'warning';
                    html += '<div style="display:flex;align-items:center;gap:8px;' +
                        'padding:6px 12px;margin-bottom:3px;background:var(--bg3);' +
                        'border-radius:6px;cursor:pointer;border:1px solid var(--bd);transition:background 0.15s" ' +
                        'onmouseover="this.style.background=\'var(--bg4)\'" ' +
                        'onmouseout="this.style.background=\'var(--bg3)\'" ' +
                        'onclick="window.almShowByCode(\'' + ev.alarm_code + '\',' + (ev.device_id || 'null') + ')">' +
                        '<span style="font-size:14px">' + severityEmoji(sev) + '</span>' +
                        '<b style="font-family:monospace;font-size:12px;color:var(--t,#e0e6ed)">' + ev.alarm_code + '</b> ' +
                        '<span style="flex:1;font-size:12px;color:var(--t2,#a0aec0)">' + ev.alarm_name_ru + '</span>' +
                    '</div>';
                }
                if (remaining > 0) {
                    html += '<div style="font-size:12px;color:var(--t3,#6c7a8d);margin-top:6px;text-align:center">' +
                        '\u0438 \u0435\u0449\u0451 ' + remaining + ' \u0430\u0432\u0430\u0440\u0438' +
                        (remaining === 1 ? '\u044F' : (remaining < 5 ? '\u0438' : '\u0439')) +
                    '</div>';
                }
                // Button to open full alarms page
                html += '<div style="margin-top:12px;text-align:center">' +
                    '<button onclick="document.querySelector(\'.alm-overlay\').click();if(typeof showAlarms===\'function\')showAlarms();" ' +
                    'style="background:var(--p,#60a5fa);color:#fff;border:none;border-radius:6px;' +
                    'padding:8px 20px;font-size:13px;cursor:pointer;transition:opacity 0.15s" ' +
                    'onmouseover="this.style.opacity=\'0.85\'" onmouseout="this.style.opacity=\'1\'">' +
                    '\u041E\u0442\u043A\u0440\u044B\u0442\u044C \u0441\u0442\u0440\u0430\u043D\u0438\u0446\u0443 \u0430\u0432\u0430\u0440\u0438\u0439</button>' +
                '</div></div>';
            } else {
                html += '<div class="alm-section">' +
                    '<div class="alm-desc" style="color:var(--t3,#6c7a8d);font-size:12px">' +
                    '\u041D\u0435\u0442 \u0430\u043A\u0442\u0438\u0432\u043D\u044B\u0445 \u0430\u0432\u0430\u0440\u0438\u0439 \u0432 \u043C\u043E\u0434\u0443\u043B\u0435 \u0430\u043D\u0430\u043B\u0438\u0442\u0438\u043A\u0438.' +
                    '</div></div>';
            }

            showModal(html);
        } catch (err) {
            showModal(
                '<div class="alm-header">' +
                    '<button class="alm-close" onclick="document.querySelector(\'.alm-overlay\').click()">&times;</button>' +
                    '<div class="alm-title">' + severityEmoji('warning') + ' ' + code + '</div>' +
                '</div>' +
                '<div class="alm-section">' +
                    '<div class="alm-desc">' +
                    '\u042D\u0442\u043E \u0441\u0443\u043C\u043C\u0430\u0440\u043D\u044B\u0439 \u0444\u043B\u0430\u0433 \u0430\u0432\u0430\u0440\u0438\u0438. \u041D\u0435 \u0443\u0434\u0430\u043B\u043E\u0441\u044C \u0437\u0430\u0433\u0440\u0443\u0437\u0438\u0442\u044C \u0434\u0435\u0442\u0430\u043B\u0438: ' + err.message +
                    '</div>' +
                '</div>'
            );
        }
    }

    function attachHandlers() {
        const items = document.querySelectorAll('.ai');
        items.forEach(el => {
            if (el._almBound) return;
            el._almBound = true;
            el.style.cursor = 'pointer';
            el.addEventListener('click', handleAlarmClick);
        });
    }

    // Also handle alarms on the Alarms page (almH-list items)
    function attachAlarmsPageHandlers() {
        const rows = document.querySelectorAll('[data-alarm-id]');
        rows.forEach(el => {
            if (el._almBound) return;
            el._almBound = true;
            el.style.cursor = 'pointer';
            el.addEventListener('click', function() {
                const eventId = el.dataset.alarmId;
                if (eventId) fetchAndShowEvent(parseInt(eventId, 10));
            });
        });
    }

    // Keyboard: Escape to close
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') closeModal();
    });

    // Observe DOM for new .ai elements (alarm items are dynamically generated)
    // Debounced to avoid excessive calls during real-time metric updates
    let _almObsTimer = null;
    const observer = new MutationObserver(function() {
        if (_almObsTimer) clearTimeout(_almObsTimer);
        _almObsTimer = setTimeout(function() {
            attachHandlers();
            attachAlarmsPageHandlers();
        }, 300);
    });
    observer.observe(document.body, { childList: true, subtree: true });

    // Initial attachment
    attachHandlers();

    // LLM explain function (calls POST /api/alarm-analytics/explain)
    window._almAskLLM = async function(alarmCode, deviceId, deviceType) {
        const btn = document.getElementById('alm-llm-btn');
        const resultDiv = document.getElementById('alm-llm-result');
        if (!btn || !resultDiv) return;

        btn.disabled = true;
        btn.innerHTML = '<span class="alm-llm-spinner"></span> Санёк анализирует...';
        resultDiv.innerHTML = '';

        try {
            const resp = await fetch('/api/alarm-analytics/explain', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    alarm_code: alarmCode,
                    device_id: deviceId || 0,
                    device_type: deviceType || 'generator',
                }),
            });
            const data = await resp.json();
            if (data.success && data.explanation) {
                resultDiv.innerHTML = '<div class="alm-llm-result">' +
                    '<div style="font-size:11px;color:var(--t3);margin-bottom:8px;display:flex;align-items:center;gap:6px">' +
                    '\uD83E\uDD16 <b>\u0421\u0430\u043D\u0451\u043A</b> \u2014 AI-\u0430\u043D\u0430\u043B\u0438\u0437</div>' +
                    data.explanation.replace(/\n/g, '<br>') +
                '</div>';
                btn.innerHTML = '\u2705 \u0410\u043D\u0430\u043B\u0438\u0437 \u043F\u043E\u043B\u0443\u0447\u0435\u043D';
            } else {
                resultDiv.innerHTML = '<div style="color:#f87171;font-size:12px;margin-top:8px">\u2717 ' +
                    (data.error || '\u041D\u0435 \u0443\u0434\u0430\u043B\u043E\u0441\u044C \u043F\u043E\u043B\u0443\u0447\u0438\u0442\u044C \u0430\u043D\u0430\u043B\u0438\u0437') + '</div>';
                btn.disabled = false;
                btn.innerHTML = '\uD83E\uDD16 \u041F\u043E\u043F\u0440\u043E\u0431\u043E\u0432\u0430\u0442\u044C \u0441\u043D\u043E\u0432\u0430';
            }
        } catch (err) {
            resultDiv.innerHTML = '<div style="color:#f87171;font-size:12px;margin-top:8px">\u2717 \u041E\u0448\u0438\u0431\u043A\u0430: ' + err.message + '</div>';
            btn.disabled = false;
            btn.innerHTML = '\uD83E\uDD16 \u041F\u043E\u043F\u0440\u043E\u0431\u043E\u0432\u0430\u0442\u044C \u0441\u043D\u043E\u0432\u0430';
        }
    };

    // Export for external use
    window.almShowEvent = fetchAndShowEvent;
    window.almShowByCode = fetchAndShowByCode;

    console.log('[alarm_modal.js] Alarm Analytics modal loaded');
})();
