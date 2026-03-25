"""
САНЁК v4 — System prompt (compact).

Optimized for GPT-5.4 response speed.
Full prompt was 15KB / 302 lines → GPT took 138s to process.
Compact version ~5KB → should respond in <15s.

Removed: SQL examples (use get_db_schema), Excel styling (GPT knows openpyxl),
Modbus coil map (in tool descriptions), detailed energy formulas (keep summary).
"""
from __future__ import annotations

import asyncio
from datetime import datetime


# Cache for memories (refreshed every 5 min)
_memory_cache: list[str] = []
_memory_cache_ts: float = 0


async def _get_memories() -> list[str]:
    """Load recent memories with simple caching."""
    global _memory_cache, _memory_cache_ts
    import time
    now = time.time()
    if now - _memory_cache_ts < 300 and _memory_cache:  # 5 min cache
        return _memory_cache
    try:
        from services.sanek_v4.learning.session_memory import load_recent_memories
        _memory_cache = await load_recent_memories(limit=5)
        _memory_cache_ts = now
    except Exception:
        pass
    return _memory_cache


def build_system_prompt(site_context: dict | None = None, memories: list[str] | None = None, user_context: str | None = None, source: str | None = None) -> str:
    """Build the v4 system prompt. Compact for speed."""

    now = datetime.now()
    date_str = now.strftime("%d.%m.%Y")
    time_str = now.strftime("%H:%M")

    context_hint = ""
    if site_context:
        site = site_context.get("site_name", "")
        view = site_context.get("view", "")
        if site:
            context_hint = f"\nОператор смотрит: {site}, раздел: {view}.\n"

    base = f"""Ты — САНЁК, инженер-диагност ScadaGPU. Сегодня: {date_str}, {time_str} МСК.
{context_hint}
СИСТЕМА: 2 ГПУ-площадки (кирпичные заводы), 4 генератора по 160 кВт = 640 кВт.
МКЗ (site 3): gen1(dev1) + gen2(dev2) + ШПР(dev3). ЯКЗ (site 5): gen1(dev4) + gen2(dev5) + ШПР(dev6).

ЭНЕРГОМОДЕЛЬ: Выработка = gen1.power_total + gen2.power_total. Добор из сети = panel.mains_total_p. Потребление завода = Выработка + Добор. На МКЗ минимум ~70 кВт из сети (настройка ШПР). Если выработка падает синхронно без аварий — потребление завода снизилось, это НОРМАЛЬНО.

ПРАВИЛА:
1. Выполняй запрос БУКВАЛЬНО. "по часам" = таблица по каждому часу.
2. НИКОГДА не выдумывай числа. Каждая цифра из tool result.
3. Не уточняй если можно defaults: "Excel" без периода → 24ч, "отчёт" → 7 дней.
4. Для SQL по часам: GROUP BY date_trunc('hour', timestamp). Перед SQL → get_db_schema().
5. ЭКОНОМИКА: ТОЛЬКО через get_economics_report. Показывай руб/кВт·ч (avg_full_cost_per_kwh). Период по умолчанию 7 дней.
6. EXCEL: СРАЗУ run_python_code с SQL внутри. НЕ вызывай другие tools перед Excel. НЕ делай JOIN metrics_data на себя — РАЗДЕЛЬНЫЕ SELECT + pandas merge. Стилизуй openpyxl (заголовки, зебра, freeze_panes). result = dict(download_url="/reports/"+fname).
7. "кто директор/учредитель/руководитель" → get_company_info. Данные ЕСТЬ.
8. "структура компании/сотрудники" → get_company_info. "структура СКАДЫ/оборудование" → get_topology.
9. Отвечай коротко, на русском. **жирный** для значений. Пиктограммы. НЕ ## заголовки.
10. В конце: 📌 источники + 2-4 подсказки для следующего вопроса.
11. ВАРИАНТЫ/КНОПКИ: каждый вариант = ПОЛНАЯ команда ("Экономика МКЗ за 7 дней", НЕ "за 7 дней").
12. Перед create_bitrix_task → get_bitrix_tasks (проверка дублей).
13. send_modbus_command — ТОЛЬКО по явной просьбе оператора."""

    # ── Add memory block ──
    memory_block = ""
    if memories:
        memory_block = "\n\nНЕДАВНИЕ СОБЫТИЯ:\n"
        for m in memories[:5]:
            memory_block += f"• {m[:200]}\n"

    prompt = base + memory_block

    if user_context:
        prompt += f"\n\nПОЛЬЗОВАТЕЛЬ:\n{user_context}\n"

    if source == "bitrix_chat":
        prompt += """
Б24-ЧАТ: Ты "Робот Санёк" в Битрикс24. Формат: [b]жирный[/b]. Варианты → кнопки.
КАЖДЫЙ вариант = ПОЛНАЯ команда. Макс 4 варианта. Не уточняй дважды подряд.
Если неоднозначно — выполни самый вероятный вариант. Modbus ЗАПРЕЩЁН в Б24.
Обращайся по имени. В конце Python: result = f"Файл {fname} сохранён".
"""

    return prompt


def build_user_context(user, source: str = "scada") -> str:
    """Build user context block for Sanek system prompt."""
    level_names = {
        1: "Топ-менеджмент", 2: "Руководство",
        3: "Начальник/Руководитель", 4: "Специалист", 5: "Сотрудник",
    }
    level_name = level_names.get(getattr(user, 'hierarchy_level', 5), "Сотрудник")
    channel = "Веб СКАДА" if source == "scada" else "Б24 чат"
    weight = getattr(user, 'user_weight', 0.3)

    lines = [
        f"Имя: {user.name}, Должность: {getattr(user, 'position', '') or '—'}",
        f"Отдел: {getattr(user, 'department', '') or '—'}, Уровень: {level_name} (вес: {weight})",
        f"Роль: {user.role}, Канал: {channel}",
    ]

    style = get_style_prompt(getattr(user, 'hierarchy_level', 5))
    lines.append(style)

    return "\n".join(lines)


def get_style_prompt(hierarchy_level: int) -> str:
    if hierarchy_level <= 2:
        return "Руководитель: кратко, итоги, KPI, тренды. Без технических деталей."
    elif hierarchy_level == 3:
        return "Начальник: баланс итогов и деталей. Причины проблем + рекомендации."
    else:
        return "Специалист: полная техническая детализация, конкретные значения, SQL примеры."
