# Phase 2 — Modbus Poller + WebSocket Realtime

## Цель
Фоновый опрос контроллеров Smartgen по Modbus (TCP и RTU over TCP),
публикация метрик в Redis и push через WebSocket на фронт.

---

## Общая схема потока данных

```
                  ┌────────────────────────────────┐
                  │       modbus_poller.py          │
                  │  asyncio task в lifespan        │
                  │                                 │
                  │  ┌───────────┐ ┌─────────────┐  │
                  │  │ TCP 9520N │ │ RTU 9560    │  │
                  │  │ pymodbus  │ │ raw socket  │  │
                  │  │ async     │ │ + CRC       │  │
                  │  └─────┬─────┘ └──────┬──────┘  │
                  │        └──────┬───────┘         │
                  │               ▼                  │
                  │     Redis HSET + PUBLISH         │
                  └───────────────┬──────────────────┘
                                  │
               ┌──────────────────┼───────────────────┐
               ▼                                      ▼
      WebSocket endpoint                      GET /api/metrics
      /ws/metrics                             (snapshot из Redis)
      (Redis PubSub → push)
```

---

## Файл 1: `backend/app/services/modbus_poller.py`

### Задача
- Один asyncio task, запускается в `lifespan` (main.py)
- Читает из БД список активных устройств (`Device.is_active == True`)
- Для каждого устройства опрашивает регистры по расписанию (интервал из конфига, default 2 сек)
- Результат → Redis hash + Redis pub/sub

### Конфигурация (добавить в config.py)
```python
class Settings(BaseSettings):
    # ... существующие поля ...

    # Modbus Poller
    POLL_INTERVAL: float = 2.0          # секунды между циклами опроса
    MODBUS_TIMEOUT: float = 2.0         # таймаут подключения к контроллеру
    MODBUS_RETRY_DELAY: float = 5.0     # пауза перед повторной попыткой при ошибке
```

### Архитектура класса

```python
class ModbusPoller:
    """Главный класс опроса."""

    def __init__(self, redis: Redis, session_factory):
        self.redis = redis
        self.session_factory = session_factory
        self._running = False
        self._readers: dict[int, BaseReader] = {}  # device_id → reader

    async def start(self):
        """Загрузить устройства из БД и запустить цикл."""

    async def stop(self):
        """Остановить и закрыть все соединения."""

    async def _poll_cycle(self):
        """Один цикл опроса всех устройств."""

    async def _publish(self, device_id: int, site_code: str, data: dict):
        """Записать в Redis HSET и PUBLISH."""
```

### Протокол-специфичные ридеры

```python
class BaseReader(ABC):
    @abstractmethod
    async def connect(self):
    @abstractmethod
    async def disconnect(self):
    @abstractmethod
    async def read_all(self) -> dict:

class HGM9520NReader(BaseReader):
    """Modbus TCP — pymodbus AsyncModbusTcpClient"""

class HGM9560Reader(BaseReader):
    """Modbus RTU over TCP — raw socket + CRC16"""
```

### HGM9520N Reader (Modbus TCP) — карта регистров

**ВАЖНО**: Данные ниже извлечены из протестированного скрипта `hgm9520n_monitor_v2.0.py`.
Используется `read_holding_registers` (FC 03H). Параметр `slave` передаётся из `Device.slave_id`.

