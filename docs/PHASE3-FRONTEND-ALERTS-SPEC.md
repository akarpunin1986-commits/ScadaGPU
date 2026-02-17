# Phase 3 Task 4 — Фронтенд: алерты ТО из backend

## Цель
Подключить фронтенд к backend-алертам техобслуживания:
1. WS-сообщения `maintenance_alert` обновляют карточки генераторов и статус объекта в реальном времени
2. При загрузке страницы — запрос `GET /api/alerts` для начального состояния
3. Кнопка acknowledge — оператор подтверждает уведомление
4. Полностью заменить localStorage-логику расчёта ТО на backend-данные

**Файл для изменения:** `frontend/scada-v3.html` (один файл)

---

## Обзор изменений

| # | Область | Что делать |
|---|---------|-----------|
| 1 | Глобальное состояние | Добавить переменную `maintenanceAlerts = {}` |
| 2 | WS onmessage (~L777) | Добавить обработку `type === 'maintenance_alert'` |
| 3 | Загрузка страницы (~L522) | Добавить `loadMaintenanceAlerts()` при инициализации |
| 4 | Карточки генераторов | Обновлять ТО-секцию из backend-алертов вместо localStorage |
| 5 | Статус объекта | Показывать значок ТО в `statusCard` / `statusText` |
| 6 | Алерт-бейджи на карточках | Добавить ТО-бейджи в `alerts-g1` / `alerts-g2` |
| 7 | Модальное окно алертов | Показывать ТО-алерты в модалке при клике |

---

## Изменение 1: Глобальное состояние

**Где:** после строки с `let toData = {};` (~строка 1102)

**Добавить:**
```javascript
// ---- Maintenance alerts from backend (Phase 3) ----
let maintenanceAlerts = {};  // { device_id: { alert_id, severity, status, ... } }
```

---

## Изменение 2: WS onmessage — обработка maintenance_alert

**Где:** внутри `ws.onmessage` (~строка 775-789)

**Текущий код:**
```javascript
ws.onmessage = (event) => {
    try {
        const msg = JSON.parse(event.data);
        if (msg.type === 'snapshot' && Array.isArray(msg.data)) {
            for (const m of msg.data) {
                applyMetrics(m);
            }
        } else if (msg.device_id !== undefined) {
            applyMetrics(msg);
        }
    } catch (e) {
        console.warn('[WS] parse error', e);
    }
};
```

**Заменить на:**
```javascript
ws.onmessage = (event) => {
    try {
        const msg = JSON.parse(event.data);
        if (msg.type === 'snapshot' && Array.isArray(msg.data)) {
            for (const m of msg.data) {
                applyMetrics(m);
            }
        } else if (msg.type === 'maintenance_alert') {
            applyMaintenanceAlert(msg);
        } else if (msg.device_id !== undefined) {
            applyMetrics(msg);
        }
    } catch (e) {
        console.warn('[WS] parse error', e);
    }
};
```

Единственное добавление — блок `else if (msg.type === 'maintenance_alert')` **ПЕРЕД** блоком `else if (msg.device_id !== undefined)`.

---

## Изменение 3: Загрузка алертов при инициализации

**Где:** в функции `load()` (~строка 522), после строк `initTOData(id, 'g1'); initTOData(id, 'g2');`

**Добавить вызов:**
```javascript
// Load maintenance alerts from backend
loadMaintenanceAlerts();
```

**Новая функция** (добавить после `updateTOProgress` ~строка 1226):

```javascript
// ===========================================================================
// Maintenance Alerts from Backend (Phase 3)
// ===========================================================================

async function loadMaintenanceAlerts() {
    try {
        const alerts = await api.get('/api/alerts');
        // Reset state
        maintenanceAlerts = {};
        for (const a of alerts) {
            maintenanceAlerts[a.device_id] = a;
        }
        // Apply to UI
        applyAllMaintenanceAlerts();
        console.log('[TO] Loaded', alerts.length, 'maintenance alerts from backend');
    } catch (e) {
        console.warn('[TO] Failed to load alerts:', e);
    }
}
```

---

## Изменение 4: Функция обработки WS-алерта

**Добавить после `loadMaintenanceAlerts`:**

