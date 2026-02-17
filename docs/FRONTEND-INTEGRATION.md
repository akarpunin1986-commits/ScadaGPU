# Интеграция фронтенда с Backend API

## Контекст

`frontend/scada-v3.html` — монолит 148 KB. Сейчас работает автономно на localStorage.
Backend API (FastAPI) работает на `http://localhost:8010`.
WebSocket — `ws://localhost:8010/ws/metrics`.

**Стратегия**: минимальные точечные изменения. НЕ рефакторим весь фронт.
localStorage остаётся как fallback и для данных, которых нет в API (alarms, TO, templates, bitrix).

---

## Задача 1 (текущая): API Layer + загрузка Sites из API

### Что делаем

Добавляем модуль `api` — тонкий слой для общения с бэкендом.
Переключаем `sites` с localStorage на API. При загрузке страницы фронт
запрашивает список объектов из `GET /api/sites`, а не из `scada3_sites`.
CRUD сайтов — через API. localStorage `scada3_sites` **больше не используется**.

### Что менять в `scada-v3.html`

#### 1.1. Добавить блок API config + helpers (вставить В НАЧАЛО `<script>`, перед `const $ = id => ...`)

```js
// ========================== API CONFIG ==========================
const API_BASE = window.location.port === '8011'
    ? 'http://' + window.location.hostname + ':8010'
    : '';  // same origin
const WS_BASE  = API_BASE.replace('http', 'ws');

const api = {
    async get(path) {
        const res = await fetch(API_BASE + path);
        if (!res.ok) throw new Error(`GET ${path}: ${res.status}`);
        return res.json();
    },
    async post(path, body) {
        const res = await fetch(API_BASE + path, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (!res.ok) throw new Error(`POST ${path}: ${res.status}`);
        return res.json();
    },
    async patch(path, body) {
        const res = await fetch(API_BASE + path, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        if (!res.ok) throw new Error(`PATCH ${path}: ${res.status}`);
        return res.json();
    },
    async del(path) {
        const res = await fetch(API_BASE + path, { method: 'DELETE' });
        if (!res.ok && res.status !== 204) throw new Error(`DELETE ${path}: ${res.status}`);
    },
};
// ======================== END API CONFIG ========================
```

**Почему такой `API_BASE`:** фронт отдаётся nginx на порту 8011, а API — на 8010.
Если запуск будет через reverse proxy (один порт), `API_BASE` станет пустой строкой.

#### 1.2. Новая глобальная переменная для маппинга

Сейчас `sites` — объект с ключами `'site_' + timestamp`. API возвращает объекты
с числовыми `id`. Нужен мост:

```js
// Маппинг: API id (number) → фронтовый ключ, и обратно
// sites теперь хранятся с ключами 'site_{api_id}' вместо 'site_{timestamp}'
// Каждый site объект получает поле _apiId
```

#### 1.3. Переписать `load()` — загрузка sites из API

**Было:**
```js
function load() {
    sites = JSON.parse(localStorage.getItem('scada3_sites') || '{}');
    events = JSON.parse(localStorage.getItem('scada3_events') || '[]');
    alarms = JSON.parse(localStorage.getItem('scada3_alarms') || '{}');
    toData = JSON.parse(localStorage.getItem('scada3_to') || '{}');
}
```

**Стало:**
```js
async function load() {
    // Sites — из API (source of truth)
    try {
        const apiSites = await api.get('/api/sites');
        sites = {};
        for (const s of apiSites) {
            const key = 'site_' + s.id;
            sites[key] = {
                _apiId: s.id,
                name: s.name,
                code: s.code,
                network: s.network,
                address: s.description || '',
                // Дефолтные device-слоты (IP заполнятся из GET /api/devices позже)
                g1: { ip: '', port: 502, unit: 1 },
                g2: { ip: '', port: 502, unit: 2 },
                spr: { ip: '', port: 502, unit: 1, baud: 9600 },
            };
        }
        // Загрузить devices для каждого site
        for (const s of apiSites) {
            const key = 'site_' + s.id;
            try {
                const devices = await api.get('/api/devices?site_id=' + s.id);
                for (const d of devices) {
                    // Маппинг device_type → слот (g1/g2/spr)
                    let slot = null;
                    if (d.device_type === 'generator') {
                        slot = !sites[key].g1._deviceId ? 'g1' : 'g2';
                    } else if (d.device_type === 'ats') {
                        slot = 'spr';
                    }
                    if (slot) {
                        sites[key][slot] = {
                            _deviceId: d.id,
                            ip: d.ip_address,
                            port: d.port,
                            unit: d.slave_id,
                            ...(slot === 'spr' ? { baud: 9600 } : {}),
                        };
                    }
                }
            } catch (e) {
                console.warn('Failed to load devices for site', s.id, e);
            }
        }
    } catch (e) {
        console.error('API unavailable, falling back to localStorage', e);
        sites = JSON.parse(localStorage.getItem('scada3_sites') || '{}');
    }

    // Остальное — пока из localStorage (alarms, events, TO)
    events = JSON.parse(localStorage.getItem('scada3_events') || '[]');
    alarms = JSON.parse(localStorage.getItem('scada3_alarms') || '{}');
    toData = JSON.parse(localStorage.getItem('scada3_to') || '{}');
}
```

