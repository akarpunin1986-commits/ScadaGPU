# Demo Poller — эмуляция Modbus-устройств для E2E тестирования

## Цель

Скрипт `backend/app/services/demo_poller.py` генерирует реалистичные метрики
двух генераторов HGM9520N и одного ШПР HGM9560, пушит их в Redis в том же
формате что и настоящий `modbus_poller.py`. Фронтенд не отличает demo от реальных
данных — показания меняются в реальном времени.

## Архитектура

```
main.py lifespan
  ├── DEMO_MODE=true  → DemoPoller.start()      ← НОВОЕ
  └── DEMO_MODE=false → ModbusPoller.start()     ← как сейчас
```

Переключение через env-переменную `DEMO_MODE=true`. По умолчанию `false`.

---

## Файл 1: `backend/app/services/demo_poller.py`

### Класс `DemoPoller`

```python
class DemoPoller:
    """Эмулятор Modbus-устройств. Генерирует реалистичные метрики и пушит в Redis."""

    def __init__(self, redis: Redis):
        self.redis = redis
        self._running = False
        self._tick = 0  # Счётчик циклов для плавных изменений

    async def start(self):
        """Главный цикл: каждые POLL_INTERVAL секунд генерирует и публикует метрики."""

    async def stop(self):
        self._running = False
```

### НЕ зависит от БД

DemoPoller **не читает Device/Site из БД**. Он хардкодит 3 виртуальных устройства.
Это позволяет работать даже с пустой базой — достаточно создать site + devices
через API один раз, и ID будут совпадать.

### Конфигурация виртуальных устройств

```python
DEMO_DEVICES = [
    {"device_id": 1, "site_code": "MKZ", "device_type": "generator", "name": "Gen1"},
    {"device_id": 2, "site_code": "MKZ", "device_type": "generator", "name": "Gen2"},
    {"device_id": 3, "site_code": "MKZ", "device_type": "ats",       "name": "SPR"},
]
```

> **ВАЖНО**: `device_id` должны совпадать с реальными ID в таблице `devices`.
> Если в БД Gen1=id:1, Gen2=id:2, SPR=id:3 — всё работает.
> Если ID другие — поменять в `DEMO_DEVICES`.

### Генерация метрик — Generator (HGM9520N)

Каждые 2 сек генерировать payload, **идентичный** формату `ModbusPoller._publish()`:

