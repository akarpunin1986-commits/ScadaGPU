"""Root-cause analysis engine for alarm events.

Given alarm_code + metrics_snapshot → produces analysis_result dict with:
  - manual_description (what the alarm means)
  - manual_danger (why it's dangerous)
  - evidence (metrics proving the alarm)
  - probable_cause (why it happened)
  - recommendation (what to do)

Analysis is performed on the backend at the moment of alarm occurrence,
not on the frontend.
"""
from __future__ import annotations

import logging

logger = logging.getLogger("scada.alarm_analytics.analyzer")


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def determine_undervoltage_cause(m: dict) -> str:
    """Determine probable cause of mains undervoltage."""
    try:
        mains = m.get("mains", {})
        ua = mains.get("ua", 0) or 0
        ub = mains.get("ub", 0) or 0
        uc = mains.get("uc", 0) or 0
        min_v = min(ua, ub, uc)
        max_v = max(ua, ub, uc)
        spread = max_v - min_v

        if max_v < 180:
            return "Общая просадка напряжения сети по всем фазам — проблема на стороне энергоснабжающей организации"
        elif spread > 20:
            lost = "A" if ua == min_v else ("B" if ub == min_v else "C")
            return (
                f"Асимметрия напряжений. Просадка на фазе {lost} ({min_v}V). "
                f"Возможен плохой контакт на фазе {lost} или перегрузка этой фазы"
            )
        else:
            return (
                f"Равномерная просадка ({min_v}-{max_v}V). "
                f"Вероятно, проблема на подстанции или перегрузка трансформатора"
            )
    except Exception:
        return "Не удалось определить причину просадки"


def identify_lost_phase(m: dict) -> str:
    """Identify which phase(s) are lost."""
    try:
        mains = m.get("mains", {})
        ua = mains.get("ua", 0) or 0
        ub = mains.get("ub", 0) or 0
        uc = mains.get("uc", 0) or 0
        threshold = 50
        lost = []
        if ua < threshold:
            lost.append("A")
        if ub < threshold:
            lost.append("B")
        if uc < threshold:
            lost.append("C")
        return ", ".join(lost) if lost else "Не определена (все фазы > 50V)"
    except Exception:
        return "Ошибка определения"


def determine_sync_failure_cause(m: dict) -> str:
    """Determine why synchronization failed."""
    try:
        busbar = m.get("busbar", {})
        mains = m.get("mains", {})
        bf = busbar.get("freq", 0) or 0
        mf = mains.get("freq", 0) or 0
        bu = busbar.get("uab", 0) or 0
        mu = mains.get("uab", 0) or 0
        df = abs(bf - mf)
        du = abs(bu - mu)

        reasons = []
        if df > 0.5:
            reasons.append(f"Большая разница частот (DF={df:.2f} Гц) — проблема с регулятором оборотов (GOV)")
        if du > 15:
            reasons.append(f"Большая разница напряжений (DU={du}V) — проблема с регулятором напряжения (AVR)")
        if not reasons:
            reasons.append("Фазовый угол не совпал в течение таймаута синхронизации")
        return "; ".join(reasons)
    except Exception:
        return "Не удалось определить причину"


# ---------------------------------------------------------------------------
# Analysis rules: HGM9560 (SPR)
# ---------------------------------------------------------------------------

def _analyze_mains_undervoltage(m: dict) -> dict:
    mains = m.get("mains", {})
    return {
        "trigger": "Mains Undervoltage",
        "evidence": [
            f"UA={mains.get('ua', '?')}V, UB={mains.get('ub', '?')}V, UC={mains.get('uc', '?')}V",
            f"Частота сети: {mains.get('freq', '?')} Гц",
        ],
        "probable_cause": determine_undervoltage_cause(m),
        "recommendation": "Проверить качество входного напряжения от энергоснабжающей организации. Проверить состояние подводящего кабеля и контактных соединений.",
    }


