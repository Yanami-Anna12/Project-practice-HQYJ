"""调度任务服务：把求解器接到数据库上。

职责：
    · 从库里装配求解输入（门店 + 货量 + 车辆 + 车型规则 + 线路映射）
    · 调用求解器生成多方案
    · 校验方案是否满足硬约束
    · 落库（任务、方案、方案明细、评分）
"""

from __future__ import annotations

import logging
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Driver,
    Route,
    SchedulingPlan,
    SchedulingPlanDetail,
    SchedulingReport,
    SchedulingTask,
    Store,
    StoreDemand,
    StoreRouteMapping,
    Vehicle,
    VehicleType,
)
from app.services.solver import (
    PLAN_STRATEGIES,
    Solution,
    SolveInput,
    StoreInput,
    VehicleInput,
    check_assignable,
    generate_plans,
    validate_solution,
)

logger = logging.getLogger(__name__)

# 任务编号前缀
TASK_PREFIX = "T"


# ---------------------------------------------------------------------------
# 装配求解输入
# ---------------------------------------------------------------------------
def build_solve_input(db: Session, schedule_date: date, time_window: str = "FULL") -> SolveInput:
    """把库里的门店、货量、车辆、规则装配成求解器输入。

    time_window 为 AM / PM 时只取对应时段的门店（用于「只排上午」这种局部调度）。
    """
    stores = db.query(Store).filter(Store.is_active.is_(True)).order_by(Store.id).all()

    demands = {
        d.store_id: float(d.quantity)
        for d in db.execute(
            select(StoreDemand).where(StoreDemand.schedule_date == schedule_date)
        ).scalars()
    }

    mapping: dict[int, list[int]] = {}
    for m in db.query(StoreRouteMapping).all():
        mapping.setdefault(m.store_id, []).append(m.route_id)

    store_inputs: list[StoreInput] = []
    for s in stores:
        qty = demands.get(s.id, 0.0)
        if qty <= 0:
            continue  # 当天没有货量的门店不参与调度
        if time_window in ("AM", "PM") and s.delivery_window != time_window:
            continue
        store_inputs.append(
            StoreInput(
                id=s.id,
                code=s.code,
                name=s.name,
                terrain_type=s.terrain_type,
                delivery_window=s.delivery_window,
                quantity=qty,
                route_ids=mapping.get(s.id, []),
                priority=s.priority,
            )
        )

    vtypes = {
        t.code: t
        for t in db.query(VehicleType).filter(VehicleType.is_active.is_(True)).all()
    }
    route_code_to_id = {r.code: r.id for r in db.query(Route).all()}

    # 只取「可出勤」的车辆：启用 + 非维保状态
    unavailable_driver_ids = {
        d.id
        for d in db.query(Driver).filter(Driver.status.in_(["leave", "offline"])).all()
    }
    vehicles = (
        db.query(Vehicle)
        .filter(
            Vehicle.is_active.is_(True),
            Vehicle.status.in_(["idle", "running"]),
        )
        .order_by(Vehicle.id)
        .all()
    )

    vehicle_inputs: list[VehicleInput] = []
    for v in vehicles:
        # 司机请假则该车当天不可用
        if v.driver_id and v.driver_id in unavailable_driver_ids:
            continue
        vt = vtypes.get(v.vehicle_type_code)
        if vt is None:
            continue
        scope = []
        if v.route_scope:
            scope = [
                route_code_to_id[c]
                for c in v.route_scope.split(",")
                if c in route_code_to_id
            ]
        vehicle_inputs.append(
            VehicleInput(
                id=v.id,
                plate_no=v.plate_no,
                vehicle_type=v.vehicle_type_code,
                terrain_capability=v.terrain_capability,
                route_scope=scope,
                min_load=vt.min_load,
                max_load=vt.max_load,
                trips_per_day=vt.trips_per_day,
            )
        )

    return SolveInput(
        stores=store_inputs,
        vehicles=vehicle_inputs,
        schedule_date=str(schedule_date),
        time_window=time_window,
    )


