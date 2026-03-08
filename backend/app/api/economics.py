"""Economics API — gas prices CRUD and cost-per-kWh report.

GET  /api/economics/gas-prices/{site_id}       → list prices
POST /api/economics/gas-prices                 → create price
DELETE /api/economics/gas-prices/{price_id}     → delete price
GET  /api/economics/report/{site_id}           → aggregated report
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from models import get_session, Device
from models.gas_price import GasPrice

router = APIRouter(prefix="/api/economics", tags=["economics"])
logger = logging.getLogger("scada.economics")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class GasPriceCreate(BaseModel):
    site_id: int
    effective_from: date
    price_per_m3: float
    note: str | None = None


class GasPriceOut(BaseModel):
    id: int
    site_id: int
    effective_from: date
    price_per_m3: float
    note: str | None
    model_config = {"from_attributes": True}


class DeviceDayDetail(BaseModel):
    device_id: int
    name: str
    avg_power_kw: float
    avg_gas_m3h: float
    hours: float
    energy_kwh: float
    gas_m3: float


class DayReport(BaseModel):
    date: date
    gas_m3: float
    energy_kwh: float
    price_per_m3: float | None
    cost_rub: float | None
    cost_per_kwh: float | None
    last_ts: str | None = None  # last timestamp for incomplete days (HH:MM MSK)
    devices: list[DeviceDayDetail]


class ReportTotals(BaseModel):
    gas_m3: float
    energy_kwh: float
    total_cost: float | None
    avg_cost_per_kwh: float | None


class ReportOut(BaseModel):
    days: list[DayReport]
    totals: ReportTotals
    requested_days: int | None = None  # how many days were requested
    actual_days_with_data: int | None = None  # how many days have actual data
    data_warning: str | None = None  # warning if data is incomplete


# ---------------------------------------------------------------------------
# Gas prices CRUD
# ---------------------------------------------------------------------------
@router.get("/gas-prices/{site_id}", response_model=list[GasPriceOut])
async def list_gas_prices(
    site_id: int,
    session: AsyncSession = Depends(get_session),
):
    """List all gas prices for a site, newest first."""
    stmt = (
        select(GasPrice)
        .where(GasPrice.site_id == site_id)
        .order_by(GasPrice.effective_from.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.post("/gas-prices", response_model=GasPriceOut, status_code=201)
async def create_gas_price(
    data: GasPriceCreate,
    session: AsyncSession = Depends(get_session),
):
    """Create a new gas price entry."""
    gp = GasPrice(**data.model_dump())
    session.add(gp)
    try:
        await session.commit()
    except Exception as exc:
        await session.rollback()
        if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
            raise HTTPException(409, "Price for this site and date already exists")
        raise HTTPException(500, f"Database error: {exc}")
    await session.refresh(gp)
    return gp


@router.delete("/gas-prices/{price_id}", status_code=204)
async def delete_gas_price(
    price_id: int,
    session: AsyncSession = Depends(get_session),
):
    """Delete a gas price entry."""
    gp = await session.get(GasPrice, price_id)
    if not gp:
        raise HTTPException(404, "Gas price not found")
    await session.delete(gp)
    await session.commit()


# ---------------------------------------------------------------------------
# Economics report
# ---------------------------------------------------------------------------
@router.get("/report/{site_id}", response_model=ReportOut)
async def get_economics_report(
    site_id: int,
    start: Optional[date] = Query(None),
    end: Optional[date] = Query(None),
    last_days: int = Query(7, ge=1, le=365),
    session: AsyncSession = Depends(get_session),
):
    """Aggregated economics report: gas consumption, energy output, costs.

    Uses metrics_data (fuel_consumption, power_total) grouped by day per device,
    with gas prices applied per effective date.
    Includes per-device breakdown for detailed drill-down.
    """
    today = datetime.utcnow().date()
    if start is not None:
        start_date = start
        end_date = end or today
    else:
        start_date = today - timedelta(days=last_days - 1)
        end_date = today

    # 1. Get generator devices for this site (id + name)
    dev_stmt = select(Device.id, Device.name).where(
        and_(Device.site_id == site_id, Device.device_type == "generator")
    )
    dev_result = await session.execute(dev_stmt)
    dev_rows = dev_result.all()
    device_ids = [r[0] for r in dev_rows]
    device_names = {r[0]: r[1] for r in dev_rows}  # {device_id: name}

    if not device_ids:
        return ReportOut(
            days=[],
            totals=ReportTotals(gas_m3=0, energy_kwh=0, total_cost=None, avg_cost_per_kwh=None),
        )

    # 2. Get gas prices for this site (ascending by date)
    price_stmt = (
        select(GasPrice)
        .where(GasPrice.site_id == site_id)
        .order_by(GasPrice.effective_from.asc())
    )
    price_result = await session.execute(price_stmt)
    prices = list(price_result.scalars().all())

    price_timeline = [(p.effective_from, p.price_per_m3) for p in prices]

    def _get_price_for_date(d: date) -> float | None:
        """Find latest price effective on or before date d."""
        result = None
        for eff, price in price_timeline:
            if eff <= d:
                result = price
            else:
                break
        return result

    # 3. Aggregate metrics per device per day.
    #    Use actual time span (max-min timestamp) instead of hardcoded poll interval.
    #    Use ANY(:ids) for safe parameterized IN clause (no SQL injection)
    sql = text("""
        SELECT
            DATE(timestamp) AS day,
            device_id,
            AVG(fuel_consumption) AS avg_fc,
            AVG(power_total) AS avg_pt,
            COUNT(*) AS cnt,
            EXTRACT(EPOCH FROM (MAX(timestamp) - MIN(timestamp))) / 3600.0 AS hours_span,
            MAX(timestamp) AS max_ts
        FROM metrics_data
        WHERE device_id = ANY(:device_ids)
          AND timestamp >= :start_ts
          AND timestamp < :end_ts
          AND (fuel_consumption IS NOT NULL OR power_total IS NOT NULL)
        GROUP BY DATE(timestamp), device_id
        ORDER BY day ASC, device_id
    """)

    start_ts = datetime(start_date.year, start_date.month, start_date.day)
    end_ts = datetime(end_date.year, end_date.month, end_date.day) + timedelta(days=1)

    agg_result = await session.execute(sql, {
        "device_ids": device_ids,
        "start_ts": start_ts,
        "end_ts": end_ts,
    })
    raw_rows = agg_result.all()

    # Aggregate per-device rows into per-day totals + keep device details
    day_agg: dict[date, dict] = defaultdict(
        lambda: {"gas_m3": 0.0, "energy_kwh": 0.0, "devices": [], "max_ts": None}
    )

    for row in raw_rows:
        day_date = row[0]
        dev_id = int(row[1])
        avg_fc = float(row[2] or 0)     # avg fuel_consumption (m³/h)
        avg_pt = float(row[3] or 0)     # avg power_total (kW)
        cnt = int(row[4] or 0)          # number of data points
        hours_span = float(row[5] or 0) # actual hours from timestamps
        row_max_ts = row[6]             # max timestamp for this device-day

        # Fix: if only 1-2 data points, hours_span ≈ 0 but device was running.
        # Estimate hours from count * poll_interval (typically 10s).
        if hours_span < 0.01 and cnt > 0:
            hours_span = cnt * 10.0 / 3600.0  # assume 10s poll interval

        dev_gas = avg_fc * hours_span
        dev_energy = avg_pt * hours_span

        day_agg[day_date]["gas_m3"] += dev_gas
        day_agg[day_date]["energy_kwh"] += dev_energy
        # Track latest timestamp across all devices for this day
        if row_max_ts is not None:
            cur_max = day_agg[day_date]["max_ts"]
            if cur_max is None or row_max_ts > cur_max:
                day_agg[day_date]["max_ts"] = row_max_ts
        day_agg[day_date]["devices"].append(DeviceDayDetail(
            device_id=dev_id,
            name=device_names.get(dev_id, f"Device {dev_id}"),
            avg_power_kw=round(avg_pt, 1),
            avg_gas_m3h=round(avg_fc, 1),
            hours=round(hours_span, 2),
            energy_kwh=round(dev_energy, 1),
            gas_m3=round(dev_gas, 1),
        ))

    # 4. Build daily report
    days: list[DayReport] = []
    total_gas = 0.0
    total_energy = 0.0
    total_cost = 0.0
    has_any_price = False

    for day_date in sorted(day_agg.keys()):
        agg = day_agg[day_date]
        gas_m3 = agg["gas_m3"]
        energy_kwh = agg["energy_kwh"]

        # Determine if day is incomplete: last data point before 23:50
        last_ts_str = None
        max_ts = agg["max_ts"]
        if max_ts is not None:
            # Add 3 hours for MSK (UTC+3) display
            msk_ts = max_ts + timedelta(hours=3)
            if msk_ts.hour < 23 or (msk_ts.hour == 23 and msk_ts.minute < 50):
                last_ts_str = msk_ts.strftime("%H:%M")

        price = _get_price_for_date(day_date)

        cost_rub = None
        cost_per_kwh = None
        if price is not None:
            cost_rub = round(gas_m3 * price, 2)
            if energy_kwh > 0:
                cost_per_kwh = round(cost_rub / energy_kwh, 4)
            has_any_price = True
            total_cost += cost_rub

        total_gas += gas_m3
        total_energy += energy_kwh

        days.append(DayReport(
            date=day_date,
            gas_m3=round(gas_m3, 2),
            energy_kwh=round(energy_kwh, 2),
            price_per_m3=price,
            cost_rub=cost_rub,
            cost_per_kwh=cost_per_kwh,
            last_ts=last_ts_str,
            devices=agg["devices"],
        ))

    avg_cost_per_kwh = None
    if has_any_price and total_energy > 0:
        avg_cost_per_kwh = round(total_cost / total_energy, 4)

    # Calculate data completeness info
    # last_days=7 means "7 days including today" → start = today-7, end = today → 8 calendar days
    # But the user semantics is "за 7 дней", so use last_days when start/end are auto-calculated
    if start is not None:
        requested_days_count = (end_date - start_date).days + 1
    else:
        requested_days_count = last_days
    actual_days_count = len(days)

    def _plural_days(n: int) -> str:
        """Russian pluralization for 'день/дня/дней'."""
        if 11 <= n % 100 <= 19:
            return "дней"
        mod10 = n % 10
        if mod10 == 1:
            return "день"
        if 2 <= mod10 <= 4:
            return "дня"
        return "дней"

    data_warning = None
    if actual_days_count < requested_days_count:
        missing = requested_days_count - actual_days_count
        data_warning = (
            f"ВНИМАНИЕ: запрошено {requested_days_count} {_plural_days(requested_days_count)}, "
            f"но данные есть только за {actual_days_count} {_plural_days(actual_days_count)}. "
            f"Отсутствуют данные за {missing} {_plural_days(missing)}. "
            f"Итоги показывают суммы ТОЛЬКО за дни с данными."
        )

    return ReportOut(
        days=days,
        totals=ReportTotals(
            gas_m3=round(total_gas, 2),
            energy_kwh=round(total_energy, 2),
            total_cost=round(total_cost, 2) if has_any_price else None,
            avg_cost_per_kwh=avg_cost_per_kwh,
        ),
        requested_days=requested_days_count,
        actual_days_with_data=actual_days_count,
        data_warning=data_warning,
    )
