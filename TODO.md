# TODO

## Phase 1 — Скелет (в работе)
- [x] Структура проекта + docker-compose
- [x] FastAPI scaffold + /health
- [ ] SQLAlchemy модели: Site, Device
- [ ] Alembic init + первая миграция
- [ ] CRUD /api/sites
- [ ] CRUD /api/devices
- [ ] docker compose up — всё запускается

## Phase 2 — Modbus + Realtime
- [ ] Modbus TCP poller (HGM9520N)
- [ ] Modbus RTU через TCP (HGM9560)
- [ ] WebSocket endpoint /ws/{site_id}
- [ ] Frontend → WS подключение

## Phase 3 — ТО
- [ ] Модели: MaintenanceTemplate, Interval, Task, History
- [ ] API регламентов
- [ ] API выполнения ТО
- [ ] Scheduler проверки моточасов

## Phase 4 — Битрикс24
- [ ] REST клиент Б24
- [ ] Создание задач с чеклистами
- [ ] Webhook обработка
- [ ] Синхронизация статусов

## Phase 5 — AI + Уведомления
- [ ] Claude API парсинг регламентов
- [ ] Telegram бот
- [ ] Email отчёты
