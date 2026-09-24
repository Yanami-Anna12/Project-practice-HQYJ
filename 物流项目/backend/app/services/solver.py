"""调度求解器：启发式 + CP-SAT 三阶段混合求解。

对应需求文档 四.2「调度求解器设计」：

    阶段 1  启发式快速生成初始可行解
    阶段 2  CP-SAT 优化
    阶段 3  多方案生成（A 四米二优先 / B 成本最低 / C 大包小包保障优先 / D 装载率均衡）

硬约束
------
    1. 每个门店的货量必须全部被满足
    2. 上午门店只能排上午趟，下午门店只能排下午趟
    3. 车辆地形能力必须覆盖门店地形
    4. 门店必须属于车辆可跑线路
    5. 发车必须达到最低装载量
    6. 不能超过最高装载量
    7. 四米二最多 2 趟、大包最多 2 趟、小包最多 4 趟

★ 关于「拆单」
--------------
需求文档没有要求一个门店必须由同一趟车一次送完。而现实数据里，
单店日货量常常超过单车最大装载量（例如四米二上限 800，而某店 2290），
一趟车物理上装不下。

因此本求解器**允许把一个门店的货量拆到多个趟次**，每个趟次记录实际配送量。
这使得：
    · 门店在方案明细里可能出现多条记录（不同车/不同趟，各带数量）
    · 「每个门店需求必须满足」的校验口径变成「各趟配送量之和 == 门店货量」

设计说明
--------
· 「趟次」是求解的最小单位：一次求解为每个 (车辆, 趟次) 分配 (门店, 数量) 对。
· 「趟次时段」由门店的 delivery_window 决定，上午门店只能进 AM 趟。
· 空趟（没有任何门店的趟次）不计入方案，也不受「达到最低装载量才发车」约束。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from ortools.sat.python import cp_model

logger = logging.getLogger(__name__)

# 车辆类型码
TYPE_42 = "4.2m"
TYPE_BIG = "big"
TYPE_SMALL = "small"

# 车型成本系数（用于「成本最低」方案）：演示用的相对系数，真实场景应对接财务口径
COST_FACTOR = {TYPE_42: 1.0, TYPE_BIG: 0.85, TYPE_SMALL: 0.5}

# 地形能力 → 可通行的地形集合
CAPABILITY_TERRAINS = {
    "all": {"normal", "medium", "strict"},
    "big_small": {"normal", "medium"},
    "small_only": {"normal"},
}

# 单趟最多服务几个门店（避免一趟绕行过长）
MAX_STORES_PER_TRIP = 8

# 浮点比较容差。货量用 Numeric(10,2) 存储，0.01 的误差属于正常范围。
EPS = 0.01


# ---------------------------------------------------------------------------
# 输入数据结构
# ---------------------------------------------------------------------------
@dataclass
class StoreInput:
    id: int
    code: str
    name: str
    terrain_type: str
    delivery_window: str  # AM / PM
    quantity: float
    route_ids: list[int] = field(default_factory=list)
    priority: int = 100


@dataclass
class VehicleInput:
    id: int
    plate_no: str
    vehicle_type: str
    terrain_capability: str
    route_scope: list[int] = field(default_factory=list)  # 空 = 不限制
    min_load: int = 0
    max_load: int = 0
    trips_per_day: int = 1


@dataclass
class SolveInput:
    stores: list[StoreInput]
    vehicles: list[VehicleInput]
    schedule_date: str = ""
    time_window: str = "FULL"


# ---------------------------------------------------------------------------
# 输出数据结构
# ---------------------------------------------------------------------------
@dataclass
class StoreLoad:
    """一个趟次里给某门店配送的数量。"""

    store_id: int
    quantity: float
    sequence: int = 1


@dataclass
class TripAssignment:
    """一个趟次：某车的第 N 趟，服务哪些门店、各送多少。"""

    vehicle_id: int
    plate_no: str
    vehicle_type: str
    trip_no: int
    time_window: str
    loads: list[StoreLoad]
    min_load: int
    max_load: int

    @property
    def store_ids(self) -> list[int]:
        return [x.store_id for x in self.loads]

    @property
    def load(self) -> float:
        return round(sum(x.quantity for x in self.loads), 2)

    @property
    def is_valid_load(self) -> bool:
        """达到最低装载量且不超最高装载量。空趟不参与判断。"""
        if not self.loads:
            return True
        return self.min_load <= self.load <= self.max_load + EPS


@dataclass
class Solution:
    trips: list[TripAssignment] = field(default_factory=list)
    # 未能完全满足的门店：{store_id: 缺口数量}
    shortfall: dict[int, float] = field(default_factory=dict)
    strategy: str = ""
    notes: list[str] = field(default_factory=list)
    solver_used: str = "heuristic"
    duration_ms: int = 0
    metrics: dict[str, float] = field(default_factory=dict)
    recommended: bool = False

    @property
    def uncovered_store_ids(self) -> list[int]:
        """完全没有被安排任何货量的门店。"""
        served = {x.store_id for t in self.trips for x in t.loads}
        return sorted(sid for sid in self.shortfall if sid not in served)

    @property
    def active_vehicle_ids(self) -> list[int]:
        return sorted({t.vehicle_id for t in self.trips if t.loads})

    @property
    def vehicle_count(self) -> int:
        return len(self.active_vehicle_ids)

    @property
    def trip_count(self) -> int:
        return sum(1 for t in self.trips if t.loads)

    @property
    def total_load(self) -> float:
        return round(sum(t.load for t in self.trips), 2)

    @property
    def avg_load_rate(self) -> float:
        used = [t for t in self.trips if t.loads]
        if not used:
            return 0.0
        return round(sum(t.load / t.max_load for t in used if t.max_load) / len(used) * 100, 2)

    @property
    def four_two_usage(self) -> float:
        used = [t for t in self.trips if t.loads]
        if not used:
            return 0.0
        return round(sum(1 for t in used if t.vehicle_type == TYPE_42) / len(used) * 100, 2)

    @property
    def total_cost(self) -> float:
        return round(sum(COST_FACTOR.get(t.vehicle_type, 1.0) for t in self.trips if t.loads), 2)


# ---------------------------------------------------------------------------
# 可行性判断
# ---------------------------------------------------------------------------
def capability_can_serve(capability: str, terrain_type: str) -> bool:
    """车辆地形能力是否能覆盖门店地形。"""
    return terrain_type in CAPABILITY_TERRAINS.get(capability, set())


def vehicle_can_serve_store(vehicle: VehicleInput, store: StoreInput) -> bool:
    """地形 + 线路双重判断（硬约束 3、4）。"""
    if not capability_can_serve(vehicle.terrain_capability, store.terrain_type):
        return False
    if vehicle.route_scope and store.route_ids:
        if not set(vehicle.route_scope).intersection(store.route_ids):
            return False
    return True


def check_assignable(stores: list[StoreInput], vehicles: list[VehicleInput]) -> list[str]:
    """求解前的可行性自检，返回人类可读的问题列表。

    为什么要做这一步：如果某些门店没有任何车辆能服务，与其让求解器
    「静默地少覆盖几家店」，不如提前把原因说清楚。
    """
    problems: list[str] = []
    if not stores:
        problems.append("当日没有任何门店货量需求，无法调度")
        return problems
    if not vehicles:
        problems.append("没有可出勤车辆，无法调度")
        return problems

    for store in stores:
        capable = [v for v in vehicles if vehicle_can_serve_store(v, store)]
        if not capable:
            terrain_ok = [
                v for v in vehicles
                if capability_can_serve(v.terrain_capability, store.terrain_type)
            ]
            if not terrain_ok:
                problems.append(
                    f"门店 {store.code} {store.name} 地形为 {store.terrain_type}，"
                    f"没有任何车辆的地形能力可覆盖"
                )
            else:
                problems.append(
                    f"门店 {store.code} {store.name} 所属线路 "
                    f"{store.route_ids or '（未映射线路）'} 与所有可用车辆的可跑线路都不匹配"
                )

    if not problems:
        capacity = sum(v.max_load * v.trips_per_day for v in vehicles)
        demand = sum(s.quantity for s in stores)
        if demand > capacity:
            problems.append(
                f"当日总货量 {demand:.0f} 超过车辆总运力 {capacity:.0f}，必然有门店无法覆盖"
            )
    return problems


# ---------------------------------------------------------------------------
# 槽位池
# ---------------------------------------------------------------------------
def _build_slot_pool(data: SolveInput) -> list[dict[str, Any]]:
    """为每台车生成候选趟次槽位。上午/下午按车型的趟次规则拆分。"""
    pool: list[dict[str, Any]] = []
    for v in data.vehicles:
        total = max(1, v.trips_per_day)
        am_count = (total + 1) // 2
        pm_count = total - am_count
        for i in range(am_count):
            pool.append(
                {
                    "vehicle": v,
                    "trip_no": i + 1,
                    "time_window": "AM",
                    "loads": {},  # store_id -> quantity
                    "load": 0.0,
                }
            )
        for i in range(pm_count):
            pool.append(
                {
                    "vehicle": v,
                    "trip_no": am_count + i + 1,
                    "time_window": "PM",
                    "loads": {},
                    "load": 0.0,
                }
            )
    return pool


# ---------------------------------------------------------------------------
# 阶段 1：启发式
# ---------------------------------------------------------------------------
def heuristic_solve(
    data: SolveInput,
    *,
    strategy: str = "A",
    type_priority: tuple[str, ...] = (TYPE_42, TYPE_BIG, TYPE_SMALL),
) -> Solution:
    """启发式求解：贪心装车 + 拆单 + 达标修复。

    思路（对应需求文档阶段 1）：
      · 只投放到「地形/线路/时段都匹配」的槽位
      · 优先使用四米二（type_priority 决定顺序）
      · 上午/下午分开排趟
      · 货量降序处理，大店先安置，避免碎片化
      · 单店货量超过单车容量时**拆到多个趟次**
      · 最后修复「装不满最低装载量」的趟次
    """
    started = time.perf_counter()
    solution = Solution(strategy=strategy, solver_used="heuristic")

    pool = _build_slot_pool(data)
    type_rank = {t: i for i, t in enumerate(type_priority)}
    pool.sort(key=lambda s: (type_rank.get(s["vehicle"].vehicle_type, 99), s["trip_no"]))

    stores = sorted(data.stores, key=lambda s: -s.quantity)

    for store in stores:
        remaining = float(store.quantity)

        while remaining > EPS:
            # 收集这次能接纳的门店容量
            options = []
            for slot in pool:
                v: VehicleInput = slot["vehicle"]
                if slot["time_window"] != store.delivery_window:
                    continue
                if not vehicle_can_serve_store(v, store):
                    continue
                if len(slot["loads"]) >= MAX_STORES_PER_TRIP and store.id not in slot["loads"]:
                    continue
                room = v.max_load - slot["load"]
                if room <= EPS:
                    continue
                options.append((slot, room))

            if not options:
                break

            # 选槽位的排序键，两个因素共同决定：
            #   1. 车型优先级（type_priority）—— 让方案 A/B/C/D 有各自性格。
            #      必须作为**主**排序键，否则车型选择会被装载率因素完全吃掉。
            #   2. 装完后剩余空间最小（best-fit）—— 追求高装载率。
            #
            # 早先版本用「剩余空间最大」（worst-fit）且不排车型优先级，
            # 结果是四米二因容量最大而永远被选中，四套方案完全一样，
            # 多方案比选失去意义。这里改成优先级主导 + best-fit 装载。
            def rank(o):
                slot, room = o
                v: VehicleInput = slot["vehicle"]
                return (type_rank.get(v.vehicle_type, 99), room - min(remaining, room))

            slot, room = min(options, key=rank)
            take = round(min(remaining, room), 2)

            slot["loads"][store.id] = round(slot["loads"].get(store.id, 0.0) + take, 2)
            slot["load"] = round(slot["load"] + take, 2)
            remaining = round(remaining - take, 2)

        if remaining > EPS:
            # 记入缺口。这里不抛异常：调度员需要看到「哪些店没排完」，
            # 而不是一个失败的页面。
            solution.shortfall[store.id] = round(
                solution.shortfall.get(store.id, 0.0) + remaining, 2
            )

    _repair_underload(pool, data)

    # ★ 修复阶段可能取消了不达标的趟次，那部分货量就成了缺口。
    #   这里按「实际装上的量」重算缺口，而不是沿用装车时的中间值 ——
    #   否则会出现「校验器发现缺口但 shortfall 里没记录」的不一致。
    delivered: dict[int, float] = {}
    for slot in pool:
        for sid, qty in slot["loads"].items():
            delivered[sid] = round(delivered.get(sid, 0.0) + qty, 2)

    solution.shortfall = {}
    for store in data.stores:
        missing = round(float(store.quantity) - delivered.get(store.id, 0.0), 2)
        if missing > EPS:
            solution.shortfall[store.id] = missing

    for slot in pool:
        if not slot["loads"]:
            continue
        v: VehicleInput = slot["vehicle"]
        solution.trips.append(
            TripAssignment(
                vehicle_id=v.id,
                plate_no=v.plate_no,
                vehicle_type=v.vehicle_type,
                trip_no=slot["trip_no"],
                time_window=slot["time_window"],
                loads=[
                    StoreLoad(store_id=sid, quantity=qty, sequence=i + 1)
                    for i, (sid, qty) in enumerate(slot["loads"].items())
                ],
                # 这里存的是槽位车型的规则，不是单车覆盖值（单车不一定有覆盖值）
                min_load=v.min_load,
                max_load=v.max_load,
            )
        )

    solution.trips.sort(key=lambda t: (t.plate_no, t.trip_no))
    solution.duration_ms = int((time.perf_counter() - started) * 1000)
    served = len(data.stores) - len(solution.shortfall)
    solution.notes.append(
        f"启发式：{len(data.stores)} 个门店装入 {solution.trip_count} 个趟次，"
        f"完整满足 {served} 个"
    )
    return solution


def _repair_underload(pool: list[dict[str, Any]], data: SolveInput) -> None:
    """修复「装不满最低装载量」的趟次。

    需求硬约束：达到最低装载量才发车。worst-fit 铺开货量后必然出现多个
    不达标的小趟次，修复策略按优先级来：

      1. 合并：把两个不达标趟次的货量并到一个趟次里（不超上限）
      2. 转移：把货量挪到别的「加了能达标」的趟次；或从未达标趟次
         反向接纳其他趟次多出来的量
      3. 放弃：仍不达标就整趟取消，货量计入缺口

    与其发一趟不达标的车（违反硬约束），不如明确报告缺口 ——
    方案里的 shortfall 会让调度员看到并人工处理。
    """
    store_by_id = {s.id: s for s in data.stores}

    def can_merge(target: dict, source: dict) -> bool:
        """source 的货量能否整体并入 target。"""
        if target["time_window"] != source["time_window"]:
            return False
        tv: VehicleInput = target["vehicle"]
        if target["load"] + source["load"] > tv.max_load + EPS:
            return False
        # source 里所有门店都必须能被 target 的车服务
        for sid in source["loads"]:
            store = store_by_id.get(sid)
            if store is None or not vehicle_can_serve_store(tv, store):
                return False
        # 门店数合并后不能超过单趟上限
        merged_ids = set(target["loads"]) | set(source["loads"])
        return len(merged_ids) <= MAX_STORES_PER_TRIP

    # ---- 策略 1：合并两个不达标趟次（循环到再也合不动为止）----
    for _ in range(len(pool)):
        under = [s for s in pool if s["loads"] and s["load"] < s["vehicle"].min_load]
        if len(under) < 2:
            break
        under.sort(key=lambda s: -s["load"])

        progressed = False
        for i, target in enumerate(under):
            for source in under[i + 1:]:
                if not can_merge(target, source):
                    continue
                for sid, qty in source["loads"].items():
                    target["loads"][sid] = round(target["loads"].get(sid, 0.0) + qty, 2)
                target["load"] = round(target["load"] + source["load"], 2)
                source["loads"] = {}
                source["load"] = 0.0
                progressed = True
                break
            if progressed:
                break
        if not progressed:
            break

    # ---- 策略 2：把货量挪到「加了之后能达标」的趟次 ----
    for slot in pool:
        if not slot["loads"]:
            continue
        v: VehicleInput = slot["vehicle"]
        if slot["load"] + EPS >= v.min_load:
            continue

        for sid, qty in list(slot["loads"].items()):
            store = store_by_id.get(sid)
            if store is None:
                continue
            for other in pool:
                if other is slot or not other["loads"]:
                    continue
                ov: VehicleInput = other["vehicle"]
                if other["time_window"] != store.delivery_window:
                    continue
                if not vehicle_can_serve_store(ov, store):
                    continue
                if other["load"] + qty > ov.max_load + EPS:
                    continue
                # 只往「本来就达标」或「加了之后能达标」的趟次里挪
                if other["load"] + EPS < ov.min_load and other["load"] + qty + EPS < ov.min_load:
                    continue
                if sid not in other["loads"] and len(other["loads"]) >= MAX_STORES_PER_TRIP:
                    continue
                other["loads"][sid] = round(other["loads"].get(sid, 0.0) + qty, 2)
                other["load"] = round(other["load"] + qty, 2)
                del slot["loads"][sid]
                slot["load"] = round(slot["load"] - qty, 2)
                break

    # ---- 策略 3：放弃仍不达标的趟次（货量变成缺口）----
    for slot in pool:
        if not slot["loads"]:
            continue
        if slot["load"] + EPS < slot["vehicle"].min_load:
            slot["loads"] = {}
            slot["load"] = 0.0


# ---------------------------------------------------------------------------
# 阶段 2：CP-SAT 优化
# ---------------------------------------------------------------------------
def cp_sat_solve(
    data: SolveInput,
    *,
    strategy: str = "A",
    weights: dict[str, float] | None = None,
    timeout_seconds: int = 30,
) -> Solution | None:
    """CP-SAT 求解。无解或失败时返回 None，由调用方回退到启发式。

    建模思路
    --------
    ★ 为了在「允许拆单」的前提下保持模型是线性的，这里把每个门店按
      「不可再分的最小装载单位」拆成一叠**需求单元**（unit）：

          门店货量 2290、四米二上限 800  →  3 个 800 的单元 + 1 个 490 的单元
          最后一个单元可能小于最低装载量，所以它不能独立成趟，
          必须和其他单元共处一趟 —— 下面用「补足约束」处理。

      这样每个 (unit, 槽位) 的分配仍是 0/1 变量，模型保持线性。

    决策变量：
        x[i, k] = 1  单元 i 分配到槽位 k
        u[i]    = 1  单元 i 未被安排（重罚，保证模型总有解）
        y[k]    = 1  槽位 k 发车

    约束：
        · 每个单元恰好分配一次：Σ_k x[i,k] + u[i] = 1
        · 装载量：Σ_i qty[i]·x[i,k] = load[k]，且 min·y[k] ≤ load[k] ≤ max·y[k]
        · 只允许分配到「能服务该门店」的槽位（地形/线路/时段预筛）
        · 单趟门店数上限

    目标：按 weights 加权最大化，weights 不同 → 方案 A/B/C/D 性格不同。
    """
    started = time.perf_counter()
    w = {
        "coverage": 10000.0,
        "four_two": 30.0,
        "load_rate": 40.0,
        "small_trip": 20.0,
        "cost": -25.0,
        "vehicle": -8.0,
    }
    if weights:
        w.update(weights)

    if not data.stores or not data.vehicles:
        return None

    specs = _vehicle_type_specs(data)

    # --- 生成槽位 ---
    slots: list[dict[str, Any]] = []
    for v in data.vehicles:
        spec = specs.get(v.vehicle_type)
        if spec is None:
            continue
        total = max(1, spec["trips_per_day"])
        am_count = (total + 1) // 2
        plan = [("AM", i + 1) for i in range(am_count)] + [
            ("PM", am_count + i + 1) for i in range(total - am_count)
        ]
        for window, trip_no in plan:
            slots.append(
                {
                    "vehicle": v,
                    "trip_no": trip_no,
                    "time_window": window,
                    "min_load": spec["min_load"],
                    "max_load": spec["max_load"],
                    "vehicle_type": v.vehicle_type,
                }
            )

    if not slots:
        return None

    # --- 把门店拆成需求单元 ---
    # 单元大小取决于「能服务该门店的最大车型容量」，否则会造成不必要的碎片
    units: list[dict[str, Any]] = []
    for si, s in enumerate(data.stores):
        capable_caps = [
            specs[v.vehicle_type]["max_load"]
            for v in data.vehicles
            if v.vehicle_type in specs and vehicle_can_serve_store(v, s)
        ]
        unit_size = max(capable_caps) if capable_caps else 0
        if unit_size <= 0:
            # 没有车辆能服务这个门店 —— 整店未覆盖
            units.append({"store_index": si, "qty": float(s.quantity), "forced_uncovered": True})
            continue

        remaining = float(s.quantity)
        while remaining > EPS:
            take = round(min(remaining, unit_size), 2)
            units.append({"store_index": si, "qty": take, "forced_uncovered": False})
            remaining = round(remaining - take, 2)

    n_units, n_slots = len(units), len(slots)
    if n_units == 0:
        return None

    # --- 每个单元可用的槽位（地形/线路/时段 + 容量足够）---
    unit_slots: list[list[int]] = []
    for unit in units:
        s = data.stores[unit["store_index"]]
        avail = []
        if not unit["forced_uncovered"]:
            for k, slot in enumerate(slots):
                v: VehicleInput = slot["vehicle"]
                if slot["time_window"] != s.delivery_window:
                    continue
                if not vehicle_can_serve_store(v, s):
                    continue
                if unit["qty"] > slot["max_load"] + EPS:
                    continue
                avail.append(k)
        unit_slots.append(avail)

    slot_units: list[list[int]] = [[] for _ in range(n_slots)]
    for i, ks in enumerate(unit_slots):
        for k in ks:
            slot_units[k].append(i)

    # --- 建模 ---
    model = cp_model.CpModel()
    SCALE = 100  # 货量放大 100 倍转整数（保留两位小数）

    x: dict[tuple[int, int], Any] = {}
    for i in range(n_units):
        for k in unit_slots[i]:
            x[(i, k)] = model.NewBoolVar(f"x_{i}_{k}")

    u = [model.NewBoolVar(f"u_{i}") for i in range(n_units)]
    y = [model.NewBoolVar(f"y_{k}") for k in range(n_slots)]

    qty_int = [int(round(unit["qty"] * SCALE)) for unit in units]

    # 每个单元恰好分配一次（或未覆盖）
    for i in range(n_units):
        terms = [x[(i, k)] for k in unit_slots[i]]
        if terms:
            model.Add(sum(terms) + u[i] == 1)
        else:
            model.Add(u[i] == 1)  # 无可用槽位，只能未覆盖

    # 装载量与发车约束
    load_exprs = []
    for k in range(n_slots):
        members = slot_units[k]
        if not members:
            model.Add(y[k] == 0)
            load_exprs.append(None)
            continue
        load = sum(qty_int[i] * x[(i, k)] for i in members)
        load_exprs.append(load)
        model.Add(load <= int(slots[k]["max_load"] * SCALE) * y[k])
        model.Add(load >= int(slots[k]["min_load"] * SCALE) * y[k])
        model.Add(sum(x[(i, k)] for i in members) <= MAX_STORES_PER_TRIP)
        # 发车必须有货
        model.Add(sum(x[(i, k)] for i in members) >= y[k])

    # --- 目标 ---
    objective = []

    # 1) 覆盖（按货量加权，优先覆盖大店）
    coverage_w = int(w["coverage"] / 100)
    if coverage_w:
        for i in range(n_units):
            objective.append(coverage_w * (1 - u[i]))

    # 2) 四米二使用率
    fw = int(w["four_two"])
    if fw:
        for k, slot in enumerate(slots):
            if slot["vehicle_type"] == TYPE_42:
                objective.append(fw * y[k])

    # 3) 装载率（归一化到 0~100 再加权）
    # ★ 注意：OR-Tools 的 LinearExpr 不支持 Python 的 // 运算符，
    #   表达「除以容量」必须用 AddDivisionEquality 引入中间变量。
    lw = int(w["load_rate"])
    if lw:
        for k in range(n_slots):
            if load_exprs[k] is None:
                continue
            cap = max(1, int(slots[k]["max_load"] * SCALE))
            # rate_k = load / cap，取值 0~100（对应 0%~100%）
            rate = model.NewIntVar(0, 100, f"load_rate_{k}")
            model.AddDivisionEquality(rate, load_exprs[k] * 100, cap)
            objective.append(lw * rate)

    # 4) 大包/小包趟次保障
    sw = int(w["small_trip"])
    if sw:
        for k, slot in enumerate(slots):
            if slot["vehicle_type"] in (TYPE_BIG, TYPE_SMALL):
                objective.append(sw * y[k])

    # 5) 成本（权重为负）
    cw = int(-w["cost"] * 10)
    if cw:
        for k, slot in enumerate(slots):
            factor = COST_FACTOR.get(slot["vehicle_type"], 1.0)
            objective.append(-int(cw * factor) * y[k])

    # 6) 用车数（权重为负）
    vw = int(-w["vehicle"])
    if vw:
        by_vehicle: dict[int, list[int]] = {}
        for k, slot in enumerate(slots):
            by_vehicle.setdefault(slot["vehicle"].id, []).append(k)
        for vid, ks in by_vehicle.items():
            vv = model.NewBoolVar(f"use_v_{vid}")
            model.AddMaxEquality(vv, [y[k] for k in ks])
            objective.append(-vw * 20 * vv)

    model.Maximize(sum(objective))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(timeout_seconds)
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        logger.warning("CP-SAT 未找到可行解，status=%s", solver.StatusName(status))
        return None

    # --- 还原 ---
    solution = Solution(strategy=strategy, solver_used="cp-sat")
    served_qty: dict[int, float] = {}

    for k, slot in enumerate(slots):
        if solver.Value(y[k]) != 1:
            continue
        loads: dict[int, float] = {}
        for i in slot_units[k]:
            if solver.Value(x[(i, k)]) == 1:
                sid = data.stores[units[i]["store_index"]].id
                loads[sid] = round(loads.get(sid, 0.0) + units[i]["qty"], 2)
                served_qty[sid] = round(served_qty.get(sid, 0.0) + units[i]["qty"], 2)
        if not loads:
            continue
        v: VehicleInput = slot["vehicle"]
        solution.trips.append(
            TripAssignment(
                vehicle_id=v.id,
                plate_no=v.plate_no,
                vehicle_type=v.vehicle_type,
                trip_no=slot["trip_no"],
                time_window=slot["time_window"],
                loads=[
                    StoreLoad(store_id=sid, quantity=q, sequence=idx + 1)
                    for idx, (sid, q) in enumerate(loads.items())
                ],
                min_load=slot["min_load"],
                max_load=slot["max_load"],
            )
        )

    # 未覆盖 / 缺口
    for i in range(n_units):
        if solver.Value(u[i]) != 1:
            continue
        s = data.stores[units[i]["store_index"]]
        solution.shortfall[s.id] = round(
            solution.shortfall.get(s.id, 0.0) + units[i]["qty"], 2
        )

    solution.trips.sort(key=lambda t: (t.plate_no, t.trip_no))
    solution.duration_ms = int((time.perf_counter() - started) * 1000)
    total_stores = len(data.stores)
    served_stores = total_stores - len(solution.shortfall)
    solution.notes.append(
        f"CP-SAT（{solver.StatusName(status)}，目标值 {solver.ObjectiveValue():.0f}）："
        f"{solution.trip_count} 个趟次，完整满足 {served_stores} 个门店"
    )
    return solution


def _vehicle_type_specs(data: SolveInput) -> dict[str, dict[str, Any]]:
    """按车型汇总规则参数（求解器只需要类型级别的装载量与趟次上限）。"""
    specs: dict[str, dict[str, Any]] = {}
    for v in data.vehicles:
        if v.vehicle_type in specs:
            continue
        specs[v.vehicle_type] = {
            "code": v.vehicle_type,
            "min_load": v.min_load,
            "max_load": v.max_load,
            "trips_per_day": v.trips_per_day,
        }
    return specs


# ---------------------------------------------------------------------------
# 阶段 3：多方案生成
# ---------------------------------------------------------------------------
PLAN_STRATEGIES: dict[str, dict[str, Any]] = {
    "A": {
        "name": "四米二优先",
        "desc": "优先使用四米二车辆，减少车型切换",
        "type_priority": (TYPE_42, TYPE_BIG, TYPE_SMALL),
        "weights": {"four_two": 80.0, "load_rate": 30.0, "small_trip": 10.0},
    },
    "B": {
        "name": "成本最低",
        "desc": "优先使用成本更低的车型，压缩用车数",
        "type_priority": (TYPE_SMALL, TYPE_BIG, TYPE_42),
        "weights": {"cost": -120.0, "vehicle": -40.0, "four_two": -20.0},
    },
    "C": {
        "name": "大包小包趟次保障优先",
        "desc": "优先保障大包、小包的日出车次数",
        "type_priority": (TYPE_BIG, TYPE_SMALL, TYPE_42),
        "weights": {"small_trip": 120.0, "four_two": -10.0, "load_rate": 20.0},
    },
    "D": {
        "name": "装载率均衡",
        "desc": "追求各趟装载率均衡，减少半空车",
        "type_priority": (TYPE_42, TYPE_SMALL, TYPE_BIG),
        "weights": {"load_rate": 150.0, "vehicle": -25.0},
    },
}

SCORE_WEIGHTS = {
    "coverage": 100.0,
    "four_two": 0.30,
    "load_rate": 0.40,
    "trip_achievement": 0.30,
    "cost": -0.20,
    "shortfall_penalty": -50.0,
}


def generate_plans(
    data: SolveInput,
    *,
    timeout_seconds: int = 30,
    use_cp_sat: bool = True,
) -> list[Solution]:
    """生成 A/B/C/D 四套方案。

    每套先跑启发式（保证一定有解），再用对应权重跑 CP-SAT 优化；
    CP-SAT 失败或未更优则保留启发式结果 —— 保证「一定有方案可看」。
    """
    solutions: list[Solution] = []
    total_demand = sum(s.quantity for s in data.stores) or 1.0

    for code, cfg in PLAN_STRATEGIES.items():
        base = heuristic_solve(data, strategy=code, type_priority=cfg["type_priority"])
        base.notes.insert(0, f"方案 {code} · {cfg['name']}：{cfg['desc']}")

        best = base
        if use_cp_sat:
            optimized = cp_sat_solve(
                data,
                strategy=code,
                weights=cfg["weights"],
                timeout_seconds=timeout_seconds,
            )
            if optimized is not None and _is_better(optimized, base, cfg["weights"], total_demand):
                optimized.notes.insert(0, f"方案 {code} · {cfg['name']}：{cfg['desc']}")
                optimized.notes.append("已在启发式解基础上用 CP-SAT 优化")
                best = optimized
            elif optimized is not None:
                base.notes.append("CP-SAT 结果未优于启发式解，保留启发式方案")

        solutions.append(best)

    _score_solutions(solutions, data, total_demand)
    return solutions


def _served_quantity(sol: Solution) -> float:
    return sum(load.quantity for t in sol.trips for load in t.loads)


def _is_better(
    candidate: Solution, base: Solution, weights: dict[str, float], total_demand: float
) -> bool:
    """判断 CP-SAT 解是否优于启发式解（按方案自身的权重口径）。"""

    def value(sol: Solution) -> float:
        served = _served_quantity(sol)
        return (
            served / total_demand * 100000
            + weights.get("four_two", 0) * sol.four_two_usage / 100
            + weights.get("load_rate", 0) * sol.avg_load_rate / 100
            + weights.get("small_trip", 0)
            * sum(1 for t in sol.trips if t.vehicle_type in (TYPE_BIG, TYPE_SMALL))
            + weights.get("cost", 0) * sol.total_cost / 10
            + weights.get("vehicle", 0) * sol.vehicle_count / 10
        )

    return value(candidate) > value(base)


def _score_solutions(
    solutions: list[Solution], data: SolveInput, total_demand: float
) -> None:
    """给每套方案打分并标出推荐方案。

    评分口径（对应需求文档目标函数）：
        满足货量比例（最重要）→ 四米二使用率 → 装载率 → 趟次保障 → 成本
    """
    best_index, best_score = 0, float("-inf")

    for i, sol in enumerate(solutions):
        served = _served_quantity(sol)
        coverage = served / total_demand * 100 if total_demand else 0.0

        small_types = [t for t in sol.trips if t.vehicle_type in (TYPE_BIG, TYPE_SMALL)]
        trip_achievement = (
            round(min(100.0, len(small_types) / max(1, len(sol.trips)) * 100 * 1.5), 2)
            if sol.trips
            else 0.0
        )

        shortfall_qty = sum(sol.shortfall.values())
        score = (
            coverage * SCORE_WEIGHTS["coverage"]
            + sol.four_two_usage * SCORE_WEIGHTS["four_two"]
            + sol.avg_load_rate * SCORE_WEIGHTS["load_rate"]
            + trip_achievement * SCORE_WEIGHTS["trip_achievement"]
            + sol.total_cost * SCORE_WEIGHTS["cost"]
            + shortfall_qty / total_demand * 100 * SCORE_WEIGHTS["shortfall_penalty"]
        )

        sol.metrics = {
            "coverage": round(coverage, 2),
            "trip_achievement": trip_achievement,
            "shortfall_quantity": round(shortfall_qty, 2),
            "score": round(score, 2),
        }
        sol.notes.append(
            f"评分 {score:.1f}（货量满足 {coverage:.1f}%、"
            f"四米二使用率 {sol.four_two_usage}%、装载率 {sol.avg_load_rate}%）"
        )
        if score > best_score:
            best_index, best_score = i, score

    for i, sol in enumerate(solutions):
        sol.recommended = i == best_index


# ---------------------------------------------------------------------------
# 校验：方案是否满足全部硬约束
# ---------------------------------------------------------------------------
def validate_solution(sol: Solution, data: SolveInput) -> list[str]:
    """独立校验方案，返回违规列表（空 = 全部满足）。

    ★ 刻意不复用求解器内部的判断，而是拿原始输入重新算一遍 ——
      求解器的 bug 不应该被自己的校验逻辑掩盖。
    """
    issues: list[str] = []
    store_by_id = {s.id: s for s in data.stores}
    vehicle_by_id = {v.id: v for v in data.vehicles}

    # 每个门店实际被配送的总量
    delivered: dict[int, float] = {s.id: 0.0 for s in data.stores}
    trips_per_vehicle: dict[int, int] = {}

    for trip in sol.trips:
        v = vehicle_by_id.get(trip.vehicle_id)
        if v is None:
            issues.append(f"趟次引用了不存在的车辆 id={trip.vehicle_id}")
            continue

        trips_per_vehicle[trip.vehicle_id] = trips_per_vehicle.get(trip.vehicle_id, 0) + 1

        if not trip.loads:
            continue

        # 硬约束 6：不超最高装载量
        if trip.load > v.max_load + EPS:
            issues.append(
                f"{v.plate_no} 第 {trip.trip_no} 趟装载 {trip.load} 超过上限 {v.max_load}"
            )
        # 硬约束 5：达到最低装载量才发车
        if trip.load + EPS < v.min_load:
            issues.append(
                f"{v.plate_no} 第 {trip.trip_no} 趟装载 {trip.load} 未达最低 {v.min_load}"
            )
        if len(trip.loads) > MAX_STORES_PER_TRIP:
            issues.append(
                f"{v.plate_no} 第 {trip.trip_no} 趟服务了 {len(trip.loads)} 个门店，"
                f"超过上限 {MAX_STORES_PER_TRIP}"
            )

        for item in trip.loads:
            store = store_by_id.get(item.store_id)
            if store is None:
                issues.append(f"趟次引用了不存在的门店 id={item.store_id}")
                continue
            if item.quantity <= 0:
                issues.append(f"{store.code} 在某趟次里的配送量为 {item.quantity}")

            delivered[store.id] = round(delivered[store.id] + item.quantity, 2)

            # 硬约束 2：时段匹配
            if store.delivery_window != trip.time_window:
                issues.append(
                    f"{store.code} 配送时段为 {store.delivery_window}，"
                    f"却被排入 {trip.time_window} 趟"
                )
            # 硬约束 3：地形能力覆盖
            if not capability_can_serve(v.terrain_capability, store.terrain_type):
                issues.append(
                    f"{v.plate_no}（{v.terrain_capability}）无法进入 "
                    f"{store.code} 的 {store.terrain_type} 地形"
                )
            # 硬约束 4：线路匹配
            if v.route_scope and store.route_ids:
                if not set(v.route_scope).intersection(store.route_ids):
                    issues.append(f"{v.plate_no} 的可跑线路与 {store.code} 所属线路不匹配")

    # 硬约束 7：趟次上限（只数有货的趟次）
    active_trips: dict[int, int] = {}
    for trip in sol.trips:
        if trip.loads:
            active_trips[trip.vehicle_id] = active_trips.get(trip.vehicle_id, 0) + 1
    for vid, count in active_trips.items():
        v = vehicle_by_id[vid]
        if count > v.trips_per_day:
            issues.append(f"{v.plate_no} 安排了 {count} 趟，超过每日上限 {v.trips_per_day}")

    # 硬约束 1：门店货量必须被完整满足（或明确记入 shortfall）
    for store in data.stores:
        got = delivered.get(store.id, 0.0)
        missing = round(float(store.quantity) - got, 2)
        recorded = round(sol.shortfall.get(store.id, 0.0), 2)
        if missing > EPS:
            if abs(missing - recorded) > EPS:
                issues.append(
                    f"{store.code} 缺口 {missing} 与记录的 shortfall {recorded} 不一致"
                )
        elif recorded > EPS:
            issues.append(
                f"{store.code} 已配送 {got}，却被记为缺口 {recorded}"
            )

    return issues