def _analyze_mains_overvoltage(m: dict) -> dict:
    mains = m.get("mains", {})
    return {
        "evidence": [f"UA={mains.get('ua', '?')}V, UB={mains.get('ub', '?')}V, UC={mains.get('uc', '?')}V"],
        "probable_cause": "Повышенное напряжение от энергоснабжающей организации или сброс нагрузки в сети",
        "recommendation": "Проверить напряжение на вводе. Если проблема постоянная — обратиться в энергосбыт.",
    }


def _analyze_mains_overfreq(m: dict) -> dict:
    mains = m.get("mains", {})
    return {
        "evidence": [f"Частота сети: {mains.get('freq', '?')} Гц"],
        "probable_cause": "Нестабильность внешней электросети, избыток генерации",
        "recommendation": "Проверить частоту на вводе. Если проблема повторяется — установить стабилизатор частоты.",
    }


def _analyze_mains_underfreq(m: dict) -> dict:
    mains = m.get("mains", {})
    return {
        "evidence": [f"Частота сети: {mains.get('freq', '?')} Гц"],
        "probable_cause": "Перегрузка внешней энергосистемы, дефицит генерации",
        "recommendation": "Проверить частоту на вводе. При постоянных просадках — рассмотреть увеличение доли собственной генерации.",
    }


def _analyze_mains_loss_phase(m: dict) -> dict:
    mains = m.get("mains", {})
    return {
        "evidence": [
            f"UA={mains.get('ua', '?')}V, UB={mains.get('ub', '?')}V, UC={mains.get('uc', '?')}V",
            f"Потерянная фаза: {identify_lost_phase(m)}",
        ],
        "probable_cause": "Обрыв фазного провода на вводе, сгорел предохранитель на одной фазе, авария на подстанции",
        "recommendation": "СРОЧНО проверить все три фазы на вводе. Проверить предохранители и автоматы.",
    }


def _analyze_mains_blackout(m: dict) -> dict:
    mains = m.get("mains", {})
    switches = m.get("switches", {})
    return {
        "evidence": [
            f"UA={mains.get('ua', '?')}V, UB={mains.get('ub', '?')}V, UC={mains.get('uc', '?')}V",
            f"Автомат сети: {switches.get('mains_switch_text', '?')}",
        ],
        "probable_cause": "Отключение электроснабжения от энергоснабжающей организации, авария на подстанции",
        "recommendation": "Проверить наличие напряжения на вводе в здание. Проверить вводной автомат. Связаться с диспетчером энергосбыта.",
    }


def _analyze_mains_reverse_phase(m: dict) -> dict:
    mains = m.get("mains", {})
    return {
        "evidence": [f"UAB={mains.get('uab', '?')}V, UBC={mains.get('ubc', '?')}V, UCA={mains.get('uca', '?')}V"],
        "probable_cause": "Перепутаны фазы при подключении кабеля (после ремонта, после аварии)",
        "recommendation": "Проверить подключение фаз на вводе. НЕ замыкать автомат сети до устранения!",
    }


def _analyze_mains_overcurrent(m: dict) -> dict:
    mains = m.get("mains", {})
    return {
        "evidence": [
            f"IA={mains.get('ia', '?')}A, IB={mains.get('ib', '?')}A, IC={mains.get('ic', '?')}A",
            f"P сети={mains.get('total_p', '?')} кВт",
        ],
        "probable_cause": "Подключение слишком большой нагрузки, короткое замыкание в нагрузке",
        "recommendation": "Проверить потребление нагрузки. Проверить, нет ли КЗ в сети потребителей.",
    }


def _analyze_battery_undervoltage(m: dict) -> dict:
    return {
        "evidence": [f"Напряжение батареи: {m.get('battery_voltage', '?')}V"],
        "probable_cause": "Неисправность зарядного устройства, старение аккумулятора, длительный простой без подзарядки",
        "recommendation": "Проверить зарядное устройство. Измерить напряжение батареи мультиметром. При необходимости заменить батарею.",
    }