```python
# Блок чтения → имя поля → адрес, количество, обработка

REGISTER_MAP_9520N = {
    # --- Статус ---
    "status": {
        "address": 0, "count": 1,
        "fields": {
            "mode_auto":     lambda regs: bool(regs[0] & (1 << 9)),
            "mode_manual":   lambda regs: bool(regs[0] & (1 << 10)),
            "mode_stop":     lambda regs: bool(regs[0] & (1 << 11)),
            "mode_test":     lambda regs: bool(regs[0] & (1 << 8)),
            "alarm_common":  lambda regs: bool(regs[0] & (1 << 0)),
            "alarm_shutdown":lambda regs: bool(regs[0] & (1 << 1)),
            "alarm_warning": lambda regs: bool(regs[0] & (1 << 2)),
            "alarm_block":   lambda regs: bool(regs[0] & (1 << 7)),
        }
    },

    # --- Выключатели (breaker) ---
    "breaker": {
        "address": 114, "count": 1,
        "fields": {
            "mains_normal":  lambda regs: bool(regs[0] & (1 << 0)),
            "mains_load":    lambda regs: bool(regs[0] & (1 << 1)),
            "gen_normal":    lambda regs: bool(regs[0] & (1 << 2)),
            "gen_closed":    lambda regs: bool(regs[0] & (1 << 3)),
        }
    },

    # --- Напряжение сети (mains) ---
    # Адреса 120-135: 32-bit напряжения + частота
    "mains_voltage": {
        "address": 120, "count": 16,
        "fields": {
            "mains_uab":  lambda regs: (regs[1] * 65536 + regs[0]) * 0.1,
            "mains_ubc":  lambda regs: (regs[3] * 65536 + regs[2]) * 0.1,
            "mains_uca":  lambda regs: (regs[5] * 65536 + regs[4]) * 0.1,
            "mains_freq": lambda regs: regs[15] * 0.01,
        }
    },

    # --- Напряжение генератора ---
    # Адреса 140-158: 32-bit напряжения + частота + синхронизация
    "gen_voltage": {
        "address": 140, "count": 19,
        "fields": {
            "gen_uab":     lambda regs: (regs[1] * 65536 + regs[0]) * 0.1,
            "gen_ubc":     lambda regs: (regs[3] * 65536 + regs[2]) * 0.1,
            "gen_uca":     lambda regs: (regs[5] * 65536 + regs[4]) * 0.1,
            "gen_freq":    lambda regs: regs[15] * 0.01,
            "volt_diff":   lambda regs: _signed16(regs[16]) * 0.1,
            "freq_diff":   lambda regs: _signed16(regs[17]) * 0.01,
            "phase_diff":  lambda regs: _signed16(regs[18]) * 0.1,
        }
    },

    # --- Токи генератора ---
    # Адреса 166-173
    "gen_current": {
        "address": 166, "count": 8,
        "fields": {
            "current_a":     lambda regs: _no_data_or(regs[0], regs[0] * 0.1),
            "current_b":     lambda regs: _no_data_or(regs[1], regs[1] * 0.1),
            "current_c":     lambda regs: _no_data_or(regs[2], regs[2] * 0.1),
            "current_earth": lambda regs: _no_data_or(regs[3], regs[3] * 0.1),
        }
    },

    # --- Мощность ---
    # Адреса 174-201: 32-bit signed P/Q по фазам + PF
    "power": {
        "address": 174, "count": 28,
        "fields": {
            "power_a":       lambda regs: _signed32(regs[0], regs[1]) * 0.1,
            "power_b":       lambda regs: _signed32(regs[2], regs[3]) * 0.1,
            "power_c":       lambda regs: _signed32(regs[4], regs[5]) * 0.1,
            "power_total":   lambda regs: _signed32(regs[6], regs[7]) * 0.1,
            "reactive_a":    lambda regs: _signed32(regs[8],  regs[9])  * 0.1,
            "reactive_b":    lambda regs: _signed32(regs[10], regs[11]) * 0.1,
            "reactive_c":    lambda regs: _signed32(regs[12], regs[13]) * 0.1,
            "reactive_total":lambda regs: _signed32(regs[14], regs[15]) * 0.1,
            "pf_a":          lambda regs: _signed16(regs[24]) * 0.001,
            "pf_b":          lambda regs: _signed16(regs[25]) * 0.001,
            "pf_c":          lambda regs: _signed16(regs[26]) * 0.001,
            "pf_avg":        lambda regs: _signed16(regs[27]) * 0.001,
        }
    },

    # --- Двигатель ---
    # Адреса 212-241
    "engine": {
        "address": 212, "count": 30,
        "fields": {
            "engine_speed":     lambda regs: None if regs[0] > 5000 or regs[0] == 32766 else regs[0],
            "battery_volt":     lambda regs: _no_data_or(regs[1], regs[1] * 0.1),
            "charger_volt":     lambda regs: _no_data_or(regs[2], regs[2] * 0.1),
            "coolant_temp":     lambda regs: None if _is_bad_temp(regs[8]) else _signed16(regs[8]),
            "oil_pressure":     lambda regs: None if regs[10] >= 10000 or regs[10] == 32766 else regs[10],
            "fuel_level":       lambda regs: None if regs[12] > 100 or regs[12] == 32766 else regs[12],
            "load_pct":         lambda regs: _safe_load(regs[20]),
            "oil_temp":         lambda regs: None if _is_bad_temp(regs[22]) else _signed16(regs[22]),
            "fuel_pressure":    lambda regs: None if regs[24] >= 10000 or regs[24] == 32766 else regs[24],
            "turbo_pressure":   lambda regs: None if regs[28] >= 10000 or regs[28] == 32766 else regs[28],
            "fuel_consumption": lambda regs: None if regs[29] > 10000 or regs[29] == 32766 else regs[29] * 0.1,
        }
    },

    # --- Накопленные / статус ---
    # Адреса 260-275
    "accumulated": {
        "address": 260, "count": 16,
        "fields": {
            "gen_status":  lambda regs: regs[0],     # 0-15, код статуса
            "run_hours":   lambda regs: regs[10],     # часы
            "run_minutes": lambda regs: regs[11],     # минуты
            "start_count": lambda regs: regs[13],     # количество пусков
            "energy_kwh":  lambda regs: regs[15] * 65536 + regs[14],  # 32-bit
        }
    },

    # --- Количество аварий ---
    "alarms": {
        "address": 511, "count": 1,
        "fields": {
            "alarm_count": lambda regs: regs[0],
        }
    },
}

# Коды статуса генератора (для фронта)
GEN_STATUS_CODES = {
    0: "standby", 1: "preheat", 2: "fuel_on", 3: "cranking",
    4: "crank_rest", 5: "safety_run", 6: "idle", 7: "warming",
    8: "wait_load", 9: "running", 10: "cooling", 11: "idle_stop",
    12: "ets", 13: "wait_stop", 14: "post_stop", 15: "stop_failure"
}
```

