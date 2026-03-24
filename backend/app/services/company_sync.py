"""ScadaGPU — Company structure sync from Bitrix24 to Redis cache.

Fetches departments + employees once per 24h → Redis cache.
Tool `get_company_info` reads from cache (0 API calls).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

logger = logging.getLogger("scada.company_sync")

CACHE_TTL = 86400 + 3600  # 25 hours


async def sync_company_structure(redis) -> dict:
    """Sync company structure from B24 → Redis. Returns stats."""
    from services.bitrix24.client import Bitrix24Client
    from config import settings
    from sqlalchemy import select
    from models.base import async_session as db_session_factory
    from models.scada_user import ScadaUser

    b24 = Bitrix24Client(settings.BITRIX24_WEBHOOK_URL)

    logger.info("Company structure sync started")

    try:
        # 1. Departments — try dedicated API, fallback to building from users
        departments = []
        try:
            start = 0
            while True:
                resp = await b24.call("department.get", {"start": start})
                batch = resp.get("result", [])
                if not batch:
                    break
                for d in batch:
                    departments.append({
                        "id": int(d["ID"]),
                        "name": d.get("NAME", ""),
                        "parent_id": int(d["PARENT"]) if d.get("PARENT") else None,
                        "head_user_id": int(d["UF_HEAD"]) if d.get("UF_HEAD") else None,
                    })
                if len(batch) < 50:
                    break
                start += 50
        except Exception as dept_err:
            logger.warning("department.get unavailable (%s), will build from users", dept_err)

        # 2. Employees
        employees = []
        start = 0
        while True:
            resp = await b24.call("user.get", {"ACTIVE": True, "start": start})
            batch = resp.get("result", [])
            if not batch:
                break
            for e in batch:
                if e.get("USER_TYPE") == "bot":
                    continue
                dept_ids = e.get("UF_DEPARTMENT", [])
                employees.append({
                    "bitrix_id": int(e["ID"]),
                    "name": f"{e.get('NAME', '')} {e.get('LAST_NAME', '')}".strip(),
                    "position": e.get("WORK_POSITION", ""),
                    "email": e.get("EMAIL", ""),
                    "department_ids": [int(d) for d in dept_ids] if dept_ids else [],
                    "is_head": bool(e.get("UF_DEPARTMENT_HEAD")),
                    "manager_id": int(e["UF_HEAD"]) if e.get("UF_HEAD") else None,
                    "phone": e.get("PERSONAL_MOBILE", "") or e.get("WORK_PHONE", ""),
                    "active": True,
                })
            if len(batch) < 50:
                break
            start += 50

        # 2a. Build departments from users if API unavailable
        if not departments:
            seen_depts = set()
            for emp in employees:
                for did in emp["department_ids"]:
                    if did not in seen_depts:
                        seen_depts.add(did)
                        departments.append({
                            "id": did,
                            "name": f"Department #{did}",
                            "parent_id": None,
                            "head_user_id": None,
                        })

        # 2b. Enrich with scada_users data (user_weight, hierarchy_level)
        try:
            async with db_session_factory() as db:
                result = await db.execute(select(ScadaUser).where(ScadaUser.is_active.is_(True)))
                scada_users = {u.bitrix_id: u for u in result.scalars().all()}
            for emp in employees:
                su = scada_users.get(emp["bitrix_id"])
                emp["id"] = emp["bitrix_id"]  # alias for task_supervisor compatibility
                if su:
                    emp["user_weight"] = su.user_weight
                    emp["hierarchy_level"] = su.hierarchy_level
                    emp["scada_role"] = su.role
                    # Fill manager_id from scada_users if B24 UF_HEAD is empty
                    if not emp["manager_id"] and su.manager_bitrix_id:
                        emp["manager_id"] = su.manager_bitrix_id
                else:
                    emp["user_weight"] = 0.3
                    emp["hierarchy_level"] = 5
                    emp["scada_role"] = "viewer"
        except Exception as e:
            logger.warning("Failed to enrich from scada_users: %s", e)
            for emp in employees:
                emp["id"] = emp["bitrix_id"]

        # 3. Build structure
        structure = _build_structure(departments, employees)

        # 4. Save to Redis
        await redis.set("company:departments", json.dumps(departments, ensure_ascii=False), ex=CACHE_TTL)
        await redis.set("company:employees", json.dumps(employees, ensure_ascii=False), ex=CACHE_TTL)
        await redis.set("company:structure", json.dumps(structure, ensure_ascii=False), ex=CACHE_TTL)
        await redis.set("company:last_sync", datetime.utcnow().isoformat(), ex=CACHE_TTL)

        logger.info("Company sync done: %d departments, %d employees", len(departments), len(employees))
        return {"departments": len(departments), "employees": len(employees)}

    except Exception as e:
        logger.error("Company sync failed: %s", e, exc_info=True)
        return {"error": str(e)}


def _build_structure(departments: list[dict], employees: list[dict]) -> dict:
    dept_map = {d["id"]: d for d in departments}
    emp_by_dept: dict = {}
    emp_by_name: dict = {}
    emp_by_position: dict = {}

    for emp in employees:
        name_lower = emp["name"].lower()
        emp_by_name[name_lower] = emp

        for dept_id in emp["department_ids"]:
            if dept_id not in emp_by_dept:
                di = dept_map.get(dept_id, {})
                emp_by_dept[dept_id] = {
                    "name": di.get("name", f"#{dept_id}"),
                    "head": None,
                    "employees": [],
                }
            emp_by_dept[dept_id]["employees"].append(emp)
            if emp["is_head"]:
                emp_by_dept[dept_id]["head"] = emp

        pos_lower = (emp["position"] or "").lower()
        for kw in ["директор", "руководитель", "начальник", "инженер",
                    "менеджер", "оператор", "аналитик", "диспетчер"]:
            if kw in pos_lower:
                emp_by_position.setdefault(kw, []).append(emp)

    # Head from department.UF_HEAD
    for dept_id, dd in emp_by_dept.items():
        if not dd["head"] and dept_map.get(dept_id, {}).get("head_user_id"):
            hid = dept_map[dept_id]["head_user_id"]
            for e in dd["employees"]:
                if e["bitrix_id"] == hid:
                    dd["head"] = e
                    break

    return {
        "by_department": {str(k): v for k, v in emp_by_dept.items()},
        "by_name": emp_by_name,
        "by_position": emp_by_position,
        "total_employees": len(employees),
        "total_departments": len(departments),
    }