def _analyze_sync_failure(m: dict) -> dict:
    busbar = m.get("busbar", {})
    mains = m.get("mains", {})
    bf = busbar.get("freq", 0) or 0
    mf = mains.get("freq", 0) or 0
    bu = busbar.get("uab", 0) or 0
    mu = mains.get("uab", 0) or 0
    return {
        "evidence": [
            f"F шины: {bf} Гц, F сети: {mf} Гц",
            f"U шины: {bu}V, U сети: {mu}V",
            f"DF = {abs(bf - mf):.2f} Гц",
            f"DU = {abs(bu - mu)}V",
        ],
        "probable_cause": determine_sync_failure_cause(m),
        "recommendation": "Проверить работу GOV (регулятор оборотов) и AVR (регулятор напряжения). Проверить уставки окна синхронизации.",
    }


ANALYSIS_RULES_HGM9560 = {
    "mains_undervoltage": {
        "manual_description": "Напряжение сети упало ниже уставки Mains Undervoltage. Контроллер фиксирует аварию сети.",
        "manual_danger": "При пониженном напряжении растут токи, перегреваются кабели и оборудование. Генератор может перегрузиться при попытке компенсировать.",
        "analyze": _analyze_mains_undervoltage,
    },
    "mains_overvoltage": {
        "manual_description": "Напряжение сети превысило уставку Mains Overvoltage.",
        "manual_danger": "Перенапряжение может повредить чувствительное оборудование, электронику, конденсаторы.",
        "analyze": _analyze_mains_overvoltage,
    },
    "mains_overfrequency": {
        "manual_description": "Частота сети превысила уставку Mains Overfrequency (обычно >51 Гц).",
        "manual_danger": "Повышенная частота ускоряет вращение асинхронных двигателей, нарушает работу электроники.",
        "analyze": _analyze_mains_overfreq,
    },
    "mains_underfrequency": {
        "manual_description": "Частота сети упала ниже уставки Mains Underfrequency (обычно <49 Гц).",
        "manual_danger": "Пониженная частота указывает на перегрузку энергосистемы. Двигатели замедляются.",
        "analyze": _analyze_mains_underfreq,
    },
    "mains_loss_phase": {
        "manual_description": "Потеря одной или нескольких фаз сетевого напряжения.",
        "manual_danger": "КРИТИЧНО. Работа трёхфазного оборудования на двух фазах приводит к перегреву и выходу из строя двигателей.",
        "analyze": _analyze_mains_loss_phase,
    },
    "mains_blackout": {
        "manual_description": "Полное отключение сетевого напряжения (все три фазы = 0).",
        "manual_danger": "КРИТИЧНО. Полная потеря внешнего питания. Нагрузка переходит полностью на генератор.",
        "analyze": _analyze_mains_blackout,
    },
    "mains_reverse_phase": {
        "manual_description": "Обратная последовательность фаз сетевого напряжения.",
        "manual_danger": "Трёхфазные двигатели будут вращаться в обратном направлении. Компрессоры, насосы выйдут из строя.",
        "analyze": _analyze_mains_reverse_phase,
    },
    "mains_overcurrent_trip": {
        "manual_description": "Ток сети превысил уставку Mains Overcurrent. Сработал Trip автомата сети.",
        "manual_danger": "Перегрузка сетевого ввода. Возможен перегрев кабелей и оборудования.",
        "analyze": _analyze_mains_overcurrent,
    },
    "battery_undervoltage_warning": {
        "manual_description": "Напряжение аккумуляторной батареи ниже уставки.",
        "manual_danger": "При полной разрядке батареи контроллер потеряет питание и не сможет запустить генератор.",
        "analyze": _analyze_battery_undervoltage,
    },
    "sync_failure_warning": {
        "manual_description": "Не удалось синхронизировать генератор с сетью в отведённое время.",
        "manual_danger": "Включение генератора параллельно с сетью без синхронизации вызовет мощный бросок тока.",
        "analyze": _analyze_sync_failure,
    },
}