**Вспомогательные функции** (поместить в начало файла или отдельный модуль):

```python
NO_DATA_VALUE = 32766

def _signed16(val: int) -> int:
    return val - 65536 if val > 32767 else val

def _signed32(lsb: int, msb: int) -> int:
    val = msb * 65536 + lsb
    return val - 0x100000000 if val > 0x7FFFFFFF else val

def _no_data_or(raw: int, converted: float) -> float | None:
    return None if raw >= 32000 or raw == NO_DATA_VALUE else converted

def _is_bad_temp(raw: int) -> bool:
    s = _signed16(raw)
    return raw == NO_DATA_VALUE or raw >= 32000 or s > 200 or s < -50

def _safe_load(raw: int) -> int | None:
    if raw == NO_DATA_VALUE or raw >= 32000:
        return None
    s = _signed16(raw)
    return None if s > 150 or s < -50 else s
```

### HGM9560 Reader (RTU over TCP) — карта регистров

**ВАЖНО**: HGM9560 использует **Modbus RTU over TCP** (raw socket), НЕ стандартный Modbus TCP!
Кадр RTU = `[slave][FC][data][CRC16]` отправляется напрямую в TCP socket без MBAP header.
Параметры: USR-TCP232-410S конвертер, RS-485, 9600/8/N/2.

**НЕ использовать pymodbus для HGM9560!** Нужна ручная реализация (как в тестовом скрипте).

```python
# CRC16 Modbus
def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc

# Построение RTU фрейма FC03 (Read Holding Registers)
def build_read_registers(slave: int, start: int, count: int) -> bytes:
    frame = struct.pack('>BBhH', slave, 0x03, start, count)
    crc = crc16_modbus(frame)
    return frame + struct.pack('<H', crc)

# Парсинг ответа FC03
def parse_read_registers_response(data: bytes) -> list[int] | None:
    if len(data) < 5:
        return None
    slave, fc, byte_count = struct.unpack('>BBB', data[:3])
    if fc & 0x80:
        return None  # Exception response
    n_regs = byte_count // 2
    values = []
    for i in range(n_regs):
        val = struct.unpack('>H', data[3 + i*2 : 5 + i*2])[0]
        values.append(val)
    return values
```

