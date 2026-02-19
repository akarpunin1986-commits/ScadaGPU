"""Alarm definitions — bitfield maps for HGM9560 and HGM9520N.

Each entry: (register_field, bit) -> {code, name, name_ru, severity}
Used by detector.py to identify specific alarms from raw register values.

Source: SmartGen HGM9560 / HGM9520N manuals (Alarm Data Tables).
"""

# ---------------------------------------------------------------------------
# HGM9560 (SPR) — Alarm Register Map
# Registers 0000-0044 from the controller
# Keys: (register_field_name, bit_number)
# ---------------------------------------------------------------------------

ALARM_MAP_HGM9560: dict[tuple[str, int], dict] = {
    # Register 0001 — Shutdown alarms
    ("alarm_reg_01", 10): {
        "code": "M_SD_1_10",
        "name": "Maintenance Time Due Alarm Shutdown",
        "name_ru": "Плановое ТО — аварийный останов",
        "severity": "shutdown",
    },

    # Register 0002 — Shutdown (continued)
    ("alarm_reg_02", 1): {
        "code": "M_SD_2_1",
        "name": "MSC ID Error Alarm Shutdown",
        "name_ru": "Ошибка MSC ID — аварийный останов",
        "severity": "shutdown",
    },
    ("alarm_reg_02", 2): {
        "code": "M_SD_2_2",
        "name": "Voltage Bus Error Alarm Shutdown",
        "name_ru": "Ошибка шины напряжения — аварийный останов",
        "severity": "shutdown",
    },
    ("alarm_reg_02", 3): {
        "code": "M_SD_2_3",
        "name": "Gen Phase Error Alarm Shutdown",
        "name_ru": "Ошибка чередования фаз генератора — аварийный останов",
        "severity": "shutdown",
    },
    ("alarm_reg_02", 4): {
        "code": "M_SD_2_4",
        "name": "Bus (Mains) Phase Error Alarm Shutdown",
        "name_ru": "Ошибка чередования фаз шины (сети) — аварийный останов",
        "severity": "shutdown",
    },

    # Register 0008 — Input Shutdown (discrete inputs 1-8)
    ("alarm_reg_08", 0): {
        "code": "M_ISD_8_0",
        "name": "Input 1 Shutdown",
        "name_ru": "Дискретный вход 1 — аварийный останов",
        "severity": "shutdown",
    },
    ("alarm_reg_08", 1): {
        "code": "M_ISD_8_1",
        "name": "Input 2 Shutdown",
        "name_ru": "Дискретный вход 2 — аварийный останов",
        "severity": "shutdown",
    },
    ("alarm_reg_08", 2): {
        "code": "M_ISD_8_2",
        "name": "Input 3 Shutdown",
        "name_ru": "Дискретный вход 3 — аварийный останов",
        "severity": "shutdown",
    },
    ("alarm_reg_08", 3): {
        "code": "M_ISD_8_3",
        "name": "Input 4 Shutdown",
        "name_ru": "Дискретный вход 4 — аварийный останов",
        "severity": "shutdown",
    },
    ("alarm_reg_08", 4): {
        "code": "M_ISD_8_4",
        "name": "Input 5 Shutdown",
        "name_ru": "Дискретный вход 5 — аварийный останов",
        "severity": "shutdown",
    },
    ("alarm_reg_08", 5): {
        "code": "M_ISD_8_5",
        "name": "Input 6 Shutdown",
        "name_ru": "Дискретный вход 6 — аварийный останов",
        "severity": "shutdown",
    },
    ("alarm_reg_08", 6): {
        "code": "M_ISD_8_6",
        "name": "Input 7 Shutdown",
        "name_ru": "Дискретный вход 7 — аварийный останов",
        "severity": "shutdown",
    },
    ("alarm_reg_08", 7): {
        "code": "M_ISD_8_7",
        "name": "Input 8 Shutdown",
        "name_ru": "Дискретный вход 8 — аварийный останов",
        "severity": "shutdown",
    },

    # Register 0012 — Trip and Stop
    ("alarm_reg_12", 1): {
        "code": "M_TS_12_1",
        "name": "Maintenance Time Due Trip and Stop",
        "name_ru": "Плановое ТО — Trip and Stop",
        "severity": "trip",
    },
    ("alarm_reg_12", 4): {
        "code": "M_TS_12_4",
        "name": "Input 1 Trip and Stop",
        "name_ru": "Дискретный вход 1 — Trip and Stop",
        "severity": "trip",
    },
    ("alarm_reg_12", 5): {
        "code": "M_TS_12_5",
        "name": "Input 2 Trip and Stop",
        "name_ru": "Дискретный вход 2 — Trip and Stop",
        "severity": "trip",
    },
    ("alarm_reg_12", 6): {
        "code": "M_TS_12_6",
        "name": "Input 3 Trip and Stop",
        "name_ru": "Дискретный вход 3 — Trip and Stop",
        "severity": "trip",
    },
    ("alarm_reg_12", 7): {
        "code": "M_TS_12_7",
        "name": "Input 4 Trip and Stop",
        "name_ru": "Дискретный вход 4 — Trip and Stop",
        "severity": "trip",
    },
    ("alarm_reg_12", 8): {
        "code": "M_TS_12_8",
        "name": "Input 5 Trip and Stop",
        "name_ru": "Дискретный вход 5 — Trip and Stop",
        "severity": "trip",
    },
    ("alarm_reg_12", 9): {
        "code": "M_TS_12_9",
        "name": "Input 6 Trip and Stop",
        "name_ru": "Дискретный вход 6 — Trip and Stop",
        "severity": "trip",
    },
    ("alarm_reg_12", 10): {
        "code": "M_TS_12_10",
        "name": "Input 7 Trip and Stop",
        "name_ru": "Дискретный вход 7 — Trip and Stop",
        "severity": "trip",
    },
    ("alarm_reg_12", 11): {
        "code": "M_TS_12_11",
        "name": "Input 8 Trip and Stop",
        "name_ru": "Дискретный вход 8 — Trip and Stop",
        "severity": "trip",
    },

    # Register 0014 — Trip and Stop (continued)
    ("alarm_reg_14", 8): {
        "code": "M_TS_14_8",
        "name": "Mains Overcurrent 1 Trip and Stop",
        "name_ru": "Перегрузка по току сети 1 — Trip and Stop",
        "severity": "trip",
    },
    ("alarm_reg_14", 9): {
        "code": "M_TS_14_9",
        "name": "Mains Overcurrent 2 Trip and Stop",
        "name_ru": "Перегрузка по току сети 2 — Trip and Stop",
        "severity": "trip",
    },

    # Register 0016 — Trip
    ("alarm_reg_16", 4): {
        "code": "M_TR_16_4",
        "name": "Input 1 Trip",
        "name_ru": "Дискретный вход 1 — Trip",
        "severity": "trip",
    },
    ("alarm_reg_16", 5): {
        "code": "M_TR_16_5",
        "name": "Input 2 Trip",
        "name_ru": "Дискретный вход 2 — Trip",
        "severity": "trip",
    },
    ("alarm_reg_16", 6): {
        "code": "M_TR_16_6",
        "name": "Input 3 Trip",
        "name_ru": "Дискретный вход 3 — Trip",
        "severity": "trip",
    },
    ("alarm_reg_16", 7): {
        "code": "M_TR_16_7",
        "name": "Input 4 Trip",
        "name_ru": "Дискретный вход 4 — Trip",
        "severity": "trip",
    },
    ("alarm_reg_16", 8): {
        "code": "M_TR_16_8",
        "name": "Input 5 Trip",
        "name_ru": "Дискретный вход 5 — Trip",
        "severity": "trip",
    },
    ("alarm_reg_16", 9): {
        "code": "M_TR_16_9",
        "name": "Input 6 Trip",
        "name_ru": "Дискретный вход 6 — Trip",
        "severity": "trip",
    },
    ("alarm_reg_16", 10): {
        "code": "M_TR_16_10",
        "name": "Input 7 Trip",
        "name_ru": "Дискретный вход 7 — Trip",
        "severity": "trip",
    },
    ("alarm_reg_16", 11): {
        "code": "M_TR_16_11",
        "name": "Input 8 Trip",
        "name_ru": "Дискретный вход 8 — Trip",
        "severity": "trip",
    },

    # Register 0020 — Warning
    ("alarm_reg_20", 0): {
        "code": "M_WN_20_0",
        "name": "Battery Undervoltage Warning",
        "name_ru": "Пониженное напряжение батареи",
        "severity": "warning",
        "analysis_key": "battery_undervoltage_warning",
    },
    ("alarm_reg_20", 1): {
        "code": "M_WN_20_1",
        "name": "Battery Overvoltage Warning",
        "name_ru": "Повышенное напряжение батареи",
        "severity": "warning",
    },
    ("alarm_reg_20", 4): {
        "code": "M_WN_20_4",
        "name": "Input 1 Warning",
        "name_ru": "Дискретный вход 1 — предупреждение",
        "severity": "warning",
    },
    ("alarm_reg_20", 5): {
        "code": "M_WN_20_5",
        "name": "Input 2 Warning",
        "name_ru": "Дискретный вход 2 — предупреждение",
        "severity": "warning",
    },
    ("alarm_reg_20", 6): {
        "code": "M_WN_20_6",
        "name": "Input 3 Warning",
        "name_ru": "Дискретный вход 3 — предупреждение",
        "severity": "warning",
    },
    ("alarm_reg_20", 7): {
        "code": "M_WN_20_7",
        "name": "Input 4 Warning",
        "name_ru": "Дискретный вход 4 — предупреждение",
        "severity": "warning",
    },
    ("alarm_reg_20", 8): {
        "code": "M_WN_20_8",
        "name": "Input 5 Warning",
        "name_ru": "Дискретный вход 5 — предупреждение",
        "severity": "warning",
    },
    ("alarm_reg_20", 9): {
        "code": "M_WN_20_9",
        "name": "Input 6 Warning",
        "name_ru": "Дискретный вход 6 — предупреждение",
        "severity": "warning",
    },
    ("alarm_reg_20", 10): {
        "code": "M_WN_20_10",
        "name": "Input 7 Warning",
        "name_ru": "Дискретный вход 7 — предупреждение",
        "severity": "warning",
    },
    ("alarm_reg_20", 11): {
        "code": "M_WN_20_11",
        "name": "Input 8 Warning",
        "name_ru": "Дискретный вход 8 — предупреждение",
        "severity": "warning",
    },

    # Register 0021 — Warning (continued)
    ("alarm_reg_21", 2): {
        "code": "M_WN_21_2",
        "name": "Sync. Failure Warning",
        "name_ru": "Ошибка синхронизации",
        "severity": "warning",
        "analysis_key": "sync_failure_warning",
    },
    ("alarm_reg_21", 6): {
        "code": "M_WN_21_6",
        "name": "Mains Switch Transfer Failure Warning",
        "name_ru": "Ошибка переключения автомата сети",
        "severity": "warning",
    },
    ("alarm_reg_21", 7): {
        "code": "M_WN_21_7",
        "name": "Gen Switch Transfer Failure Warning",
        "name_ru": "Ошибка переключения автомата генератора",
        "severity": "warning",
    },
    ("alarm_reg_21", 15): {
        "code": "M_WN_21_15",
        "name": "Mains Output Power Limit",
        "name_ru": "Ограничение мощности сети",
        "severity": "warning",
    },

    # Register 0024 — Indication
    ("alarm_reg_24", 1): {
        "code": "M_IND_24_1",
        "name": "Maintenance Time Due Indication",
        "name_ru": "Плановое ТО — индикация",
        "severity": "indication",
    },

    # Register 0030 — Mains Trip
    ("alarm_reg_30", 0): {
        "code": "M_MT_30_0",
        "name": "Input 1 Mains Trip",
        "name_ru": "Дискретный вход 1 — Mains Trip",
        "severity": "mains_trip",
    },
    ("alarm_reg_30", 1): {
        "code": "M_MT_30_1",
        "name": "Input 2 Mains Trip",
        "name_ru": "Дискретный вход 2 — Mains Trip",
        "severity": "mains_trip",
    },
    ("alarm_reg_30", 2): {
        "code": "M_MT_30_2",
        "name": "Input 3 Mains Trip",
        "name_ru": "Дискретный вход 3 — Mains Trip",
        "severity": "mains_trip",
    },
    ("alarm_reg_30", 3): {
        "code": "M_MT_30_3",
        "name": "Input 4 Mains Trip",
        "name_ru": "Дискретный вход 4 — Mains Trip",
        "severity": "mains_trip",
    },
    ("alarm_reg_30", 4): {
        "code": "M_MT_30_4",
        "name": "Input 5 Mains Trip",
        "name_ru": "Дискретный вход 5 — Mains Trip",
        "severity": "mains_trip",
    },
    ("alarm_reg_30", 5): {
        "code": "M_MT_30_5",
        "name": "Input 6 Mains Trip",
        "name_ru": "Дискретный вход 6 — Mains Trip",
        "severity": "mains_trip",
    },
    ("alarm_reg_30", 6): {
        "code": "M_MT_30_6",
        "name": "Input 7 Mains Trip",
        "name_ru": "Дискретный вход 7 — Mains Trip",
        "severity": "mains_trip",
    },
    ("alarm_reg_30", 7): {
        "code": "M_MT_30_7",
        "name": "Input 8 Mains Trip",
        "name_ru": "Дискретный вход 8 — Mains Trip",
        "severity": "mains_trip",
    },
    ("alarm_reg_30", 8): {
        "code": "M_MT_30_8",
        "name": "Mains Overcurrent 1 Mains Trip",
        "name_ru": "Перегрузка по току сети 1 — Mains Trip",
        "severity": "mains_trip",
        "analysis_key": "mains_overcurrent_trip",
    },
    ("alarm_reg_30", 9): {
        "code": "M_MT_30_9",
        "name": "Mains Overcurrent 2 Mains Trip",
        "name_ru": "Перегрузка по току сети 2 — Mains Trip",
        "severity": "mains_trip",
        "analysis_key": "mains_overcurrent_trip",
    },
    ("alarm_reg_30", 10): {
        "code": "M_MT_30_10",
        "name": "Mains Output Power Limit Mains Trip",
        "name_ru": "Ограничение мощности сети — Mains Trip",
        "severity": "mains_trip",
    },

    # Register 0044 — Mains fault detail
    ("alarm_reg_44", 0): {
        "code": "M001",
        "name": "Mains Abnormal",
        "name_ru": "Авария сети (общий флаг)",
        "severity": "warning",
    },
    ("alarm_reg_44", 1): {
        "code": "M002",
        "name": "Mains Overvoltage",
        "name_ru": "Перенапряжение сети",
        "severity": "warning",
        "analysis_key": "mains_overvoltage",
    },
    ("alarm_reg_44", 2): {
        "code": "M003",
        "name": "Mains Undervoltage",
        "name_ru": "Пониженное напряжение сети",
        "severity": "warning",
        "analysis_key": "mains_undervoltage",
    },
    ("alarm_reg_44", 3): {
        "code": "M004",
        "name": "Mains Overfrequency",
        "name_ru": "Повышенная частота сети",
        "severity": "warning",
        "analysis_key": "mains_overfrequency",
    },
    ("alarm_reg_44", 4): {
        "code": "M005",
        "name": "Mains Underfrequency",
        "name_ru": "Пониженная частота сети",
        "severity": "warning",
        "analysis_key": "mains_underfrequency",
    },
    ("alarm_reg_44", 5): {
        "code": "M006",
        "name": "Mains Loss Phase",
        "name_ru": "Потеря фазы сети",
        "severity": "warning",
        "analysis_key": "mains_loss_phase",
    },
    ("alarm_reg_44", 6): {
        "code": "M007",
        "name": "Mains Reverse Phase Sequence",
        "name_ru": "Обратная последовательность фаз сети",
        "severity": "warning",
        "analysis_key": "mains_reverse_phase",
    },
    ("alarm_reg_44", 7): {
        "code": "M008",
        "name": "Mains Blackout",
        "name_ru": "Полное отключение сети (блэкаут)",
        "severity": "warning",
        "analysis_key": "mains_blackout",
    },
}