#### 1.4. Переписать `addSite()`

**Было:** создаёт запись в `sites`, вызывает `save()`.

**Стало:**
```js
async function addSite() {
    const num = Object.keys(sites).length + 1;
    try {
        const created = await api.post('/api/sites', {
            name: 'Объект ' + num,
            code: 'OBJ' + num,
            network: '192.168.0.x',
            description: '',
        });
        const key = 'site_' + created.id;
        sites[key] = {
            _apiId: created.id,
            name: created.name,
            code: created.code,
            network: created.network,
            address: created.description || '',
            g1: { ip: '', port: 502, unit: 1 },
            g2: { ip: '', port: 502, unit: 2 },
            spr: { ip: '', port: 502, unit: 1, baud: 9600 },
        };
        renderSites();
        selectSite(key);
        addEvent('Создан: ' + created.name);
    } catch (e) {
        console.error('addSite failed', e);
        alert('Ошибка создания объекта: ' + e.message);
    }
}
```

#### 1.5. Переписать `saveEditSite(id)`

**Было:** мутирует `sites[id]`, вызывает `save()`.

**Стало:**
```js
async function saveEditSite(id) {
    const name = $('edit-name').value.trim();
    const addr = $('edit-addr').value.trim();
    if (!name) return;

    const apiId = sites[id]._apiId;
    if (apiId) {
        try {
            await api.patch('/api/sites/' + apiId, {
                name: name,
                description: addr,
            });
        } catch (e) {
            console.error('saveEditSite failed', e);
            alert('Ошибка сохранения: ' + e.message);
            return;
        }
    }
    sites[id].name = name;
    sites[id].address = addr;
    save();  // сохранить events/alarms
    renderSites();
    if (currentSite === id) {
        $('siteName').textContent = name;
    }
    closeModal();
    addEvent('Изменён: ' + name);
}
```

#### 1.6. Переписать `deleteSite(id)`

**Было:** `delete sites[id]`, вызывает `save()`.

**Стало:**
```js
async function deleteSite(id) {
    const name = sites[id]?.name || id;
    if (!confirm('Удалить объект "' + name + '"?')) return;

    const apiId = sites[id]._apiId;
    if (apiId) {
        try {
            await api.del('/api/sites/' + apiId);
        } catch (e) {
            console.error('deleteSite failed', e);
            alert('Ошибка удаления: ' + e.message);
            return;
        }
    }
    delete sites[id];
    delete alarms[id];
    save();
    const ids = Object.keys(sites);
    if (currentSite === id) {
        currentSite = ids.length > 0 ? ids[0] : null;
        if (currentSite) selectSite(currentSite);
        else { $('dashboard').classList.add('hidden'); $('welcome').classList.remove('hidden'); }
    }
    renderSites();
    addEvent('Удалён: ' + name);
}
```

#### 1.7. Переписать `saveSettings()` — сохранение IP/port/unit

При сохранении настроек контроллера создаём/обновляем `Device` в API.

