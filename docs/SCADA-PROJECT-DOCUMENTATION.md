# 📖 Полное описание проекта SCADA v3

## 🎯 Общая информация

**Проект:** Веб-SCADA система для мониторинга генераторных установок

**Заказчик/Разработчик:** Aleksandr

**Оборудование:**
- Генераторные контейнеры (GPU) с 2 генераторами каждый
- Контроллеры Smartgen HGM9520N — генераторы (Modbus TCP, порт 502)
- Контроллеры Smartgen HGM9560 — ШПР/параллельная работа (Modbus RTU через RS-485)
- Конвертеры USR-TCP232-410S — RS-485 → Ethernet

**Объекты:**
- МКЗ (IP: 192.168.97.x)
- ЯКЗ (IP: 192.168.96.x)

---

## 📁 Файлы проекта

### Frontend (готов):
```
/mnt/user-data/outputs/scada-v3.html — Основной файл (текущая версия)
/mnt/user-data/outputs/scada-v2.html — Предыдущая версия
/mnt/user-data/outputs/gpu-scada-final.html — Версия v1
```

### Документация контроллеров:
```
/mnt/project/HGM9510N_HGM9520N_HGM9530N_Protocol_en_1.pdf
/mnt/project/HGM9510N_HGM9520N_HGM9530N_Protocol_en_2.pdf
/mnt/project/HGM9560_Protocol_en_1.pdf
/mnt/project/HGM9560_Protocol_en_2.pdf
```

### Транскрипт предыдущих сессий:
```
/mnt/transcripts/2026-02-03-02-25-27-scada-v3-multiscreen-maintenance.txt
```

---

## 🏗️ Архитектура Frontend (scada-v3.html)

### Структура хранения (localStorage):

```javascript
// Объекты
scada3_sites = {
  "site_1234567890": {
    name: "МКЗ",
    address: "ул. Примерная, 1",
    g1: { ip: "192.168.97.10", port: 502, unit: 1 },
    g2: { ip: "192.168.97.11", port: 502, unit: 2 },
    spr: { ip: "192.168.97.20", port: 502, unit: 1, baud: 9600 },
    bitrixResponsible: "1",  // ID ответственного в Б24
    bitrixGroup: "5"         // ID группы в Б24
  }
}

// Аварии
scada3_alarms = {
  "site_id": {
    "g1": {
      active: [{ id, type: "alarm"|"warning", code, text, time }],
      archived: [{ id, type, code, text, time, resolved }]
    },
    "g2": { ... },
    "spr": { ... }
  }
}

// Данные ТО
scada3_to = {
  "site_id": {
    "g1": {
      lastTO: "2024-01-15T10:00:00Z",
      hoursAtLastTO: 0,
      history: [
        { type: "ТО-1", hours: 250, date: "...", completedTasks: 10, totalTasks: 10 }
      ]
    },
    "g2": { ... }
  }
}

// Регламенты ТО
scada3_templates = {
  "default": {
    name: "Стандартный регламент",
    intervals: [
      {
        id: "to1",
        name: "ТО-1",
        hours: 250,
        tasks: [
          { id: 1, text: "Замена моторного масла", critical: true },
          { id: 2, text: "Замена масляного фильтра", critical: true },
          // ... полный список без "все работы ТО-1"
        ]
      },
      // ТО-2 (500ч) — 18 работ
      // ТО-3 (1000ч) — 30 работ  
      // ТО-4 (2000ч) — 45 работ
    ]
  }
}

// Настройки Битрикс24
scada3_bitrix = {
  enabled: true,
  webhookUrl: "https://xxx.bitrix24.ru/rest/1/xxx/",
  hoursBeforeTO: 48,
  responsibleDefault: "1",
  groupId: "5",
  autoCreateTasks: true,
  autoCloseTasks: true,
  notifyOnCreate: true
}

// События
scada3_events = [
  { time: "2024-01-15T10:00:00Z", text: "ТО-1 выполнено...", siteId: "..." }
]
```