```javascript
function applyMaintenanceAlert(msg) {
    const action = msg.action; // "created" | "updated" | "resolved"
    const alert = msg.alert;

    if (!alert || !alert.device_id) return;

    if (action === 'resolved') {
        delete maintenanceAlerts[alert.device_id];
    } else {
        maintenanceAlerts[alert.device_id] = alert;
    }

    // Update UI for this specific device
    applyDeviceMaintenanceAlert(alert.device_id);
    // Update site-level status
    updateMaintenanceStatusBadge();
}
```

---

## Изменение 5: Отображение алерта на карточке генератора

**Добавить:**

```javascript
function applyAllMaintenanceAlerts() {
    // Apply each alert to its device card
    for (const deviceId of Object.keys(maintenanceAlerts)) {
        applyDeviceMaintenanceAlert(parseInt(deviceId));
    }
    // Also clear any device cards that no longer have alerts
    for (const did of Object.keys(deviceSlotIndex)) {
        if (!maintenanceAlerts[did]) {
            applyDeviceMaintenanceAlert(parseInt(did));
        }
    }
    updateMaintenanceStatusBadge();
}

function applyDeviceMaintenanceAlert(deviceId) {
    // Find which slot (g1/g2) this device maps to
    const entry = deviceSlotIndex[deviceId];
    if (!entry) return;
    if (entry.siteKey !== currentSite) return;

    const slot = entry.slot; // 'g1' or 'g2'
    const alert = maintenanceAlerts[deviceId];

    // ---- Update TO section on generator card ----
    const nameEl = $(slot + '-to-name');
    const remainEl = $(slot + '-to-remain');
    const barEl = $(slot + '-to-bar');
    const warnEl = $(slot + '-to-warn');
    const warnTextEl = $(slot + '-to-warn-text');

    if (!alert) {
        // No alert — reset to normal (green)
        if (nameEl) nameEl.textContent = 'ТО';
        if (remainEl) {
            remainEl.textContent = 'норма';
            remainEl.className = 'text-slate-400';
        }
        if (barEl) {
            barEl.style.width = '0%';
            barEl.className = 'h-full bg-green-500 rounded-full transition-all';
        }
        if (warnEl) warnEl.classList.add('hidden');
        // Remove TO badge from card
        _removeAlertBadge(slot);
        return;
    }

    // ---- Has alert: show severity ----
    const severity = alert.severity; // "warning" | "critical" | "overdue"
    const remaining = alert.hours_remaining;
    const intervalName = alert.interval_name;
    const intervalHours = alert.interval_hours;
    const engineHours = alert.engine_hours;

    // Name
    if (nameEl) nameEl.textContent = intervalName;

    // Remaining text
    if (remainEl) {
        if (severity === 'overdue') {
            remainEl.textContent = 'просрочено на ' + Math.abs(Math.round(remaining)) + ' ч';
            remainEl.className = 'text-red-400 font-medium';
        } else {
            remainEl.textContent = 'через ' + Math.round(remaining) + ' ч';
            remainEl.className = severity === 'critical' ? 'text-orange-400' : 'text-yellow-400';
        }
    }

    // Progress bar
    if (barEl) {
        const hoursAt = alert.hours_remaining !== undefined
            ? intervalHours - remaining
            : 0;
        const pct = Math.min(100, Math.max(0, (hoursAt / intervalHours) * 100));
        barEl.style.width = pct + '%';

        if (severity === 'overdue') {
            barEl.className = 'h-full bg-red-500 rounded-full transition-all animate-pulse';
        } else if (severity === 'critical') {
            barEl.className = 'h-full bg-orange-500 rounded-full transition-all';
        } else {
            barEl.className = 'h-full bg-yellow-500 rounded-full transition-all';
        }
    }

    // Warning label
    if (warnEl && warnTextEl) {
        warnEl.classList.remove('hidden', 'text-yellow-400', 'text-orange-400', 'text-red-400');
        if (severity === 'overdue') {
            warnEl.classList.add('text-red-400');
            warnTextEl.textContent = intervalName + ' просрочено! Требуется обслуживание';
        } else if (severity === 'critical') {
            warnEl.classList.add('text-orange-400');
            warnTextEl.textContent = intervalName + ' через ' + Math.round(remaining) + ' ч';
        } else {
            warnEl.classList.add('text-yellow-400');
            warnTextEl.textContent = intervalName + ' через ' + Math.round(remaining) + ' ч';
        }
    }

    // Add TO alert badge on card
    _setAlertBadge(slot, severity, intervalName, remaining);
}
```