**Стало:**
```js
async function saveSettings() {
    const s = sites[currentSite];
    if (!s) return;
    const apiSiteId = s._apiId;

    // Собрать значения из формы (как было)
    const g1 = { ip: $('cfg-g1-ip').value, port: parseInt($('cfg-g1-port').value) || 502, unit: parseInt($('cfg-g1-unit').value) || 1 };
    const g2 = { ip: $('cfg-g2-ip').value, port: parseInt($('cfg-g2-port').value) || 502, unit: parseInt($('cfg-g2-unit').value) || 1 };
    const spr = { ip: $('cfg-spr-ip').value, port: parseInt($('cfg-spr-port').value) || 502, unit: parseInt($('cfg-spr-unit').value) || 1, baud: parseInt($('cfg-spr-baud').value) || 9600 };

    // Синхронизировать с API (создать или обновить device)
    if (apiSiteId) {
        await _syncDevice(s, 'g1', g1, apiSiteId, 'generator', 'tcp');
        await _syncDevice(s, 'g2', g2, apiSiteId, 'generator', 'tcp');
        await _syncDevice(s, 'spr', spr, apiSiteId, 'ats', 'rtu_over_tcp');
    }

    // Обновить локальный стейт
    s.g1 = { ...s.g1, ...g1 };
    s.g2 = { ...s.g2, ...g2 };
    s.spr = { ...s.spr, ...spr };
    save();
    closeModal();
    addEvent('Настройки сохранены');
}

async function _syncDevice(siteObj, slot, formData, apiSiteId, deviceType, protocol) {
    const deviceId = siteObj[slot]?._deviceId;
    const name = currentSite ? (sites[currentSite].name + ' — ' + slot.toUpperCase()) : slot.toUpperCase();

    if (!formData.ip) return;  // пустой IP = не создаём

    try {
        if (deviceId) {
            // Обновить существующий
            await api.patch('/api/devices/' + deviceId, {
                ip_address: formData.ip,
                port: formData.port,
                slave_id: formData.unit,
            });
        } else {
            // Создать новый
            const created = await api.post('/api/devices', {
                site_id: apiSiteId,
                name: name,
                device_type: deviceType,
                ip_address: formData.ip,
                port: formData.port,
                slave_id: formData.unit,
                protocol: protocol,
            });
            siteObj[slot]._deviceId = created.id;
        }
    } catch (e) {
        console.warn('_syncDevice failed for', slot, e);
    }
}
```

#### 1.8. Обновить init-последовательность (конец `<script>`)

**Было:**
```js
load();
loadMaintenanceTemplates();
loadBitrixSettings();
renderSites();
const ids = Object.keys(sites);
if (ids.length > 0) selectSite(ids[0]);
```

**Стало:**
```js
(async () => {
    await load();        // теперь async
    loadMaintenanceTemplates();
    loadBitrixSettings();
    renderSites();
    const ids = Object.keys(sites);
    if (ids.length > 0) selectSite(ids[0]);
})();
```

#### 1.9. В `save()` — убрать `scada3_sites`

**Было:**
```js
function save() {
    localStorage.setItem('scada3_sites', JSON.stringify(sites));
    localStorage.setItem('scada3_events', JSON.stringify(events));
    localStorage.setItem('scada3_alarms', JSON.stringify(alarms));
}
```

**Стало:**
```js
function save() {
    // sites теперь в API — не сохраняем в localStorage
    localStorage.setItem('scada3_events', JSON.stringify(events));
    localStorage.setItem('scada3_alarms', JSON.stringify(alarms));
}
```

### Что НЕ трогаем в задаче 1

- `renderSites()` — работает как есть (читает `sites` объект)
- `selectSite()` — работает как есть
- `renderAlarms()`, `renderEvents()` — без изменений
- Demo режим — пока работает
- Метрики / WebSocket — будет в задаче 2
- TO/Templates/Bitrix — остаётся на localStorage

### Как проверить

1. Открыть `http://localhost:8011` в браузере
2. В DevTools Console не должно быть ошибок fetch
3. Нажать "Добавить" — должен создаться объект (проверить: `curl http://localhost:8010/api/sites`)
4. Переименовать объект — должен обновиться в API
5. Удалить объект — должен удалиться из API
6. Перезагрузить страницу — объекты должны загрузиться из API, а не из localStorage
7. Настройки IP/port → сохранить → проверить `curl http://localhost:8010/api/devices`

---

## Задача 2: WebSocket — приём метрик + обновление однолинейной схемы

### Что делаем

Подключаемся к `WS /ws/metrics` на бэкенде. При получении данных от Modbus poller —
обновляем показания (P, U, I, f, моточасы) на карточках генераторов и ШПР, обновляем
статусы устройств (online/offline/alarm), обновляем однолинейную схему (шины, линии).

### Что приходит по WebSocket

Бэкенд шлёт два типа сообщений:

**1. Snapshot (при подключении):**
```json
{
    "type": "snapshot",
    "data": [
        { "device_id": 1, "site_code": "MKZ", "device_type": "generator", "online": true, ... },
        { "device_id": 2, "site_code": "MKZ", "device_type": "generator", "online": true, ... },
        { "device_id": 3, "site_code": "MKZ", "device_type": "ats",       "online": true, ... }
    ]
}
```

**2. Update (каждые ~2 сек, по одному устройству):**
```json
{
    "device_id": 1,
    "site_code": "MKZ",
    "device_type": "generator",
    "timestamp": "2026-02-17T14:30:00.123Z",
    "online": true,
    "error": null,

    "gen_uab": 398.5, "gen_ubc": 399.1, "gen_uca": 397.8,
    "gen_freq": 50.01,
    "current_a": 120.3, "current_b": 119.8, "current_c": 121.1,
    "power_total": 245.3, "reactive_total": 48.2,
    "pf_avg": 0.981,
    "engine_speed": 1500,
    "battery_volt": 27.8, "coolant_temp": 82,
    "oil_pressure": 420, "fuel_level": 73,
    "gen_status": 9, "gen_status_text": "running",
    "run_hours": 1237, "run_minutes": 42,
    "alarm_common": false, "alarm_shutdown": false, "alarm_warning": false,
    "mode_auto": true, "mode_manual": false
}
```

Для ШПР (`device_type: "ats"`) поля отличаются:
```json
{
    "device_id": 3,
    "device_type": "ats",
    "online": true,
    "busbar_uab": 399, "busbar_freq": 50.00,
    "busbar_p": 180.5, "busbar_q": 32.1,
    "mains_uab": 400, "mains_freq": 49.99,
    "mains_total_p": 150.2,
    "busbar_switch": 3, "busbar_switch_text": "closed",
    "mains_status": 0, "mains_status_text": "normal",
    "genset_status": 9, "genset_status_text": "running",
    "battery_v": 27.5,
    "accum_kwh": 45230.1,
    "maint_hours": 163
}
```

### Маппинг device_id → слот (g1/g2/spr)

`_deviceId` уже хранится в `sites[siteKey].g1._deviceId`, `.g2._deviceId`, `.spr._deviceId`.
Нужен обратный индекс для быстрого поиска при получении WS-сообщения.

### Что менять в `scada-v3.html`

#### 2.1. Добавить глобальные переменные (рядом с `let demoInterval`)

```js
// ======================== WEBSOCKET STATE ========================
let ws = null;                          // WebSocket instance
let wsReconnectTimer = null;            // reconnect setTimeout id
const WS_RECONNECT_DELAY = 3000;       // ms
let deviceSlotIndex = {};               // { deviceId → { siteKey, slot } }
// ======================== END WS STATE ==========================
```

#### 2.2. Добавить функцию построения индекса (после `_syncDevice`)

```js
function rebuildDeviceIndex() {
    deviceSlotIndex = {};
    for (const [siteKey, site] of Object.entries(sites)) {
        for (const slot of ['g1', 'g2', 'spr']) {
            const did = site[slot]?._deviceId;
            if (did) {
                deviceSlotIndex[did] = { siteKey, slot };
            }
        }
    }
}
```

Вызывать `rebuildDeviceIndex()` в конце `load()` (после загрузки devices), а также в `saveSettings()` после `_syncDevice`.

#### 2.3. Добавить функцию подключения WS (после `rebuildDeviceIndex`)

```js
function connectWebSocket() {
    if (ws && ws.readyState <= WebSocket.OPEN) return;

    const url = WS_BASE + '/ws/metrics';
    console.log('[WS] connecting to', url);
    ws = new WebSocket(url);

    ws.onopen = () => {
        console.log('[WS] connected');
        if (wsReconnectTimer) { clearTimeout(wsReconnectTimer); wsReconnectTimer = null; }
    };

    ws.onclose = () => {
        console.warn('[WS] disconnected, reconnecting in', WS_RECONNECT_DELAY, 'ms');
        ws = null;
        wsReconnectTimer = setTimeout(connectWebSocket, WS_RECONNECT_DELAY);
    };

    ws.onerror = (e) => {
        console.error('[WS] error', e);
    };

    ws.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            if (msg.type === 'snapshot' && Array.isArray(msg.data)) {
                // Начальный snapshot — применить все устройства
                for (const m of msg.data) {
                    applyMetrics(m);
                }
            } else if (msg.device_id !== undefined) {
                // Обычный update одного устройства
                applyMetrics(msg);
            }
        } catch (e) {
            console.warn('[WS] parse error', e);
        }
    };
}
```

