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
    planned_daily: float | None = None
    full_cost_per_kwh: float | None = None
    grid_price_per_kwh: float | None = None
    last_ts: str | None = None
    devices: list[DeviceDayDetail]


class ReportTotals(BaseModel):
    gas_m3: float
    energy_kwh: float
    total_cost: float | None
    avg_cost_per_kwh: float | None
    planned_costs: float | None = None
    avg_full_cost_per_kwh: float | None = None
    grid_price: float | None = None
    plan_kwh: float | None = None
    utilization_pct: float | None = None
    breakeven_pct: float | None = None
    nominal_kw: int = 320


class ReportOut(BaseModel):
    days: list[DayReport]
    totals: ReportTotals
    requested_days: int | None = None
    actual_days_with_data: int | None = None
    data_warning: str | None = None


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
        and_(Device.site_id == site_id, Device.device_type == "GENERATOR")
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

    # ---- Planned costs & grid prices enrichment ----
    planned_daily = 0.0
    total_planned = 0.0
    try:
        pc_result = await session.execute(
            text("SELECT SUM(amount) FROM planned_costs WHERE site_id = :sid AND year = :y"),
            {"sid": site_id, "y": start_date.year},
        )
        yearly_planned = float(pc_result.scalar() or 0)
        if yearly_planned > 0:
            planned_daily = yearly_planned / 365.0
            total_planned = planned_daily * actual_days_count
    except Exception:
        pass

    # Grid price lookup
    grid_price = None
    try:
        gp_result = await session.execute(
            text("SELECT price_per_kwh FROM grid_prices WHERE site_id = :sid AND effective_from <= :d ORDER BY effective_from DESC LIMIT 1"),
            {"sid": site_id, "d": end_date},
        )
        gp_row = gp_result.first()
        if gp_row:
            grid_price = float(gp_row[0])
    except Exception:
        pass

    # Enrich day reports with planned + grid
    for d in days:
        if planned_daily > 0:
            d.planned_daily = round(planned_daily, 2)
            if d.energy_kwh > 0 and d.cost_rub is not None:
                d.full_cost_per_kwh = round((d.cost_rub + planned_daily) / d.energy_kwh, 4)
        if grid_price is not None:
            d.grid_price_per_kwh = grid_price

    # Full cost totals
    avg_full_cost = None
    if total_energy > 0 and has_any_price:
        avg_full_cost = round((total_cost + total_planned) / total_energy, 4)

    # Utilization & breakeven
    nominal_kw = 320  # 2 generators × 160 kW
    plan_kwh = nominal_kw * 24 * actual_days_count if actual_days_count > 0 else None
    util_pct = round(total_energy / plan_kwh * 100, 1) if plan_kwh and plan_kwh > 0 else None
    breakeven_pct = None
    if grid_price and grid_price > 0 and planned_daily > 0 and has_any_price and actual_days_count > 0:
        # breakeven: at what utilization % does full_cost = grid_price
        # full_cost = (gas_cost + planned) / energy; energy = nominal * 24 * days * util%
        # grid_price = (total_cost + total_planned) / (nominal * 24 * days * x)
        # x = (total_cost + total_planned) / (grid_price * nominal * 24 * days)
        denom = grid_price * nominal_kw * 24 * actual_days_count
        if denom > 0:
            breakeven_pct = round((total_cost + total_planned) / denom * 100, 1)

    return ReportOut(
        days=days,
        totals=ReportTotals(
            gas_m3=round(total_gas, 2),
            energy_kwh=round(total_energy, 2),
            total_cost=round(total_cost, 2) if has_any_price else None,
            avg_cost_per_kwh=avg_cost_per_kwh,
            planned_costs=round(total_planned, 2) if total_planned > 0 else None,
            avg_full_cost_per_kwh=avg_full_cost,
            grid_price=grid_price,
            plan_kwh=round(plan_kwh, 0) if plan_kwh else None,
            utilization_pct=util_pct,
            breakeven_pct=breakeven_pct,
            nominal_kw=nominal_kw,
        ),
        requested_days=requested_days_count,
        actual_days_with_data=actual_days_count,
        data_warning=data_warning,
    )


# ---------------------------------------------------------------------------
# Grid Prices CRUD
# ---------------------------------------------------------------------------
class GridPriceCreate(BaseModel):
    site_id: int
    effective_from: str
    price_per_kwh: float
    note: Optional[str] = None

class GridPriceOut(BaseModel):
    id: int
    site_id: int
    effective_from: str
    price_per_kwh: float
    note: Optional[str] = None