# ---------------------------------------------------------------------------
# 生成任务编号
# ---------------------------------------------------------------------------
def next_task_code(db: Session, schedule_date: date) -> str:
    """形如 T20260924-001。同日多次调度自动递增。"""
    prefix = f"{TASK_PREFIX}{schedule_date.strftime('%Y%m%d')}-"
    rows = (
        db.query(SchedulingTask.code)
        .filter(SchedulingTask.code.like(f"{prefix}%"))
        .all()
    )
    seq = 1
    for (code,) in rows:
        tail = code.rsplit("-", 1)[-1]
        if tail.isdigit():
            seq = max(seq, int(tail) + 1)
    return f"{prefix}{seq:03d}"


# ---------------------------------------------------------------------------
# 执行调度
# ---------------------------------------------------------------------------
def run_scheduling(
    db: Session,
    *,
    schedule_date: date,
    time_window: str = "FULL",
    created_by: str = "",
    timeout_seconds: int = 5,
    use_cp_sat: bool = True,
    rule_version: str = "v1.0.0",
) -> dict:
    """执行一次调度：装配输入 → 求解多方案 → 校验 → 落库。

    返回包含任务、方案、可行性问题、校验结果的字典。
    """
    data = build_solve_input(db, schedule_date, time_window)

    # 可行性自检：有问题也继续跑（方案里会体现缺口），但要把原因返回给前端
    problems = check_assignable(data.stores, data.vehicles)

    task = SchedulingTask(
        code=next_task_code(db, schedule_date),
        schedule_date=schedule_date,
        time_window=time_window,
        status="running",
        rule_version=rule_version,
        created_by=created_by,
    )
    db.add(task)
    db.flush()

    started = datetime.now()

    if not data.stores or not data.vehicles:
        # 没有输入就没有方案可生成，直接把任务标为失败并说明原因
        task.status = "failed"
        task.solver_note = "；".join(problems)[:255] or "无可用输入"
        task.duration_ms = 0
        db.commit()
        return {
            "task": task,
            "plans": [],
            "problems": problems,
            "validations": {},
        }

    solutions = generate_plans(
        data, timeout_seconds=timeout_seconds, use_cp_sat=use_cp_sat
    )

    duration_ms = int((datetime.now() - started).total_seconds() * 1000)
    task.duration_ms = duration_ms

    total_demand = sum(s.quantity for s in data.stores)
    store_by_id = {s.id: s for s in data.stores}
    vehicle_by_id = {v.id: v for v in data.vehicles}

    validations: dict[str, list[str]] = {}
    persisted: list[SchedulingPlan] = []

    for sol in solutions:
        issues = validate_solution(sol, data)
        validations[sol.strategy] = issues

        cfg = PLAN_STRATEGIES[sol.strategy]
        uncovered_codes = [
            store_by_id[sid].code
            for sid in sorted(sol.shortfall)
            if sid in store_by_id
        ]

        plan = SchedulingPlan(
            task_id=task.id,
            plan_code=sol.strategy,
            strategy=cfg["name"],
            four_two_usage=sol.four_two_usage,
            avg_load_rate=sol.avg_load_rate,
            trip_achievement=sol.metrics.get("trip_achievement", 0),
            total_load=sol.total_load,
            vehicle_count=sol.vehicle_count,
            trip_count=sol.trip_count,
            total_cost=sol.total_cost,
            soft_violation=sol.metrics.get("shortfall_quantity", 0),
            score=sol.metrics.get("score", 0),
            uncovered_stores=",".join(uncovered_codes)[:512],
            explanation=_build_explanation(sol, cfg, total_demand, issues),
            is_recommended=1 if sol.recommended else 0,
        )
        db.add(plan)
        db.flush()

        for trip in sol.trips:
            for item in trip.loads:
                db.add(
                    SchedulingPlanDetail(
                        plan_id=plan.id,
                        vehicle_id=trip.vehicle_id,
                        vehicle_type=trip.vehicle_type,
                        trip_no=trip.trip_no,
                        time_window=trip.time_window,
                        store_id=item.store_id,
                        load_amount=item.quantity,
                        sequence=item.sequence,
                        status="planned",
                    )
                )

        persisted.append(plan)

    # 求解完成后进入待确认
    task.status = "pending_confirm"
    task.solver_note = (
        "；".join(solutions[0].notes[:2]) if solutions else ""
    )[:255]

    db.commit()

    return {
        "task": task,
        "plans": persisted,
        "problems": problems,
        "validations": validations,
        "input_summary": {
            "store_count": len(data.stores),
            "vehicle_count": len(data.vehicles),
            "total_demand": total_demand,
            "schedule_date": str(schedule_date),
        },
        "store_by_id": store_by_id,
        "vehicle_by_id": vehicle_by_id,
    }


