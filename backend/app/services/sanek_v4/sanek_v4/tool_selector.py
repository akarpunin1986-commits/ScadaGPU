"""
САНЁК v4 — Smart Tool Selection.

Selects relevant tools based on user query keywords.
Used by both GPT-5.4 and Claude loops.
"""
from __future__ import annotations

_CORE_TOOLS = {
    "get_current_metrics", "get_metrics_history", "get_economics_report",
    "get_alarms", "get_topology",
    "run_python_code", "query_db",
    "get_company_info",
}

_EXTRA_TOOL_TRIGGERS = {
    "search_knowledge": ["документация", "мануал", "руководство", "знаний", "manual", "допустим", "спецификац"],
    "get_alarm_reference": ["аларм", "alarm", "авари", "ошибк", "код ошибк", "fault"],
    "get_bitrix_tasks": ["битрикс", "bitrix", "задач", "task", "тикет", "заявк"],
    "create_bitrix_task": ["создай задач", "создать задач", "новая задач"],
    "read_modbus_register": ["регистр", "modbus", "register", "прочитай", "считай значен"],
    "send_modbus_command": ["запусти", "останови", "start", "stop", "команд", "coil"],
    "run_python_code": ["excel", "xlsx", "график", "python", "вычисл", "pandas", "файл", "отчёт", "отчет", "pdf"],
    "query_db": ["sql", "запрос к базе", "select", "сколько записей", "по часам", "почасов", "потреблен завод", "потреблен объект", "суммарн", "нагрузк"],
    "get_db_schema": ["схем", "структур данных", "таблиц", "колонк", "schema"],
    "save_sop_entry": ["запомни", "сохрани", "sop", "процедур", "решил", "помогло", "починил", "исправил", "прокачал"],
    "get_company_info": [
        "кто отвечает", "кто руководит", "сотрудник", "отдел", "структура компании",
        "коллега", "команда", "штат", "персонал",
        "учредитель", "собственник", "владелец", "акционер",
        "директор", "подчинён", "подчинен", "иерархи", "оргструктур",
        "кто работает", "кто в команде", "состав отдела",
        "контакт сотрудник", "телефон сотрудник", "email сотрудник",
        "начальство", "босс",
    ],
    "get_scada_tasks": ["задач", "мои задач", "задачи", "текущие задач", "открытые задач"],
    "create_scada_task": ["создай задач", "новая задач", "задач на то", "задач на ремонт"],
    "get_scada_task_details": ["детали задач", "подробности задач", "статус задач"],
    "get_executor_stats": ["статистик исполнител", "показатели сотрудник"],
    "escalate_task": ["эскалац", "просрочен задач", "жалоб"],
    "upload_maintenance_card": ["карт то", "карта обслуживан", "распарси карт", "загрузить карту"],
    "get_maintenance_status": ["статус то", "обслуживан", "моточас", "наработк", "ближайш то", "следующ то", "когда то"],
    "record_maintenance": ["записать то", "выполнил то", "сделал то", "зафиксировать", "провели то"],
    "update_equipment_hours": ["обновить часы", "ввести моточас", "показан счётчик", "ручной ввод"],
    "create_scada_rule": ["правил", "автомат", "при ошибк", "при аларм", "при авари", "настрой реакци", "контролируй"],
}

# Keywords that indicate "people" context (not equipment)
_PEOPLE_KEYWORDS = [
    "сотрудник", "отдел", "руководител", "начальник", "директор",
    "должност", "учредител", "акционер", "персонал", "штат",
    "кто работает", "кто в команде", "подчинён", "подчинен",
    "собственник", "владелец", "оргструктур", "иерархи",
    "коллег", "босс", "начальство",
    "кто главн", "самый главн", "кто в компании",
]


def select_tools(all_tools: list[dict], user_message: str) -> list[dict]:
    """Select relevant tools based on user query."""
    msg_lower = user_message.lower()
    selected = set(_CORE_TOOLS)

    for tool_name, triggers in _EXTRA_TOOL_TRIGGERS.items():
        if any(kw in msg_lower for kw in triggers):
            selected.add(tool_name)

    # If "people" context detected — prioritize get_company_info over get_topology
    has_people = any(kw in msg_lower for kw in _PEOPLE_KEYWORDS)
    if has_people:
        selected.add("get_company_info")
        # Don't remove get_topology if user explicitly asks about equipment
        if not any(kw in msg_lower for kw in ["генератор", "контроллер", "modbus", "мощност"]):
            selected.discard("get_topology")

    # Always include search_knowledge and get_db_schema if no extra triggers matched
    if len(selected) <= len(_CORE_TOOLS):
        selected.add("search_knowledge")
        selected.add("get_db_schema")

    return [t for t in all_tools if t["name"] in selected]
