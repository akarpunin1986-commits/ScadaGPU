# Phase 3 Task 1 — Модели ТО + Alembic миграция

## Цель
Создать SQLAlchemy модели для системы технического обслуживания (ТО) и сгенерировать Alembic миграцию. Модели должны полностью покрывать текущую фронтенд-логику (`scada3_templates`, `scada3_to` в localStorage) и подготовить базу для API в следующей задаче.

---

## Схема данных

```
maintenance_templates
  ├── maintenance_intervals (1:N)
  │     └── maintenance_tasks (1:N)
  │
maintenance_logs (привязка к device)
  └── maintenance_log_items (1:N, чеклист выполненных задач)
```

### ER-диаграмма

```
┌──────────────────────┐       ┌──────────────────────────┐
│ maintenance_templates│       │  maintenance_intervals   │
│──────────────────────│       │──────────────────────────│
│ id          PK       │──1:N──│ id              PK       │
│ name        str(100) │       │ template_id     FK       │
│ description str(500) │       │ name            str(50)  │
│ is_default  bool     │       │ code            str(20)  │
│ created_at           │       │ hours           int      │
│ updated_at           │       │ sort_order      int      │
└──────────────────────┘       └─────────┬────────────────┘
                                         │
                                         │ 1:N
                                         ▼
                               ┌──────────────────────────┐
                               │  maintenance_tasks       │
                               │──────────────────────────│
                               │ id              PK       │
                               │ interval_id     FK       │
                               │ text            str(500) │
                               │ is_critical     bool     │
                               │ sort_order      int      │
                               └──────────────────────────┘

┌──────────────────────┐       ┌──────────────────────────┐
│  maintenance_logs    │       │ maintenance_log_items    │
│──────────────────────│       │──────────────────────────│
│ id           PK      │──1:N──│ id              PK       │
│ device_id    FK      │       │ log_id          FK       │
│ interval_id  FK      │       │ task_id         FK(null) │
│ performed_at dt      │       │ task_text       str(500) │
│ engine_hours float   │       │ is_completed    bool     │
│ completed    int     │       │ is_critical     bool     │
│ total        int     │       └──────────────────────────┘
│ notes        text    │
│ performed_by str(100)│
│ created_at           │
└──────────────────────┘
```

---

## Файл 1: `backend/app/models/maintenance.py`

**Создать новый файл** с четырьмя моделями:

```python
"""Phase 3 — Maintenance (ТО) models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from models.base import Base, TimestampMixin


# ---------------------------------------------------------------------------
# MaintenanceTemplate — регламент ТО (например, "Стандартный регламент")
# ---------------------------------------------------------------------------

class MaintenanceTemplate(TimestampMixin, Base):
    __tablename__ = "maintenance_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(String(500), default=None)
    is_default: Mapped[bool] = mapped_column(default=False)

    # Relationships
    intervals: Mapped[list[MaintenanceInterval]] = relationship(
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="MaintenanceInterval.sort_order",
    )

    def __repr__(self) -> str:
        return f"<MaintenanceTemplate {self.name}>"


# ---------------------------------------------------------------------------
# MaintenanceInterval — интервал внутри регламента (ТО-1 250ч, ТО-2 500ч ...)
# ---------------------------------------------------------------------------

class MaintenanceInterval(Base):
    __tablename__ = "maintenance_intervals"

    id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(
        ForeignKey("maintenance_templates.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(50))        # "ТО-1"
    code: Mapped[str] = mapped_column(String(20))         # "to1"
    hours: Mapped[int] = mapped_column()                  # 250
    sort_order: Mapped[int] = mapped_column(default=0)

    # Relationships
    template: Mapped[MaintenanceTemplate] = relationship(back_populates="intervals")
    tasks: Mapped[list[MaintenanceTask]] = relationship(
        back_populates="interval",
        cascade="all, delete-orphan",
        order_by="MaintenanceTask.sort_order",
    )
    logs: Mapped[list[MaintenanceLog]] = relationship(back_populates="interval")

    def __repr__(self) -> str:
        return f"<MaintenanceInterval {self.name} ({self.hours}h)>"


# ---------------------------------------------------------------------------
# MaintenanceTask — задача внутри интервала (чеклист-пункт)
# ---------------------------------------------------------------------------

class MaintenanceTask(Base):
    __tablename__ = "maintenance_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    interval_id: Mapped[int] = mapped_column(
        ForeignKey("maintenance_intervals.id", ondelete="CASCADE")
    )
    text: Mapped[str] = mapped_column(String(500))
    is_critical: Mapped[bool] = mapped_column(default=False)
    sort_order: Mapped[int] = mapped_column(default=0)

    # Relationships
    interval: Mapped[MaintenanceInterval] = relationship(back_populates="tasks")

    def __repr__(self) -> str:
        return f"<MaintenanceTask {'[!]' if self.is_critical else ''}{self.text[:40]}>"


# ---------------------------------------------------------------------------
# MaintenanceLog — запись о выполненном ТО (привязка к device + interval)
# ---------------------------------------------------------------------------

class MaintenanceLog(Base):
    __tablename__ = "maintenance_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(
        ForeignKey("devices.id", ondelete="CASCADE")
    )
    interval_id: Mapped[int] = mapped_column(
        ForeignKey("maintenance_intervals.id", ondelete="SET NULL"),
        nullable=True,
    )
    performed_at: Mapped[datetime] = mapped_column(server_default=func.now())
    engine_hours: Mapped[float] = mapped_column()           # Моточасы на момент ТО
    completed_count: Mapped[int] = mapped_column()           # Сколько задач выполнено
    total_count: Mapped[int] = mapped_column()               # Всего задач в интервале
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    performed_by: Mapped[str | None] = mapped_column(String(100), default=None)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    # Relationships
    device = relationship("Device", back_populates="maintenance_logs")
    interval: Mapped[MaintenanceInterval | None] = relationship(back_populates="logs")
    items: Mapped[list[MaintenanceLogItem]] = relationship(
        back_populates="log",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<MaintenanceLog device={self.device_id} hours={self.engine_hours}>"


# ---------------------------------------------------------------------------
# MaintenanceLogItem — конкретная задача в рамках выполненного ТО
# ---------------------------------------------------------------------------

class MaintenanceLogItem(Base):
    __tablename__ = "maintenance_log_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    log_id: Mapped[int] = mapped_column(
        ForeignKey("maintenance_logs.id", ondelete="CASCADE")
    )
    task_id: Mapped[int | None] = mapped_column(
        ForeignKey("maintenance_tasks.id", ondelete="SET NULL"),
        nullable=True,
    )
    task_text: Mapped[str] = mapped_column(String(500))     # Копия текста задачи (снапшот)
    is_completed: Mapped[bool] = mapped_column(default=False)
    is_critical: Mapped[bool] = mapped_column(default=False) # Копия критичности (снапшот)

    # Relationships
    log: Mapped[MaintenanceLog] = relationship(back_populates="items")

    def __repr__(self) -> str:
        return f"<MaintenanceLogItem {'✓' if self.is_completed else '✗'} {self.task_text[:30]}>"
```