# ---------------------------------------------------------------------------
# HGM9520N (Generator) — Alarm Data Table
# 7 groups, each with offsets 0-5 (6 registers x 16 bits)
# Keys: (register_field_name, bit_number)
# ---------------------------------------------------------------------------

ALARM_MAP_HGM9520N: dict[tuple[str, int], dict] = {
    # ============ SHUTDOWN GROUP (alarm_sd_0 .. alarm_sd_5) ============

    # Offset 0 (alarm_sd_0)
    ("alarm_sd_0", 0): {
        "code": "G_SD_0_0",
        "name": "Emergency Stop Alarm",
        "name_ru": "Аварийный останов (кнопка)",
        "severity": "shutdown",
        "group": "shutdown",
        "analysis_key": "emergency_stop",
    },
    ("alarm_sd_0", 1): {
        "code": "G_SD_0_1",
        "name": "Overspeed Alarm",
        "name_ru": "Превышение оборотов двигателя",
        "severity": "shutdown",
        "group": "shutdown",
        "analysis_key": "overspeed",
    },
    ("alarm_sd_0", 2): {
        "code": "G_SD_0_2",
        "name": "Underspeed Alarm",
        "name_ru": "Пониженные обороты двигателя",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_0", 3): {
        "code": "G_SD_0_3",
        "name": "Speed Signal Loss",
        "name_ru": "Потеря сигнала скорости (датчик оборотов)",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_0", 4): {
        "code": "G_SD_0_4",
        "name": "Gen Overfrequency",
        "name_ru": "Повышенная частота генератора",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_0", 5): {
        "code": "G_SD_0_5",
        "name": "Gen Underfrequency",
        "name_ru": "Пониженная частота генератора",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_0", 6): {
        "code": "G_SD_0_6",
        "name": "Gen Overvoltage",
        "name_ru": "Перенапряжение генератора",
        "severity": "shutdown",
        "group": "shutdown",
        "analysis_key": "gen_overvoltage",
    },
    ("alarm_sd_0", 7): {
        "code": "G_SD_0_7",
        "name": "Gen Undervoltage",
        "name_ru": "Пониженное напряжение генератора",
        "severity": "shutdown",
        "group": "shutdown",
        "analysis_key": "gen_undervoltage",
    },
    ("alarm_sd_0", 8): {
        "code": "G_SD_0_8",
        "name": "Crank Failure Alarm",
        "name_ru": "Отказ запуска (стартер)",
        "severity": "shutdown",
        "group": "shutdown",
        "analysis_key": "crank_failure",
    },
    ("alarm_sd_0", 9): {
        "code": "G_SD_0_9",
        "name": "Gen Overcurrent",
        "name_ru": "Перегрузка по току генератора",
        "severity": "shutdown",
        "group": "shutdown",
        "analysis_key": "gen_overcurrent",
    },
    ("alarm_sd_0", 10): {
        "code": "G_SD_0_10",
        "name": "Current Imbalance",
        "name_ru": "Дисбаланс токов по фазам",
        "severity": "shutdown",
        "group": "shutdown",
        "analysis_key": "current_imbalance",
    },
    ("alarm_sd_0", 11): {
        "code": "G_SD_0_11",
        "name": "Earth Fault",
        "name_ru": "Замыкание на землю",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_0", 12): {
        "code": "G_SD_0_12",
        "name": "Reverse Power Alarm",
        "name_ru": "Обратная мощность (генератор потребляет)",
        "severity": "shutdown",
        "group": "shutdown",
        "analysis_key": "reverse_power",
    },
    ("alarm_sd_0", 13): {
        "code": "G_SD_0_13",
        "name": "Over Power Alarm",
        "name_ru": "Перегрузка по мощности",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_0", 14): {
        "code": "G_SD_0_14",
        "name": "Loss of Excitation Fault",
        "name_ru": "Потеря возбуждения генератора",
        "severity": "shutdown",
        "group": "shutdown",
        "analysis_key": "loss_of_excitation",
    },
    ("alarm_sd_0", 15): {
        "code": "G_SD_0_15",
        "name": "ECU Communication Failure",
        "name_ru": "Потеря связи с блоком управления двигателем",
        "severity": "shutdown",
        "group": "shutdown",
    },

    # Offset 1 (alarm_sd_1)
    ("alarm_sd_1", 0): {
        "code": "G_SD_1_0",
        "name": "ECU Alarm",
        "name_ru": "Ошибка блока управления двигателем",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_1", 1): {
        "code": "G_SD_1_1",
        "name": "High Temp. Input Alarm",
        "name_ru": "Высокая температура (дискретный вход)",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_1", 2): {
        "code": "G_SD_1_2",
        "name": "Low Oil Pressure Input Alarm",
        "name_ru": "Низкое давление масла (дискретный вход)",
        "severity": "shutdown",
        "group": "shutdown",
        "analysis_key": "low_oil_pressure",
    },
    ("alarm_sd_1", 3): {
        "code": "G_SD_1_3",
        "name": "MSC ID Error",
        "name_ru": "Ошибка ID в мультисетевой коммуникации",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_1", 4): {
        "code": "G_SD_1_4",
        "name": "Voltage Bus Error",
        "name_ru": "Ошибка шины напряжения",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_1", 5): {
        "code": "G_SD_1_5",
        "name": "Gen Phase Sequence Error",
        "name_ru": "Ошибка чередования фаз генератора",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_1", 6): {
        "code": "G_SD_1_6",
        "name": "Voltage Bus Phase Sequence Error",
        "name_ru": "Ошибка чередования фаз шины",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_1", 7): {
        "code": "G_SD_1_7",
        "name": "Temp. Sensor Open",
        "name_ru": "Обрыв датчика температуры",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_1", 8): {
        "code": "G_SD_1_8",
        "name": "High Engine Temp.",
        "name_ru": "Высокая температура двигателя",
        "severity": "shutdown",
        "group": "shutdown",
        "analysis_key": "high_engine_temp",
    },
    ("alarm_sd_1", 9): {
        "code": "G_SD_1_9",
        "name": "Low Engine Temp.",
        "name_ru": "Низкая температура двигателя",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_1", 10): {
        "code": "G_SD_1_10",
        "name": "Temp. Sensor Error",
        "name_ru": "Ошибка датчика температуры",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_1", 11): {
        "code": "G_SD_1_11",
        "name": "Oil Pressure Sensor Open",
        "name_ru": "Обрыв датчика давления масла",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_1", 12): {
        "code": "G_SD_1_12",
        "name": "High Oil Pressure",
        "name_ru": "Высокое давление масла",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_1", 13): {
        "code": "G_SD_1_13",
        "name": "Low Oil Pressure",
        "name_ru": "Низкое давление масла",
        "severity": "shutdown",
        "group": "shutdown",
        "analysis_key": "low_oil_pressure",
    },
    ("alarm_sd_1", 14): {
        "code": "G_SD_1_14",
        "name": "Oil Pressure Sensor Error",
        "name_ru": "Ошибка датчика давления масла",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_1", 15): {
        "code": "G_SD_1_15",
        "name": "Fuel Level Sensor Open",
        "name_ru": "Обрыв датчика уровня топлива",
        "severity": "shutdown",
        "group": "shutdown",
    },

    # Offset 2 (alarm_sd_2)
    ("alarm_sd_2", 0): {
        "code": "G_SD_2_0",
        "name": "High Fuel Level",
        "name_ru": "Высокий уровень топлива",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_2", 1): {
        "code": "G_SD_2_1",
        "name": "Low Fuel Level",
        "name_ru": "Низкий уровень топлива",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_2", 2): {
        "code": "G_SD_2_2",
        "name": "Fuel Level Sensor Error",
        "name_ru": "Ошибка датчика уровня топлива",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_2", 3): {
        "code": "G_SD_2_3",
        "name": "Aux. Sensor 1 Open",
        "name_ru": "Обрыв доп. датчика 1",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_2", 4): {
        "code": "G_SD_2_4",
        "name": "Aux. Sensor 1 High",
        "name_ru": "Доп. датчик 1 — высокое значение",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_2", 5): {
        "code": "G_SD_2_5",
        "name": "Aux. Sensor 1 Low",
        "name_ru": "Доп. датчик 1 — низкое значение",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_2", 6): {
        "code": "G_SD_2_6",
        "name": "Aux. Sensor 1 Error",
        "name_ru": "Ошибка доп. датчика 1",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_2", 7): {
        "code": "G_SD_2_7",
        "name": "Aux. Sensor 2 Open",
        "name_ru": "Обрыв доп. датчика 2",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_2", 11): {
        "code": "G_SD_2_11",
        "name": "Stop Failure",
        "name_ru": "Неудачная остановка двигателя",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_2", 12): {
        "code": "G_SD_2_12",
        "name": "Charging Failure",
        "name_ru": "Отказ зарядки аккумулятора",
        "severity": "shutdown",
        "group": "shutdown",
        "analysis_key": "charging_failure",
    },
    ("alarm_sd_2", 13): {
        "code": "G_SD_2_13",
        "name": "Battery Overvoltage",
        "name_ru": "Перенапряжение батареи",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_2", 14): {
        "code": "G_SD_2_14",
        "name": "Battery Undervoltage",
        "name_ru": "Пониженное напряжение батареи",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_2", 15): {
        "code": "G_SD_2_15",
        "name": "Synchronization Failure",
        "name_ru": "Ошибка синхронизации",
        "severity": "shutdown",
        "group": "shutdown",
    },

    # Offset 3 (alarm_sd_3)
    ("alarm_sd_3", 0): {
        "code": "G_SD_3_0",
        "name": "GOV Reach Limit",
        "name_ru": "Регулятор оборотов на пределе",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_3", 1): {
        "code": "G_SD_3_1",
        "name": "AVR Reach Limit",
        "name_ru": "Регулятор напряжения на пределе",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_3", 2): {
        "code": "G_SD_3_2",
        "name": "Gen Insufficient Capacity",
        "name_ru": "Недостаточная мощность генератора",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_3", 3): {
        "code": "G_SD_3_3",
        "name": "Voltage Out of Synchronization",
        "name_ru": "Напряжение вне окна синхронизации",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_3", 4): {
        "code": "G_SD_3_4",
        "name": "Frequency Out of Synchronization",
        "name_ru": "Частота вне окна синхронизации",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_3", 5): {
        "code": "G_SD_3_5",
        "name": "Phase Out of Synchronization",
        "name_ru": "Фаза вне окна синхронизации",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_3", 6): {
        "code": "G_SD_3_6",
        "name": "Mains Breaker Alarm",
        "name_ru": "Авария автомата сети",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_3", 7): {
        "code": "G_SD_3_7",
        "name": "Gen Breaker Alarm",
        "name_ru": "Авария автомата генератора",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_3", 8): {
        "code": "G_SD_3_8",
        "name": "Mains Close Failure",
        "name_ru": "Не удалось замкнуть автомат сети",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_3", 9): {
        "code": "G_SD_3_9",
        "name": "Gen Close Failure",
        "name_ru": "Не удалось замкнуть автомат генератора",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_3", 10): {
        "code": "G_SD_3_10",
        "name": "Mains Open Failure",
        "name_ru": "Не удалось разомкнуть автомат сети",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_3", 11): {
        "code": "G_SD_3_11",
        "name": "Gen Open Failure",
        "name_ru": "Не удалось разомкнуть автомат генератора",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_3", 12): {
        "code": "G_SD_3_12",
        "name": "Mains Overfrequency",
        "name_ru": "Повышенная частота сети",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_3", 13): {
        "code": "G_SD_3_13",
        "name": "Mains Underfrequency",
        "name_ru": "Пониженная частота сети",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_3", 14): {
        "code": "G_SD_3_14",
        "name": "Mains Overvoltage",
        "name_ru": "Перенапряжение сети",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_3", 15): {
        "code": "G_SD_3_15",
        "name": "Mains Undervoltage",
        "name_ru": "Пониженное напряжение сети",
        "severity": "shutdown",
        "group": "shutdown",
    },

    # Offset 4 (alarm_sd_4)
    ("alarm_sd_4", 0): {
        "code": "G_SD_4_0",
        "name": "Mains Frequency Change",
        "name_ru": "Резкое изменение частоты сети",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_4", 1): {
        "code": "G_SD_4_1",
        "name": "Mains Vector Drift",
        "name_ru": "Дрейф вектора напряжения сети",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_4", 2): {
        "code": "G_SD_4_2",
        "name": "Large Frequency Difference Warning",
        "name_ru": "Большая разница частот (генератор vs сеть)",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_4", 3): {
        "code": "G_SD_4_3",
        "name": "Few MSC",
        "name_ru": "Мало устройств в мультисети",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_4", 4): {
        "code": "G_SD_4_4",
        "name": "Maintenance 1 Time Due",
        "name_ru": "Подошло время ТО-1",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_4", 5): {
        "code": "G_SD_4_5",
        "name": "Maintenance 2 Time Due",
        "name_ru": "Подошло время ТО-2",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_4", 6): {
        "code": "G_SD_4_6",
        "name": "Maintenance 3 Time Due",
        "name_ru": "Подошло время ТО-3",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_4", 7): {
        "code": "G_SD_4_7",
        "name": "Low Water Level Alarm",
        "name_ru": "Низкий уровень охлаждающей жидкости",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_4", 8): {
        "code": "G_SD_4_8",
        "name": "Detonation Alarm",
        "name_ru": "Детонация",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_4", 9): {
        "code": "G_SD_4_9",
        "name": "Gas Leak Alarm",
        "name_ru": "Утечка газа",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_4", 10): {
        "code": "G_SD_4_10",
        "name": "Gen Reverse Phase Sequence",
        "name_ru": "Обратное чередование фаз генератора",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_4", 11): {
        "code": "G_SD_4_11",
        "name": "Gen Loss of Phase",
        "name_ru": "Потеря фазы генератора",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_4", 12): {
        "code": "G_SD_4_12",
        "name": "MSC1 Communication Failure",
        "name_ru": "Потеря связи с MSC1",
        "severity": "shutdown",
        "group": "shutdown",
    },
    ("alarm_sd_4", 13): {
        "code": "G_SD_4_13",
        "name": "MSC2 Communication Failure",
        "name_ru": "Потеря связи с MSC2",
        "severity": "shutdown",
        "group": "shutdown",
    },

    # Offset 5 (alarm_sd_5) — Digital Inputs
    ("alarm_sd_5", 0): {"code": "G_SD_5_0", "name": "Digital Input 1 Shutdown", "name_ru": "Дискретный вход 1 — останов", "severity": "shutdown", "group": "shutdown"},
    ("alarm_sd_5", 1): {"code": "G_SD_5_1", "name": "Digital Input 2 Shutdown", "name_ru": "Дискретный вход 2 — останов", "severity": "shutdown", "group": "shutdown"},
    ("alarm_sd_5", 2): {"code": "G_SD_5_2", "name": "Digital Input 3 Shutdown", "name_ru": "Дискретный вход 3 — останов", "severity": "shutdown", "group": "shutdown"},
    ("alarm_sd_5", 3): {"code": "G_SD_5_3", "name": "Digital Input 4 Shutdown", "name_ru": "Дискретный вход 4 — останов", "severity": "shutdown", "group": "shutdown"},
    ("alarm_sd_5", 4): {"code": "G_SD_5_4", "name": "Digital Input 5 Shutdown", "name_ru": "Дискретный вход 5 — останов", "severity": "shutdown", "group": "shutdown"},
    ("alarm_sd_5", 5): {"code": "G_SD_5_5", "name": "Digital Input 6 Shutdown", "name_ru": "Дискретный вход 6 — останов", "severity": "shutdown", "group": "shutdown"},
    ("alarm_sd_5", 6): {"code": "G_SD_5_6", "name": "Digital Input 7 Shutdown", "name_ru": "Дискретный вход 7 — останов", "severity": "shutdown", "group": "shutdown"},
    ("alarm_sd_5", 7): {"code": "G_SD_5_7", "name": "Digital Input 8 Shutdown", "name_ru": "Дискретный вход 8 — останов", "severity": "shutdown", "group": "shutdown"},

    # ============ WARNING GROUP (alarm_wn_0 .. alarm_wn_5) ============
    # Same bit layout as shutdown, but severity = "warning"

    # Offset 0 (alarm_wn_0)
    ("alarm_wn_0", 0): {"code": "G_WN_0_0", "name": "Emergency Stop Warning", "name_ru": "Аварийный останов — предупреждение", "severity": "warning", "group": "warning"},
    ("alarm_wn_0", 1): {"code": "G_WN_0_1", "name": "Overspeed Warning", "name_ru": "Превышение оборотов — предупреждение", "severity": "warning", "group": "warning"},
    ("alarm_wn_0", 2): {"code": "G_WN_0_2", "name": "Underspeed Warning", "name_ru": "Пониженные обороты — предупреждение", "severity": "warning", "group": "warning"},
    ("alarm_wn_0", 3): {"code": "G_WN_0_3", "name": "Speed Signal Loss Warning", "name_ru": "Потеря сигнала скорости — предупреждение", "severity": "warning", "group": "warning"},
    ("alarm_wn_0", 4): {"code": "G_WN_0_4", "name": "Gen Overfrequency Warning", "name_ru": "Повышенная частота генератора — предупреждение", "severity": "warning", "group": "warning"},
    ("alarm_wn_0", 5): {"code": "G_WN_0_5", "name": "Gen Underfrequency Warning", "name_ru": "Пониженная частота генератора — предупреждение", "severity": "warning", "group": "warning"},
    ("alarm_wn_0", 6): {"code": "G_WN_0_6", "name": "Gen Overvoltage Warning", "name_ru": "Перенапряжение генератора — предупреждение", "severity": "warning", "group": "warning"},
    ("alarm_wn_0", 7): {"code": "G_WN_0_7", "name": "Gen Undervoltage Warning", "name_ru": "Пониженное напряжение генератора — предупреждение", "severity": "warning", "group": "warning"},
    ("alarm_wn_0", 8): {"code": "G_WN_0_8", "name": "Crank Failure Warning", "name_ru": "Отказ запуска — предупреждение", "severity": "warning", "group": "warning"},
    ("alarm_wn_0", 9): {"code": "G_WN_0_9", "name": "Gen Overcurrent Warning", "name_ru": "Перегрузка по току — предупреждение", "severity": "warning", "group": "warning"},
    ("alarm_wn_0", 10): {"code": "G_WN_0_10", "name": "Current Imbalance Warning", "name_ru": "Дисбаланс токов — предупреждение", "severity": "warning", "group": "warning"},
    ("alarm_wn_0", 11): {"code": "G_WN_0_11", "name": "Earth Fault Warning", "name_ru": "Замыкание на землю — предупреждение", "severity": "warning", "group": "warning"},
    ("alarm_wn_0", 12): {"code": "G_WN_0_12", "name": "Reverse Power Warning", "name_ru": "Обратная мощность — предупреждение", "severity": "warning", "group": "warning"},
    ("alarm_wn_0", 13): {"code": "G_WN_0_13", "name": "Over Power Warning", "name_ru": "Перегрузка по мощности — предупреждение", "severity": "warning", "group": "warning"},
    ("alarm_wn_0", 14): {"code": "G_WN_0_14", "name": "Loss of Excitation Warning", "name_ru": "Потеря возбуждения — предупреждение", "severity": "warning", "group": "warning"},
    ("alarm_wn_0", 15): {"code": "G_WN_0_15", "name": "ECU Communication Warning", "name_ru": "Потеря связи с ECU — предупреждение", "severity": "warning", "group": "warning"},

    # Offset 1 (alarm_wn_1)
    ("alarm_wn_1", 0): {"code": "G_WN_1_0", "name": "ECU Warning", "name_ru": "Ошибка ECU — предупреждение", "severity": "warning", "group": "warning"},
    ("alarm_wn_1", 1): {"code": "G_WN_1_1", "name": "High Temp. Input Warning", "name_ru": "Высокая температура (вход) — предупреждение", "severity": "warning", "group": "warning"},
    ("alarm_wn_1", 2): {"code": "G_WN_1_2", "name": "Low Oil Pressure Input Warning", "name_ru": "Низкое давление масла (вход) — предупреждение", "severity": "warning", "group": "warning"},
    ("alarm_wn_1", 8): {"code": "G_WN_1_8", "name": "High Engine Temp. Warning", "name_ru": "Высокая температура двигателя — предупреждение", "severity": "warning", "group": "warning"},
    ("alarm_wn_1", 9): {"code": "G_WN_1_9", "name": "Low Engine Temp. Warning", "name_ru": "Низкая температура двигателя — предупреждение", "severity": "warning", "group": "warning"},
    ("alarm_wn_1", 12): {"code": "G_WN_1_12", "name": "High Oil Pressure Warning", "name_ru": "Высокое давление масла — предупреждение", "severity": "warning", "group": "warning"},
    ("alarm_wn_1", 13): {"code": "G_WN_1_13", "name": "Low Oil Pressure Warning", "name_ru": "Низкое давление масла — предупреждение", "severity": "warning", "group": "warning"},

    # Offset 2 (alarm_wn_2)
    ("alarm_wn_2", 0): {"code": "G_WN_2_0", "name": "High Fuel Level Warning", "name_ru": "Высокий уровень топлива — предупреждение", "severity": "warning", "group": "warning"},
    ("alarm_wn_2", 1): {"code": "G_WN_2_1", "name": "Low Fuel Level Warning", "name_ru": "Низкий уровень топлива — предупреждение", "severity": "warning", "group": "warning"},
    ("alarm_wn_2", 12): {"code": "G_WN_2_12", "name": "Charging Failure Warning", "name_ru": "Отказ зарядки — предупреждение", "severity": "warning", "group": "warning", "analysis_key": "charging_failure"},
    ("alarm_wn_2", 13): {"code": "G_WN_2_13", "name": "Battery Overvoltage Warning", "name_ru": "Перенапряжение батареи — предупреждение", "severity": "warning", "group": "warning"},
    ("alarm_wn_2", 14): {"code": "G_WN_2_14", "name": "Battery Undervoltage Warning", "name_ru": "Пониженное напряжение батареи — предупреждение", "severity": "warning", "group": "warning"},
    ("alarm_wn_2", 15): {"code": "G_WN_2_15", "name": "Synchronization Failure Warning", "name_ru": "Ошибка синхронизации — предупреждение", "severity": "warning", "group": "warning"},

    # Offset 3 (alarm_wn_3)
    ("alarm_wn_3", 14): {"code": "G_WN_3_14", "name": "Mains Overvoltage Warning", "name_ru": "Перенапряжение сети — предупреждение", "severity": "warning", "group": "warning"},
    ("alarm_wn_3", 15): {"code": "G_WN_3_15", "name": "Mains Undervoltage Warning", "name_ru": "Пониженное напряжение сети — предупреждение", "severity": "warning", "group": "warning"},

    # Offset 4 (alarm_wn_4)
    ("alarm_wn_4", 4): {"code": "G_WN_4_4", "name": "Maintenance 1 Time Due Warning", "name_ru": "Подошло время ТО-1 — предупреждение", "severity": "warning", "group": "warning"},
    ("alarm_wn_4", 5): {"code": "G_WN_4_5", "name": "Maintenance 2 Time Due Warning", "name_ru": "Подошло время ТО-2 — предупреждение", "severity": "warning", "group": "warning"},
    ("alarm_wn_4", 6): {"code": "G_WN_4_6", "name": "Maintenance 3 Time Due Warning", "name_ru": "Подошло время ТО-3 — предупреждение", "severity": "warning", "group": "warning"},
    ("alarm_wn_4", 7): {"code": "G_WN_4_7", "name": "Low Water Level Warning", "name_ru": "Низкий уровень ОЖ — предупреждение", "severity": "warning", "group": "warning"},

    # Offset 5 (alarm_wn_5) — Digital Inputs Warning
    ("alarm_wn_5", 0): {"code": "G_WN_5_0", "name": "Digital Input 1 Warning", "name_ru": "Дискретный вход 1 — предупреждение", "severity": "warning", "group": "warning"},
    ("alarm_wn_5", 1): {"code": "G_WN_5_1", "name": "Digital Input 2 Warning", "name_ru": "Дискретный вход 2 — предупреждение", "severity": "warning", "group": "warning"},
    ("alarm_wn_5", 2): {"code": "G_WN_5_2", "name": "Digital Input 3 Warning", "name_ru": "Дискретный вход 3 — предупреждение", "severity": "warning", "group": "warning"},
    ("alarm_wn_5", 3): {"code": "G_WN_5_3", "name": "Digital Input 4 Warning", "name_ru": "Дискретный вход 4 — предупреждение", "severity": "warning", "group": "warning"},
    ("alarm_wn_5", 4): {"code": "G_WN_5_4", "name": "Digital Input 5 Warning", "name_ru": "Дискретный вход 5 — предупреждение", "severity": "warning", "group": "warning"},
    ("alarm_wn_5", 5): {"code": "G_WN_5_5", "name": "Digital Input 6 Warning", "name_ru": "Дискретный вход 6 — предупреждение", "severity": "warning", "group": "warning"},
    ("alarm_wn_5", 6): {"code": "G_WN_5_6", "name": "Digital Input 7 Warning", "name_ru": "Дискретный вход 7 — предупреждение", "severity": "warning", "group": "warning"},
    ("alarm_wn_5", 7): {"code": "G_WN_5_7", "name": "Digital Input 8 Warning", "name_ru": "Дискретный вход 8 — предупреждение", "severity": "warning", "group": "warning"},

    # ============ TRIP & STOP GROUP (alarm_ts_0 .. alarm_ts_5) ============
    # Same offset layout, severity = "trip"

    ("alarm_ts_0", 0): {"code": "G_TS_0_0", "name": "Emergency Stop Trip&Stop", "name_ru": "Аварийный останов — Trip&Stop", "severity": "trip", "group": "trip_stop"},
    ("alarm_ts_0", 1): {"code": "G_TS_0_1", "name": "Overspeed Trip&Stop", "name_ru": "Превышение оборотов — Trip&Stop", "severity": "trip", "group": "trip_stop"},
    ("alarm_ts_0", 6): {"code": "G_TS_0_6", "name": "Gen Overvoltage Trip&Stop", "name_ru": "Перенапряжение генератора — Trip&Stop", "severity": "trip", "group": "trip_stop"},
    ("alarm_ts_0", 7): {"code": "G_TS_0_7", "name": "Gen Undervoltage Trip&Stop", "name_ru": "Пониженное напряжение генератора — Trip&Stop", "severity": "trip", "group": "trip_stop"},
    ("alarm_ts_0", 8): {"code": "G_TS_0_8", "name": "Crank Failure Trip&Stop", "name_ru": "Отказ запуска — Trip&Stop", "severity": "trip", "group": "trip_stop"},
    ("alarm_ts_0", 9): {"code": "G_TS_0_9", "name": "Gen Overcurrent Trip&Stop", "name_ru": "Перегрузка по току — Trip&Stop", "severity": "trip", "group": "trip_stop"},
    ("alarm_ts_0", 12): {"code": "G_TS_0_12", "name": "Reverse Power Trip&Stop", "name_ru": "Обратная мощность — Trip&Stop", "severity": "trip", "group": "trip_stop"},

    ("alarm_ts_1", 8): {"code": "G_TS_1_8", "name": "High Engine Temp. Trip&Stop", "name_ru": "Высокая температура двигателя — Trip&Stop", "severity": "trip", "group": "trip_stop"},
    ("alarm_ts_1", 13): {"code": "G_TS_1_13", "name": "Low Oil Pressure Trip&Stop", "name_ru": "Низкое давление масла — Trip&Stop", "severity": "trip", "group": "trip_stop"},

    ("alarm_ts_5", 0): {"code": "G_TS_5_0", "name": "Digital Input 1 Trip&Stop", "name_ru": "Дискретный вход 1 — Trip&Stop", "severity": "trip", "group": "trip_stop"},
    ("alarm_ts_5", 1): {"code": "G_TS_5_1", "name": "Digital Input 2 Trip&Stop", "name_ru": "Дискретный вход 2 — Trip&Stop", "severity": "trip", "group": "trip_stop"},
    ("alarm_ts_5", 2): {"code": "G_TS_5_2", "name": "Digital Input 3 Trip&Stop", "name_ru": "Дискретный вход 3 — Trip&Stop", "severity": "trip", "group": "trip_stop"},
    ("alarm_ts_5", 3): {"code": "G_TS_5_3", "name": "Digital Input 4 Trip&Stop", "name_ru": "Дискретный вход 4 — Trip&Stop", "severity": "trip", "group": "trip_stop"},

    # ============ TRIP GROUP (alarm_tr_0 .. alarm_tr_5) ============
    ("alarm_tr_0", 0): {"code": "G_TR_0_0", "name": "Emergency Stop Trip", "name_ru": "Аварийный останов — Trip", "severity": "trip", "group": "trip"},
    ("alarm_tr_0", 1): {"code": "G_TR_0_1", "name": "Overspeed Trip", "name_ru": "Превышение оборотов — Trip", "severity": "trip", "group": "trip"},
    ("alarm_tr_0", 9): {"code": "G_TR_0_9", "name": "Gen Overcurrent Trip", "name_ru": "Перегрузка по току — Trip", "severity": "trip", "group": "trip"},
    ("alarm_tr_0", 12): {"code": "G_TR_0_12", "name": "Reverse Power Trip", "name_ru": "Обратная мощность — Trip", "severity": "trip", "group": "trip"},

    # ============ BLOCK GROUP (alarm_bk_0 .. alarm_bk_5) ============
    ("alarm_bk_0", 8): {"code": "G_BK_0_8", "name": "Crank Failure Block", "name_ru": "Отказ запуска — блокировка", "severity": "block", "group": "block"},
    ("alarm_bk_2", 11): {"code": "G_BK_2_11", "name": "Stop Failure Block", "name_ru": "Неудачная остановка — блокировка", "severity": "block", "group": "block"},
    ("alarm_bk_2", 12): {"code": "G_BK_2_12", "name": "Charging Failure Block", "name_ru": "Отказ зарядки — блокировка", "severity": "block", "group": "block"},
}


