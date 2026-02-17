# BUGFIX + Hot-reload + Connection Test — Consolidated Spec

**Приоритет**: Баги первые, фичи потом.
**Файлы**: backend + frontend.
**Контекст**: backend запускается на хосте (не в Docker), .env указывает на localhost:5433/6380.

---

## BUG 1: HGM9560Reader — online=false, данные не приходят

### Суть проблемы

`HGM9560Reader._send_and_receive()` в `backend/app/services/modbus_poller.py` (строки 446-470) использует **одиночный `self._reader.read()`** для получения ответа от конвертера USR-TCP232. Конвертер может отдавать данные частями (фрагментация TCP), и один read() не гарантирует полный RTU-фрейм.

Протестированный рабочий скрипт `docs/tested-scripts/hgm9560_modbus_gui (3).py` (строки 208-232) использует **цикл накопления** с проверкой длины фрейма.

Также `_flush_stale()` вызывает `self._reader.read(1024)` — на asyncio StreamReader при закрытом соединении это возвращает `b''` мгновенно (не TimeoutError), что может вызвать бесконечный цикл или некорректное состояние.

### Что исправить

**Файл**: `backend/app/services/modbus_poller.py`

**1. Заменить `_flush_stale()`** (строки 437-444):

```python
async def _flush_stale(self) -> None:
    """Drain any stale bytes sitting in the buffer."""
    if self._reader is None:
        return
    try:
        # readexactly вызовет IncompleteReadError при EOF,
        # а read() с timeout покажет есть ли мусор
        stale = await asyncio.wait_for(self._reader.read(1024), timeout=0.05)
        if stale:
            logger.debug("HGM9560: flushed %d stale bytes", len(stale))
        if not stale:
            # EOF — соединение закрыто удалённой стороной
            raise ConnectionError("HGM9560: connection closed by peer (EOF on flush)")
    except asyncio.TimeoutError:
        pass  # Нет stale данных — OK
```

**2. Заменить `_send_and_receive()`** (строки 446-470) — реализовать накопительное чтение по образцу tested-script:

```python
async def _send_and_receive(self, start: int, count: int) -> list[int] | None:
    if self._writer is None or self._reader is None:
        raise ConnectionError("HGM9560: not connected")

    await self._flush_stale()

    frame = build_read_registers(self.slave_id, start, count)
    self._writer.write(frame)
    await self._writer.drain()

    await asyncio.sleep(self.INTER_FRAME_DELAY)

    # Накопительное чтение ответа (как в tested-script)
    expected_bytes = 3 + count * 2 + 2  # slave + fc + bytecount + data + crc
    response = b""
    deadline = asyncio.get_event_loop().time() + settings.MODBUS_TIMEOUT

    while asyncio.get_event_loop().time() < deadline:
        remaining_time = deadline - asyncio.get_event_loop().time()
        if remaining_time <= 0:
            break
        try:
            chunk = await asyncio.wait_for(
                self._reader.read(256),
                timeout=min(remaining_time, 0.5),
            )
            if not chunk:
                # EOF
                raise ConnectionError("HGM9560: connection closed by peer")
            response += chunk

            # Проверяем полноту фрейма
            if len(response) >= 5:
                if response[1] == 0x03:
                    # FC03 Read Registers response
                    frame_len = 3 + response[2] + 2
                    if len(response) >= frame_len:
                        response = response[:frame_len]
                        break
                elif response[1] & 0x80:
                    # Exception response
                    if len(response) >= 5:
                        break
        except asyncio.TimeoutError:
            if response:
                break  # Есть частичные данные — попробуем распарсить
            return None  # Вообще нет ответа

    if len(response) < 5:
        logger.warning(
            "HGM9560 incomplete response for block @%d: got %d bytes: %s",
            start, len(response), response.hex() if response else "empty",
        )
        return None

    return parse_read_registers_response(response)
```

**3. Добавить логирование в `read_all()`** — при пустом результате:

После цикла по блокам (строка ~507), перед return, добавить:

```python
if not result:
    logger.warning("HGM9560 device=%s: all blocks returned empty", self.device_id)
```