---

## Изменение 6: Бейджи ТО-алертов на карточках

**Добавить:**

```javascript
const toAlertIcons = {
    warning:  `<span class="flex items-center gap-1 px-1.5 py-0.5 bg-yellow-500/20 text-yellow-400 text-xs rounded cursor-pointer" title="ТО скоро">🔧</span>`,
    critical: `<span class="flex items-center gap-1 px-1.5 py-0.5 bg-orange-500/20 text-orange-400 text-xs rounded cursor-pointer animate-pulse" title="ТО скоро!">🔧</span>`,
    overdue:  `<span class="flex items-center gap-1 px-1.5 py-0.5 bg-red-500/20 text-red-400 text-xs rounded cursor-pointer animate-pulse" title="ТО просрочено!">🔧⚠</span>`,
};

function _setAlertBadge(slot, severity, intervalName, remaining) {
    const container = $('alerts-' + slot);
    if (!container) return;

    // Remove old TO badge if exists
    const old = container.querySelector('[data-to-badge]');
    if (old) old.remove();

    const badge = document.createElement('span');
    badge.setAttribute('data-to-badge', '1');
    badge.className = _badgeClass(severity);
    badge.title = severity === 'overdue'
        ? intervalName + ' просрочено!'
        : intervalName + ' через ' + Math.round(remaining) + ' ч';
    badge.innerHTML = '🔧' + (severity === 'overdue' ? '⚠' : '');
    badge.onclick = (e) => {
        e.stopPropagation();
        openMaintenanceAlertModal(slot);
    };
    container.appendChild(badge);

    // Add card highlight
    const card = $('card-' + slot);
    if (card) {
        card.classList.remove('warning'); // Don't override alarm class
        if (severity === 'overdue' || severity === 'critical') {
            if (!card.classList.contains('alarm')) {
                card.classList.add('warning');
            }
        }
    }
}

function _badgeClass(severity) {
    const base = 'flex items-center gap-1 px-1.5 py-0.5 text-xs rounded cursor-pointer';
    if (severity === 'overdue') return base + ' bg-red-500/20 text-red-400 animate-pulse';
    if (severity === 'critical') return base + ' bg-orange-500/20 text-orange-400 animate-pulse';
    return base + ' bg-yellow-500/20 text-yellow-400';
}

function _removeAlertBadge(slot) {
    const container = $('alerts-' + slot);
    if (!container) return;
    const old = container.querySelector('[data-to-badge]');
    if (old) old.remove();
}
```

---

## Изменение 7: Статус ТО в общем статусе объекта

**Добавить функцию:**

```javascript
function updateMaintenanceStatusBadge() {
    // Count active alerts by severity
    let overdueCount = 0, criticalCount = 0, warningCount = 0;
    for (const a of Object.values(maintenanceAlerts)) {
        if (a.severity === 'overdue') overdueCount++;
        else if (a.severity === 'critical') criticalCount++;
        else if (a.severity === 'warning') warningCount++;
    }

    const total = overdueCount + criticalCount + warningCount;
    if (total === 0) return; // Don't override alarm-based status

    // Inject TO indicator into statusText if not alarm
    const statusText = $('statusText');
    const statusCard = $('statusCard');
    if (!statusText || !statusCard) return;

    // Check if there's already an alarm/warning from device alarms
    const hasDeviceAlarm = statusCard.classList.contains('alarm');
    if (hasDeviceAlarm) return; // Device alarms take priority

    if (overdueCount > 0) {
        statusText.innerHTML = `<span class="dot dot-red"></span><span class="text-red-400">ТО просрочено</span><span class="ml-2 text-xs text-red-400">🔧 ${overdueCount}</span>`;
        statusCard.classList.add('warning');
    } else if (criticalCount > 0) {
        statusText.innerHTML = `<span class="dot dot-yellow animate-pulse"></span><span class="text-orange-400">ТО скоро</span><span class="ml-2 text-xs text-orange-400">🔧 ${criticalCount}</span>`;
        statusCard.classList.add('warning');
    } else if (warningCount > 0) {
        statusText.innerHTML = `<span class="dot dot-yellow"></span><span class="text-yellow-400">ТО приближается</span><span class="ml-2 text-xs text-yellow-400">🔧 ${warningCount}</span>`;
    }
}
```