@router.get("/grid-prices/{site_id}")
async def get_grid_prices(site_id: int, db: AsyncSession = Depends(get_session)):
    r = await db.execute(
        text("SELECT id, site_id, effective_from, price_per_kwh, note FROM grid_prices WHERE site_id = :sid ORDER BY effective_from DESC"),
        {"sid": site_id},
    )
    return [
        GridPriceOut(id=row[0], site_id=row[1], effective_from=str(row[2]), price_per_kwh=row[3], note=row[4])
        for row in r.fetchall()
    ]


@router.post("/grid-prices", status_code=201)
async def create_grid_price(body: GridPriceCreate, db: AsyncSession = Depends(get_session)):
    await db.execute(
        text("INSERT INTO grid_prices (site_id, effective_from, price_per_kwh, note) VALUES (:sid, :ef, :p, :n)"),
        {"sid": body.site_id, "ef": body.effective_from, "p": body.price_per_kwh, "n": body.note},
    )
    await db.commit()
    return {"status": "ok"}


@router.delete("/grid-prices/{price_id}", status_code=204)
async def delete_grid_price(price_id: int, db: AsyncSession = Depends(get_session)):
    await db.execute(text("DELETE FROM grid_prices WHERE id = :pid"), {"pid": price_id})
    await db.commit()


# ---------------------------------------------------------------------------
# Planned Costs CRUD
# ---------------------------------------------------------------------------
class PlannedCostCategory(BaseModel):
    category: str
    category_name: str
    months: list[float]  # 12 values, Jan-Dec


@router.get("/planned-costs/{site_id}")
async def get_planned_costs(site_id: int, year: int = Query(default=2026), db: AsyncSession = Depends(get_session)):
    r = await db.execute(
        text("SELECT category, category_name, month, amount FROM planned_costs WHERE site_id = :sid AND year = :y ORDER BY category, month"),
        {"sid": site_id, "y": year},
    )
    BASE_CATS = {"maintenance", "staff", "capital", "lease", "insurance", "other"}
    cats: dict[str, dict] = {}
    for row in r.fetchall():
        cat, cat_name, month, amount = row
        if cat not in cats:
            cats[cat] = {"category": cat, "category_name": cat_name, "months": {}, "is_base": cat in BASE_CATS}
        val = float(amount) if amount else 0.0
        if 1 <= month <= 12:
            cats[cat]["months"][str(month)] = val
    # Compute totals
    monthly_totals: dict[str, float] = {}
    grand_total = 0.0
    for cat in cats.values():
        cat_total = 0.0
        for m in range(1, 13):
            v = cat["months"].get(str(m), 0.0)
            cat_total += v
            monthly_totals[str(m)] = monthly_totals.get(str(m), 0.0) + v
        cat["total"] = cat_total
        grand_total += cat_total
    return {"categories": list(cats.values()), "year": year, "monthly_totals": monthly_totals, "grand_total": grand_total}


@router.put("/planned-costs/{site_id}")
async def upsert_planned_cost(site_id: int, body: PlannedCostCategory, year: int = Query(default=2026), db: AsyncSession = Depends(get_session)):
    # Delete existing for this category+year
    await db.execute(
        text("DELETE FROM planned_costs WHERE site_id = :sid AND year = :y AND category = :cat"),
        {"sid": site_id, "y": year, "cat": body.category},
    )
    # Insert 12 months
    for i, amount in enumerate(body.months):
        if amount:
            await db.execute(
                text("INSERT INTO planned_costs (site_id, year, month, category, category_name, amount) VALUES (:sid, :y, :m, :cat, :cn, :a)"),
                {"sid": site_id, "y": year, "m": i + 1, "cat": body.category, "cn": body.category_name, "a": amount},
            )
    await db.commit()
    return {"status": "ok"}


@router.post("/planned-costs/{site_id}/category")
async def add_planned_category(site_id: int, body: PlannedCostCategory, year: int = Query(default=2026), db: AsyncSession = Depends(get_session)):
    for i, amount in enumerate(body.months):
        if amount:
            await db.execute(
                text("INSERT INTO planned_costs (site_id, year, month, category, category_name, amount) VALUES (:sid, :y, :m, :cat, :cn, :a)"),
                {"sid": site_id, "y": year, "m": i + 1, "cat": body.category, "cn": body.category_name, "a": amount},
            )
    await db.commit()
    return {"status": "ok"}


