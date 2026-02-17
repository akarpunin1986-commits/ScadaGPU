# SCADA — Система диспетчеризации ГПУ

## Назначение
Веб-SCADA для удалённого мониторинга и управления газопоршневыми установками (ГПУ).
Опрос контроллеров Smartgen по Modbus, отображение параметров в реальном времени,
управление техническим обслуживанием, интеграция с Битрикс24.

## Стек
- **Backend:** Python 3.12 + FastAPI + SQLAlchemy + Alembic
- **Frontend:** HTML/JS (монолит scada-v3.html, Tailwind CDN) — позже React
- **БД:** PostgreSQL 16
- **Кэш/очереди:** Redis 7
- **Протоколы:** Modbus TCP (HGM9520N), Modbus RTU через TCP (HGM9560)
- **Modbus:** pymodbus
- **Realtime:** WebSocket (FastAPI native)
- **Деплой:** Docker Compose → VPS

## Объекты мониторинга
| Объект | Сеть | Генераторы (HGM9520N) | ШПР (HGM9560) |
|--------|------|-----------------------|----------------|
| МКЗ | 192.168.97.x | .10, .11 (TCP:502) | .20 (RTU через конвертер) |
| ЯКЗ | 192.168.96.x | .10, .11 (TCP:502) | .20 (RTU через конвертер) |

## Архитектура
```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  Frontend   │◄───►│   Backend    │◄───►│  PostgreSQL  │
│  (nginx)    │ WS  │  (FastAPI)   │     │             │
│  :8011      │     │  :8010       │     │  :5433      │
└─────────────┘     └──────┬───────┘     └─────────────┘
                           │
                    ┌──────┴───────┐
                    │              │
              ┌─────▼─────┐ ┌─────▼─────┐
              │  Redis     │ │  Modbus   │
              │  :6380     │ │  Poller   │
              └───────────┘ └───────────┘
                                  │
                    ┌─────────────┼─────────────┐
                    ▼             ▼              ▼
              HGM9520N      HGM9520N       HGM9560
              Gen1 TCP      Gen2 TCP       ШПР RTU
```

## Структура проекта
```
scada/
├── ARCHITECTURE.md          # ← этот файл
├── CHANGELOG.md
├── TODO.md
├── docker-compose.yml
├── docker-compose.dev.yml
├── .env.example
├── .gitignore
│
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── app/
│       ├── main.py           # FastAPI app + lifespan + routers
│       ├── config.py         # Pydantic Settings
│       ├── alembic.ini       # Alembic config
│       ├── alembic/
│       │   ├── env.py        # Async Alembic env
│       │   └── versions/     # Migration files
│       ├── api/
│       │   ├── __init__.py
│       │   ├── sites.py      # ✅ CRUD объектов
│       │   ├── devices.py    # ✅ CRUD устройств
│       │   ├── metrics.py    # (Phase 2) Текущие показания + история
│       │   ├── maintenance.py # (Phase 3) ТО
│       │   └── bitrix.py     # (Phase 4) Б24 webhooks
│       ├── models/
│       │   ├── __init__.py   # ✅ Re-exports
│       │   ├── base.py       # ✅ Base, engine, async_session
│       │   ├── site.py       # ✅ Site model
│       │   ├── device.py     # ✅ Device, DeviceType, ModbusProtocol
│       │   ├── maintenance.py # (Phase 3)
│       │   └── alarm.py      # (Phase 2)
│       ├── services/
│       │   ├── __init__.py
│       │   ├── modbus_poller.py        # (Phase 2)
│       │   ├── bitrix_client.py        # (Phase 4)
│       │   ├── maintenance_scheduler.py # (Phase 3)
│       │   └── notification.py         # (Phase 5)
│       └── core/
│           ├── __init__.py
│           └── websocket.py   # (Phase 2)
│
├── frontend/
│   └── scada-v3.html
│
├── migrations/               # Alembic
│   ├── alembic.ini
│   ├── env.py
│   └── versions/
│
└── docs/
    ├── modbus-registers.md
    └── SCADA-PROJECT-DOCUMENTATION.md
```

## Docker порты (не конфликтуют с 1c24pro)
| Сервис | Порт хоста | Порт контейнера |
|--------|-----------|-----------------|
| Backend API | 8010 | 8000 |
| Frontend | 8011 | 80 |
| PostgreSQL | 5433 | 5432 |
| Redis | 6380 | 6379 |

## Фазы разработки

### Фаза 1 — Скелет (завершена)
- [x] Структура проекта
- [x] FastAPI scaffold + healthcheck
- [x] SQLAlchemy модели (sites, devices)
- [x] Alembic миграции (async, autogenerate)
- [x] CRUD sites/devices (GET/POST/PATCH/DELETE)
- [x] Docker compose up — всё работает

### Фаза 2 — Modbus + Realtime (завершена)
- [x] Modbus poller (TCP для HGM9520N) — modbus_poller.py HGM9520NReader
- [x] Modbus RTU через TCP (HGM9560) — modbus_poller.py HGM9560Reader (raw socket + CRC16)
- [x] WebSocket push метрик — /ws/metrics + Redis pub/sub bridge
- [x] Фронт подключается к WS — applyMetrics(), deviceSlotIndex
- [x] Demo poller — эмуляция 2 генераторов + 1 ШПР без реального железа
- [x] REST API метрик — GET /api/metrics с фильтрами

### Фаза 3 — ТО (завершена)
- [x] Модели: MaintenanceTemplate, Interval, Task, Log, LogItem, Alert
- [x] API регламентов — 18 эндпоинтов (CRUD templates/intervals/tasks + execution + alerts)
- [x] Seed стандартного регламента — POST /api/seed-templates (ТО-1..ТО-4, 56 задач)
- [x] Scheduler проверки моточасов — MaintenanceScheduler (30s цикл, Redis → DB → WS)
- [x] Алерты ТО — severity: warning/critical/overdue, acknowledge
- [x] Фронтенд алерты — бейджи 🔧 на карточках, статус объекта, модалка деталей

### Фаза 4 — Деплой + Боевой тест
- [ ] Деплой на VPS (docker compose production)
- [ ] VPN/маршрутизация к сетям объектов (192.168.97.x МКЗ, 192.168.96.x ЯКЗ)
- [ ] DEMO_MODE=False, реальные devices в БД
- [ ] Тест ModbusPoller с реальными HGM9520N + HGM9560
- [ ] Мониторинг ошибок и reconnect

### Фаза 5 — Битрикс24
- [ ] REST клиент Б24
- [ ] Создание задач с чеклистами при ТО-алертах
- [ ] Синхронизация статусов (ТО выполнено → задача закрыта)

### Фаза 6 — AI + Уведомления
- [ ] Claude API парсинг регламентов из PDF
- [ ] Telegram бот (алерты, статус)
- [ ] Email отчёты

## Ключевые решения
1. HGM9560 только RTU — требует конвертер USR-TCP232-410S (9600/8/N/2)
2. HGM9520N поддерживает TCP и RS-485 одновременно
3. Frontend пока монолит — разбивать на React после стабилизации API
4. localStorage → PostgreSQL миграция при подключении бэкенда

## Как работать с проектом
1. Архитектор (Claude): планирует, ревьюит, создаёт ARCHITECTURE.md
2. Исполнитель (Cursor): пишет код по плану
3. Тестирование: docker compose up в локальном Docker Desktop
4. Деплой: git push → VPS

---
*Обновлено: 2026-02-18*
