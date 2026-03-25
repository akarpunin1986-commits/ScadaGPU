"""DI Alarm Mapping — human-readable descriptions for Digital Input alarms.

Per-device mapping of DI numbers to physical equipment descriptions.
Based on electrical diagrams for HGM9520N controllers.

STATUS: PRELIMINARY — based on electrical schema analysis.
Requires on-site verification of actual controller settings.
"""

# ---------------------------------------------------------------------------
# Per-device DI descriptions
# Key: device_id (int) from DB
# Value: dict of di_number (1-based) -> {name_short, name_full, description_detail}
#
# Devices: MKZ site_id=3 (device 1,2), YKZ site_id=5 (device 4,5)
# Generators only (HGM9520N). ATS (device 3,6) has different DI layout.
# ---------------------------------------------------------------------------

_DI_DESCRIPTIONS_GENERATOR = {
    # ---- Common mapping for all HGM9520N generators ----
    # Based on A1 connector electrical schema
    1: {
        "name_short": "Общая авария",
        "name_full": "Внешний сигнал общей аварии",
        "description_detail": (
            "Внешний сигнал общей аварии от панели двигателя или вспомогательного "
            "оборудования. Подключён к контакту A1:12 контроллера."
        ),
        "pin_a1": 12,
    },
    2: {
        "name_short": "Перегрев ОЖ",
        "name_full": "Аварийная температура охлаждающей жидкости",
        "description_detail": (
            "Сработал внешний датчик/реле перегрева охлаждающей жидкости двигателя. "
            "Дублирует аналоговый датчик температуры ОЖ. Проверить уровень ОЖ, "
            "термостат, радиатор, помпу. Контакт A1:13."
        ),
        "pin_a1": 13,
    },
    3: {
        "name_short": "Резерв",
        "name_full": "Резервный вход (не подключён)",
        "description_detail": (
            "Вход в резерве, провод не задействован. Если сработал — возможна "
            "наводка или ошибка конфигурации контроллера. Контакт A1:14."
        ),
        "pin_a1": 14,
    },
    4: {
        "name_short": "Масл. бак пуст",
        "name_full": "Масляный бак пуст — угроза масляного голодания",
        "description_detail": (
            "Сработал поплавковый датчик или реле уровня в масляном расходном баке. "
            "Угроза масляного голодания двигателя. Немедленно проверить уровень масла "
            "и долить при необходимости. НЕ ЗАПУСКАТЬ при низком уровне. Контакт A1:15."
        ),
        "pin_a1": 15,
    },
    5: {
        "name_short": "Авария ОНВ",
        "name_full": "Авария охладителя наддувочного воздуха (интеркулера)",
        "description_detail": (
            "Перегрев или отказ системы охлаждения воздуха после турбокомпрессора. "
            "Снижает эффективность наддува и может повредить двигатель. "
            "Проверить интеркулер, патрубки, вентилятор охлаждения. Контакт A1:16."
        ),
        "pin_a1": 16,
    },
    6: {
        "name_short": "Авария градирни 1",
        "name_full": "Отказ системы охлаждения — градирня №1",
        "description_detail": (
            "Отказ первого контура радиаторного охлаждения (вентилятор, "
            "циркуляционный насос, перегрев контура). Без охлаждения двигатель "
            "перегреется. Проверить градирню, насос, вентилятор. Контакт A1:17."
        ),
        "pin_a1": 17,
    },
    7: {
        "name_short": "Авария градирни 2",
        "name_full": "Отказ системы охлаждения — градирня №2",
        "description_detail": (
            "Отказ второго контура радиаторного охлаждения или второй градирни. "
            "Проверить состояние второй градирни, насос, вентилятор. Контакт A1:21."
        ),
        "pin_a1": 21,
    },
}

# Per-device overrides (if a specific generator has different wiring)
# For now, all generators share the same mapping.
# After on-site verification, add per-device overrides here:
#
# _DEVICE_OVERRIDES = {
#     4: {  # YKZ GPU1 — different DI3
#         3: {"name_short": "...", "name_full": "...", "description_detail": "..."},
#     },
# }
_DEVICE_OVERRIDES: dict[int, dict[int, dict]] = {}


def get_di_description(device_id: int, di_number: int, device_type: str = "generator") -> dict | None:
    """Get human-readable DI description for a specific device and input number.

    Works for ANY generator (device_type="generator" / HGM9520N).
    ATS devices (HGM9560) have a different DI layout — not mapped yet.

    Args:
        device_id: device_id from DB
        di_number: 1-based DI number (1-7 used, 8-10 possible)
        device_type: "generator" or "ats" — only generators are mapped

    Returns:
        dict with name_short, name_full, description_detail or None if no mapping
    """
    if device_type != "generator":
        return None

    # Check per-device override first
    overrides = _DEVICE_OVERRIDES.get(device_id, {})
    if di_number in overrides:
        return overrides[di_number]

    # Fall back to common mapping (same wiring for all HGM9520N)
    return _DI_DESCRIPTIONS_GENERATOR.get(di_number)


def get_di_alarm_description_ru(
    device_id: int,
    di_number: int,
    severity_ru: str = "",
    device_type: str = "generator",
) -> str | None:
    """Build full alarm description string for a DI alarm.

    Args:
        device_id: device_id from DB
        di_number: 1-based DI number
        severity_ru: severity suffix like "аварийный останов", "предупреждение"
        device_type: "generator" or "ats"

    Returns:
        Formatted description string or None if no mapping exists
    """
    desc = get_di_description(device_id, di_number, device_type)
    if desc is None:
        return None

    parts = [f"{desc['name_short']} (DI{di_number})"]
    if severity_ru:
        parts[0] += f" — {severity_ru}"
    parts.append(desc["description_detail"])

    return ". ".join(parts)


def get_di_name_ru(device_id: int, di_number: int, device_type: str = "generator") -> str | None:
    """Get short Russian name for a DI alarm.

    Returns e.g. "Перегрев ОЖ (DI2)" or None if no mapping.
    """
    desc = get_di_description(device_id, di_number, device_type)
    if desc is None:
        return None
    return f"{desc['name_short']} (DI{di_number})"
