"""Alarm Correlation Engine — pattern-based cascade detection.

Analyzes sets of alarm codes to identify known failure patterns
(load dump, loss of excitation, fuel starvation, etc.).
Used by SanekAgent between PHASE 4 (ACT) and PHASE 5 (VERIFY).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("scada.sanek_correlation")


@dataclass
class CorrelationPattern:
    """A known alarm correlation pattern."""
    name: str
    description_ru: str
    required_alarms: set[str]
    optional_alarms: set[str] = field(default_factory=set)
    confidence: float = 0.8
    root_cause: str = ""
    recommended_action: str = ""


# ── 7 correlation patterns from TZ ──────────────────────────────────────

CORRELATION_PATTERNS: list[CorrelationPattern] = [
    CorrelationPattern(
        name="load_dump",
        description_ru="Сброс нагрузки — перечастота + перенапряжение",
        required_alarms={"OVER_FREQUENCY", "OVER_VOLTAGE"},
        optional_alarms={"SHUTDOWN", "TRIP_STOP"},
        confidence=0.9,
        root_cause="Резкий сброс нагрузки, вызывающий всплеск частоты и напряжения генератора",
        recommended_action="Проверить нагрузку на шине, состояние автоматов АВР, журнал коммутаций",
    ),
    CorrelationPattern(
        name="loss_of_excitation",
        description_ru="Потеря возбуждения — низкое напряжение + высокий ток",
        required_alarms={"UNDER_VOLTAGE"},
        optional_alarms={"OVER_CURRENT", "SHUTDOWN", "WARNING"},
        confidence=0.85,
        root_cause="Неисправность AVR или обрыв цепи возбуждения генератора",
        recommended_action="Проверить AVR, обмотку возбуждения, щётки/контактные кольца",
    ),
    CorrelationPattern(
        name="fuel_starvation",
        description_ru="Топливное голодание — недочастота + останов",
        required_alarms={"UNDER_FREQUENCY"},
        optional_alarms={"SHUTDOWN", "TRIP_STOP", "LOW_FUEL"},
        confidence=0.85,
        root_cause="Недостаточная подача топлива — засор фильтра, воздух в системе, отказ насоса",
        recommended_action="Проверить уровень топлива, фильтры, топливный насос, удалить воздух из системы",
    ),
    CorrelationPattern(
        name="lubrication_failure",
        description_ru="Отказ смазки — низкое давление масла + высокая температура",
        required_alarms={"LOW_OIL_PRESSURE"},
        optional_alarms={"HIGH_COOLANT_TEMP", "SHUTDOWN", "WARNING"},
        confidence=0.9,
        root_cause="Недостаточная смазка — низкий уровень масла, отказ насоса, засор фильтра",
        recommended_action="Проверить уровень масла, давление, масляный фильтр, работу насоса",
    ),
    CorrelationPattern(
        name="overload_thermal",
        description_ru="Тепловая перегрузка — высокая температура ОЖ + высокая нагрузка",
        required_alarms={"HIGH_COOLANT_TEMP"},
        optional_alarms={"OVER_CURRENT", "SHUTDOWN", "WARNING"},
        confidence=0.8,
        root_cause="Перегрузка генератора или отказ системы охлаждения",
        recommended_action="Проверить нагрузку генератора, уровень ОЖ, термостат, радиатор, вентилятор",
    ),
    CorrelationPattern(
        name="sync_failure",
        description_ru="Отказ синхронизации — несовпадение параметров сети и генератора",
        required_alarms={"SYNC_FAIL"},
        optional_alarms={"MIN_SETS_NOT_REACHED", "WARNING", "BLOCK"},
        confidence=0.85,
        root_cause="Параметры генератора не соответствуют параметрам сети при попытке синхронизации",
        recommended_action="Проверить параметры синхронизации в HGM9560, настройки dF/dV/dPhi, состояние сети",
    ),
    CorrelationPattern(
        name="comm_storm",
        description_ru="Коммуникационный шторм — массовая потеря связи",
        required_alarms={"CONN_LOST"},
        optional_alarms={"WARNING", "BLOCK"},
        confidence=0.75,
        root_cause="Проблема связи — обрыв RS-485/Ethernet, перегрузка Modbus-шины, сбой конвертера",
        recommended_action="Проверить физическую линию RS-485, конвертер Modbus-TCP, питание контроллера",
    ),
]


class CorrelationEngine:
    """Matches alarm sets against known correlation patterns."""

    def __init__(self) -> None:
        self._patterns = CORRELATION_PATTERNS

    def analyze(
        self,
        alarm_codes: list[str],
        metrics_snapshot: dict[str, Any] | None = None,
        alarm_bits: dict[str, bool] | None = None,
    ) -> list[dict[str, Any]]:
        """Find matching correlation patterns for a set of alarm codes.

        Returns list of dicts sorted by confidence (descending):
        {name, description_ru, confidence, root_cause, recommended_action, matched_required, matched_optional}
        """
        if not alarm_codes:
            return []

        # Normalize alarm codes — strip EVENT_/MAINTENANCE_ prefixes
        normalized: set[str] = set()
        for code in alarm_codes:
            base = code.replace("EVENT_", "").replace("MAINTENANCE_", "")
            normalized.add(base)

        results: list[dict[str, Any]] = []

        for pattern in self._patterns:
            # Check if all required alarms are present
            if not pattern.required_alarms.issubset(normalized):
                continue

            # Count optional matches for confidence boost
            matched_optional = pattern.optional_alarms & normalized
            optional_boost = len(matched_optional) * 0.03  # +3% per optional match
            final_confidence = min(0.99, pattern.confidence + optional_boost)

            results.append({
                "name": pattern.name,
                "description_ru": pattern.description_ru,
                "confidence": round(final_confidence, 2),
                "root_cause": pattern.root_cause,
                "recommended_action": pattern.recommended_action,
                "matched_required": sorted(pattern.required_alarms),
                "matched_optional": sorted(matched_optional),
            })

        results.sort(key=lambda x: x["confidence"], reverse=True)

        if results:
            logger.info(
                "CorrelationEngine: %d patterns matched for alarms %s: %s",
                len(results),
                sorted(normalized),
                [r["name"] for r in results],
            )

        return results