### Обоснование решений

| Решение | Почему |
|---------|--------|
| `MaintenanceLogItem.task_text` дублирует `MaintenanceTask.text` | Снапшот на момент выполнения: если регламент позже изменится, история останется корректной |
| `MaintenanceLogItem.task_id` nullable + `SET NULL` | Если задачу удалят из шаблона, история не потеряется |
| `MaintenanceLog.interval_id` nullable + `SET NULL` | Если интервал удалят, запись о ТО сохранится |
| `sort_order` на intervals и tasks | Фронтенд показывает интервалы по порядку (ТО-1, ТО-2...), а не по ID |
| `code` на interval (`to1`, `to2`...) | Соответствие фронтенд-логике (`id: 'to1'` в `scada3_templates`) |
| `is_default` на template | Помечает стандартный регламент, который создаётся при инициализации |
| Нет `TimestampMixin` на intervals/tasks | Они вложены в template, `updated_at` на template достаточно |
| `TimestampMixin` только на template | Template — корневая сущность, intervals/tasks каскадно зависят |

---

## Файл 2: `backend/app/models/__init__.py`

**Обновить** — добавить реэкспорт новых моделей:

```python
from models.base import Base, async_session, engine, get_session
from models.site import Site
from models.device import Device, DeviceType, ModbusProtocol
from models.maintenance import (
    MaintenanceTemplate,
    MaintenanceInterval,
    MaintenanceTask,
    MaintenanceLog,
    MaintenanceLogItem,
)

__all__ = [
    "Base",
    "async_session",
    "engine",
    "get_session",
    "Site",
    "Device",
    "DeviceType",
    "ModbusProtocol",
    "MaintenanceTemplate",
    "MaintenanceInterval",
    "MaintenanceTask",
    "MaintenanceLog",
    "MaintenanceLogItem",
]
```

---

## Файл 3: `backend/app/models/device.py`

**Добавить** обратную связь `maintenance_logs` в модель `Device`:

```python
# В классе Device, после строки:
#     site = relationship("Site", back_populates="devices")
# Добавить:

    maintenance_logs = relationship(
        "MaintenanceLog",
        back_populates="device",
        cascade="all, delete-orphan",
    )
```

Полный diff для `device.py`:
```diff
 class Device(TimestampMixin, Base):
     __tablename__ = "devices"

     id: Mapped[int] = mapped_column(primary_key=True)
     site_id: Mapped[int] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"))
     name: Mapped[str] = mapped_column(String(100))
     device_type: Mapped[DeviceType]
     ip_address: Mapped[str] = mapped_column(String(45))
     port: Mapped[int] = mapped_column(default=502)
     slave_id: Mapped[int] = mapped_column(default=1)
     protocol: Mapped[ModbusProtocol]
     is_active: Mapped[bool] = mapped_column(default=True)
     description: Mapped[str | None] = mapped_column(String(500), default=None)

     site = relationship("Site", back_populates="devices")
+    maintenance_logs = relationship(
+        "MaintenanceLog",
+        back_populates="device",
+        cascade="all, delete-orphan",
+    )

     def __repr__(self) -> str:
         return f"<Device {self.name} ({self.device_type.value}) @ {self.ip_address}>"
```