**Критические нюансы send/receive для HGM9560:**
- После отправки нужна пауза `time.sleep(0.15)` (RTU inter-frame gap)
- Буфер нужно очистить перед отправкой (прочитать stale data с timeout 0.1)
- Размер ответа: проверять по FC → byte_count → expected length
- CRC-верификация обязательна (ответ[-2:])
- Между блоками чтения pause `0.05` сек

**Карта регистров HGM9560 (из протестированного скрипта):**

```python
REGISTER_MAP_9560 = {
    # --- Статус / Режим ---
    "status": {
        "address": 0, "count": 3,
        "fields": {
            "mode_test":     lambda regs: bool(regs[0] & (1 << 8)),
            "mode_auto":     lambda regs: bool(regs[0] & (1 << 9)),
            "mode_manual":   lambda regs: bool(regs[0] & (1 << 10)),
            "mode_stop":     lambda regs: bool(regs[0] & (1 << 11)),
            "alarm_common":  lambda regs: bool(regs[0] & (1 << 0)),
            "alarm_shutdown":lambda regs: bool(regs[0] & (1 << 1)),
            "alarm_warning": lambda regs: bool(regs[0] & (1 << 2)),
            "alarm_trip_stop":lambda regs: bool(regs[0] & (1 << 3)),
        }
    },

    # --- Статус генераторной установки ---
    "genset_status": {
        "address": 40, "count": 3,
        "fields": {
            "genset_status": lambda regs: regs[0],   # 0-14 код
        }
    },

    # --- Напряжение сети (mains) ---
    "mains_voltage": {
        "address": 55, "count": 10,
        "fields": {
            "mains_uab":  lambda regs: regs[0],       # V (целые, без множителя)
            "mains_ubc":  lambda regs: regs[1],
            "mains_uca":  lambda regs: regs[2],
            "mains_ua":   lambda regs: regs[3],
            "mains_ub":   lambda regs: regs[4],
            "mains_uc":   lambda regs: regs[5],
            "mains_freq": lambda regs: regs[9] * 0.01,  # Гц
        }
    },

    # --- Напряжение шины (busbar) ---
    "busbar_voltage": {
        "address": 75, "count": 10,
        "fields": {
            "busbar_uab":  lambda regs: regs[0],
            "busbar_ubc":  lambda regs: regs[1],
            "busbar_uca":  lambda regs: regs[2],
            "busbar_ua":   lambda regs: regs[3],
            "busbar_ub":   lambda regs: regs[4],
            "busbar_uc":   lambda regs: regs[5],
            "busbar_freq": lambda regs: regs[9] * 0.01,
        }
    },

    # --- Ток сети (mains current) ---
    "mains_current": {
        "address": 95, "count": 3,
        "fields": {
            "mains_ia": lambda regs: regs[0] * 0.1,
            "mains_ib": lambda regs: regs[1] * 0.1,
            "mains_ic": lambda regs: regs[2] * 0.1,
        }
    },

    # --- Суммарная мощность сети ---
    "mains_power": {
        "address": 109, "count": 10,
        "fields": {
            "mains_total_p": lambda regs: _signed32(regs[0], regs[1]) * 0.1,  # kW
            "mains_total_q": lambda regs: _signed32(regs[8], regs[9]) * 0.1,  # kvar
        }
    },

    # --- Ток шины + Батарея ---
    "busbar_misc": {
        "address": 134, "count": 12,
        "fields": {
            "busbar_current": lambda regs: regs[0] * 0.1,   # A (reg 134)
            "battery_v":      lambda regs: regs[8] * 0.1,   # V (reg 142)
        }
    },

    # --- Мощность шины + Статусы выключателей ---
    "busbar_power": {
        "address": 182, "count": 17,
        "fields": {
            "busbar_p":       lambda regs: _signed32(regs[0], regs[1]) * 0.1,   # kW  (182-183)
            "busbar_q":       lambda regs: _signed32(regs[2], regs[3]) * 0.1,   # kvar (184-185)
            "busbar_switch":  lambda regs: regs[11],   # 193
            "mains_status":   lambda regs: regs[13],   # 195
            "mains_switch":   lambda regs: regs[15],   # 197
        }
    },

    # --- Накопленная энергия ---
    "accumulated": {
        "address": 203, "count": 9,
        "fields": {
            "accum_kwh":   lambda regs: _signed32(regs[0], regs[1]) * 0.1,   # kWh
            "accum_kvarh": lambda regs: _signed32(regs[2], regs[3]) * 0.1,   # kvarh
            "maint_hours": lambda regs: regs[8],  # Часы до ТО (reg 211)
        }
    },
}

# Коды статуса HGM9560
GENSET_STATUS_9560 = {
    0: "standby", 1: "preheat", 2: "fuel_output", 3: "crank",
    4: "crank_rest", 5: "safety_run", 6: "start_idle",
    7: "warming_up", 8: "wait_load", 9: "running",
    10: "cooling", 11: "stop_idle", 12: "ets",
    13: "wait_stop", 14: "stop_failure"
}

# Статусы выключателей (для фронта)
SWITCH_STATUS = {
    0: "synchronizing", 1: "close_delay", 2: "wait_closing",
    3: "closed", 4: "unloading", 5: "open_delay",
    6: "wait_opening", 7: "opened"
}

MAINS_STATUS = {
    0: "normal", 1: "normal_delay", 2: "abnormal", 3: "abnormal_delay"
}
```