**4. В `_poll_device()`** (строка 572) — пустой result при online=True вводит в заблуждение. Добавить проверку:

```python
async def _poll_device(self, device_id: int, reader: BaseReader) -> None:
    try:
        data = await reader.read_all()
        if not data:
            # Все блоки вернули None — считаем offline
            logger.warning("Device %s: read_all returned empty data", device_id)
            await self._publish(device_id, reader.device, {}, online=False, error="no data received")
        else:
            await self._publish(device_id, reader.device, data, online=True)
    except Exception as exc:
        logger.error(
            "Poll error device=%s (%s): %s",
            device_id, reader.ip, exc,
        )
        await self._publish(device_id, reader.device, {}, online=False, error=str(exc))
        try:
            await reader.disconnect()
        except Exception:
            pass
        await asyncio.sleep(settings.MODBUS_RETRY_DELAY)
```

---

## BUG 2: ModbusPoller не перечитывает устройства после изменения в UI

### Суть проблемы

`ModbusPoller.start()` вызывает `_load_devices()` **один раз** при запуске (строка 540). После этого `self._readers` фиксирован навсегда. Если пользователь:
- Добавил устройство через UI (`POST /api/devices`)
- Изменил IP/port/unit (`PATCH /api/devices/{id}`)
- Удалил устройство

...poller продолжает опрашивать старый набор по старым адресам.

### Что сделать

**Файл**: `backend/app/services/modbus_poller.py`

**1. Добавить метод `reload_devices()`** в класс `ModbusPoller`:

```python
async def reload_devices(self) -> None:
    """Hot-reload: перечитать устройства из БД и пересоздать readers."""
    logger.info("ModbusPoller: reloading devices from DB...")

    new_devices = await self._load_devices()
    new_device_map = {d.id: d for d in new_devices}

    # Удалить readers для устройств которых больше нет
    removed_ids = set(self._readers.keys()) - set(new_device_map.keys())
    for rid in removed_ids:
        logger.info("Removing reader for deleted device %s", rid)
        try:
            await self._readers[rid].disconnect()
        except Exception:
            pass
        del self._readers[rid]

    # Обновить или добавить readers
    for dev in new_devices:
        existing_reader = self._readers.get(dev.id)
        if existing_reader:
            # Проверить изменился ли IP/port/slave_id
            if (existing_reader.ip != dev.ip_address
                or existing_reader.port != dev.port
                or existing_reader.slave_id != dev.slave_id):
                logger.info(
                    "Device %s config changed (%s:%s -> %s:%s), reconnecting",
                    dev.id, existing_reader.ip, existing_reader.port,
                    dev.ip_address, dev.port,
                )
                try:
                    await existing_reader.disconnect()
                except Exception:
                    pass
                self._readers[dev.id] = _make_reader(dev)
            # else: без изменений, оставляем как есть
        else:
            # Новое устройство
            logger.info(
                "New device %s (%s) at %s:%s [%s]",
                dev.id, dev.name, dev.ip_address, dev.port, dev.protocol.value,
            )
            self._readers[dev.id] = _make_reader(dev)

    logger.info("ModbusPoller: reload complete. Active readers: %d", len(self._readers))
```

**2. Подписать poller на Redis канал `poller:reload`** — в `start()`:

```python
async def start(self) -> None:
    self._running = True
    logger.info("ModbusPoller starting...")

    devices = await self._load_devices()
    if not devices:
        logger.warning("No active devices found in DB")

    for dev in devices:
        self._readers[dev.id] = _make_reader(dev)
        logger.info(
            "Registered reader for device %s (%s) at %s:%s [%s]",
            dev.id, dev.name, dev.ip_address, dev.port, dev.protocol.value,
        )

    # Подписка на команду reload через Redis
    self._reload_requested = False
    self._reload_task = asyncio.create_task(self._listen_reload())

    while self._running:
        if self._reload_requested:
            self._reload_requested = False
            await self.reload_devices()
        await self._poll_cycle()
        await asyncio.sleep(settings.POLL_INTERVAL)


async def _listen_reload(self) -> None:
    """Слушать Redis канал poller:reload для hot-reload."""
    try:
        pubsub = self.redis.pubsub()
        await pubsub.subscribe("poller:reload")
        async for message in pubsub.listen():
            if message["type"] == "message":
                logger.info("Received reload signal")
                self._reload_requested = True
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.error("Reload listener error: %s", exc)
```