# ---------------------------------------------------------------------------
# Register field names per device type
# Used by detector to know which fields to scan for alarm bits
# ---------------------------------------------------------------------------

ALARM_REGISTER_FIELDS_HGM9560 = [
    "alarm_reg_00", "alarm_reg_01", "alarm_reg_02", "alarm_reg_08",
    "alarm_reg_12", "alarm_reg_14", "alarm_reg_16",
    "alarm_reg_20", "alarm_reg_21", "alarm_reg_24",
    "alarm_reg_30", "alarm_reg_44",
]

ALARM_REGISTER_FIELDS_HGM9520N = [
    "alarm_sd_0", "alarm_sd_1", "alarm_sd_2", "alarm_sd_3", "alarm_sd_4", "alarm_sd_5",
    "alarm_ts_0", "alarm_ts_1", "alarm_ts_2", "alarm_ts_3", "alarm_ts_4", "alarm_ts_5",
    "alarm_tr_0", "alarm_tr_1", "alarm_tr_2", "alarm_tr_3", "alarm_tr_4", "alarm_tr_5",
    "alarm_bk_0", "alarm_bk_1", "alarm_bk_2", "alarm_bk_3", "alarm_bk_4", "alarm_bk_5",
    "alarm_wn_0", "alarm_wn_1", "alarm_wn_2", "alarm_wn_3", "alarm_wn_4", "alarm_wn_5",
]


def get_alarm_map(device_type: str) -> dict[tuple[str, int], dict]:
    """Return alarm map for device type."""
    if device_type == "ats":
        return ALARM_MAP_HGM9560
    elif device_type == "generator":
        return ALARM_MAP_HGM9520N
    return {}


def get_alarm_fields(device_type: str) -> list[str]:
    """Return list of alarm register field names for device type."""
    if device_type == "ats":
        return ALARM_REGISTER_FIELDS_HGM9560
    elif device_type == "generator":
        return ALARM_REGISTER_FIELDS_HGM9520N
    return []