#### 2.4. Добавить главную функцию `applyMetrics(m)` (обновление DOM)

Это ядро задачи. Функция получает один объект метрик и обновляет нужные DOM-элементы.

```js
function applyMetrics(m) {
    const did = m.device_id;
    const entry = deviceSlotIndex[did];
    if (!entry) return;  // неизвестное устройство

    const { siteKey, slot } = entry;

    // Обновляем DOM только если это текущий выбранный site
    if (siteKey !== currentSite) return;

    if (m.device_type === 'generator') {
        _applyGeneratorMetrics(slot, m);
    } else if (m.device_type === 'ats') {
        _applySPRMetrics(m);
    }

    // Обновить суммарные показатели в шапке
    _updateSummary();
}

function _applyGeneratorMetrics(slot, m) {
    // slot = 'g1' | 'g2'
    const el = (id) => $(slot + '-' + id);

    // --- Статус online/offline ---
    if (!m.online) {
        setDeviceStatus(slot, 'offline');
        // Не очищаем значения — показываем последние известные
        return;
    }

    // --- Определить статус ---
    if (m.alarm_common || m.alarm_shutdown) {
        setDeviceStatus(slot, 'alarm');
    } else if (m.alarm_warning) {
        setDeviceStatus(slot, 'warning');
    } else if (m.gen_status === 9) {
        setDeviceStatus(slot, 'running');
    } else if (m.gen_status >= 1 && m.gen_status <= 8) {
        setDeviceStatus(slot, 'sync');
    } else {
        setDeviceStatus(slot, 'offline');
    }

    // --- Электрические параметры ---
    const p = el('p');
    const u = el('u');
    const i = el('i');
    const f = el('f');
    const hours = el('hours');

    if (p) p.textContent = m.power_total != null ? m.power_total.toFixed(1) : '—';
    if (u) u.textContent = m.gen_uab != null ? m.gen_uab.toFixed(0) : '—';
    if (i) {
        // Показываем среднее из трёх фаз
        const ia = m.current_a, ib = m.current_b, ic = m.current_c;
        if (ia != null && ib != null && ic != null) {
            i.textContent = ((ia + ib + ic) / 3).toFixed(1);
        } else {
            i.textContent = '—';
        }
    }
    if (f) f.textContent = m.gen_freq != null ? m.gen_freq.toFixed(2) : '—';

    // --- Моточасы ---
    if (hours && m.run_hours != null) {
        hours.textContent = m.run_hours;
        updateTOProgress(slot, m.run_hours);
    }
}

function _applySPRMetrics(m) {
    // --- Статус online/offline ---
    if (!m.online) {
        setDeviceStatus('spr', 'offline');
        return;
    }

    // --- Определить статус ШПР ---
    if (m.alarm_common || m.alarm_shutdown) {
        setDeviceStatus('spr', 'alarm');
    } else if (m.alarm_warning) {
        setDeviceStatus('spr', 'warning');
    } else if (m.genset_status === 9) {
        setDeviceStatus('spr', 'running');
    } else {
        setDeviceStatus('spr', 'offline');
    }

    // --- Показания ШПР ---
    const p = $('spr-p');
    const u = $('spr-u');
    const f = $('spr-f');

    if (p) p.textContent = m.busbar_p != null ? m.busbar_p.toFixed(1) : '—';
    if (u) u.textContent = m.busbar_uab != null ? m.busbar_uab.toFixed(0) : '—';
    if (f) f.textContent = m.busbar_freq != null ? m.busbar_freq.toFixed(2) : '—';
}

function _updateSummary() {
    if (!currentSite) return;
    const s = sites[currentSite];
    if (!s) return;

    // Собрать текущие значения из DOM
    const g1p = parseFloat($('g1-p')?.textContent) || 0;
    const g2p = parseFloat($('g2-p')?.textContent) || 0;
    const g1u = parseFloat($('g1-u')?.textContent) || 0;
    const g2u = parseFloat($('g2-u')?.textContent) || 0;

    // Суммарная мощность
    const total = g1p + g2p;
    $('totalP').textContent = total > 0 ? total.toFixed(1) : '—';

    // Напряжение — показать от первого работающего генератора
    const voltage = g1u || g2u;
    $('totalU').textContent = voltage > 0 ? voltage.toFixed(0) : '—';

    // Активные генераторы
    const g1on = $('g1-status')?.textContent === 'Работа';
    const g2on = $('g2-status')?.textContent === 'Работа';
    $('activeGen').textContent = (g1on ? 1 : 0) + (g2on ? 1 : 0);

    // Однолинейная схема — обновить линии и шины
    setPower(g1on, g2on);
}
```

