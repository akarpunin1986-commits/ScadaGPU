"""ScadaGPU — Tool: get_company_info.

Reads company structure from Redis cache (synced from B24 daily).
Zero API calls to B24 — only cache reads.
"""
from __future__ import annotations

import json
import logging

from services.sanek_v4.tools import registry

logger = logging.getLogger("sanek.tools.company")


@registry.tool(
    name="get_company_info",
    description=(
        "Получить информацию о ЛЮДЯХ в компании: сотрудники, отделы, должности, руководители, оргструктура. "
        "Вызывай когда юзер спрашивает про ЛЮДЕЙ: "
        "'кто отвечает', 'кто руководитель', 'покажи отдел', 'сколько сотрудников', "
        "'структура компании' (если про людей, не оборудование), "
        "'кто в отделе', 'найди сотрудника', 'кто учредитель', 'кто собственник', "
        "'кто акционер', 'кто владелец', 'кто директор', 'начальство'. "
        "НЕ вызывай для вопросов про оборудование, площадки МКЗ/ЯКЗ, генераторы — это get_topology."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query_type": {
                "type": "string",
                "enum": ["department", "employee", "position", "hierarchy", "all"],
                "description": (
                    "department — информация об отделе. "
                    "employee — найти сотрудника по имени. "
                    "position — найти сотрудников по должности. "
                    "hierarchy — кто руководитель кого. "
                    "all — общая сводка по компании."
                ),
            },
            "search": {
                "type": "string",
                "description": "Имя сотрудника, название отдела, или ключевое слово должности.",
            },
        },
        "required": ["query_type"],
    },
)
async def get_company_info(query_type: str, search: str = "", **kwargs) -> dict:
    """Read company structure from Redis cache."""
    import redis as _redis_mod

    # Get Redis from app state
    try:
        from models.base import async_session
        import redis.asyncio as aioredis
        from config import settings as _cfg
        r = aioredis.from_url(_cfg.REDIS_URL)
        structure_raw = await r.get("company:structure")
        await r.aclose()
    except Exception:
        structure_raw = None

    if not structure_raw:
        return {
            "error": "Структура компании не загружена. Попросите админа: POST /api/admin/sync-company",
        }

    structure = json.loads(structure_raw)
    search_lower = (search or "").lower().strip()

    if query_type == "all":
        return _query_all(structure)
    elif query_type == "department":
        return _query_department(structure, search_lower)
    elif query_type == "employee":
        return _query_employee(structure, search_lower)
    elif query_type == "position":
        return _query_position(structure, search_lower)
    elif query_type == "hierarchy":
        return _query_hierarchy(structure, search_lower)
    return {"error": f"Неизвестный query_type: {query_type}"}


def _query_all(s: dict) -> dict:
    depts = s.get("by_department", {})
    summary = {
        "total_employees": s.get("total_employees", 0),
        "total_departments": s.get("total_departments", 0),
        "departments": [],
    }
    for did, dd in depts.items():
        head = dd.get("head", {})
        summary["departments"].append({
            "name": dd.get("name", ""),
            "head": head.get("name", "не назначен") if head else "не назначен",
            "employees": len(dd.get("employees", [])),
        })
    return summary


def _query_department(s: dict, search: str) -> dict:
    if not search:
        return _query_all(s)
    for did, dd in s.get("by_department", {}).items():
        if search in dd.get("name", "").lower():
            emps = [{"name": e["name"], "position": e["position"], "email": e.get("email", ""),
                     "is_head": e.get("is_head", False)} for e in dd.get("employees", [])]
            head = dd.get("head", {})
            return {
                "department": dd["name"],
                "head": head.get("name", "не назначен") if head else "не назначен",
                "employee_count": len(emps),
                "employees": emps,
            }
    avail = [dd["name"] for dd in s.get("by_department", {}).values()]
    return {"error": f"Отдел '{search}' не найден", "available": avail}


def _query_employee(s: dict, search: str) -> dict:
    if not search:
        return {"error": "Укажите имя сотрудника"}
    results = []
    for nl, emp in s.get("by_name", {}).items():
        if search in nl:
            dept_names = []
            for did, dd in s.get("by_department", {}).items():
                for e in dd.get("employees", []):
                    if e.get("bitrix_id") == emp.get("bitrix_id"):
                        dept_names.append(dd["name"])
            mgr = None
            if emp.get("manager_id"):
                for n, e in s.get("by_name", {}).items():
                    if e.get("bitrix_id") == emp["manager_id"]:
                        mgr = e["name"]
                        break
            results.append({
                "name": emp["name"], "position": emp.get("position", ""),
                "email": emp.get("email", ""),
                "department": ", ".join(dept_names) or "—",
                "manager": mgr or "—",
                "phone": emp.get("phone", "") or "—",
            })
    if not results:
        return {"error": f"Сотрудник '{search}' не найден"}
    return {"found": len(results), "employees": results}


_POSITION_SYNONYMS = {
    "учредитель": ["акционер", "собственник", "владелец", "учредитель"],
    "собственник": ["акционер", "собственник", "владелец", "учредитель"],
    "владелец": ["акционер", "собственник", "владелец", "учредитель"],
    "босс": ["директор", "генеральный директор", "руководитель"],
    "начальство": ["директор", "руководитель", "начальник"],
}


def _query_position(s: dict, search: str) -> dict:
    if not search:
        return {"error": "Укажите должность"}

    # Expand search with synonyms
    search_terms = [search]
    for syn_key, syns in _POSITION_SYNONYMS.items():
        if syn_key in search:
            search_terms.extend(syns)
    search_terms = list(set(search_terms))

    results = []
    seen = set()
    for term in search_terms:
        for nl, emp in s.get("by_name", {}).items():
            if term in (emp.get("position") or "").lower() and nl not in seen:
                seen.add(nl)
                results.append({"name": emp["name"], "position": emp["position"]})
    if not results:
        return {"error": f"Сотрудники с должностью '{search}' не найдены"}
    return {"found": len(results), "employees": results}


def _query_hierarchy(s: dict, search: str) -> dict:
    if not search:
        return {"error": "Укажите имя сотрудника"}
    target = None
    for nl, emp in s.get("by_name", {}).items():
        if search in nl:
            target = emp
            break
    if not target:
        return {"error": f"Сотрудник '{search}' не найден"}
    chain = [{"name": target["name"], "position": target.get("position", "")}]
    current = target
    visited = {current["bitrix_id"]}
    for _ in range(5):
        mid = current.get("manager_id")
        if not mid or mid in visited:
            break
        visited.add(mid)
        mgr = None
        for n, e in s.get("by_name", {}).items():
            if e.get("bitrix_id") == mid:
                mgr = e
                break
        if not mgr:
            chain.append({"name": f"ID={mid}", "position": "не найден"})
            break
        chain.append({"name": mgr["name"], "position": mgr.get("position", "")})
        current = mgr
    return {
        "employee": target["name"],
        "hierarchy_chain": chain,
        "chain_description": " → ".join(c["name"] for c in chain),
    }