---

## Alembic миграция

### Команда (внутри контейнера backend):
```bash
docker exec -it scadagpu-backend-1 bash -c \
  "cd /app && alembic revision --autogenerate -m 'add_maintenance_models'"
```

### Ожидаемые таблицы в миграции:

1. **`maintenance_templates`** — id, name, description, is_default, created_at, updated_at
2. **`maintenance_intervals`** — id, template_id (FK → maintenance_templates), name, code, hours, sort_order
3. **`maintenance_tasks`** — id, interval_id (FK → maintenance_intervals), text, is_critical, sort_order
4. **`maintenance_logs`** — id, device_id (FK → devices), interval_id (FK nullable → maintenance_intervals), performed_at, engine_hours, completed_count, total_count, notes, performed_by, created_at
5. **`maintenance_log_items`** — id, log_id (FK → maintenance_logs), task_id (FK nullable → maintenance_tasks), task_text, is_completed, is_critical

### Применить миграцию:
```bash
docker exec -it scadagpu-backend-1 bash -c "cd /app && alembic upgrade head"
```

### Проверка (psql):
```bash
docker exec -it scadagpu-postgres-1 psql -U scada -d scada -c "\dt maintenance_*"
```

Ожидаемый результат:
```
              List of relations
 Schema |          Name           | Type  | Owner
--------+-------------------------+-------+-------
 public | maintenance_intervals   | table | scada
 public | maintenance_log_items   | table | scada
 public | maintenance_logs        | table | scada
 public | maintenance_tasks       | table | scada
 public | maintenance_templates   | table | scada
```

---

## Маппинг Frontend localStorage → PostgreSQL

### `scada3_templates` → Таблицы `maintenance_templates` + `maintenance_intervals` + `maintenance_tasks`

| Frontend (localStorage) | PostgreSQL |
|-------------------------|------------|
| `templates[templateId].name` | `maintenance_templates.name` |
| `templates[templateId].intervals[i].id` | `maintenance_intervals.code` |
| `templates[templateId].intervals[i].name` | `maintenance_intervals.name` |
| `templates[templateId].intervals[i].hours` | `maintenance_intervals.hours` |
| `templates[templateId].intervals[i].tasks[j].text` | `maintenance_tasks.text` |
| `templates[templateId].intervals[i].tasks[j].critical` | `maintenance_tasks.is_critical` |

### `scada3_to` → Таблицы `maintenance_logs` + `maintenance_log_items`

| Frontend (localStorage) | PostgreSQL |
|-------------------------|------------|
| `to[siteId][dev].history[k].type` | `maintenance_logs.interval_id` → lookup по `name` |
| `to[siteId][dev].history[k].hours` | `maintenance_logs.engine_hours` |
| `to[siteId][dev].history[k].date` | `maintenance_logs.performed_at` |
| `to[siteId][dev].history[k].completedTasks` | `maintenance_logs.completed_count` |
| `to[siteId][dev].history[k].totalTasks` | `maintenance_logs.total_count` |
| `to[siteId][dev].lastTO` | Вычисляется: `MAX(performed_at)` по device_id |
| `to[siteId][dev].hoursAtLastTO` | Вычисляется: `engine_hours` из последнего `maintenance_logs` |

---

## Seed-данные (стандартный регламент)

**НЕ создавать seed-скрипт в этой задаче** — он будет в Task 2 (API). Но модели должны поддерживать следующую структуру стандартного регламента:

```
MaintenanceTemplate(name="Стандартный регламент", is_default=True)
  ├── MaintenanceInterval(code="to1", name="ТО-1", hours=250, sort_order=0)
  │     ├── MaintenanceTask(text="Замена моторного масла", is_critical=True, sort_order=0)
  │     ├── MaintenanceTask(text="Замена масляного фильтра", is_critical=True, sort_order=1)
  │     └── ... (10 задач)
  ├── MaintenanceInterval(code="to2", name="ТО-2", hours=500, sort_order=1)
  │     └── ... (18 задач)
  ├── MaintenanceInterval(code="to3", name="ТО-3", hours=1000, sort_order=2)
  │     └── ... (30 задач)
  └── MaintenanceInterval(code="to4", name="ТО-4", hours=2000, sort_order=3)
        └── ... (45 задач)
```

---

## Чеклист готовности

- [ ] Файл `backend/app/models/maintenance.py` создан с 5 моделями
- [ ] `backend/app/models/__init__.py` обновлён с новыми импортами
- [ ] `backend/app/models/device.py` — добавлен `maintenance_logs` relationship
- [ ] Alembic миграция сгенерирована (`alembic revision --autogenerate`)
- [ ] Миграция применена (`alembic upgrade head`)
- [ ] Таблицы созданы в PostgreSQL (проверить `\dt maintenance_*`)
- [ ] Backend стартует без ошибок (`docker compose logs backend`)