**Обновить** `renderAlarms()` (~строка 2610, в конце функции):

После последнего `else` блока (строка `statusText.innerHTML = \`...Норма...\``) добавить вызов:
```javascript
    // After device alarm status is set, overlay TO alerts if needed
    updateMaintenanceStatusBadge();
```

---

## Изменение 8: Модальное окно алерта ТО

**Добавить функцию:**

```javascript
function openMaintenanceAlertModal(slot) {
    // Find device_id for this slot
    let deviceId = null;
    for (const [did, entry] of Object.entries(deviceSlotIndex)) {
        if (entry.slot === slot && entry.siteKey === currentSite) {
            deviceId = parseInt(did);
            break;
        }
    }
    if (!deviceId) return;

    const alert = maintenanceAlerts[deviceId];
    if (!alert) return;

    const severityLabels = {
        warning: '<span class="text-yellow-400">⚠ Предупреждение</span>',
        critical: '<span class="text-orange-400">⚠ Критично</span>',
        overdue: '<span class="text-red-400">⛔ Просрочено</span>',
    };

    const statusLabels = {
        active: 'Активен',
        acknowledged: 'Подтверждён',
        resolved: 'Решён',
    };

    let html = `
        <div class="space-y-4">
            <div class="bg-slate-800 rounded-lg p-4">
                <div class="flex items-center justify-between mb-3">
                    <span class="text-lg font-medium">${alert.interval_name}</span>
                    ${severityLabels[alert.severity] || ''}
                </div>
                <div class="grid grid-cols-2 gap-3 text-sm">
                    <div>
                        <span class="text-slate-500">Устройство:</span>
                        <span class="ml-2">${alert.device_name}</span>
                    </div>
                    <div>
                        <span class="text-slate-500">Интервал:</span>
                        <span class="ml-2">${alert.interval_hours} ч</span>
                    </div>
                    <div>
                        <span class="text-slate-500">Моточасы:</span>
                        <span class="ml-2 text-white font-medium">${Math.round(alert.engine_hours)} ч</span>
                    </div>
                    <div>
                        <span class="text-slate-500">Осталось:</span>
                        <span class="ml-2 ${alert.severity === 'overdue' ? 'text-red-400' : 'text-yellow-400'} font-medium">
                            ${alert.hours_remaining > 0 ? Math.round(alert.hours_remaining) + ' ч' : 'просрочено на ' + Math.abs(Math.round(alert.hours_remaining)) + ' ч'}
                        </span>
                    </div>
                    <div>
                        <span class="text-slate-500">Статус:</span>
                        <span class="ml-2">${statusLabels[alert.status] || alert.status}</span>
                    </div>
                    <div>
                        <span class="text-slate-500">Создан:</span>
                        <span class="ml-2">${new Date(alert.created_at).toLocaleString('ru')}</span>
                    </div>
                </div>
                <p class="mt-3 text-sm text-slate-400">${alert.message}</p>
            </div>

            <div class="flex gap-2">
    `;

    // Acknowledge button (only if active)
    if (alert.status === 'active') {
        html += `
                <button onclick="acknowledgeAlert(${alert.id}, '${slot}')"
                    class="flex-1 py-2 bg-blue-600 hover:bg-blue-500 rounded text-sm font-medium">
                    ✓ Подтвердить
                </button>
        `;
    }

    // Open TO Manager button
    html += `
                <button onclick="closeModal(); openTOManager('${slot}')"
                    class="flex-1 py-2 bg-green-700 hover:bg-green-600 rounded text-sm font-medium">
                    🔧 Провести ТО
                </button>
            </div>
        </div>
    `;

    $('modalTitle').textContent = '🔧 Техобслуживание — ' + alert.device_name;
    $('modalContent').innerHTML = html;
    $('modal').classList.remove('hidden');
}
```

---

## Изменение 9: Функция acknowledge

**Добавить:**