### Формат данных в Redis

**Hash key:** `device:{device_id}:metrics`

```json
{
    "device_id": 1,
    "site_code": "MKZ",
    "device_type": "generator",
    "timestamp": "2026-02-17T14:30:00.123Z",
    "online": true,
    "error": null,

    "gen_uab": 398.5,
    "gen_ubc": 399.1,
    "gen_freq": 50.01,
    "power_total": 245.3,
    "coolant_temp": 82,
    "engine_speed": 1500,
    "...": "..."
}
```

Значения `null` означают "нет данных" (датчик не подключен).

**Pub/Sub channel:** `metrics:updates`

Payload — тот же JSON что в хэше. Фронт получает через WebSocket.

---

## Файл 2: `backend/app/core/websocket.py`

### Задача
WebSocket endpoint, подписывается на Redis PubSub channel `metrics:updates`,
пересылает JSON клиентам.

### Endpoint

```
WS /ws/metrics
```

Опционально клиент может передать `?devices=1,2,3` для фильтрации по device_id.

### Архитектура

```python
from fastapi import WebSocket, WebSocketDisconnect
from fastapi import APIRouter

router = APIRouter()

class ConnectionManager:
    """Менеджер WebSocket-соединений."""

    def __init__(self):
        self.connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.connections.append(ws)

    def disconnect(self, ws: WebSocket):
        self.connections.remove(ws)

    async def broadcast(self, message: str):
        dead = []
        for ws in self.connections:
            try:
                await ws.send_text(message)
            except:
                dead.append(ws)
        for ws in dead:
            self.connections.remove(ws)

manager = ConnectionManager()

@router.websocket("/ws/metrics")
async def ws_metrics(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        # Отправить snapshot текущих метрик при подключении
        snapshot = await get_all_metrics_from_redis()
        await websocket.send_json({"type": "snapshot", "data": snapshot})

        # Держать соединение открытым
        while True:
            # Ждём ping от клиента (или просто keepalive)
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket)
```

### Redis → WebSocket bridge

Отдельная asyncio task (запускается в lifespan):

```python
async def redis_to_ws_bridge(redis):
    """Подписывается на Redis PubSub и рассылает по WebSocket."""
    pubsub = redis.pubsub()
    await pubsub.subscribe("metrics:updates")

    async for message in pubsub.listen():
        if message["type"] == "message":
            await manager.broadcast(message["data"])
```

---

## Файл 3: `backend/app/api/metrics.py`

### REST endpoint для snapshot (без WS)

```
GET /api/metrics                    → все устройства
GET /api/metrics?device_id=1        → конкретное устройство
GET /api/metrics?site_id=1          → устройства площадки
```

