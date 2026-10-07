# -*- coding: utf-8 -*-
"""调试求解器：打印槽位池与每个门店的安置情况。"""

from __future__ import annotations

from datetime import date, timedelta

from check_solver import build_input
from app.database import SessionLocal
from app.services.solver import (
    SolveInput,
    _build_slot_pool,
    heuristic_solve,
    vehicle_can_serve_store,
)

db = SessionLocal()
try:
    d = date.today() + timedelta(days=2)
    data = build_input(db, d)

    print(f"门店 {len(data.stores)}、车辆 {len(data.vehicles)}")
    print("\n门店：")
    am = [s for s in data.stores if s.delivery_window == "AM"]
    pm = [s for s in data.stores if s.delivery_window == "PM"]
    print(f"  AM {len(am)} 个，货量 {sum(s.quantity for s in am):.0f}")
    print(f"  PM {len(pm)} 个，货量 {sum(s.quantity for s in pm):.0f}")
    for s in sorted(data.stores, key=lambda x: -x.quantity)[:20]:
        print(f"    {s.code} {s.terrain_type:<7} {s.delivery_window} qty={s.quantity:>7.0f} routes={s.route_ids}")

    print("\n车型参数：")
    seen = {}
    for v in data.vehicles:
        if v.vehicle_type not in seen:
            seen[v.vehicle_type] = v
    for k, v in seen.items():
        print(f"  {k}: min={v.min_load} max={v.max_load} trips={v.trips_per_day} cap={v.terrain_capability}")

    pool = _build_slot_pool(data)
    print(f"\n槽位池：{len(pool)} 个")
    am_slots = [s for s in pool if s["time_window"] == "AM"]
    pm_slots = [s for s in pool if s["time_window"] == "PM"]
    print(f"  AM 槽位 {len(am_slots)}，PM 槽位 {len(pm_slots)}")
    cap_am = sum(s["vehicle"].max_load for s in am_slots)
    cap_pm = sum(s["vehicle"].max_load for s in pm_slots)
    print(f"  AM 容量 {cap_am}，PM 容量 {cap_pm}")

    print("\n每个门店的可服务槽位数：")
    for s in sorted(data.stores, key=lambda x: -x.quantity):
        cands = [
            sl for sl in pool
            if sl["time_window"] == s.delivery_window
            and vehicle_can_serve_store(sl["vehicle"], s)
            and sl["load"] + s.quantity <= sl["vehicle"].max_load
        ]
        print(f"    {s.code} qty={s.quantity:>7.0f} {s.delivery_window} terrain={s.terrain_type:<7} 可用槽位={len(cands)}")

    print("\n=== 跑启发式 ===")
    sol = heuristic_solve(data, strategy="A")
    print(f"趟次 {sol.trip_count}，未覆盖 {len(sol.uncovered_store_ids)}")
    for t in sol.trips:
        print(f"  {t.plate_no} 第{t.trip_no}趟 {t.time_window} load={t.load} stores={t.store_ids}")
    print("未覆盖门店 id:", sol.uncovered_store_ids)

    # 重新算一遍池子看最终状态
    pool2 = _build_slot_pool(data)
    stores = sorted(data.stores, key=lambda s: -s.quantity)
    for store in stores:
        cands = []
        for slot in pool2:
            v = slot["vehicle"]
            if slot["time_window"] != store.delivery_window:
                continue
            if not vehicle_can_serve_store(v, store):
                continue
            if slot["load"] + store.quantity > v.max_load:
                continue
            cands.append(slot)
        if not cands:
            print(f"  !! {store.code} qty={store.quantity} 无处可放（池中已无匹配槽位）")
            continue
        best = max(cands, key=lambda s: s["vehicle"].max_load - s["load"] - store.quantity)
        best["stores"].append(store.id)
        best["load"] += store.quantity
    used = [s for s in pool2 if s["stores"]]
    print(f"\n模拟装车：使用槽位 {len(used)} 个")
    for s in used[:12]:
        print(f"    {s['vehicle'].plate_no} 第{s['trip_no']}趟 {s['time_window']} load={s['load']} n={len(s['stores'])}")
finally:
    db.close()