**3. В `stop()`** — отменить reload listener:

```python
async def stop(self) -> None:
    logger.info("ModbusPoller stopping...")
    self._running = False
    if hasattr(self, '_reload_task'):
        self._reload_task.cancel()
    for reader in self._readers.values():
        try:
            await reader.disconnect()
        except Exception as exc:
            logger.debug("Disconnect error: %s", exc)
    self._readers.clear()
```

---

**Файл**: `backend/app/api/devices.py`

**4. После create/update/delete устройства — публиковать `poller:reload` в Redis:**

Добавить зависимость от Redis:

```python
from fastapi import APIRouter, Depends, HTTPException, Query, Request
```

Изменить `create_device`:
```python
@router.post("", response_model=DeviceOut, status_code=201)
async def create_device(
    data: DeviceCreate, request: Request, session: AsyncSession = Depends(get_session)
):
    site = await session.get(Site, data.site_id)
    if not site:
        raise HTTPException(404, "Site not found")
    device = Device(**data.model_dump())
    session.add(device)
    await session.commit()
    await session.refresh(device)
    # Signal poller to reload
    await request.app.state.redis.publish("poller:reload", "device_created")
    return device
```

Аналогично `update_device`:
```python
@router.patch("/{device_id}", response_model=DeviceOut)
async def update_device(
    device_id: int,
    data: DeviceUpdate,
    request: Request,
    session: AsyncSession = Depends(get_session),
):
    device = await session.get(Device, device_id)
    if not device:
        raise HTTPException(404, "Device not found")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(device, field, value)
    await session.commit()
    await session.refresh(device)
    # Signal poller to reload
    await request.app.state.redis.publish("poller:reload", "device_updated")
    return device
```

Аналогично `delete_device`:
```python
@router.delete("/{device_id}", status_code=204)
async def delete_device(device_id: int, request: Request, session: AsyncSession = Depends(get_session)):
    device = await session.get(Device, device_id)
    if not device:
        raise HTTPException(404, "Device not found")
    await session.delete(device)
    await session.commit()
    # Signal poller to reload
    await request.app.state.redis.publish("poller:reload", "device_deleted")
```

---

## BUG 3: IP в Poller не обновляется (следствие BUG 2)

### Суть проблемы

Это **прямое следствие BUG 2**. Poller загружает `device.ip_address` из БД при старте и хранит в `reader.ip`. При PATCH через UI новый IP пишется в БД, но poller продолжает опрашивать старый IP.

### Решение

Полностью покрывается BUG 2: метод `reload_devices()` сравнивает IP/port/slave_id текущего reader с БД и пересоздаёт reader при расхождении. Сигнал `poller:reload` отправляется при PATCH.

**Дополнительных изменений не требуется.**

---

## FEATURE 1: Кнопка "Проверка связи" в настройках контроллеров

### Суть

В модальном окне настроек рядом с каждым контроллером — кнопка "Проверить". При нажатии:
1. Frontend POST → backend endpoint
2. Backend пытается подключиться к IP:port и прочитать 1 регистр
3. Возвращает результат: OK + модель контроллера, или ошибку

### Backend

**Файл**: `backend/app/api/devices.py`

Добавить endpoint:

```python
from pydantic import BaseModel as PydanticBaseModel

class ConnectionTestRequest(PydanticBaseModel):
    ip_address: str
    port: int = 502
    slave_id: int = 1
    protocol: ModbusProtocol  # "tcp" или "rtu_over_tcp"

class ConnectionTestResponse(PydanticBaseModel):
    success: bool
    message: str
    data: dict | None = None  # Прочитанные данные если success


@router.post("/test-connection", response_model=ConnectionTestResponse)
async def test_connection(req: ConnectionTestRequest):
    """Проверить связь с контроллером: подключиться и прочитать status register."""
    import asyncio

    try:
        if req.protocol == ModbusProtocol.TCP:
            # HGM9520N — Modbus TCP через pymodbus
            from pymodbus.client import AsyncModbusTcpClient
            client = AsyncModbusTcpClient(
                host=req.ip_address,
                port=req.port,
                timeout=3,
            )
            connected = await client.connect()
            if not connected:
                return ConnectionTestResponse(
                    success=False,
                    message=f"Cannot connect to {req.ip_address}:{req.port}",
                )
            try:
                # Читаем status register (0) — 1 регистр
                resp = await client.read_holding_registers(
                    address=0, count=1, slave=req.slave_id,
                )
                if resp.isError():
                    return ConnectionTestResponse(
                        success=False,
                        message=f"Modbus error: {resp}",
                    )
                status_word = resp.registers[0]
                return ConnectionTestResponse(
                    success=True,
                    message=f"HGM9520N connected OK. Status register: 0x{status_word:04X}",
                    data={"status_register": status_word},
                )
            finally:
                client.close()

        else:
            # HGM9560 — RTU over TCP через raw socket
            from services.modbus_poller import build_read_registers, parse_read_registers_response

            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(req.ip_address, req.port),
                    timeout=3,
                )
            except (asyncio.TimeoutError, OSError) as e:
                return ConnectionTestResponse(
                    success=False,
                    message=f"Cannot connect to {req.ip_address}:{req.port}: {e}",
                )

            try:
                # Flush stale
                await asyncio.sleep(0.05)

                frame = build_read_registers(req.slave_id, 0, 3)
                writer.write(frame)
                await writer.drain()

                await asyncio.sleep(0.15)  # RTU inter-frame delay

                # Накопительное чтение
                response = b""
                expected = 3 + 3 * 2 + 2  # 11 bytes
                deadline = asyncio.get_event_loop().time() + 3

                while asyncio.get_event_loop().time() < deadline:
                    remaining = deadline - asyncio.get_event_loop().time()
                    if remaining <= 0:
                        break
                    try:
                        chunk = await asyncio.wait_for(
                            reader.read(256),
                            timeout=min(remaining, 0.5),
                        )
                        if not chunk:
                            break
                        response += chunk
                        if len(response) >= 5 and response[1] == 0x03:
                            frame_len = 3 + response[2] + 2
                            if len(response) >= frame_len:
                                break
                    except asyncio.TimeoutError:
                        break

                regs = parse_read_registers_response(response)
                if regs is None:
                    return ConnectionTestResponse(
                        success=False,
                        message=f"No valid response. Raw: {response.hex() if response else 'empty'}",
                    )
                return ConnectionTestResponse(
                    success=True,
                    message=f"HGM9560 connected OK. Status: 0x{regs[0]:04X}",
                    data={"status_register": regs[0], "registers_count": len(regs)},
                )
            finally:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass

    except Exception as exc:
        return ConnectionTestResponse(
            success=False,
            message=f"Error: {exc}",
        )
```

### Frontend

**Файл**: `frontend/scada-v3.html`

**1. Добавить кнопку "Проверить" в каждую секцию настроек** — в `openSettings()`:

После каждого блока полей (G1, G2, SPR), перед закрывающим `</div>`, добавить кнопку.

Для **Генератор 1** — после строки с input `cfg-g1-port` (перед закрывающим `</div>` блока G1):

```html
<button onclick="testConnection('g1')" id="test-g1-btn"
    class="mt-2 w-full py-1.5 bg-slate-600 hover:bg-slate-500 rounded text-xs font-medium flex items-center justify-center gap-2">
    <span id="test-g1-icon">🔌</span>
    <span id="test-g1-text">Проверить связь</span>
</button>
<div id="test-g1-result" class="mt-1 text-xs hidden"></div>
```

Для **Генератор 2** — аналогично с id `test-g2-btn`, `test-g2-icon`, `test-g2-text`, `test-g2-result`.