---

## 🎨 UI компоненты

### 1. Сайдбар (левая панель)
- Логотип "SCADA"
- Кнопка "+ Добавить" — новый объект
- Кнопка "⊞" — мультиэкран
- Кнопка "Регламенты ТО" — редактор регламентов
- Кнопка "Битрикс24" — настройки интеграции
- Список объектов с индикаторами статуса
  - Hover: кнопки ✏️ редактировать, ✕ удалить

### 2. Главная панель
- Заголовок с названием объекта
- Кнопки: "Настройки", "Демо"
- Карточки сводки: Мощность, Напряжение, Активные генераторы, Статус

### 3. Однолинейная схема (flexbox, динамическая)
```
┌─────────────────────────────────────┐
│  ┌─────────────┐ ┌─────────────┐   │
│  │ Генератор 1 │ │ Генератор 2 │   │
│  │ P, U, I, f  │ │ P, U, I, f  │   │
│  │ Моточасы    │ │ Моточасы    │   │
│  │ [ТО прогресс]│ │ [ТО прогресс]│   │
│  │ [Работы...]│ │ [Работы...] │   │  ← скролл при hover
│  │ [Выполнить] │ │ [Выполнить] │   │
│  └─────────────┘ └─────────────┘   │
│         ════════●════════          │  ← линии питания
│            ┌─────────┐             │
│            │   ШПР   │             │
│            │ P, U, f │             │
│            └─────────┘             │
│                 │                  │
│      ═══════════════════════       │  ← шина 0.4 кВ
│                 │                  │
│            🏢 Нагрузка             │
└─────────────────────────────────────┘
```

### 4. Карточка генератора
```
┌─────────────────────────────────┐
│ ● Генератор 1             ID:1 │  ← статус-точка + Unit ID
│ ⚠1 ⚠+3                         │  ← кликабельные счётчики алармов
├─────────────────────────────────┤
│ P: 120 кВт      U: 400 В       │
│ I: 180 А        f: 50.0 Гц     │
├─────────────────────────────────┤
│ Работа          Моточасы: 237 ч│
├─────────────────────────────────┤
│ ТО-1                 через 13 ч│
│ ████████████████░░░░           │  ← прогресс-бар
│ ⚠ ТО-1 через 13 ч              │  ← предупреждение
├─────────────────────────────────┤
│ Работы ТО-1:                   │
│ • Замена моторного масла       │  ← красный (critical)
│ • Замена масляного фильтра     │
│ • Проверка уровня ОЖ           │
│ ↕ наведите для просмотра       │  ← при hover разворачивается
├─────────────────────────────────┤
│     [⚠ Выполнить ТО-1]         │  ← жёлтая/красная кнопка
└─────────────────────────────────┘
```

### 5. Журнал событий
- Последние 15 событий
- Формат: [HH:MM:SS] Текст
- Максимум 50 в памяти

---

## 🔧 Функции JavaScript

### Основные:
```javascript
// Утилиты
$(id)                    // document.getElementById
load() / save()          // localStorage
openModal() / closeModal()

// Объекты
addSite()               // Добавить объект
editSite(id)            // Редактировать
deleteSite(id)          // Удалить
selectSite(id)          // Выбрать
renderSites()           // Отрисовать список

// Настройки контроллеров
openSettings()          // Окно настроек IP/port/unit

// Схема питания
setPower(g1, g2)        // Обновить индикацию линий

// Алармы
initAlarms(siteId)
addAlarm(device, type, code, text)
resolveAlarm(device, id)
openDeviceAlarms(device) // Окно алармов устройства
openAllAlarms()          // Все алармы объекта
renderAlarms()

// События
addEvent(text)
renderEvents()

// Демо
toggleDemo()
demoStep()              // 12 шагов демонстрации

// Мультиэкран
openMultiscreen()
showMultiscreen()
renderMultiscreenCard(siteId)
```

