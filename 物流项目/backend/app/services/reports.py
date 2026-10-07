"""报表与看板的数据聚合服务。

对应需求文档 二.5「报表与看板」：
    车辆出勤看板、趟次达成看板、装载率看板、门店配送达成、
    线路覆盖、车型使用、成本分析、方案对比、大包/小包保障达成、
    四米二使用率、动态车辆调节分析。

★ 数据来源是**调度方案明细**（scheduling_plan_detail）：
  只有已生成方案的趟次才计入统计。任务未确认时数据仍然可见，
  但页面会标注「基于方案，尚未下发」。

★ 这里刻意不做「按日期推算」之类的假设：所有口径都从实际记录算出来，
  没有数据就返回 0 并说明原因，不编造趋势。
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    DispatchRecord,
    Driver,
    Route,
    SchedulingPlan,
    SchedulingPlanDetail,
    SchedulingTask,
    Store,
    StoreDemand,
    StoreRouteMapping,
    Vehicle,
    VehicleType,
)


def _plans_of(db: Session, schedule_date: date | None) -> list[SchedulingPlan]:
    """取指定日期（或全部）的调度方案。

    ★ 注意：这里返回的是**原始方案集合**，一天里可能有多次调度任务，
      每个任务又有 4 套候选方案。做统计时必须先用 _selected_plans()
      收缩到「每次任务只取一套」，否则会把多套方案的趟次叠加，
      算出 500% 这种荒唐的装载率。
    """
    q = db.query(SchedulingPlan).join(
        SchedulingTask, SchedulingTask.id == SchedulingPlan.task_id
    )
    if schedule_date is not None:
        q = q.filter(SchedulingTask.schedule_date == schedule_date)
    return q.all()


def _selected_plans(db: Session, schedule_date: date | None) -> list[SchedulingPlan]:
    """取出用于统计的方案，**每个日期只取最近一次调度**。

    ★ 为什么不是「每个任务取一套」：
      同一天可能被调度很多次（重跑、调参、人工重排都会新建任务），
      每次都会产出一整套包含全部货量的方案。按任务去重会把这些内容
      完全相同的方案叠加统计 —— 实测 5 个任务叠加后装载率算成 497%、
      配送量翻 5 倍。

      报表是「日报表」而不是「任务汇总」，所以正确口径是：
        · 指定日期 → 该日期**任务 id 最大**（最近一次）的那套方案
        · 未指定日期 → 每个日期各取最近一次，再合并

    选取规则（同一任务内）：
        1. 优先 is_recommended=1（人工确认后指向的方案）
        2. 否则取评分最高的
    """
    tasks = db.query(SchedulingTask)
    if schedule_date is not None:
        tasks = tasks.filter(SchedulingTask.schedule_date == schedule_date)
    task_rows = tasks.all()
    if not task_rows:
        return []

    # 每个日期保留 id 最大的任务
    latest_per_date: dict[date, int] = {}
    for t in task_rows:
        cur = latest_per_date.get(t.schedule_date)
        if cur is None or t.id > cur:
            latest_per_date[t.schedule_date] = t.id
    keep_task_ids = set(latest_per_date.values())

    plans = [p for p in _plans_of(db, schedule_date) if p.task_id in keep_task_ids]

    best: dict[int, SchedulingPlan] = {}
    for p in plans:
        cur = best.get(p.task_id)
        if cur is None or (p.is_recommended, float(p.score)) > (
            cur.is_recommended,
            float(cur.score),
        ):
            best[p.task_id] = p
    return list(best.values())


def _details_of(db: Session, plan_ids: list[int]) -> list[SchedulingPlanDetail]:
    if not plan_ids:
        return []
    return (
        db.query(SchedulingPlanDetail)
        .filter(SchedulingPlanDetail.plan_id.in_(plan_ids))
        .all()
    )


# ---------------------------------------------------------------------------
# 1. 车辆出勤
# ---------------------------------------------------------------------------
def attendance_report(db: Session, schedule_date: date | None = None) -> dict:
    """车辆出勤看板 + 动态车辆调节分析。"""
    vehicles = db.query(Vehicle).filter(Vehicle.is_active.is_(True)).all()
    vtypes = {t.code: t for t in db.query(VehicleType).all()}
    drivers = {d.id: d for d in db.query(Driver).all()}

    # 当日不可出勤（与调度口径一致）
    unavailable = {
        v.id
        for v in db.query(Vehicle).filter(Vehicle.is_active.is_(True)).all()
        if v.status == "maintenance"
        or (v.driver_id and drivers.get(v.driver_id) and drivers[v.driver_id].status != "available")
    }

    # ★ 必须用 _selected_plans：每个任务只取一套，否则多套方案会被重复统计
    selected = _selected_plans(db, schedule_date)
    details = _details_of(db, [p.id for p in selected])

    used_vehicle_ids = {d.vehicle_id for d in details}

    # 已下发的趟次（用于区分「计划出勤」与「实际下发」）
    dispatched = (
        db.query(DispatchRecord)
        .filter(DispatchRecord.task_id.in_([p.task_id for p in selected]))
        .count()
        if selected
        else 0
    )

    by_type = []
    for code, vt in vtypes.items():
        total = [v for v in vehicles if v.vehicle_type_code == code]
        used = [v for v in total if v.id in used_vehicle_ids]
        by_type.append(
            {
                "code": code,
                "name": vt.name,
                "planned_count": vt.planned_count,
                "total": len(total),
                "available": len([v for v in total if v.id not in unavailable]),
                "used": len(used),
                "trips_per_day": vt.trips_per_day,
                # 出勤率 = 实际出车 / 计划保有量
                "attendance_rate": round(len(used) / vt.planned_count * 100, 2)
                if vt.planned_count
                else 0.0,
            }
        )

    return {
        "schedule_date": str(schedule_date) if schedule_date else None,
        "vehicle_total": len(vehicles),
        "vehicle_available": len(vehicles) - len(unavailable),
        "vehicle_unavailable": len(unavailable),
        "vehicle_used": len(used_vehicle_ids),
        "dispatched_trips": dispatched,
        "by_type": by_type,
    }


# ---------------------------------------------------------------------------
# 2. 趟次达成
# ---------------------------------------------------------------------------
def trip_report(db: Session, schedule_date: date | None = None) -> dict:
    """趟次达成看板 + 大包/小包保障达成。"""
    # ★ 必须用 _selected_plans：每个任务只取一套，否则多套方案会被重复统计
    selected = _selected_plans(db, schedule_date)
    details = _details_of(db, [p.id for p in selected])

    # 按 (车辆, 趟次) 聚合出趟次
    trips: dict[tuple[int, int], float] = {}
    for d in details:
        key = (d.vehicle_id, d.trip_no)
        trips[key] = trips.get(key, 0.0) + float(d.load_amount)

    vehicles = {v.id: v for v in db.query(Vehicle).all()}
    vtypes = {t.code: t for t in db.query(VehicleType).all()}

    by_type: dict[str, dict] = {}
    for (vid, _trip_no), load in trips.items():
        v = vehicles.get(vid)
        if v is None:
            continue
        vt = vtypes.get(v.vehicle_type_code)
        if vt is None:
            continue
        row = by_type.setdefault(
            v.vehicle_type_code,
            {
                "code": v.vehicle_type_code,
                "name": vt.name,
                "planned_count": vt.planned_count,
                "trips_per_day": vt.trips_per_day,
                "actual_trips": 0,
                "vehicles_used": set(),
                "total_load": 0.0,
                "min_load": vt.min_load,
                "max_load": vt.max_load,
            },
        )
        row["actual_trips"] += 1
        row["vehicles_used"].add(vid)
        row["total_load"] += load

    rows = []
    for row in by_type.values():
        used = len(row.pop("vehicles_used"))
        # 计划趟次 = 计划保有量 × 每车日趟次
        planned_trips = row["planned_count"] * row["trips_per_day"]
        rows.append(
            {
                **row,
                "vehicles_used": used,
                "planned_trips": planned_trips,
                # 达成率 = 实际趟次 / 计划趟次
                "achievement_rate": round(row["actual_trips"] / planned_trips * 100, 2)
                if planned_trips
                else 0.0,
                "total_load": round(row["total_load"], 2),
            }
        )

    rows.sort(key=lambda r: r["code"])
    total_trips = sum(r["actual_trips"] for r in rows)
    total_planned = sum(r["planned_trips"] for r in rows)

    # 大包/小包保障达成（需求：货量不足时优先保障它们的日出车次数）
    small_codes = {"big", "small"}
    small_rows = [r for r in rows if r["code"] in small_codes]
    small_planned = sum(r["planned_trips"] for r in small_rows)
    small_actual = sum(r["actual_trips"] for r in small_rows)

    return {
        "schedule_date": str(schedule_date) if schedule_date else None,
        "total_trips": total_trips,
        "planned_trips": total_planned,
        "achievement_rate": round(total_trips / total_planned * 100, 2) if total_planned else 0.0,
        "small_package": {
            "planned_trips": small_planned,
            "actual_trips": small_actual,
            "achievement_rate": round(small_actual / small_planned * 100, 2)
            if small_planned
            else 0.0,
        },
        "by_type": rows,
    }


# ---------------------------------------------------------------------------
# 3. 装载率
# ---------------------------------------------------------------------------
def load_rate_report(db: Session, schedule_date: date | None = None) -> dict:
    """装载率看板（含四米二使用率）。"""
    # ★ 必须用 _selected_plans：每个任务只取一套，否则多套方案会被重复统计
    selected = _selected_plans(db, schedule_date)
    details = _details_of(db, [p.id for p in selected])

    vehicles = {v.id: v for v in db.query(Vehicle).all()}
    vtypes = {t.code: t for t in db.query(VehicleType).all()}

    trips: dict[tuple[int, int], dict] = {}
    for d in details:
        key = (d.vehicle_id, d.trip_no)
        row = trips.setdefault(key, {"load": 0.0, "stores": 0})
        row["load"] += float(d.load_amount)
        row["stores"] += 1

    buckets = [
        {"label": "< 70%", "min": 0, "max": 70, "count": 0},
        {"label": "70–85%", "min": 70, "max": 85, "count": 0},
        {"label": "85–95%", "min": 85, "max": 95, "count": 0},
        {"label": "95–100%", "min": 95, "max": 100.01, "count": 0},
    ]

    rates: list[float] = []
    by_type: dict[str, dict] = {}
    four_two_trips = 0

    for (vid, _trip_no), row in trips.items():
        v = vehicles.get(vid)
        if v is None:
            continue
        vt = vtypes.get(v.vehicle_type_code)
        if vt is None or not vt.max_load:
            continue
        rate = row["load"] / vt.max_load * 100
        rates.append(rate)
        for b in buckets:
            if b["min"] <= rate < b["max"]:
                b["count"] += 1
                break
        t = by_type.setdefault(
            v.vehicle_type_code,
            {"code": v.vehicle_type_code, "name": vt.name, "trips": 0, "rate_sum": 0.0,
             "load_sum": 0.0, "max_load": vt.max_load},
        )
        t["trips"] += 1
        t["rate_sum"] += rate
        t["load_sum"] += row["load"]
        if v.vehicle_type_code == "4.2m":
            four_two_trips += 1

    total_trips = len(trips)
    rows = []
    for t in by_type.values():
        rows.append(
            {
                "code": t["code"],
                "name": t["name"],
                "trips": t["trips"],
                "avg_rate": round(t["rate_sum"] / t["trips"], 2) if t["trips"] else 0.0,
                "total_load": round(t["load_sum"], 2),
                "max_load": t["max_load"],
                "trip_share": round(t["trips"] / total_trips * 100, 2) if total_trips else 0.0,
            }
        )
    rows.sort(key=lambda r: r["code"])

    return {
        "schedule_date": str(schedule_date) if schedule_date else None,
        "trip_count": total_trips,
        "avg_load_rate": round(sum(rates) / len(rates), 2) if rates else 0.0,
        "min_load_rate": round(min(rates), 2) if rates else 0.0,
        "max_load_rate": round(max(rates), 2) if rates else 0.0,
        "four_two_usage": round(four_two_trips / total_trips * 100, 2) if total_trips else 0.0,
        "buckets": buckets,
        "by_type": rows,
    }


# ---------------------------------------------------------------------------
# 4. 门店配送达成 + 线路覆盖
# ---------------------------------------------------------------------------
def store_report(db: Session, schedule_date: date | None = None) -> dict:
    """门店配送达成 + 线路覆盖 + 车型使用（按门店维度）。"""
    # ★ 必须用 _selected_plans：每个任务只取一套，否则多套方案会被重复统计
    selected = _selected_plans(db, schedule_date)
    details = _details_of(db, [p.id for p in selected])

    stores = {s.id: s for s in db.query(Store).all()}
    vehicles = {v.id: v for v in db.query(Vehicle).all()}
    routes = {r.id: r for r in db.query(Route).all()}
    mapping: dict[int, list[int]] = {}
    for m in db.query(StoreRouteMapping).all():
        mapping.setdefault(m.store_id, []).append(m.route_id)

    # 门店 → 实际配送量
    delivered: dict[int, float] = {}
    store_trips: dict[int, set] = {}
    for d in details:
        delivered[d.store_id] = delivered.get(d.store_id, 0.0) + float(d.load_amount)
        store_trips.setdefault(d.store_id, set()).add((d.vehicle_id, d.trip_no))

    # 当日货量（达成率的分母）
    demands: dict[int, float] = {}
    if schedule_date is not None:
        for row in db.execute(
            select(StoreDemand).where(StoreDemand.schedule_date == schedule_date)
        ).scalars():
            demands[row.store_id] = float(row.quantity)

    store_rows = []
    for sid, store in stores.items():
        need = demands.get(sid)
        got = delivered.get(sid, 0.0)
        if need is None and got == 0:
            continue  # 当天无货量也无配送，不占篇幅
        store_rows.append(
            {
                "store_id": sid,
                "store_code": store.code,
                "store_name": store.name,
                "terrain_type": store.terrain_type,
                "delivery_window": store.delivery_window,
                "demand": need,
                "delivered": round(got, 2),
                "achievement_rate": round(got / need * 100, 2) if need else (100.0 if got else 0.0),
                "trip_count": len(store_trips.get(sid, set())),
                "route_codes": [routes[r].code for r in mapping.get(sid, []) if r in routes],
                "is_intersection": store.is_intersection,
            }
        )

    store_rows.sort(key=lambda r: r["store_code"])

    # 线路覆盖
    route_rows = []
    for rid, route in routes.items():
        served_stores = [r for r in store_rows if rid in mapping.get(r["store_id"], [])]
        covered = [r for r in served_stores if r["delivered"] > 0]
        route_rows.append(
            {
                "route_id": rid,
                "route_code": route.code,
                "route_name": route.name,
                "store_count": len(served_stores),
                "covered_count": len(covered),
                "coverage_rate": round(len(covered) / len(served_stores) * 100, 2)
                if served_stores
                else 0.0,
                "total_delivered": round(sum(r["delivered"] for r in covered), 2),
                "is_restricted": route.is_restricted,
            }
        )
    route_rows.sort(key=lambda r: r["route_code"])

    # 交界门店表现（多线路门店的归属效果）
    intersections = [r for r in store_rows if r["is_intersection"]]

    fully = [r for r in store_rows if r["achievement_rate"] >= 99.99]
    return {
        "schedule_date": str(schedule_date) if schedule_date else None,
        "store_count": len(store_rows),
        "fully_served": len(fully),
        "achievement_rate": round(len(fully) / len(store_rows) * 100, 2) if store_rows else 0.0,
        "intersection_count": len(intersections),
        "stores": store_rows,
        "routes": route_rows,
    }


# ---------------------------------------------------------------------------
# 5. 成本与方案对比
# ---------------------------------------------------------------------------
def cost_report(db: Session, schedule_date: date | None = None) -> dict:
    """成本分析 + 方案对比。"""
    plans = _plans_of(db, schedule_date)

    plan_rows = []
    for p in plans:
        plan_rows.append(
            {
                "id": p.id,
                "task_id": p.task_id,
                "plan_code": p.plan_code,
                "strategy": p.strategy,
                "trip_count": p.trip_count,
                "vehicle_count": p.vehicle_count,
                "total_load": float(p.total_load),
                "total_cost": float(p.total_cost),
                "four_two_usage": float(p.four_two_usage),
                "avg_load_rate": float(p.avg_load_rate),
                "trip_achievement": float(p.trip_achievement),
                "score": float(p.score),
                "is_recommended": bool(p.is_recommended),
                "uncovered_stores": p.uncovered_stores,
            }
        )

    # 成本按车型拆解。★ 这里必须用 _selected_plans（每个任务一套），
    # 否则会把这天所有任务的 4 套候选方案全算进去，成本直接翻好几倍。
    selected = _selected_plans(db, schedule_date)
    details = _details_of(db, [p.id for p in selected])
    vehicles = {v.id: v for v in db.query(Vehicle).all()}
    vtypes = {t.code: t for t in db.query(VehicleType).all()}

    COST_FACTOR = {"4.2m": 1.0, "big": 0.85, "small": 0.5}
    cost_by_type: dict[str, dict] = {}
    trips: dict[tuple[int, int], float] = {}
    for d in details:
        trips[(d.vehicle_id, d.trip_no)] = (
            trips.get((d.vehicle_id, d.trip_no), 0.0) + float(d.load_amount)
        )
    for (vid, _tn), load in trips.items():
        v = vehicles.get(vid)
        if v is None:
            continue
        row = cost_by_type.setdefault(
            v.vehicle_type_code,
            {
                "code": v.vehicle_type_code,
                "name": vtypes[v.vehicle_type_code].name if v.vehicle_type_code in vtypes else "",
                "factor": COST_FACTOR.get(v.vehicle_type_code, 1.0),
                "trips": 0,
                "load": 0.0,
                "cost": 0.0,
            },
        )
        row["trips"] += 1
        row["load"] += load
        row["cost"] += COST_FACTOR.get(v.vehicle_type_code, 1.0)

    total_cost = sum(r["cost"] for r in cost_by_type.values())
    cost_rows = []
    for r in cost_by_type.values():
        cost_rows.append(
            {
                **r,
                "load": round(r["load"], 2),
                "cost": round(r["cost"], 2),
                "cost_share": round(r["cost"] / total_cost * 100, 2) if total_cost else 0.0,
            }
        )
    cost_rows.sort(key=lambda r: r["code"])

    return {
        "schedule_date": str(schedule_date) if schedule_date else None,
        "plan_count": len(plan_rows),
        "plans": plan_rows,
        "cost_by_type": cost_rows,
        "total_cost": round(total_cost, 2),
        "cost_note": "成本为演示用相对系数：四米二 1.0、大包 0.85、小包 0.5（真实场景应对接财务口径）",
    }


# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------
def overview(db: Session, schedule_date: date | None = None) -> dict:
    """报表页的汇总数据（一次请求拿全部，避免前端串行等待）。"""
    return {
        "schedule_date": str(schedule_date) if schedule_date else None,
        "attendance": attendance_report(db, schedule_date),
        "trip": trip_report(db, schedule_date),
        "load_rate": load_rate_report(db, schedule_date),
        "store": store_report(db, schedule_date),
        "cost": cost_report(db, schedule_date),
    }


def available_dates(db: Session) -> list[str]:
    """有调度任务的日期列表，供页面日期选择器用。"""
    rows = (
        db.query(SchedulingTask.schedule_date)
        .distinct()
        .order_by(SchedulingTask.schedule_date.desc())
        .limit(30)
        .all()
    )
    return [str(r[0]) for r in rows]
