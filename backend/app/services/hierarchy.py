"""ScadaGPU — User hierarchy calculation from Bitrix24 position data."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.department_role_mapping import DepartmentRoleMapping

# -------------------------------------------------------------------
# Hierarchy rules: sorted from longest keywords to shortest so that
# more specific positions match before generic ones.
# -------------------------------------------------------------------
HIERARCHY_RULES: list[tuple[int, list[str]]] = [
    (1, [
        "генеральный директор",
        "учредитель",
        "владелец",
        "акционер",
    ]),
    (2, [
        "заместитель директора",
        "коммерческий директор",
        "технический директор",
        "финансовый директор",
        "зам. директора",
        "зам директора",
        "главный инженер",
    ]),
    (3, [
        "начальник участка",
        "начальник отдела",
        "начальник цеха",
        "главный энергетик",
        "главный механик",
        "главный технолог",
        "руководитель",
    ]),
    (4, [
        "начальник смены",
        "старший инженер",
        "ведущий инженер",
        "энергетик",
        "диспетчер",
        "инженер",
        "механик",
        "технолог",
        "мастер",
    ]),
    (5, [
        "оператор",
        "слесарь",
        "электрик",
        "рабочий",
        "стажёр",
        "помощник",
    ]),
]

FALLBACK_KEYWORDS: dict[str, int] = {
    "директор": 1,
    "начальник": 3,
}

_WEIGHT_MAP: dict[int, float] = {1: 1.0, 2: 0.8, 3: 0.6, 4: 0.4, 5: 0.3}


def calc_hierarchy_level(position: str, is_head: bool) -> int:
    """Determine hierarchy level (1-5) from a Bitrix24 position string.

    Rules are checked from longest keyword to shortest within each level
    so that e.g. "заместитель директора" matches level 2 before the
    fallback "директор" would give level 1.

    If ``is_head`` is True the resulting level is promoted by one
    (clamped to 1).
    """
    if not position:
        return 4 if is_head else 5

    pos_lower = position.lower().strip()

    # Exact / substring match against rule table
    for level, keywords in HIERARCHY_RULES:
        for kw in keywords:
            if kw in pos_lower:
                final = max(level - 1, 1) if is_head else level
                return final

    # Fallback keywords
    for kw, level in FALLBACK_KEYWORDS.items():
        if kw in pos_lower:
            final = max(level - 1, 1) if is_head else level
            return final

    # Nothing matched — head of department gets level 4, others 5
    return 4 if is_head else 5


def calc_user_weight(hierarchy_level: int) -> float:
    """Return user weight (0.3 – 1.0) for a given hierarchy level."""
    return _WEIGHT_MAP.get(hierarchy_level, 0.3)


def auto_role_from_hierarchy(level: int) -> str:
    """Map hierarchy level to a default SCADA role.

    * 1-2 → admin
    * 3   → operator
    * 4-5 → viewer
    """
    if level <= 2:
        return "admin"
    if level == 3:
        return "operator"
    return "viewer"


async def resolve_default_role(
    session: AsyncSession,
    department_id: int,
    hierarchy_level: int,
) -> str:
    """Resolve the default role for a user.

    Priority:
    1. ``DepartmentRoleMapping`` entry for the given *department_id*.
    2. Fallback to ``auto_role_from_hierarchy`` based on *hierarchy_level*.
    """
    if department_id:
        stmt = select(DepartmentRoleMapping.default_role).where(
            DepartmentRoleMapping.department_id == department_id
        )
        result = await session.execute(stmt)
        mapped_role = result.scalar_one_or_none()
        if mapped_role:
            return mapped_role

    return auto_role_from_hierarchy(hierarchy_level)