### ТО (техобслуживание):
```javascript
// Данные ТО
loadTOData() / saveTOData()
initTOData(siteId, device)
updateTOProgress(device, currentHours) // Обновить прогресс-бар

// Менеджер ТО
openTOManager(device)    // Окно со всеми интервалами
openTOChecklist(device)  // Чеклист работ
completeTOChecklist(device, toIndex) // Подтвердить выполнение
clearTOHistory(device)

// Регламенты
loadMaintenanceTemplates() / saveMaintenanceTemplates()
openMaintenanceTemplates() // Список регламентов
createNewTemplate()
editTemplate(id)
deleteTemplate(id)
resetToDefaults()

// Интервалы
addInterval(templateId)
deleteInterval(templateId, idx)
editInterval(templateId, idx)
saveInterval(templateId, idx)

// Работы
addTask(templateId, intervalIdx)
deleteTask(templateId, intervalIdx, taskIdx)
toggleTaskCritical(templateId, intervalIdx, taskIdx)

// AI импорт
openImportTemplate()
handleFileSelect(input)
parseWithAI()
simulateAIParsing(content) // Заглушка, нужен backend
showParseResult(parsed)
saveImportedTemplate()
```

### Битрикс24:
```javascript
loadBitrixSettings() / saveBitrixSettings()
openBitrixSettings()     // Главное окно настроек
toggleBitrixEnabled()
saveBitrixSettingsForm()
testBitrixConnection()   // Проверка подключения
openBitrixSiteSettings() // Ответственные по объектам
saveBitrixSiteSettings()
createBitrixTask(siteId, deviceId, toInterval) // Формирование задачи
previewBitrixTask(device) // Превью задачи
```

---

## 📊 Стандартный регламент ТО

### ТО-1 (250 моточасов) — 10 работ:
1. ✓ Замена моторного масла (критичная)
2. ✓ Замена масляного фильтра (критичная)
3. ✓ Проверка уровня охлаждающей жидкости (критичная)
4. Проверка натяжения приводных ремней
5. Проверка состояния аккумулятора
6. Проверка затяжки клемм аккумулятора
7. Визуальный осмотр на утечки масла
8. Визуальный осмотр на утечки ОЖ
9. Визуальный осмотр на утечки топлива
10. Проверка показаний приборов

### ТО-2 (500 моточасов) — 18 работ:
- Все 10 работ ТО-1 +
- Замена воздушного фильтра (критичная)
- Замена топливного фильтра (критичная)
- Проверка состояния топливных шлангов
- Проверка форсунок на подтекание
- Проверка давления масла на холостом ходу
- Проверка давления масла под нагрузкой
- Слив отстоя из топливного бака
- Очистка сапуна двигателя

### ТО-3 (1000 моточасов) — 30 работ:
- Все 18 работ ТО-2 +
- Замена охлаждающей жидкости полностью (критичная)
- Промывка системы охлаждения (критичная)
- Регулировка тепловых зазоров клапанов (критичная)
- Проверка компрессии в цилиндрах (критичная)
- Проверка турбокомпрессора на люфт
- Проверка турбокомпрессора на подтекание масла
- Проверка генератора: напряжение заряда
- Проверка генератора: ток заряда
- Проверка стартера: ток потребления
- Очистка радиатора снаружи
- Проверка термостата
- Проверка работы вентилятора охлаждения

### ТО-4 (2000 моточасов) — 45 работ:
- Все 30 работ ТО-3 +
- Замена ремня ГРМ (критичная)
- Замена натяжного ролика ГРМ (критичная)
- Замена водяного насоса/помпы (критичная)
- Замена приводных ремней (критичная)
- Проверка состояния шкивов
- Проверка опор двигателя
- Проверка выхлопной системы на герметичность
- Проверка состояния глушителя
- Диагностика блока управления двигателем
- Считывание и сброс ошибок ЭБУ
- Проверка всех датчиков двигателя
- Проверка электропроводки на повреждения
- Протяжка всех крепёжных соединений
- Замена антифриза в расширительном бачке
- Полный осмотр двигателя с фиксацией состояния (критичная)