@router.delete("/planned-costs/{site_id}/category")
async def delete_planned_category(site_id: int, category: str = Query(...), year: int = Query(default=2026), db: AsyncSession = Depends(get_session)):
    await db.execute(
        text("DELETE FROM planned_costs WHERE site_id = :sid AND year = :y AND category = :cat"),
        {"sid": site_id, "y": year, "cat": category},
    )
    await db.commit()
    return {"status": "ok"}


@router.post("/planned-costs/{site_id}/copy-year")
async def copy_planned_year(site_id: int, body: dict, db: AsyncSession = Depends(get_session)):
    src = body.get("source_year")
    tgt = body.get("target_year")
    if not src or not tgt:
        raise HTTPException(400, "source_year and target_year required")
    r = await db.execute(
        text("SELECT category, category_name, month, amount FROM planned_costs WHERE site_id = :sid AND year = :y"),
        {"sid": site_id, "y": src},
    )
    rows = r.fetchall()
    if not rows:
        raise HTTPException(404, f"No data for year {src}")
    # Delete target year
    await db.execute(text("DELETE FROM planned_costs WHERE site_id = :sid AND year = :y"), {"sid": site_id, "y": tgt})
    for row in rows:
        await db.execute(
            text("INSERT INTO planned_costs (site_id, year, month, category, category_name, amount) VALUES (:sid, :y, :m, :cat, :cn, :a)"),
            {"sid": site_id, "y": tgt, "m": row[2], "cat": row[0], "cn": row[1], "a": row[3]},
        )
    await db.commit()
    return {"status": "ok", "copied": len(rows)}