# ---------------------------------------------------------------------------
# Analysis rules: HGM9520N (Generator)
# ---------------------------------------------------------------------------

def _analyze_emergency_stop(m: dict) -> dict:
    return {
        "probable_cause": "Нажата физическая кнопка аварийного останова на контроллере или выносная кнопка",
        "recommendation": "Выяснить причину нажатия. Деблокировать кнопку, сбросить аварию.",
    }


def _analyze_overspeed(m: dict) -> dict:
    return {
        "evidence": [f"Обороты: {m.get('engine_speed', '?')} об/мин"],
        "probable_cause": "Неисправность регулятора оборотов (GOV), заклинивание топливной рейки, резкий сброс нагрузки",
        "recommendation": "НЕ ЗАПУСКАТЬ до проверки. Проверить регулятор оборотов, топливную систему, актуатор.",
    }


def _analyze_gen_overvoltage(m: dict) -> dict:
    gen = m.get("gen", {})
    return {
        "evidence": [f"UA={gen.get('ua', '?')}V, UB={gen.get('ub', '?')}V, UC={gen.get('uc', '?')}V"],
        "probable_cause": "Неисправность AVR (автоматический регулятор напряжения), повышенные обороты, резкий сброс нагрузки",
        "recommendation": "Проверить AVR, обороты двигателя, нагрузку.",
    }


def _analyze_gen_undervoltage(m: dict) -> dict:
    gen = m.get("gen", {})
    ua = gen.get("ua", 0) or 0
    ub = gen.get("ub", 0) or 0
    uc = gen.get("uc", 0) or 0
    return {
        "evidence": [
            f"UA={ua}V, UB={ub}V, UC={uc}V",
            f"Минимальная фаза: {min(ua, ub, uc)}V",
        ],
        "probable_cause": "Перегрузка генератора, неисправность AVR, проблемы с возбуждением",
        "recommendation": "Проверить нагрузку (не превышает ли номинал). Проверить AVR и обмотку возбуждения.",
    }


def _analyze_gen_overcurrent(m: dict) -> dict:
    gen = m.get("gen", {})
    return {
        "evidence": [
            f"IA={gen.get('ia', '?')}A, IB={gen.get('ib', '?')}A, IC={gen.get('ic', '?')}A",
            f"P генератора: {gen.get('total_p', '?')} кВт",
        ],
        "probable_cause": "Перегрузка, короткое замыкание в нагрузке, пусковые токи крупного двигателя",
        "recommendation": "Проверить потребление нагрузки. Проверить, нет ли КЗ.",
    }


def _analyze_current_imbalance(m: dict) -> dict:
    gen = m.get("gen", {})
    ia = gen.get("ia", 0) or 0
    ib = gen.get("ib", 0) or 0
    ic = gen.get("ic", 0) or 0
    spread = max(ia, ib, ic) - min(ia, ib, ic)
    return {
        "evidence": [
            f"IA={ia}A, IB={ib}A, IC={ic}A",
            f"Макс. разброс: {spread:.1f}A",
        ],
        "probable_cause": "Несимметричная нагрузка (много однофазных потребителей на одной фазе), обрыв фазы нагрузки",
        "recommendation": "Перераспределить однофазные нагрузки между фазами. Проверить кабели.",
    }


def _analyze_reverse_power(m: dict) -> dict:
    gen = m.get("gen", {})
    return {
        "evidence": [f"P генератора: {gen.get('total_p', '?')} кВт (отрицательное = потребление)"],
        "probable_cause": "Недостаток топлива, проблемы с регулятором оборотов (GOV), заклинивание топливной рейки",
        "recommendation": "Проверить уровень топлива. Проверить регулятор оборотов. Проверить уставки распределения нагрузки.",
    }


def _analyze_crank_failure(m: dict) -> dict:
    return {
        "evidence": [f"Напряжение батареи: {m.get('battery_voltage', '?')}V"],
        "probable_cause": "Нет топлива, разряжена батарея, неисправен стартер, засор топливного фильтра, воздух в топливной системе",
        "recommendation": "Проверить: 1) уровень топлива; 2) напряжение батареи (>24V для запуска); 3) состояние стартера; 4) топливный фильтр.",
    }