---

## 🔌 Интеграция с контроллерами

### HGM9520N (генераторы):
- **Протокол:** Modbus TCP
- **Порт:** 502
- **Поддержка:** RS-485 + TCP одновременно

### HGM9560 (ШПР):
- **Протокол:** Modbus RTU только
- **Интерфейс:** RS-485
- **Требуется:** Конвертер USR-TCP232-410S
- **Параметры:** 9600 бод, 8 бит, без чётности, 2 стоп-бита

### Ключевые регистры (из PDF):
```
Моточасы, P, U, I, f, Cos φ
Температура ОЖ, давление масла
Статус генератора
Аварии и предупреждения
Команды управления (пуск/стоп)
```

---

## 🌐 Backend (нужно реализовать)

### Технологии:
- **Python 3.11+**
- **FastAPI** — REST API + WebSocket
- **PostgreSQL** — основные данные
- **InfluxDB** (опционально) — time-series метрики
- **Redis** — кэш, очереди задач
- **pymodbus** — Modbus клиент
- **APScheduler / Celery** — фоновые задачи
- **httpx** — HTTP клиент для Б24

### Модули:

#### 1. Modbus Poller (`services/modbus_poller.py`)
```python
# Опрос каждые 1-5 сек
- Подключение к HGM9520N (TCP)
- Подключение к HGM9560 (RTU через конвертер)
- Чтение регистров: P, U, I, f, моточасы, статусы, аварии
- Запись в БД / InfluxDB
- WebSocket push клиентам
```

#### 2. REST API (`api/`)
```
GET    /api/sites                    — список объектов
POST   /api/sites                    — создать объект
GET    /api/sites/{id}               — получить объект
PUT    /api/sites/{id}               — обновить
DELETE /api/sites/{id}               — удалить

GET    /api/sites/{id}/metrics       — текущие показания
GET    /api/sites/{id}/metrics/history — история

GET    /api/sites/{id}/alarms        — аварии
POST   /api/sites/{id}/alarms/{alarm_id}/resolve — погасить

GET    /api/templates                — регламенты
POST   /api/templates                — создать
PUT    /api/templates/{id}           — обновить
POST   /api/templates/import         — AI импорт из файла

GET    /api/sites/{id}/maintenance   — статус ТО
POST   /api/sites/{id}/maintenance   — выполнить ТО

POST   /api/bitrix/webhook           — входящий webhook из Б24
```

#### 3. WebSocket (`core/websocket.py`)
```
ws://server/ws/{site_id}
- Подписка на realtime метрики
- Push аварий
- Heartbeat
```

#### 4. Битрикс24 клиент (`services/bitrix_client.py`)
```python
- tasks.task.add — создание задачи
- task.checklistitem.add — добавление чеклиста
- tasks.task.complete — закрытие задачи
- disk.file.get — получение файлов
```

#### 5. AI Parser (`services/ai_parser.py`)
```python
- Получение PDF/Word из Б24
- Отправка в Claude API
- Парсинг ответа → структурированный JSON
- Сохранение регламента
```

#### 6. Scheduler (`services/maintenance_scheduler.py`)
```python
# Каждый час:
- Проверка моточасов всех генераторов
- Если до ТО < 48 часов → создать задачу в Б24
- Если ТО просрочено → уведомление

# При выполнении ТО в SCADA:
- Закрыть задачу в Б24
- Записать в историю
```

#### 7. Notifications (`services/notification.py`)
```python
- Telegram бот — аварии, критичные события
- Email — отчёты, дайджесты
- Б24 — уведомления ответственным
```