def _build_explanation(
    sol: Solution, cfg: dict, total_demand: float, issues: list[str]
) -> str:
    """生成方案解释。

    ★ 需求文档的设计原则：「LLM 只做解释和辅助，硬约束不交给 LLM」。
      所以这里先用确定性逻辑把关键事实写清楚；配置了 DEEPSEEK_API_KEY 时
      再由 LLM 润色成更自然的表述（见 services/explain.py）。
      未配置 Key 时这段文本本身就是完整可用的解释。
    """
    served = sum(load.quantity for t in sol.trips for load in t.loads)
    pct = served / total_demand * 100 if total_demand else 0

    lines = [
        f"【{sol.strategy} · {cfg['name']}】{cfg['desc']}",
        f"求解方式：{'CP-SAT 精确求解' if sol.solver_used == 'cp-sat' else '启发式贪心'}"
        f"，耗时 {sol.duration_ms} ms",
        "",
        f"· 共安排 {sol.trip_count} 个趟次，动用 {sol.vehicle_count} 台车辆",
        f"· 配送货量 {served:.0f} / {total_demand:.0f}（{pct:.1f}%）",
        f"· 四米二使用率 {sol.four_two_usage}%，平均装载率 {sol.avg_load_rate}%",
        f"· 相对成本 {sol.total_cost}（四米二=1.0、大包=0.85、小包=0.5 的演示系数）",
    ]

    if sol.shortfall:
        lines.append("")
        lines.append(f"· 未完全满足的门店 {len(sol.shortfall)} 个：")
        for sid, missing in list(sol.shortfall.items())[:8]:
            lines.append(f"    - 门店ID {sid} 缺 {missing:.0f}")

    lines.append("")
    if issues:
        lines.append(f"· ⚠ 硬约束校验发现 {len(issues)} 处问题：")
        for issue in issues[:5]:
            lines.append(f"    - {issue}")
    else:
        lines.append("· 硬约束校验：全部通过（时段、地形、线路、装载量、趟次上限）")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 查询辅助
# ---------------------------------------------------------------------------
def get_plan_details(db: Session, plan_id: int) -> list[dict]:
    """取某个方案的明细（已联好门店与车辆名称，便于直接展示）。"""
    rows = (
        db.query(SchedulingPlanDetail, Store)
        .join(Store, Store.id == SchedulingPlanDetail.store_id)
        .filter(SchedulingPlanDetail.plan_id == plan_id)
        .order_by(
            SchedulingPlanDetail.vehicle_id,
            SchedulingPlanDetail.trip_no,
            SchedulingPlanDetail.sequence,
        )
        .all()
    )
    vehicles = {v.id: v for v in db.query(Vehicle).all()}
    drivers = {d.id: d.name for d in db.query(Driver).all()}

    out = []
    for detail, store in rows:
        v = vehicles.get(detail.vehicle_id)
        out.append(
            {
                "id": detail.id,
                "vehicle_id": detail.vehicle_id,
                "plate_no": v.plate_no if v else "",
                "driver_name": drivers.get(v.driver_id, "") if v and v.driver_id else "",
                "vehicle_type": detail.vehicle_type,
                "trip_no": detail.trip_no,
                "time_window": detail.time_window,
                "store_id": detail.store_id,
                "store_code": store.code,
                "store_name": store.name,
                "terrain_type": store.terrain_type,
                "load_amount": float(detail.load_amount),
                "sequence": detail.sequence,
                "status": detail.status,
            }
        )
    return out


def save_report(db: Session, task_id: int, plan_id: int | None, content: str) -> SchedulingReport:
    report = SchedulingReport(task_id=task_id, plan_id=plan_id, content=content)
    db.add(report)
    db.commit()
    db.refresh(report)
    return report