def _analyze_high_engine_temp(m: dict) -> dict:
    return {
        "evidence": [f"Температура ОЖ: {m.get('coolant_temp', '?')} C"],
        "probable_cause": "Низкий уровень охлаждающей жидкости, неисправность термостата, засор радиатора, перегрузка генератора",
        "recommendation": "Проверить уровень ОЖ, радиатор (чистота), вентилятор, термостат. Не запускать до остывания.",
    }


def _analyze_low_oil_pressure(m: dict) -> dict:
    return {
        "evidence": [f"Давление масла: {m.get('oil_pressure', '?')} бар"],
        "probable_cause": "Низкий уровень масла, неисправность масляного насоса, засор масляного фильтра, утечка масла",
        "recommendation": "НЕМЕДЛЕННО проверить уровень масла щупом. Проверить нет ли утечек. НЕ ЗАПУСКАТЬ при низком уровне.",
    }


def _analyze_charging_failure(m: dict) -> dict:
    return {
        "evidence": [
            f"Батарея: {m.get('battery_voltage', '?')}V",
            f"Зарядное: {m.get('charger_voltage', '?')}V",
        ],
        "probable_cause": "Обрыв ремня генератора зарядки, неисправность реле-регулятора, плохой контакт на клеммах батареи",
        "recommendation": "Проверить ремень генератора зарядки, клеммы батареи, реле-регулятор.",
    }


def _analyze_loss_of_excitation(m: dict) -> dict:
    gen = m.get("gen", {})
    return {
        "evidence": [f"Q={gen.get('total_q', '?')} квар, P={gen.get('total_p', '?')} кВт"],
        "probable_cause": "Неисправность AVR, обрыв обмотки возбуждения, обрыв кабеля возбуждения, неисправность вращающегося выпрямителя",
        "recommendation": "Проверить AVR, кабели и обмотку возбуждения, вращающийся выпрямитель (если бесщёточный генератор).",
    }


ANALYSIS_RULES_HGM9520N = {
    "emergency_stop": {
        "manual_description": "Нажата кнопка аварийного останова (Emergency Stop).",
        "manual_danger": "Двигатель экстренно остановлен. Генератор не будет запускаться до деблокировки.",
        "analyze": _analyze_emergency_stop,
    },
    "overspeed": {
        "manual_description": "Обороты двигателя превысили уставку Overspeed (обычно >1650 об/мин при номинале 1500).",
        "manual_danger": "КРИТИЧНО. Разнос двигателя может привести к механическому разрушению.",
        "analyze": _analyze_overspeed,
    },
    "gen_overvoltage": {
        "manual_description": "Напряжение генератора превысило уставку Gen Overvoltage.",
        "manual_danger": "Перенапряжение может повредить обмотки генератора и подключённое оборудование.",
        "analyze": _analyze_gen_overvoltage,
    },
    "gen_undervoltage": {
        "manual_description": "Напряжение генератора ниже уставки Gen Undervoltage.",
        "manual_danger": "Пониженное напряжение приводит к росту токов и перегреву нагрузки.",
        "analyze": _analyze_gen_undervoltage,
    },
    "gen_overcurrent": {
        "manual_description": "Ток генератора превысил уставку Gen Overcurrent.",
        "manual_danger": "Перегрузка может повредить обмотки генератора и привести к возгоранию.",
        "analyze": _analyze_gen_overcurrent,
    },
    "current_imbalance": {
        "manual_description": "Разница токов между фазами превышает уставку Current Imbalance.",
        "manual_danger": "Дисбаланс токов вызывает дополнительный нагрев обмоток статора.",
        "analyze": _analyze_current_imbalance,
    },
    "reverse_power": {
        "manual_description": "Генератор потребляет мощность из сети вместо того, чтобы отдавать (обратная мощность).",
        "manual_danger": "Двигатель переходит в моторный режим. Для дизельного двигателя это чревато повреждением.",
        "analyze": _analyze_reverse_power,
    },
    "crank_failure": {
        "manual_description": "Двигатель не запустился после заданного количества попыток прокрутки.",
        "manual_danger": "Генератор не может выйти на рабочий режим. Нагрузка остаётся без резервного питания.",
        "analyze": _analyze_crank_failure,
    },
    "high_engine_temp": {
        "manual_description": "Температура двигателя превысила уставку High Engine Temp.",
        "manual_danger": "КРИТИЧНО. Перегрев двигателя может привести к заклиниванию и разрушению.",
        "analyze": _analyze_high_engine_temp,
    },
    "low_oil_pressure": {
        "manual_description": "Давление масла двигателя ниже уставки Low Oil Pressure.",
        "manual_danger": "КРИТИЧНО. Работа без смазки приводит к задиру подшипников и заклиниванию двигателя.",
        "analyze": _analyze_low_oil_pressure,
    },
    "charging_failure": {
        "manual_description": "Напряжение зарядки аккумулятора отсутствует или ниже нормы при работающем двигателе.",
        "manual_danger": "Без зарядки батарея разрядится и контроллер потеряет питание.",
        "analyze": _analyze_charging_failure,
    },
    "loss_of_excitation": {
        "manual_description": "Потеря возбуждения генератора — напряжение резко упало, реактивная мощность выросла.",
        "manual_danger": "Генератор не способен поддерживать напряжение. Нагрузка может остаться без питания.",
        "analyze": _analyze_loss_of_excitation,
    },
}