```javascript
async function acknowledgeAlert(alertId, slot) {
    const name = prompt('Ваше имя для подтверждения:');
    if (!name) return;

    try {
        const updated = await api.patch('/api/alerts/' + alertId + '/acknowledge', {
            acknowledged_by: name,
        });
        // Update local state
        if (maintenanceAlerts[updated.device_id]) {
            maintenanceAlerts[updated.device_id] = updated;
        }
        closeModal();
        applyDeviceMaintenanceAlert(updated.device_id);
        updateMaintenanceStatusBadge();
        console.log('[TO] Alert acknowledged:', alertId);
    } catch (e) {
        alert('Ошибка: ' + e.message);
    }
}
```

---

## Изменение 10: Обновить `_applyGeneratorMetrics` — вызов backend-статуса вместо localStorage

**Где:** в `_applyGeneratorMetrics(slot, m)` (~строка 848), найти строку:
```javascript
updateTOProgress(slot, m.run_hours);
```

**Заменить на:**
```javascript
// TO progress now driven by backend alerts (Phase 3 scheduler)
// Keep updating local TO data for the openTOManager to work
updateTOProgress(slot, m.run_hours);
// Backend alert overlay (takes visual priority)
const did = m.device_id;
if (maintenanceAlerts[did]) {
    applyDeviceMaintenanceAlert(did);
}
```

**Логика:** `updateTOProgress` продолжает работать как запасной вариант (localStorage). Но если есть backend-алерт для этого device, `applyDeviceMaintenanceAlert` перезаписывает визуал карточки данными из бэкенда. Backend — источник правды.

---

## Изменение 11: Обновить `renderAlarms()` — интеграция

**Где:** в конце функции `renderAlarms()` (~строка 2610), после последнего блока `statusText.innerHTML`:

**Добавить:**
```javascript
    // Overlay maintenance TO status (from backend scheduler)
    updateMaintenanceStatusBadge();
```

---

## Порядок приоритетов отображения

1. **Аварии устройства** (alarm) — красный, высший приоритет
2. **ТО просрочено** (overdue) — красный, но не перезаписывает аварию
3. **ТО критично** (critical, ≤20ч) — оранжевый
4. **ТО предупреждение** (warning, ≤50ч) — жёлтый
5. **Норма** — зелёный

---

## Тестирование

### 1. Запустить в DEMO_MODE
```bash
docker compose up
```
Backend с demo poller + scheduler. Через 30 сек scheduler создаст алерты.

### 2. Открыть фронт
```
http://localhost:8011
```
Проверить:
- Карточки g1/g2 показывают ТО-прогресс из backend
- Если ТО скоро — жёлтый/оранжевый бейдж 🔧 на карточке
- В статусе объекта (правая карточка) — «ТО приближается» / «ТО скоро» / «ТО просрочено»

### 3. Клик по бейджу 🔧
- Открывается модалка с деталями алерта
- Кнопка «Подтвердить» → вводим имя → PATCH /api/alerts/{id}/acknowledge
- Кнопка «Провести ТО» → открывается менеджер ТО

### 4. WebSocket realtime
Открыть DevTools → Console. Подождать 30 сек.
Ожидание: сообщения `[TO] Loaded N maintenance alerts from backend` при загрузке, затем WS-обновления в реальном времени.

### 5. После проведения ТО
Провести ТО через модалку → scheduler через 30 сек пересчитает → алерт станет resolved → бейдж исчезнет.

---

## Чеклист готовности

- [ ] Глобальная переменная `maintenanceAlerts` добавлена
- [ ] WS onmessage обрабатывает `type === 'maintenance_alert'`
- [ ] `loadMaintenanceAlerts()` вызывается при `load()` и грузит `GET /api/alerts`
- [ ] `applyMaintenanceAlert(msg)` обрабатывает WS-алерты
- [ ] `applyDeviceMaintenanceAlert(deviceId)` обновляет ТО-секцию на карточке
- [ ] Бейджи 🔧 появляются на `alerts-g1` / `alerts-g2` при алертах
- [ ] `updateMaintenanceStatusBadge()` обновляет `statusText` / `statusCard`
- [ ] Модалка `openMaintenanceAlertModal(slot)` показывает детали алерта
- [ ] `acknowledgeAlert(id, slot)` отправляет PATCH и обновляет UI
- [ ] Приоритет: аварии устройства > ТО просрочено > ТО критично > ТО warning > норма
- [ ] `renderAlarms()` вызывает `updateMaintenanceStatusBadge()` в конце
