# -*- coding: utf-8 -*-
"""求解器单元自检：直接用库里的真实数据跑，校验全部硬约束。

用法：
    python check_solver.py            # 用当天日期的货量（没有则先生成）
    python check_solver.py --cp-sat    # 同时验证 CP-SAT 路径
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta

from sqlalchemy import select

from app.database import SessionLocal
from app.models import (
    Route,
    Store,
    StoreDemand,
    StoreRouteMapping,
    Vehicle,
    VehicleType,
)
from app.services import demand as demand_service
from app.services.solver import (
    PLAN_STRATEGIES,
    SolveInput,
    StoreInput,
    VehicleInput,
    check_assignable,
    generate_plans,
    heuristic_solve,
    validate_solution,
)

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

PASS, FAIL = [], []


def check(name: str, ok: bool, note: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"{'OK  ' if ok else 'FAIL'} {name}{(' — ' + note) if note else ''}")


def build_input(db, schedule_date: date) -> SolveInput:
    """把库里的门店/车辆/货量转成求解器输入。"""
    stores = db.query(Store).filter(Store.is_active.is_(True)).all()
    demands = {
        d.store_id: float(d.quantity)
        for d in db.execute(
            select(StoreDemand).where(StoreDemand.schedule_date == schedule_date)
        ).scalars()
    }
    mapping: dict[int, list[int]] = {}
    for m in db.query(StoreRouteMapping).all():
        mapping.setdefault(m.store_id, []).append(m.route_id)

    store_inputs = [
        StoreInput(
            id=s.id,
            code=s.code,
            name=s.name,
            terrain_type=s.terrain_type,
            delivery_window=s.delivery_window,
            quantity=demands.get(s.id, 0.0),
            route_ids=mapping.get(s.id, []),
            priority=s.priority,
        )
        for s in stores
        if demands.get(s.id, 0.0) > 0
    ]

    vtypes = {t.code: t for t in db.query(VehicleType).filter(VehicleType.is_active.is_(True)).all()}
    route_code_to_id = {r.code: r.id for r in db.query(Route).all()}

    vehicles = db.query(Vehicle).filter(Vehicle.is_active.is_(True)).all()
    vehicle_inputs = []
    for v in vehicles:
        vt = vtypes.get(v.vehicle_type_code)
        if vt is None:
            continue
        scope = []
        if v.route_scope:
            scope = [route_code_to_id[c] for c in v.route_scope.split(",") if c in route_code_to_id]
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
        stores=store_inputs, vehicles=vehicle_inputs, schedule_date=str(schedule_date)
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cp-sat", action="store_true", help="同时验证 CP-SAT 路径")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        # 用「明天」的货量，避免和页面演示数据互相干扰
        d = date.today() + timedelta(days=2)
        existing = db.execute(
            select(StoreDemand).where(StoreDemand.schedule_date == d)
        ).scalars().all()
        if not existing:
            print(f"生成 {d} 的演示货量…")
            demand_service.generate_demo_demands(db, d)

        data = build_input(db, d)
        print(
            f"\n输入：门店 {len(data.stores)} 个、车辆 {len(data.vehicles)} 台、"
            f"总货量 {sum(s.quantity for s in data.stores):.0f}\n"
        )

        check("求解输入非空", bool(data.stores) and bool(data.vehicles))

        # 1. 可行性自检
        problems = check_assignable(data.stores, data.vehicles)
        check("可行性自检无阻塞问题", not problems, " | ".join(problems)[:120])

        # 2. 启发式
        h = heuristic_solve(data, strategy="A")
        issues = validate_solution(h, data)
        check(
            "启发式方案满足全部硬约束",
            not issues,
            f"{len(issues)} 处违规：" + " | ".join(issues[:3]) if issues else "",
        )
        check("启发式有趟次产出", h.trip_count > 0, f"趟次={h.trip_count}")

        # 覆盖率口径：按「货量满足比例」而不是门店个数 ——
        # 允许拆单后，一个门店可能只被满足了一部分，光看门店数会虚高。
        total_demand = sum(s.quantity for s in data.stores)
        served_qty = sum(load.quantity for t in h.trips for load in t.loads)
        coverage = served_qty / total_demand * 100 if total_demand else 0
        check(
            "启发式货量满足率 >= 95%",
            coverage >= 95,
            f"{served_qty:.0f}/{total_demand:.0f} = {coverage:.1f}%",
        )
        print(
            f"     趟次 {h.trip_count}、用车 {h.vehicle_count} 台、"
            f"四米二使用率 {h.four_two_usage}%、装载率 {h.avg_load_rate}%、"
            f"耗时 {h.duration_ms}ms"
        )
        # 拆单是预期行为，但要能看到有多少门店被拆了
        split_stores = {}
        for t in h.trips:
            for load in t.loads:
                split_stores[load.store_id] = split_stores.get(load.store_id, 0) + 1
        multi = [sid for sid, n in split_stores.items() if n > 1]
        print(f"     涉及门店 {len(split_stores)} 个，其中拆分到多趟的有 {len(multi)} 个")

        # 3. 检查每个趟次都满足最低装载量（这是最容易出问题的地方）
        underload = [t for t in h.trips if t.store_ids and t.load < t.min_load]
        check("无「装不满最低装载量」的趟次", not underload,
              f"{len(underload)} 个" if underload else "")

        # 4. 时段约束：上午门店只在 AM 趟
        am_wrong = []
        store_by_id = {s.id: s for s in data.stores}
        for t in h.trips:
            for load in t.loads:
                if store_by_id[load.store_id].delivery_window != t.time_window:
                    am_wrong.append((store_by_id[load.store_id].code, t.time_window))
        check("时段约束满足（上午门店只在 AM 趟）", not am_wrong, str(am_wrong[:3]))

        # 5. 拆单不能凭空造出货量：每店配送量之和必须等于其货量
        delivered: dict[int, float] = {}
        for t in h.trips:
            for load in t.loads:
                delivered[load.store_id] = delivered.get(load.store_id, 0.0) + load.quantity
        oversupply = [
            (store_by_id[sid].code, delivered[sid], store_by_id[sid].quantity)
            for sid in delivered
            if delivered[sid] > store_by_id[sid].quantity + 0.01
        ]
        check("拆分后没有超量配送", not oversupply, str(oversupply[:3]))

        # 5. 多方案
        plans = generate_plans(data, timeout_seconds=10, use_cp_sat=args.cp_sat)
        check("生成 4 套方案", len(plans) == 4, f"实际 {len(plans)}")
        check(
            "方案编号齐全 A/B/C/D",
            [p.strategy for p in plans] == ["A", "B", "C", "D"],
            str([p.strategy for p in plans]),
        )
        check("恰好一个推荐方案", sum(1 for p in plans if p.recommended) == 1)

        all_valid = True
        for p in plans:
            v = validate_solution(p, data)
            if v:
                all_valid = False
                print(f"     方案 {p.strategy} 违规：{v[:2]}")
        check("四套方案均满足硬约束", all_valid)

        # 6. 方案之间要有实际差异（否则多方案比选没意义）
        signatures = {
            (p.trip_count, p.vehicle_count, round(p.avg_load_rate, 1)) for p in plans
        }
        check(
            "方案之间存在差异",
            len(signatures) >= 2,
            f"{len(signatures)} 种不同组合",
        )

        print("\n方案对比：")
        print(f"  {'方案':<6}{'策略':<22}{'趟次':>6}{'用车':>6}{'四米二':>8}{'装载率':>8}{'覆盖率':>8}{'评分':>10}")
        for p in plans:
            mark = "★" if p.recommended else " "
            print(
                f"  {mark}{p.strategy:<5}{PLAN_STRATEGIES[p.strategy]['name']:<20}"
                f"{p.trip_count:>6}{p.vehicle_count:>6}"
                f"{p.four_two_usage:>7.1f}%{p.avg_load_rate:>7.1f}%"
                f"{p.metrics.get('coverage', 0):>7.1f}%{p.metrics.get('score', 0):>10.1f}"
            )

        # 7. 边界：没有货量
        empty = SolveInput(stores=[], vehicles=data.vehicles, schedule_date=str(d))
        check("空货量输入不崩溃", heuristic_solve(empty).trip_count == 0)
        check("空货量给出提示", bool(check_assignable([], data.vehicles)))

        # 8. 边界：没有车辆
        no_vehicle = SolveInput(stores=data.stores, vehicles=[], schedule_date=str(d))
        empty_sol = heuristic_solve(no_vehicle)
        check("无车辆时全部门店未覆盖",
              len(empty_sol.uncovered_store_ids) == len(data.stores))
        check("无车辆给出提示", bool(check_assignable(data.stores, [])))

    finally:
        db.close()

    print()
    print("=" * 68)
    print(f"结果：{len(PASS)} 通过 / {len(FAIL)} 失败")
    for n in FAIL:
        print("  -", n)
    print("=" * 68)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
