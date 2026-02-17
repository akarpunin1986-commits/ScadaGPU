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
│       ├── main.py           # FastAPI app + lifespan
│       ├── config.py         # Pydantic Settings
│       ├── api/
│       │   ├── __init__.py
│       │   ├── sites.py      # CRUD объектов
│       │   ├── devices.py    # CRUD устройств
│       │   ├── metrics.py    # Текущие показания + история
│       │   ├── maintenance.py # ТО
│       │   └── bitrix.py     # Б24 webhooks
│       ├── models/
│       │   ├── __init__.py
│       │   ├── base.py       # Base, engine, session
│       │   ├── site.py
│       │   ├── device.py
│       │   ├── maintenance.py
│       │   └── alarm.py
│       ├── services/
│       │   ├── __init__.py
│       │   ├── modbus_poller.py
│       │   ├── bitrix_client.py
│       │   ├── maintenance_scheduler.py
│       │   └── notification.py
│       └── core/
│           ├── __init__.py
│           └── websocket.py
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

### Фаза 1 — Скелет (текущая)
- [x] Структура проекта
- [ ] FastAPI scaffold + healthcheck
- [ ] SQLAlchemy модели (sites, devices)
- [ ] Alembic миграции
- [ ] CRUD sites/devices
- [ ] Docker compose up — всё работает

### Фаза 2 — Modbus + Realtime
- [ ] Modbus poller (TCP для HGM9520N)
- [ ] Modbus RTU через TCP (HGM9560)
- [ ] WebSocket push метрик
- [ ] Фронт подключается к WS вместо демо

### Фаза 3 — ТО
- [ ] Модели: templates, intervals, tasks, history
- [ ] API регламентов и обслуживания
- [ ] Scheduler проверки моточасов

### Фаза 4 — Битрикс24
- [ ] REST клиент Б24
- [ ] Создание задач с чеклистами
- [ ] Синхронизация статусов

### Фаза 5 — AI + Уведомления
- [ ] Claude API парсинг регламентов
- [ ] Telegram бот
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
*Обновлено: 2026-02-17*