```python
def _gen_generator_metrics(self, device_cfg: dict) -> dict:
    """Генерирует реалистичные метрики генератора HGM9520N."""
    t = self._tick  # Используется для плавных синусоидальных колебаний
    noise = lambda amp=1.0: random.uniform(-amp, amp)

    # Базовая нагрузка: 200-280 кВт, медленно меняется
    base_power = 240 + 40 * math.sin(t * 0.02) + noise(5)

    # Напряжение: ~400В ±2% (линейное UAB, UBC, UCA)
    base_voltage = 400
    gen_uab = base_voltage + noise(4)
    gen_ubc = base_voltage + noise(4)
    gen_uca = base_voltage + noise(4)

    # Частота: 50.00 ±0.05 Гц
    gen_freq = 50.00 + noise(0.05)

    # Токи: P = √3 × U × I × cosφ → I ≈ P / (√3 × 400 × 0.85)
    # При 240 кВт → I ≈ 408 А ... нет, это для промышленных.
    # Для ГПУ 200 кВт / (√3 × 400 × 0.85) ≈ 340 А — слишком много для малых ГПУ.
    # Реалистично: ГПУ 100кВт, ток ~150А на фазу
    cos_phi = 0.85 + noise(0.02)
    current_per_phase = base_power / (math.sqrt(3) * base_voltage * cos_phi) * 1000 / 3
    # Для 240кВт при 400В: ~240000/(1.732*400*0.85)/3 ≈ ~136А на фазу — разумно для промышленного ГПУ
    current_a = current_per_phase + noise(2)
    current_b = current_per_phase + noise(2)
    current_c = current_per_phase + noise(2)

    # Мощности по фазам
    power_per_phase = base_power / 3
    reactive_per_phase = base_power * 0.2 / 3  # Q ≈ 20% от P

    # Двигатель
    engine_speed = 1500 + noise(3)          # об/мин (4-полюсный, 50 Гц)
    coolant_temp = 82 + 3 * math.sin(t * 0.01) + noise(1)  # °C
    oil_pressure = 420 + noise(15)          # кПа
    oil_temp = 95 + 2 * math.sin(t * 0.015) + noise(1)
    battery_volt = 27.6 + noise(0.3)        # В
    fuel_level = max(20, 75 - t * 0.005 + noise(1))  # Медленно убывает
    fuel_pressure = 350 + noise(10)
    turbo_pressure = 180 + noise(8)
    fuel_consumption = 45 + base_power * 0.08 + noise(2)  # л/ч

    # Накопленные
    run_hours = 1237 + t // 1800            # +1 час каждые 30 мин реального времени
    run_minutes = (t // 30) % 60
    start_count = 342
    energy_kwh = 456789 + int(t * base_power / 3600)

    # Статус: 9 = running
    gen_status = 9

    return {
        "device_id": device_cfg["device_id"],
        "site_code": device_cfg["site_code"],
        "device_type": "generator",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "online": True,
        "error": None,

        # Status & mode
        "mode_auto": True,
        "mode_manual": False,
        "mode_stop": False,
        "mode_test": False,
        "alarm_common": False,
        "alarm_shutdown": False,
        "alarm_warning": False,
        "alarm_block": False,

        # Breaker
        "mains_normal": True,
        "mains_load": True,
        "gen_normal": True,
        "gen_closed": True,

        # Mains voltage (сеть)
        "mains_uab": round(base_voltage + noise(3), 1),
        "mains_ubc": round(base_voltage + noise(3), 1),
        "mains_uca": round(base_voltage + noise(3), 1),
        "mains_freq": round(50.00 + noise(0.03), 2),

        # Generator voltage
        "gen_uab": round(gen_uab, 1),
        "gen_ubc": round(gen_ubc, 1),
        "gen_uca": round(gen_uca, 1),
        "gen_freq": round(gen_freq, 2),
        "volt_diff": round(noise(1.5), 1),
        "freq_diff": round(noise(0.02), 2),
        "phase_diff": round(noise(2), 1),

        # Current
        "current_a": round(current_a, 1),
        "current_b": round(current_b, 1),
        "current_c": round(current_c, 1),
        "current_earth": 0.0,

        # Power
        "power_a": round(power_per_phase + noise(3), 1),
        "power_b": round(power_per_phase + noise(3), 1),
        "power_c": round(power_per_phase + noise(3), 1),
        "power_total": round(base_power, 1),
        "reactive_a": round(reactive_per_phase + noise(1), 1),
        "reactive_b": round(reactive_per_phase + noise(1), 1),
        "reactive_c": round(reactive_per_phase + noise(1), 1),
        "reactive_total": round(base_power * 0.2 + noise(2), 1),
        "pf_a": round(cos_phi + noise(0.005), 3),
        "pf_b": round(cos_phi + noise(0.005), 3),
        "pf_c": round(cos_phi + noise(0.005), 3),
        "pf_avg": round(cos_phi, 3),

        # Engine
        "engine_speed": round(engine_speed),
        "battery_volt": round(battery_volt, 1),
        "charger_volt": round(battery_volt + 0.5 + noise(0.2), 1),
        "coolant_temp": round(coolant_temp),
        "oil_pressure": round(oil_pressure),
        "fuel_level": round(fuel_level),
        "load_pct": round(base_power / 300 * 100),  # % от номинала 300 кВт
        "oil_temp": round(oil_temp),
        "fuel_pressure": round(fuel_pressure),
        "turbo_pressure": round(turbo_pressure),
        "fuel_consumption": round(fuel_consumption, 1),

        # Accumulated
        "gen_status": gen_status,
        "gen_status_text": "running",
        "run_hours": run_hours,
        "run_minutes": run_minutes,
        "start_count": start_count,
        "energy_kwh": energy_kwh,
        "alarm_count": 0,
    }
```

### Генерация метрик — ШПР (HGM9560)

