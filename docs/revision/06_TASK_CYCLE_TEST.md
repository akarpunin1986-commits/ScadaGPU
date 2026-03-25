# Task Manager — тестовый прогон полного цикла

## Дата: 2026-03-25

---

### Шаг 1: Создание задачи

Задача создана через SQL INSERT (create_scada_task упал на отсутствующий B24_TASK_GROUP_ID в config).

- **scada_tasks id**: 2
- **title**: ТЕСТ: проверка масла МКЗ Генератор 1
- **status**: created
- **responsible_user_id**: 104 (Алексей Михайлов)
- **bitrix_task_id**: NULL (создана напрямую в БД, не через TaskEngine → Б24 не синхронизировалась)
- **deadline**: 2026-03-25 05:14:31 UTC (на 1 час раньше текущего времени — для проверки эскалации)
- **escalation_level**: 0 (при создании)
- **priority**: 2 (medium)

### Шаг 2: TaskSupervisor

TaskSupervisor (interval=60s) обнаружил просроченную задачу и выполнил эскалацию:

- **escalation_level после первого цикла**: 2 (L2 — hard_reminder)
- **reason**: overdue_1h
- **Лог**: `Escalated task #2 → L2 (overdue_1h) → user 104 (Алексей Михайлов)`
- **last_escalation_at**: 2026-03-25 06:14:00.059

**Почему сразу L2, а не L1?** L1 (soft_reminder) срабатывает когда дедлайн приближается (time_to_deadline > 0). Задача уже просрочена (overdue), поэтому Supervisor пропустил L1 и назначил L2 (hard_reminder для просроченных).

### Шаг 3: Коммуникация

- **Сообщение отправлено Михайлову (Б24 imbot)**: ДА
  - `HTTP Request: POST .../imbot.message.add → HTTP/1.1 200 OK`
  - Формат: `⚠️ Задача "ТЕСТ: проверка масла..." (#2) / Дедлайн: ... / Статус: created | Причина: overdue_1h`
- **task_communications**: 0 записей (Supervisor не пишет в task_communications, только читает для проверки ответов)
- **escalation_log**: 1 запись
  - id=1, task_id=2, level=2, reason=overdue_1h, target_user_id=104, target_name=Алексей Михайлов

### Дополнительные проверки

- **Health**: `{"status":"ok","version":"0.3.0"}` ✅
- **Sites**: 2 (МКЗ + ЯКЗ) ✅
- **Devices**: 6 ✅
- **Metrics**: 6 ✅
- **Ошибок в логах**: нет ✅
- **scada_tasks не удвоились**: 2 задачи (1 старая + 1 тестовая) ✅
- **Company sync**: 30 departments, 46 employees ✅

---

### Итог

**Что работает:**
- TaskSupervisor: обнаруживает просроченные задачи, определяет уровень эскалации ✅
- Эскалация L2: сообщение исполнителю через imbot.message.add → 200 OK ✅
- escalation_log: запись создаётся корректно ✅
- Cooldown: last_escalation_at записывается, блокирует повторную эскалацию на том же уровне ✅
- Иерархия company:employees: 46 сотрудников, Михайлов (104) → manager_id=220 ✅
- MaintenanceAlertService: запущен (interval=300s) ✅
- HoursThresholdMonitor: запущен, Redis ключ исправлен (device:{id}:metrics → run_hours) ✅
- Маршрутизация свободного текста в bitrix_bot.py: _find_pending_tasks_for_user + _handle_task_free_text ✅
- LLM-анализ ответа: _analyze_response_quality (gpt-4o-mini) ✅

**Что не работает:**
- `create_scada_task` (Sanek tool): падает на `B24_TASK_GROUP_ID` — не задан в config.py/Settings
- `bitrix_task_id = NULL`: задачи, созданные не через TaskEngine.create_task, не синхронизируются в Б24
- Supervisor записывает в escalation_log, но не в task_communications → _check_task видит 0 ответов

**Что нужно доделать:**
1. Добавить `B24_TASK_GROUP_ID` в config.py (Settings) и .env — чтобы Sanek tool мог создавать задачи
2. Supervisor: после отправки imbot.message.add — записывать исходящее сообщение в task_communications (direction=outbound, message_type=escalation) для полного аудита
3. Тестовый цикл L3 (manager_escalation): нужно ждать > ESCALATION_HARD_HOURS без ответа, или снизить порог для теста
4. Тестовый цикл L4 (founder_escalation): нужно ждать > 24ч без ответа от менеджера
5. EQUIPMENT_DEVICE_MAP: заполнить для HoursThresholdMonitor (или полностью заменить на AlertService)
6. equipment_card_links: привязать карты ТО v2 к оборудованию для работы AlertService