#### 2.5. Обновить `selectSite()` — при переключении site сбрасывать показания

Найти функцию `selectSite(id)` и **заменить строку**:
```js
setDemoHours(237, 485);
```
на:
```js
// Сбросить показания при смене site (WS обновит через ~2 сек)
_resetMetricsDisplay();
```

И добавить функцию:
```js
function _resetMetricsDisplay() {
    for (const slot of ['g1', 'g2']) {
        $(slot + '-p').textContent = '—';
        $(slot + '-u').textContent = '—';
        $(slot + '-i').textContent = '—';
        $(slot + '-f').textContent = '—';
        $(slot + '-hours').textContent = '—';
    }
    $('spr-p').textContent = '—';
    $('spr-u').textContent = '—';
    $('spr-f').textContent = '—';
    $('totalP').textContent = '—';
    $('totalU').textContent = '—';

    // Запросить свежий snapshot для нового site
    // (WS bridge шлёт ВСЕ устройства, фильтрация на клиенте)
    // Данные придут с ближайшим poll cycle (~2 сек)
}
```

#### 2.6. Обновить init-последовательность

В async IIFE в конце `<script>`, **после** `renderSites()` и `selectSite()`, добавить:

```js
(async () => {
    await load();
    loadMaintenanceTemplates();
    loadBitrixSettings();
    rebuildDeviceIndex();        // <-- ДОБАВИТЬ
    renderSites();
    const ids = Object.keys(sites);
    if (ids.length > 0) selectSite(ids[0]);
    connectWebSocket();          // <-- ДОБАВИТЬ
})();
```

#### 2.7. Обновить `saveSettings()` — перестроить индекс после сохранения

В конце `saveSettings()`, перед `closeModal()`, добавить:

```js
rebuildDeviceIndex();
```

### Что НЕ трогаем в задаче 2

- `renderSites()`, `renderAlarms()`, `renderEvents()` — без изменений
- Demo режим — пусть остаётся (кнопка демо по-прежнему работает, но реальные данные из WS перезапишут демо-значения)
- Модалки настроек, TO, Bitrix — без изменений
- Backend — **НЕ МЕНЯТЬ** (endpoint `/ws/metrics` уже готов и работает)

### Как проверить

**Без реальных контроллеров (нормальный случай при разработке):**

1. Создать site + devices через API:
```bash
curl -X POST http://localhost:8010/api/sites -H "Content-Type: application/json" \
  -d '{"name":"MKZ","code":"MKZ","network":"192.168.97.x"}'

curl -X POST http://localhost:8010/api/devices -H "Content-Type: application/json" \
  -d '{"site_id":1,"name":"Gen1","device_type":"generator","ip_address":"192.168.97.10","port":502,"slave_id":1,"protocol":"tcp"}'
```

2. Открыть `http://localhost:8011` → DevTools Console
3. Должно быть: `[WS] connecting to ws://localhost:8010/ws/metrics` → `[WS] connected`
4. Каждые ~2 сек poller публикует данные. Если контроллер недоступен — поля `online: false`.
5. Карточка Gen1 должна показать статус "Офлайн" (это правильно — контроллер не в сети).

**С симуляцией данных (для проверки DOM-обновлений):**

Вставить в DevTools Console:
```js
// Имитация данных генератора
applyMetrics({
    device_id: 1,    // подставить реальный _deviceId
    device_type: 'generator',
    online: true,
    gen_uab: 398.5, gen_freq: 50.01,
    current_a: 120, current_b: 119, current_c: 121,
    power_total: 245.3,
    gen_status: 9, gen_status_text: 'running',
    run_hours: 1237,
    alarm_common: false, alarm_shutdown: false, alarm_warning: false,
});
```

Ожидаемый результат:
- Карточка G1: P=245.3, U=399, I=120.0, f=50.01, Моточасы=1237
- Статус: зелёная точка, "Работа"
- Шина зелёная, линия G1 зелёная
- Шапка: 245.3 кВт, 399 В, 1/2 генераторов

---

## Задача 3: Аварии из backend + история метрик

> Будет описана после завершения задачи 2.
