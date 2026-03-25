"""ScadaGPU — Domain-weighted learning system.

Calculates learning signal weight based on:
1. User hierarchy (user_weight from hierarchy.py)
2. Domain competence (position → domain relevance)

Final weight = hierarchy_weight × domain_relevance

Superuser (Karpunin, id=1) always gets weight=1.0.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("scada.domain_weights")

# Superuser IDs — always weight=1.0 in all domains
SUPERUSER_IDS = [1]  # scada_users.id=1 = Карпунин (developer)

# ──────────────────────────────────────────────────────────
# Position → Domain competence mapping
# ──────────────────────────────────────────────────────────

POSITION_DOMAIN_MAP: dict[str, dict[str, float]] = {
    "генеральный директор":    {"engineering": 0.5, "economics": 0.8, "management": 1.0, "it_system": 0.3, "production": 0.7},
    "акционер":                {"engineering": 0.3, "economics": 1.0, "management": 0.9, "it_system": 0.2, "production": 0.5},
    "финансовый директор":     {"engineering": 0.1, "economics": 1.0, "management": 0.7, "it_system": 0.1, "production": 0.3},
    "коммерческий директор":   {"engineering": 0.1, "economics": 0.8, "management": 0.9, "it_system": 0.1, "production": 0.3},
    "руководитель it":         {"engineering": 0.6, "economics": 0.3, "management": 0.6, "it_system": 1.0, "production": 0.2},
    "главный инженер":         {"engineering": 1.0, "economics": 0.3, "management": 0.5, "it_system": 0.4, "production": 0.8},
    "начальник смены":         {"engineering": 0.8, "economics": 0.2, "management": 0.4, "it_system": 0.1, "production": 0.9},
    "инженер":                 {"engineering": 0.9, "economics": 0.1, "management": 0.2, "it_system": 0.3, "production": 0.6},
    "руководитель отдела продаж": {"engineering": 0.1, "economics": 0.6, "management": 0.8, "it_system": 0.1, "production": 0.2},
    "руководитель отдела аналитиков": {"engineering": 0.4, "economics": 0.8, "management": 0.7, "it_system": 0.5, "production": 0.4},
    "менеджер":                {"engineering": 0.1, "economics": 0.4, "management": 0.5, "it_system": 0.1, "production": 0.2},
    "оператор":                {"engineering": 0.7, "economics": 0.1, "management": 0.1, "it_system": 0.1, "production": 0.8},
    "диспетчер":               {"engineering": 0.6, "economics": 0.1, "management": 0.3, "it_system": 0.1, "production": 0.7},
    "аналитик":                {"engineering": 0.3, "economics": 0.7, "management": 0.5, "it_system": 0.5, "production": 0.4},
    "руководитель":            {"engineering": 0.4, "economics": 0.5, "management": 0.8, "it_system": 0.3, "production": 0.5},
}

DEFAULT_DOMAIN_RELEVANCE: dict[str, float] = {
    "engineering": 0.3, "economics": 0.3, "management": 0.3,
    "it_system": 0.1, "production": 0.3,
}

# ──────────────────────────────────────────────────────────
# Domain classification keywords
# ──────────────────────────────────────────────────────────

DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "engineering": [
        "аларм", "давлен", "температур", "масл", "modbus", "контроллер", "генератор",
        "гпу", "запуск", "остановк", "частот", "напряж", "мощност", "ток", "моточас",
        "обслуживан", "ремонт", "то-1", "то-2", "датчик", "клапан", "фильтр",
        "охлажден", "топлив", "выхлоп", "вибрац", "подшипник",
    ],
    "economics": [
        "экономик", "расход", "стоимост", "тариф", "breakeven", "окупаем",
        "выработк", "потреблен", "сеть", "квт", "рубл", "руб", "затрат",
        "бюджет", "прибыл", "эффективн", "цена",
    ],
    "management": [
        "задач", "срок", "ответствен", "kpi", "отчёт", "отчет", "план",
        "контрол", "исполнен", "просрочен", "дедлайн", "совещан",
    ],
    "it_system": [
        "скада", "scada", "база данн", "redis", "postgres", "docker", "api",
        "модуль", "баг", "ошибк", "лог", "промпт", "настройк", "конфигурац",
        "интеграц", "битрикс", "webhook", "бот",
    ],
    "production": [
        "кирпич", "печ", "экструд", "смен", "линия", "загрузк",
        "сырь", "глин", "обжиг", "сушк", "брак",
    ],
}

_DOMAIN_PRIORITY = {"engineering": 5, "economics": 4, "production": 3, "management": 2, "it_system": 1}


def classify_domain(text: str) -> str:
    """Classify text into a knowledge domain by keyword matching."""
    text_lower = text.lower()
    scores: dict[str, int] = {}

    for domain, keywords in DOMAIN_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text_lower)
        if score > 0:
            scores[domain] = score

    if not scores:
        return "management"

    return max(scores, key=lambda d: (scores[d], _DOMAIN_PRIORITY.get(d, 0)))


def get_domain_relevance(position: str, domain: str) -> float:
    """Get domain relevance for a position. Longer keywords match first."""
    if not position:
        return DEFAULT_DOMAIN_RELEVANCE.get(domain, 0.3)

    pos_lower = position.lower()
    sorted_keys = sorted(POSITION_DOMAIN_MAP.keys(), key=len, reverse=True)

    for keyword in sorted_keys:
        if keyword in pos_lower:
            return POSITION_DOMAIN_MAP[keyword].get(domain, 0.3)

    return DEFAULT_DOMAIN_RELEVANCE.get(domain, 0.3)


def calc_learning_weight(
    user_id: int,
    hierarchy_weight: float,
    position: str,
    domain: str,
) -> tuple[float, float]:
    """Calculate final learning weight.

    Returns (final_weight, domain_relevance).
    Superuser always returns (1.0, 1.0).
    """
    if user_id in SUPERUSER_IDS:
        return 1.0, 1.0

    hw = hierarchy_weight or 0.3
    dr = get_domain_relevance(position, domain)
    return round(hw * dr, 3), dr