# ---------------------------------------------------------------------------
# Comparison endpoint (all sites summary)
# ---------------------------------------------------------------------------
@router.get("/comparison")
async def comparison(last_days: int = Query(default=7), session: AsyncSession = Depends(get_session)):
    """Compare cost structure across all sites.

    Uses Redis cache (5 min TTL) to avoid scanning metrics_data on every request.
    Single SQL query aggregates ALL sites at once instead of N+1 per-site queries.
    """
    import json as _json
    from fastapi import Request
    from redis.asyncio import Redis as _Redis

    # Try Redis cache first
    cache_key = f"economics:comparison:{last_days}"
    try:
        from models.base import async_session as _as
        # Get redis from app state via a small helper
        import redis.asyncio as aioredis
        redis_url = "redis://redis:6379/0"
        redis_client = aioredis.from_url(redis_url, decode_responses=True)
        cached = await redis_client.get(cache_key)
        if cached:
            await redis_client.aclose()
            return _json.loads(cached)
    except Exception:
        redis_client = None

    from models.site import Site
    sites_result = await session.execute(select(Site))
    sites_list = list(sites_result.scalars().all())
    if not sites_list:
        return {"sites": []}

    end_date = date.today()
    start_date = end_date - timedelta(days=last_days)
    start_ts = datetime(start_date.year, start_date.month, start_date.day)
    end_ts = datetime(end_date.year, end_date.month, end_date.day) + timedelta(days=1)
    site_map = {s.id: s for s in sites_list}

    # Single query: aggregate metrics for ALL sites at once (avoid N+1)
    r = await session.execute(
        text("""
            SELECT d.site_id, md.device_id,
                AVG(md.fuel_consumption) AS avg_fc,
                AVG(md.power_total) AS avg_pt,
                EXTRACT(EPOCH FROM (MAX(md.timestamp) - MIN(md.timestamp))) / 3600.0 AS hours_span,
                COUNT(*) AS cnt
            FROM metrics_data md
            JOIN devices d ON d.id = md.device_id
            WHERE d.device_type = 'GENERATOR'
              AND md.timestamp >= :start AND md.timestamp < :end
              AND (md.fuel_consumption IS NOT NULL OR md.power_total IS NOT NULL)
            GROUP BY d.site_id, md.device_id, DATE(md.timestamp)
        """),
        {"start": start_ts, "end": end_ts},
    )
    # Aggregate per site
    site_totals: dict[int, dict] = defaultdict(lambda: {"gas": 0.0, "energy": 0.0})
    for row in r.fetchall():
        sid = int(row[0])
        avg_fc = float(row[2] or 0)
        avg_pt = float(row[3] or 0)
        hours_span = float(row[4] or 0)
        cnt = int(row[5] or 0)
        if hours_span < 0.01 and cnt > 0:
            hours_span = cnt * 10.0 / 3600.0
        site_totals[sid]["gas"] += avg_fc * hours_span
        site_totals[sid]["energy"] += avg_pt * hours_span

    # Batch: gas prices for all sites
    gp_r = await session.execute(
        text("""
            SELECT DISTINCT ON (site_id) site_id, price_per_m3
            FROM gas_prices
            WHERE effective_from <= :d
            ORDER BY site_id, effective_from DESC
        """),
        {"d": end_date},
    )
    gas_prices = {int(row[0]): float(row[1]) for row in gp_r.fetchall()}

    # Batch: grid prices for all sites
    grid_r = await session.execute(
        text("""
            SELECT DISTINCT ON (site_id) site_id, price_per_kwh
            FROM grid_prices
            WHERE effective_from <= :d
            ORDER BY site_id, effective_from DESC
        """),
        {"d": end_date},
    )
    grid_prices = {int(row[0]): float(row[1]) for row in grid_r.fetchall()}

    # Batch: planned costs for all sites
    pc_r = await session.execute(
        text("SELECT site_id, category, SUM(amount) FROM planned_costs WHERE year = :y GROUP BY site_id, category"),
        {"y": start_date.year},
    )
    planned_by_site: dict[int, dict] = defaultdict(dict)
    for row in pc_r.fetchall():
        planned_by_site[int(row[0])][row[1]] = float(row[2])

    result_sites = []
    for sid, totals in site_totals.items():
        total_gas = totals["gas"]
        total_energy = totals["energy"]
        if total_energy < 1:
            continue
        site = site_map.get(sid)
        if not site:
            continue

        gas_price = gas_prices.get(sid, 0)
        gas_cost = total_gas * gas_price
        gas_per_kwh = gas_cost / total_energy

        yearly_by_cat = planned_by_site.get(sid, {})
        daily_factor = last_days / 365.0
        maint_cost = sum(v for k, v in yearly_by_cat.items() if k in {"oil", "parts", "spare_parts", "service", "maintenance"}) * daily_factor
        staff_cost = sum(v for k, v in yearly_by_cat.items() if k in {"staff", "salary", "fot", "payroll_tax"}) * daily_factor
        capital_cost = sum(v for k, v in yearly_by_cat.items() if k in {"leasing", "capital", "insurance", "capex", "overhaul"}) * daily_factor
        total_planned = sum(yearly_by_cat.values()) * daily_factor

        full_cost = gas_cost + total_planned
        full_per_kwh = full_cost / total_energy

        grid_price_val = grid_prices.get(sid, 0)
        diff = grid_price_val - full_per_kwh if grid_price_val > 0 else 0
        savings = diff * total_energy

        nominal_kw = 320
        plan_kwh = nominal_kw * 24 * last_days
        util_pct = round(total_energy / plan_kwh * 100, 1) if plan_kwh > 0 else 0
        be_pct = round(full_cost / (grid_price_val * nominal_kw * 24 * last_days) * 100, 1) if grid_price_val > 0 else 0

        verdict = "profitable" if diff > 0.5 else "marginal" if diff > -0.5 else "loss"
        explanation = f"Полная себестоимость {full_per_kwh:.2f} ₽/кВт·ч {'ниже' if diff >= 0 else 'выше'} тарифа сети {grid_price_val:.2f} ₽/кВт·ч на {abs(diff):.2f} ₽. {'Экономия' if diff >= 0 else 'Убыток'}: {abs(savings):.0f} ₽ за {last_days} дн."

        result_sites.append({
            "site_id": sid, "site_name": site.name,
            "cost_breakdown": {
                "gas": round(gas_per_kwh, 4),
                "maintenance": round(maint_cost / total_energy, 4),
                "staff": round(staff_cost / total_energy, 4),
                "capital": round(capital_cost / total_energy, 4),
            },
            "full_cost_per_kwh": round(full_per_kwh, 4),
            "grid_price_per_kwh": grid_price_val,
            "diff_per_kwh": round(diff, 4),
            "savings_rub": round(savings, 0),
            "energy_kwh": round(total_energy, 0),
            "utilization_pct": util_pct,
            "breakeven_utilization_pct": be_pct,
            "verdict": verdict,
            "explanation": explanation,
            "days_with_data": last_days,
        })

    response_data = {"sites": result_sites}

    # Cache result in Redis for 5 minutes
    if redis_client:
        try:
            await redis_client.setex(cache_key, 300, _json.dumps(response_data, ensure_ascii=False, default=str))
            await redis_client.aclose()
        except Exception:
            pass

    return response_data