```python
def _gen_spr_metrics(self, device_cfg: dict) -> dict:
    """Генерирует реалистичные метрики ШПР HGM9560."""
    t = self._tick
    noise = lambda amp=1.0: random.uniform(-amp, amp)

    # Шина: суммарная мощность обоих генераторов
    busbar_p = 450 + 60 * math.sin(t * 0.02) + noise(8)
    busbar_q = busbar_p * 0.2 + noise(3)

    # Напряжение шины ≈ напряжение генераторов
    base_v = 400
    busbar_uab = base_v + noise(3)
    busbar_ubc = base_v + noise(3)
    busbar_uca = base_v + noise(3)
    busbar_ua = base_v / math.sqrt(3) + noise(2)
    busbar_ub = base_v / math.sqrt(3) + noise(2)
    busbar_uc = base_v / math.sqrt(3) + noise(2)
    busbar_freq = 50.00 + noise(0.04)

    # Сеть
    mains_uab = 400 + noise(5)
    mains_ubc = 400 + noise(5)
    mains_uca = 400 + noise(5)
    mains_ua = 231 + noise(3)
    mains_ub = 231 + noise(3)
    mains_uc = 231 + noise(3)
    mains_freq = 50.00 + noise(0.03)

    # Токи сети
    mains_ia = 120 + noise(5)
    mains_ib = 118 + noise(5)
    mains_ic = 122 + noise(5)

    # Мощность сети
    mains_total_p = 180 + 20 * math.sin(t * 0.03) + noise(5)
    mains_total_q = mains_total_p * 0.15 + noise(2)

    busbar_current = busbar_p / (math.sqrt(3) * base_v) * 1000 + noise(3)
    battery_v = 27.5 + noise(0.3)

    return {
        "device_id": device_cfg["device_id"],
        "site_code": device_cfg["site_code"],
        "device_type": "ats",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "online": True,
        "error": None,

        # Status & mode
        "mode_auto": True,
        "mode_manual": False,
        "mode_stop": False,
        "mode_test": False,
        "alarm_common": False,
        "alarm_shutdown": False,
        "alarm_warning": False,
        "alarm_trip_stop": False,

        # Genset status
        "genset_status": 9,
        "genset_status_text": "running",

        # Mains voltage
        "mains_uab": round(mains_uab),
        "mains_ubc": round(mains_ubc),
        "mains_uca": round(mains_uca),
        "mains_ua": round(mains_ua),
        "mains_ub": round(mains_ub),
        "mains_uc": round(mains_uc),
        "mains_freq": round(mains_freq, 2),

        # Busbar voltage
        "busbar_uab": round(busbar_uab),
        "busbar_ubc": round(busbar_ubc),
        "busbar_uca": round(busbar_uca),
        "busbar_ua": round(busbar_ua),
        "busbar_ub": round(busbar_ub),
        "busbar_uc": round(busbar_uca),
        "busbar_freq": round(busbar_freq, 2),

        # Mains current
        "mains_ia": round(mains_ia, 1),
        "mains_ib": round(mains_ib, 1),
        "mains_ic": round(mains_ic, 1),

        # Mains power
        "mains_total_p": round(mains_total_p, 1),
        "mains_total_q": round(mains_total_q, 1),

        # Busbar misc
        "busbar_current": round(busbar_current, 1),
        "battery_v": round(battery_v, 1),

        # Busbar power + switch status
        "busbar_p": round(busbar_p, 1),
        "busbar_q": round(busbar_q, 1),
        "busbar_switch": 3,                    # 3 = closed
        "busbar_switch_text": "closed",
        "mains_status": 0,                     # 0 = normal
        "mains_status_text": "normal",
        "mains_switch": 3,                     # 3 = closed
        "mains_switch_text": "closed",

        # Accumulated
        "accum_kwh": round(45230 + t * 0.15, 1),
        "accum_kvarh": round(8920 + t * 0.03, 1),
        "maint_hours": max(0, 163 - t // 3600),  # Убывает по 1 в час
    }
```

### Публикация — точно как в настоящем poller

```python
async def _publish(self, payload: dict):
    json_str = json.dumps(payload, default=str)
    redis_key = f"device:{payload['device_id']}:metrics"
    await self.redis.set(redis_key, json_str)
    await self.redis.publish("metrics:updates", json_str)
```

### Главный цикл

```python
async def start(self):
    self._running = True
    logger.info("DemoPoller started — emulating %d devices", len(DEMO_DEVICES))

    while self._running:
        for cfg in DEMO_DEVICES:
            if cfg["device_type"] == "generator":
                payload = self._gen_generator_metrics(cfg)
            else:
                payload = self._gen_spr_metrics(cfg)
            await self._publish(payload)

        self._tick += 1
        await asyncio.sleep(settings.POLL_INTERVAL)
```

---

## Файл 2: `backend/app/config.py` — добавить DEMO_MODE

```python
class Settings(BaseSettings):
    # ... существующие поля ...

    # Demo mode (эмуляция без реального Modbus)
    DEMO_MODE: bool = False
```

---

## Файл 3: `backend/app/main.py` — переключение poller/demo

Изменить lifespan — вместо безусловного `ModbusPoller` проверять `DEMO_MODE`:

```python
# Было:
poller = ModbusPoller(redis, async_session)
app.state.poller = poller
poller_task = asyncio.create_task(poller.start())

# Стало:
if settings.DEMO_MODE:
    from services.demo_poller import DemoPoller
    poller = DemoPoller(redis)
    logger.info("DEMO_MODE enabled — using DemoPoller")
else:
    poller = ModbusPoller(redis, async_session)
    logger.info("Production mode — using ModbusPoller")
app.state.poller = poller
poller_task = asyncio.create_task(poller.start())
```