Читает из Redis hash, возвращает JSON.

---

## Изменения в существующих файлах

### `backend/app/main.py` — добавить в lifespan:

```python
from redis.asyncio import Redis
from services.modbus_poller import ModbusPoller
from core.websocket import router as ws_router, redis_to_ws_bridge

# В lifespan:
async def lifespan(app: FastAPI):
    # Startup
    redis = Redis.from_url(settings.REDIS_URL)
    app.state.redis = redis

    poller = ModbusPoller(redis, async_session)
    app.state.poller = poller
    asyncio.create_task(poller.start())
    asyncio.create_task(redis_to_ws_bridge(redis))

    yield

    # Shutdown
    await poller.stop()
    await redis.close()
    await engine.dispose()

# Подключить роутер:
app.include_router(ws_router)
```

### `backend/requirements.txt` — раскомментировать pymodbus:

```
pymodbus==3.7.4
```

---

## Важные технические детали

### 1. Два разных протокола!

| | HGM9520N (Генератор) | HGM9560 (ШПР) |
|---|---|---|
| Протокол | Modbus TCP | Modbus RTU over TCP |
| Библиотека | pymodbus `AsyncModbusTcpClient` | **Raw asyncio socket + CRC** |
| Frame | MBAP header + PDU | Slave + FC + Data + CRC16 |
| Порт | 502 | 502 (через USR-TCP232 конвертер) |
| Пауза между запросами | не нужна | 0.05-0.15 сек (обязательно!) |

### 2. Значение 32766 = "нет данных" (NO_DATA)

Smartgen использует `32766` как маркер "датчик не подключен / нет данных".
Все значения >= 32000 следует считать невалидными и передавать как `null`.

### 3. 32-bit значения (напряжения, энергия)

Некоторые регистры содержат 32-bit значения, занимающие 2 регистра:
- **HGM9520N**: `high * 65536 + low` (high word в регистре +1)
- **HGM9560**: `(high << 16) | low` (тот же результат)
- Для signed: если > 0x7FFFFFFF, вычесть 0x100000000

### 4. Signed 16-bit

```python
def signed16(val): return val - 65536 if val > 32767 else val
```

Используется для: temperature, phase_diff, volt_diff, freq_diff, power_factor, power.

### 5. HGM9560 — CRC обязательна

Ответ без валидного CRC = ошибка связи. Формула: CRC-16/Modbus (polynomial 0xA001).

### 6. Reconnect логика

При ошибке связи:
- Пометить устройство как `online: false` в Redis
- Подождать `MODBUS_RETRY_DELAY` секунд
- Переподключиться
- Не блокировать опрос других устройств (все device polling должны быть независимыми)

---

## Docker: что изменить

В `backend/requirements.txt` раскомментировать:
```
pymodbus==3.7.4
```

Перестроить контейнер:
```bash
docker compose build backend
docker compose up -d
```

---

## Тестирование (без реальных контроллеров)

Поскольку контроллеры в другой сети, для разработки:

1. Создать устройства через API:
```bash
POST /api/sites   → {"name":"MKZ","code":"MKZ","network":"192.168.97.x"}
POST /api/devices → {"site_id":1,"name":"Gen1","device_type":"generator",
                      "ip_address":"192.168.97.10","protocol":"tcp"}
```

2. Poller будет пытаться подключиться, получать ошибку, ставить `online: false`.
   Это нормальное поведение — убедиться что нет crash, логи адекватные.

3. Для проверки WebSocket:
```javascript
const ws = new WebSocket("ws://localhost:8010/ws/metrics");
ws.onmessage = e => console.log(JSON.parse(e.data));
```

---

## Критерии готовности Phase 2

- [ ] `modbus_poller.py` запускается в lifespan без ошибок
- [ ] При недоступных контроллерах — graceful retry, нет crash
- [ ] Метрики пишутся в Redis hash (`HGETALL device:1:metrics`)
- [ ] WebSocket endpoint принимает соединения
- [ ] `GET /api/metrics` возвращает snapshot из Redis
- [ ] Логи показывают цикл опроса и reconnect
- [ ] Docker compose up — всё работает
