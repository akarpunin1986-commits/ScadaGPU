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
            background: var(--bg-card, #1e2430); color: var(--t1, #e0e6ed);
            border-radius: 12px; max-width: 720px; width: 95%;
            max-height: 85vh; overflow-y: auto;
            box-shadow: 0 20px 60px rgba(0,0,0,0.5);
            transform: translateY(20px); transition: transform 0.2s ease;
            border: 1px solid rgba(255,255,255,0.08);
        }
        .alm-overlay.alm-show .alm-modal { transform: translateY(0); }
        .alm-header {
            padding: 20px 24px 16px; border-bottom: 1px solid rgba(255,255,255,0.06);
            position: relative;
        }
        .alm-close {
            position: absolute; top: 12px; right: 16px; background: none; border: none;
            color: var(--t3, #6c7a8d); font-size: 22px; cursor: pointer;
            width: 32px; height: 32px; display: flex; align-items: center; justify-content: center;
            border-radius: 6px; transition: all 0.15s;
        }
        .alm-close:hover { background: rgba(255,255,255,0.08); color: var(--t1, #e0e6ed); }
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
            padding: 16px 24px; border-bottom: 1px solid rgba(255,255,255,0.04);
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
            background: rgba(255,255,255,0.03); border-radius: 8px; padding: 12px;
            border: 1px solid rgba(255,255,255,0.05);
        }
        .alm-mg-title {
            font-size: 10px; text-transform: uppercase; font-weight: 600;
            color: var(--t3, #6c7a8d); margin-bottom: 8px; letter-spacing: 0.5px;
        }
        .alm-mg-row {
            font-size: 12px; color: var(--t2, #a0aec0); padding: 2px 0;
            display: flex; justify-content: space-between;
        }
        .alm-mg-val { font-family: 'JetBrains Mono', monospace; color: var(--t1, #e0e6ed); }
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
            font-size: 13px; line-height: 1.6; color: var(--t1, #e0e6ed);
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

        // Section: Description
        const analysis = ev.analysis_result || {};
        if (analysis.manual_description) {
            html += `<div class="alm-section">
                <div class="alm-section-title">\u{1F4D6} Описание</div>
                <div class="alm-desc">${analysis.manual_description}</div>
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
                // No event in DB — show basic info from definitions
                await showDefinitionOnly(alarmCode);
            }
        } catch (err) {
            showError('Не удалось загрузить данные аварии: ' + err.message);
        }
    }

    async function showDefinitionOnly(alarmCode) {
        try {
            const resp = await fetch('/api/alarm-analytics/definitions');
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const defs = await resp.json();
            const defn = defs.find(d => d.code === alarmCode);
            if (defn) {
                showModal(`
                    <div class="alm-header">
                        <button class="alm-close" onclick="document.querySelector('.alm-overlay').click()">&times;</button>
                        <div class="alm-title">${severityEmoji(defn.severity)} ${defn.code} ${defn.name_ru}</div>
                        <div class="alm-meta">
                            <span>${defn.name}</span>
                            <span class="alm-badge alm-badge-${defn.severity}">${severityLabel(defn.severity)}</span>
                        </div>
                    </div>
                    <div class="alm-section">
                        <div class="alm-section-title">\u{1F4D6} Описание</div>
                        <div class="alm-desc">${defn.name_ru}</div>
                        <div class="alm-desc" style="margin-top:8px;color:var(--t3);font-size:12px">
                            Детальный снимок метрик и анализ причины будут доступны после следующего возникновения этой аварии.
                        </div>
                    </div>
                `);
            } else {
                showError('Определение аварии не найдено: ' + alarmCode);
            }
        } catch(err) {
            showError('Ошибка загрузки определений: ' + err.message);
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
        const code = extractAlarmCode(el);
        if (!code) return;

        // Skip CONN_LOST — handled by base AlarmDetector, not alarm_analytics
        if (code === 'CONN_LOST') return;

        // Summary flags (COMMON, SHUTDOWN, WARNING, BLOCK, TRIP_STOP) don't have
        // detailed analytics — they're summary bits. Show info message.
        const summaryFlags = ['COMMON', 'SHUTDOWN', 'WARNING', 'BLOCK', 'TRIP_STOP'];
        if (summaryFlags.includes(code)) {
            showModal(`
                <div class="alm-header">
                    <button class="alm-close" onclick="document.querySelector('.alm-overlay').click()">&times;</button>
                    <div class="alm-title">${severityEmoji('warning')} ${code}</div>
                </div>
                <div class="alm-section">
                    <div class="alm-desc">
                        Это суммарный флаг аварии. Детальная информация доступна по отдельным аварийным кодам (M001-M008, G_SD_* и т.д.).
                    </div>
                    <div class="alm-desc" style="margin-top:8px;color:var(--t3);font-size:12px">
                        Когда модуль аналитики обнаружит конкретный бит аварии, по клику будет доступен полный анализ.
                    </div>
                </div>
            `);
            return;
        }

        const deviceId = extractDeviceId(el);
        fetchAndShowByCode(code, deviceId);
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
    const observer = new MutationObserver(function() {
        attachHandlers();
        attachAlarmsPageHandlers();
    });
    observer.observe(document.body, { childList: true, subtree: true });

    // Initial attachment
    attachHandlers();

    // Export for external use
    window.almShowEvent = fetchAndShowEvent;
    window.almShowByCode = fetchAndShowByCode;

    console.log('[alarm_modal.js] Alarm Analytics modal loaded');
})();
