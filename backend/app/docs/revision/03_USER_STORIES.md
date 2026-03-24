# User Stories — ScadaGPU (после Фаз 0-3)

Обновлено: 2026-03-24

## Статусы

| Статус | До ревизии | После всех фаз |
|--------|-----------|----------------|
| OK     | 37 (74%)  | 45+ (90%+)     |
| PARTIAL| 8 (16%)   | 2-3            |
| TODO   | 2 (4%)    | 0-1            |

## Ключевые изменения (Фазы 0-3)

- US-040 (web chat v4): OK — web-chat uses sanek_v4 agentic loop (26 tools)
- US-043 (RAG): OK — ChromaDB (248 docs) + ILIKE fallback
- US-044 (SanekAgent): OK — enabled, OBSERVE/CONTEXT reasoning
- US-045 (Predictive): PARTIAL — model ready, service not implemented
- US-049 (device_map): OK — dynamic from DB, Redis cache
- US-060 (auto-tasks B24): OK — SHUTDOWN/TRIP_STOP create tasks
- US-082 (EQUIPMENT_DEVICE_MAP): OK — filled in .env
- US-020-029 (TO lifecycle): OK — v1+v2 working, overdue resolved
- US-090-095 (Task Manager): OK — API ready, SanekAgent active