# ---------------------------------------------------------------------------
# Main analyze function
# ---------------------------------------------------------------------------

def analyze(alarm_code: str, device_type: str, snapshot: dict, alarm_def: dict) -> dict:
    """Perform root-cause analysis for an alarm event.

    Args:
        alarm_code: alarm code from definitions (e.g. "M003")
        device_type: "ats" or "generator"
        snapshot: metrics snapshot dict
        alarm_def: alarm definition dict with optional 'analysis_key'

    Returns:
        analysis_result dict with description, danger, evidence, cause, recommendation
    """
    try:
        analysis_key = alarm_def.get("analysis_key")
        if not analysis_key:
            # No specific analysis available — return basic info
            return {
                "manual_description": f"{alarm_def.get('name', alarm_code)}: {alarm_def.get('name_ru', '')}",
                "manual_danger": None,
                "evidence": [],
                "probable_cause": "Специфический анализ для данной аварии не настроен",
                "recommendation": "Обратитесь к документации SmartGen для данного кода аварии.",
            }

        # Select the right rule set
        if device_type == "ats":
            rules = ANALYSIS_RULES_HGM9560
        elif device_type == "generator":
            rules = ANALYSIS_RULES_HGM9520N
        else:
            rules = {}

        rule = rules.get(analysis_key)
        if not rule:
            return {
                "manual_description": f"{alarm_def.get('name', alarm_code)}: {alarm_def.get('name_ru', '')}",
                "manual_danger": None,
                "evidence": [],
                "probable_cause": "Правило анализа не найдено",
                "recommendation": "Обратитесь к документации SmartGen.",
            }

        # Run the analysis function
        analysis = rule["analyze"](snapshot)

        return {
            "manual_description": rule.get("manual_description", ""),
            "manual_danger": rule.get("manual_danger"),
            "evidence": analysis.get("evidence", []),
            "probable_cause": analysis.get("probable_cause", "Не определена"),
            "recommendation": analysis.get("recommendation", ""),
        }

    except Exception as exc:
        logger.error("Analysis error for %s/%s: %s", alarm_code, device_type, exc)
        return {
            "manual_description": alarm_def.get("name_ru", alarm_code),
            "manual_danger": None,
            "evidence": [],
            "probable_cause": f"Ошибка анализа: {exc}",
            "recommendation": "Обратитесь к документации SmartGen.",
        }