### Структура проекта Backend:
```
scada-backend/
├── app/
│   ├── main.py              # FastAPI app
│   ├── config.py            # Настройки
│   │
│   ├── api/                 # REST endpoints
│   │   ├── sites.py         # Объекты
│   │   ├── maintenance.py   # ТО
│   │   ├── metrics.py       # Показания
│   │   └── bitrix.py        # Б24 webhooks
│   │
│   ├── services/            # Бизнес-логика
│   │   ├── modbus_poller.py # Опрос контроллеров
│   │   ├── bitrix_client.py # Клиент Б24
│   │   ├── ai_parser.py     # Claude API
│   │   ├── maintenance_scheduler.py
│   │   └── notification.py
│   │
│   ├── models/              # SQLAlchemy модели
│   │   ├── site.py
│   │   ├── device.py
│   │   ├── maintenance.py
│   │   └── event.py
│   │
│   └── core/
│       ├── database.py
│       └── websocket.py
│
├── requirements.txt
├── docker-compose.yml
└── .env
```

### Структура БД (PostgreSQL):

```sql
-- Объекты
sites (id, name, address, created_at, updated_at)

-- Устройства
devices (id, site_id, type, name, ip, port, unit_id, baud_rate)

-- Регламенты
maintenance_templates (id, name, is_default, created_at)
maintenance_intervals (id, template_id, name, hours, sort_order)
maintenance_tasks (id, interval_id, text, is_critical, sort_order)

-- История ТО
maintenance_history (id, site_id, device_id, interval_name, hours_at_service, 
                     completed_tasks, total_tasks, performed_by, performed_at)

-- Аварии
alarms (id, site_id, device_id, type, code, text, is_active, 
        created_at, resolved_at)

-- События
events (id, site_id, text, created_at)

-- Метрики (или InfluxDB)
metrics (id, site_id, device_id, timestamp, 
         power, voltage, current, frequency, engine_hours, ...)

-- Настройки Б24
bitrix_settings (id, site_id, webhook_url, responsible_id, group_id, 
                 hours_before_to, auto_create, auto_close)

-- Задачи Б24 (для синхронизации)
bitrix_tasks (id, site_id, device_id, interval_name, bitrix_task_id, 
              status, created_at, completed_at)
```

---

## 📋 TODO для Backend

### Фаза 1 — Базовый функционал:
- [ ] Модели SQLAlchemy
- [ ] Миграции Alembic
- [ ] CRUD API для sites, devices
- [ ] Modbus poller (TCP для HGM9520N)
- [ ] WebSocket для realtime

### Фаза 2 — ТО и регламенты:
- [ ] API для регламентов
- [ ] API для maintenance
- [ ] Scheduler проверки моточасов

### Фаза 3 — Битрикс24:
- [ ] Клиент REST API
- [ ] Создание задач с чеклистом
- [ ] Webhook для входящих файлов
- [ ] Синхронизация статусов

### Фаза 4 — AI:
- [ ] Интеграция Claude API
- [ ] Парсинг PDF/Word
- [ ] Автоимпорт регламентов

### Фаза 5 — Уведомления:
- [ ] Telegram бот
- [ ] Email отчёты

---

## 🔗 Важные ссылки

- **pymodbus docs:** https://pymodbus.readthedocs.io/
- **FastAPI docs:** https://fastapi.tiangolo.com/
- **Битрикс24 REST API:** https://dev.1c-bitrix.ru/rest_help/
- **Claude API:** https://docs.anthropic.com/

---

## ⚠️ Важные особенности

1. **HGM9560 только RTU** — нужен конвертер RS485→Ethernet
2. **Регламенты без ссылок** — каждое ТО содержит полный список работ
3. **Критичные работы обязательны** — нельзя завершить ТО без них
4. **Динамическая схема** — flexbox, адаптируется под контент
5. **localStorage** — данные хранятся в браузере, нужна миграция в БД

---

## 🚀 Запуск Frontend

Просто открыть `scada-v3.html` в браузере. Работает автономно с демо-данными.

Для реальной работы нужен backend с Modbus polling.

---

*Документ создан: 02.02.2026*
*Версия Frontend: v3*
*Статус Backend: В разработке*
