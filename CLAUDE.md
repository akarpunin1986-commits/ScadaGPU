# ScadaGPU — Инструкции для Claude Code

**Проект:** ScadaGPU — ИИ-система управления газопоршневыми электростанциями  
**Сервер:** 192.168.30.130 (SSH: scada-vm)  
**Backend:** /opt/scada/backend/app/ (Python 3.12, FastAPI, Docker)  
**Frontend:** /opt/scada/frontend-vite/ (Vite, vanilla JS)

## Обязательные тесты после ЛЮБОГО изменения

После каждого коммита — не просто health check, а функциональные тесты:

```bash
# 1. Перезапуск
docker restart scada-backend && sleep 10

# 2. Health
curl http://localhost:8010/health
# Ожидание: {"status":"ok","version":"..."}

# 3. Сайты
curl http://localhost:8010/api/sites
# Ожидание: JSON с МКЗ и ЯКЗ

# 4. Устройства
curl http://localhost:8010/api/devices
# Ожидание: JSON с 6 устройствами

# 5. Метрики
curl http://localhost:8010/api/metrics
# Ожидание: JSON с метриками

# 6. Логи на ошибки
docker logs scada-backend --tail 50 | grep -i "error\|exception"
# Ожидание: нет критических ошибок (WARNING от poller допустимы)

# 7. Если менял auth/bot/sanek — ОБЯЗАТЕЛЬНО:
#    - Проверить вход через Б24 OAuth вручную
#    - Проверить email-авторизацию (request-code API)
#    - Проверить чат Санька (curl POST /api/ai/chat/stream)
#    - Проверить бота в Б24 (отправить сообщение боту 228)
```

**Правило: НЕ считай задачу выполненной пока тесты 1-6 не пройдены.**

## Ключевые конфигурации

- **OPENAI_MODEL=gpt-5.4** — не менять на gpt-4o
- **BITRIX24_BOT_ID=228** (Робот Санёк) — не 224
- **BITRIX24_ENABLED=true**
- **SANEK_AGENT_ENABLED=true**
- Docker env: при изменении .env → `docker compose up -d backend` (не restart!)

## Что НЕ трогать

- modbus_poller.py, metrics_writer.py, alarm_detector.py, event_detector.py
- alarm_analytics/ (весь модуль)
- core/websocket.py, disk_manager.py
- api/auth.py, services/auth.py — **ВОССТАНОВЛЕНЫ из Docker image, не менять**
- config.py, models/ (только добавления, не изменения существующих)

## Frontend

- Production build: `frontend-vite/dist/` (nginx отдаёт)
- Node.js НЕ установлен на сервере — собирать локально: `cd frontend-vite && npx vite build`
- После сборки: `scp -r dist/* scada-vm:/opt/scada/frontend-vite/dist/`
- **Не перезаписывать dist/index.html из dev index.html** — они разные (dev = Vite HMR, dist = production)

## Уроки из рефакторинга (март 2026)

1. **ORM модели должны совпадать с БД** — если столбец есть в таблице, он должен быть в модели
2. **PostgreSQL enum case-sensitive** — `GENERATOR` ≠ `generator`
3. **Frontend bundle устаревает** — после изменений JS нужна пересборка Vite
4. **docker restart ≠ docker compose up -d** — restart не подхватывает новые env из .env
5. **auth.py — не экспериментировать** — оригинальный OAuth flow работает, не менять