Для **ШПР** — аналогично с id `test-spr-btn`, `test-spr-icon`, `test-spr-text`, `test-spr-result`.

**2. Добавить функцию `testConnection(slot)`** — после `_syncDevice()`:

```javascript
async function testConnection(slot) {
    const btn = $('test-' + slot + '-btn');
    const icon = $('test-' + slot + '-icon');
    const text = $('test-' + slot + '-text');
    const result = $('test-' + slot + '-result');

    // Собрать параметры
    const ip = $('cfg-' + slot + '-ip').value.trim();
    const port = parseInt($('cfg-' + slot + '-port').value) || 502;
    const unit = parseInt($('cfg-' + slot + '-unit').value) || 1;

    if (!ip) {
        result.textContent = 'Введите IP адрес';
        result.className = 'mt-1 text-xs text-yellow-400';
        result.classList.remove('hidden');
        return;
    }

    const protocol = (slot === 'spr') ? 'rtu_over_tcp' : 'tcp';

    // UI: loading
    btn.disabled = true;
    icon.textContent = '⏳';
    text.textContent = 'Проверка...';
    result.classList.add('hidden');

    try {
        const resp = await api.post('/api/devices/test-connection', {
            ip_address: ip,
            port: port,
            slave_id: unit,
            protocol: protocol,
        });

        if (resp.success) {
            icon.textContent = '✅';
            text.textContent = 'Связь OK';
            result.textContent = resp.message;
            result.className = 'mt-1 text-xs text-green-400';
        } else {
            icon.textContent = '❌';
            text.textContent = 'Ошибка';
            result.textContent = resp.message;
            result.className = 'mt-1 text-xs text-red-400';
        }
    } catch (e) {
        icon.textContent = '❌';
        text.textContent = 'Ошибка';
        result.textContent = 'API error: ' + e.message;
        result.className = 'mt-1 text-xs text-red-400';
    }

    result.classList.remove('hidden');
    btn.disabled = false;

    // Вернуть исходное состояние через 5 сек
    setTimeout(() => {
        icon.textContent = '🔌';
        text.textContent = 'Проверить связь';
    }, 5000);
}
```

---

## Порядок реализации

| # | Тип | Что | Файл |
|---|-----|-----|------|
| 1 | BUG | HGM9560Reader: накопительное чтение, flush fix | `modbus_poller.py` |
| 2 | BUG | `_poll_device`: empty data = offline | `modbus_poller.py` |
| 3 | BUG | `reload_devices()` + Redis listener | `modbus_poller.py` |
| 4 | BUG | `poller:reload` publish в create/update/delete | `api/devices.py` |
| 5 | BUG | `stop()` — cancel reload listener | `modbus_poller.py` |
| 6 | FEAT | `POST /api/devices/test-connection` endpoint | `api/devices.py` |
| 7 | FEAT | Кнопки "Проверить связь" в settings modal | `frontend/scada-v3.html` |
| 8 | FEAT | `testConnection(slot)` JS function | `frontend/scada-v3.html` |

---

## Тестирование

### BUG 1 (HGM9560):
```bash
# Запустить backend с LOG_LEVEL=DEBUG
# Смотреть в логах:
# - "HGM9560 connected" — TCP подключение
# - "Published metrics for device X" с online=true
# - curl http://localhost:8010/api/metrics?device_id=3 — должны быть данные
```

### BUG 2+3 (hot-reload):
```bash
# 1. Запустить backend
# 2. Через UI создать/изменить устройство
# 3. В логах должно появиться:
#    "Received reload signal"
#    "ModbusPoller: reloading devices from DB..."
#    "New device X ..." или "Device X config changed..."
# 4. Новое устройство должно начать опрашиваться без перезапуска
```

### FEATURE 1 (test-connection):
```bash
# 1. Открыть настройки контроллера
# 2. Ввести IP реального контроллера
# 3. Нажать "Проверить связь"
# 4. Должно показать "Связь OK" + status register
# 5. Ввести несуществующий IP → "Cannot connect"
```