Shutdown — без изменений (оба класса имеют `async stop()`).

---

## Файл 4: `.env` — включить demo

Добавить строку:

```ini
DEMO_MODE=true
```

---

## Подготовка данных в БД

Перед запуском DemoPoller в БД должны существовать site + 3 devices с ID=1,2,3.
Cursor должен проверить и при необходимости создать:

```bash
# Проверить существующие
curl -s http://localhost:8010/api/sites | python -m json.tool
curl -s http://localhost:8010/api/devices | python -m json.tool

# Если пусто — создать
curl -X POST http://localhost:8010/api/sites \
  -H "Content-Type: application/json" \
  -d '{"name":"МКЗ","code":"MKZ","network":"192.168.97.x","description":"Малый котельный завод"}'

curl -X POST http://localhost:8010/api/devices \
  -H "Content-Type: application/json" \
  -d '{"site_id":1,"name":"Генератор 1","device_type":"generator","ip_address":"192.168.97.10","port":502,"slave_id":1,"protocol":"tcp"}'

curl -X POST http://localhost:8010/api/devices \
  -H "Content-Type: application/json" \
  -d '{"site_id":1,"name":"Генератор 2","device_type":"generator","ip_address":"192.168.97.11","port":502,"slave_id":1,"protocol":"tcp"}'

curl -X POST http://localhost:8010/api/devices \
  -H "Content-Type: application/json" \
  -d '{"site_id":1,"name":"ШПР","device_type":"ats","ip_address":"192.168.97.20","port":502,"slave_id":1,"protocol":"rtu_over_tcp"}'
```

Затем проверить что ID совпадают с `DEMO_DEVICES`. Если device_id:1,2,3 — всё ок.

---

## Реалистичность метрик

### Что должно плавно меняться (синусоида + шум)
- `power_total` — 200–280 кВт, медленный синус ~30 сек период
- `gen_freq` — 49.95–50.05 Гц
- `gen_uab` — 396–404 В
- `current_a/b/c` — пропорционально мощности ±2А шум
- `coolant_temp` — 79–85°C, очень медленный дрейф
- `oil_pressure` — 405–435 кПа
- `busbar_p` — сумма двух генераторов ±шум

### Что должно быть стабильным
- `gen_status` = 9 (running)
- `engine_speed` ≈ 1500 об/мин
- `mode_auto` = true
- Все `alarm_*` = false
- `busbar_switch` = 3 (closed), `mains_status` = 0 (normal)

### Что должно медленно расти
- `run_hours` — +1 каждые 30 мин реального времени (быстрее чем в жизни для наглядности)
- `energy_kwh` — пропорционально мощности
- `accum_kwh` (ШПР) — аналогично

### Что должно медленно убывать
- `fuel_level` — от 75% до 20%, потом ресет (имитация заправки)
- `maint_hours` (ШПР) — от 163 до 0

### Разница между Gen1 и Gen2
Gen2 должен генерировать метрики с **другой фазой синусоиды** и немного другой базовой
нагрузкой (180-250 кВт), чтобы графики не совпадали. Добавить `phase_offset` в конфиг:

```python
DEMO_DEVICES = [
    {"device_id": 1, "site_code": "MKZ", "device_type": "generator", "name": "Gen1", "power_base": 240, "phase": 0},
    {"device_id": 2, "site_code": "MKZ", "device_type": "generator", "name": "Gen2", "power_base": 210, "phase": 1.5},
    {"device_id": 3, "site_code": "MKZ", "device_type": "ats",       "name": "SPR"},
]
```

---

## Критерии готовности

- [ ] `DEMO_MODE=true` в `.env` → при запуске в логах видно `DEMO_MODE enabled — using DemoPoller`
- [ ] `DEMO_MODE=false` или отсутствует → используется `ModbusPoller` (как раньше)
- [ ] В Redis появляются ключи `device:1:metrics`, `device:2:metrics`, `device:3:metrics`
- [ ] WebSocket получает updates каждые ~2 сек
- [ ] Фронт на `http://localhost:8011` показывает живые меняющиеся значения:
  - Gen1: P≈240 кВт, U≈400 В, I≈136 А, f≈50.00 Гц, моточасы растут
  - Gen2: P≈210 кВт, U≈400 В, I≈120 А, f≈50.00 Гц, моточасы растут
  - ШПР: P≈450 кВт (сумма), U≈400 В, f≈50.00 Гц
  - Зелёные точки, статус "Работа", шина зелёная
  - Шапка: ~450 кВт суммарная, 2/2 генераторов активно
- [ ] Значения плавно меняются от обновления к обновлению (не скачут хаотично)
- [ ] `docker compose up` → всё работает
