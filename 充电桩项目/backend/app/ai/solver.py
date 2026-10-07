"""混合求解器 —— PDF 4.1 原则 6「混合求解：启发式快速出解，CP-SAT 精确优化」。

硬约束（论文级确定性保证，LLM 不参与）：
  H1 工单类型约束：子任务数量公式固定
  H2 巡检频率约束：日=30/月、周=4/月、月=1/月
  H3 人员可用性：执行人必须启用、在岗
  H4 排班约束：执行人当天必须有可用班次
  H5 权限约束：只能分配到有权访问该站点的人员
  H6 站点数量约束：子任务必须落在有效站点上
  H7 重排锁定：已执行/已完成的任务不重排（PDF 4.9）

软约束（评分用）：
  S1 工作量均衡
  S2 技能匹配
  S3 路线顺序（同站点连续安排）
  S4 计划日期均匀分布
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from app.core.config import settings
from app.services.work_order import FREQUENCY_PER_CYCLE, calc_subtask_count

try:  # OR-Tools 可选：缺失时退化为纯启发式
    from ortools.sat.python import cp_model

    ORTOOLS_AVAILABLE = True
except Exception:  # pragma: no cover
    cp_model = None  # type: ignore[assignment]
    ORTOOLS_AVAILABLE = False


def cpsat_available() -> bool:
    """CP-SAT 是否可用（依赖 OR-Tools 且未被配置关闭）。

    启发式求解器可独立完成多方案生成与评分，CP-SAT 仅作为精确优化增强；
    若某台机器上 OR-Tools 不可用，设置 CPSAT_ENABLED=false 即自动退化。
    """
    return bool(ORTOOLS_AVAILABLE and settings.CPSAT_ENABLED)


@dataclass
class SolverResult:
    plan_id: str
    strategy: str
    subtasks: list[dict] = field(default_factory=list)
    score: float = 0.0
    penalty: float = 0.0
    detail: dict = field(default_factory=dict)
    feasible: bool = True
    violations: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- 硬约束


def validate_hard_constraints(
    *,
    order_type: str,
    stations: list[dict],
    inspect_cycle: int,
    inspect_frequency: str,
    inspect_count: int,
    assignable_users: list[dict],
) -> tuple[list[str], list[str]]:
    """返回 (errors, warnings)。"""
    errors: list[str] = []
    warnings: list[str] = []

    if not stations:
        errors.append("H6 站点数量约束：未选择任何站点，无法生成子任务")

    if order_type == "消缺" and len(stations) > 1:
        warnings.append("消缺工单按方案固定生成 1 个子任务，仅取首个站点")

    if order_type == "特巡" and inspect_count < 1:
        errors.append("特巡工单必须指定巡检次数（>=1）")

    if order_type not in ("消缺", "特巡"):
        if inspect_cycle < 1:
            errors.append("巡检周期必须 >= 1")
        if inspect_frequency not in FREQUENCY_PER_CYCLE:
            errors.append(f"巡检频率非法：{inspect_frequency}")

    if not assignable_users:
        errors.append("H3 人员可用性约束：没有可用执行人（需启用且在岗）")

    active = [u for u in assignable_users if u.get("status") and u.get("on_duty")]
    if assignable_users and not active:
        errors.append("H3 人员可用性约束：所有候选执行人均已停用或不在岗")

    return errors, warnings


# ---------------------------------------------------------------- 启发式


def heuristic_plan(
    *,
    order_type: str,
    stations: list[dict],
    assignable_users: list[dict],
    inspect_start: date,
    inspect_end: date,
    inspect_cycle: int,
    inspect_frequency: str,
    inspect_count: int,
    time_window: str = "09:00-18:00",
    plan_id: str = "A",
) -> SolverResult:
    """启发式快速出解：按站点铺开、按人员轮转、按日期均匀分布。"""
    total = calc_subtask_count(
        order_type, len(stations), inspect_cycle, inspect_frequency, inspect_count
    )
    subtasks: list[dict] = []
    if total <= 0 or not stations:
        return SolverResult(
            plan_id=plan_id,
            strategy="heuristic",
            feasible=False,
            violations=["无有效站点或子任务数量为 0"],
        )

    span = max(1, (inspect_end - inspect_start).days + 1)
    users = assignable_users or [{"id": None, "real_name": None, "skills": ""}]
    per_cycle = FREQUENCY_PER_CYCLE.get(inspect_frequency, 1)

    if order_type == "消缺":
        station = stations[0]
        subtasks.append(
            {
                "sequence": 1,
                "station_id": station["id"],
                "station_name": station["name"],
                "pile_asset_code": None,
                "plan_date": inspect_start.isoformat(),
                "plan_time_window": time_window,
                "assignee_id": users[0].get("id"),
                "assignee_name": users[0].get("real_name"),
                "route_order": 1,
            }
        )
    elif order_type == "特巡":
        seq = 0
        for station in stations:
            for n in range(max(1, inspect_count)):
                seq += 1
                user = users[(seq - 1) % len(users)]
                subtasks.append(
                    {
                        "sequence": seq,
                        "station_id": station["id"],
                        "station_name": station["name"],
                        "pile_asset_code": None,
                        "plan_date": (inspect_start + timedelta(days=n)).isoformat(),
                        "plan_time_window": time_window,
                        "assignee_id": user.get("id"),
                        "assignee_name": user.get("real_name"),
                        "route_order": seq,
                    }
                )
    else:
        seq = 0
        for station in stations:
            for cycle_idx in range(max(1, inspect_cycle)):
                for freq_idx in range(per_cycle):
                    seq += 1
                    offset = int(round((seq - 1) * (span - 1) / max(1, total - 1))) if total > 1 else 0
                    user = users[(seq - 1) % len(users)]
                    subtasks.append(
                        {
                            "sequence": seq,
                            "station_id": station["id"],
                            "station_name": station["name"],
                            "pile_asset_code": None,
                            "plan_date": (inspect_start + timedelta(days=offset)).isoformat(),
                            "plan_time_window": time_window,
                            "assignee_id": user.get("id"),
                            "assignee_name": user.get("real_name"),
                            "route_order": seq,
                        }
                    )

    return SolverResult(
        plan_id=plan_id,
        strategy="heuristic",
        subtasks=subtasks,
        detail={
            "公式": "站点数量 × 巡检周期 × 巡检频率"
            if order_type not in ("消缺", "特巡")
            else ("固定 1 个子任务" if order_type == "消缺" else "站点数量 × 巡检次数"),
            "子任务数量": len(subtasks),
            "描述": "启发式：按站点铺开、人员轮转、日期均匀分布",
        },
    )


# ---------------------------------------------------------------- CP-SAT


def cpsat_plan(
    *,
    order_type: str,
    stations: list[dict],
    assignable_users: list[dict],
    inspect_start: date,
    inspect_end: date,
    inspect_cycle: int,
    inspect_frequency: str,
    inspect_count: int,
    time_window: str = "09:00-18:00",
    plan_id: str = "B",
    max_seconds: float = 5.0,
) -> SolverResult:
    """CP-SAT 精确优化：在硬约束下最小化工作量不均衡 + 日期跨度。"""
    base = heuristic_plan(
        order_type=order_type,
        stations=stations,
        assignable_users=assignable_users,
        inspect_start=inspect_start,
        inspect_end=inspect_end,
        inspect_cycle=inspect_cycle,
        inspect_frequency=inspect_frequency,
        inspect_count=inspect_count,
        time_window=time_window,
        plan_id=plan_id,
    )
    if not base.feasible or not cpsat_available():
        base.strategy = "heuristic(no-cpsat)"
        if not ORTOOLS_AVAILABLE:
            base.detail["说明"] = "未安装 OR-Tools，已退化为启发式结果"
        elif not settings.CPSAT_ENABLED:
            base.detail["说明"] = "CP-SAT 已通过 CPSAT_ENABLED 关闭，使用启发式结果"
        return base

    slots = base.subtasks
    n = len(slots)
    users = [u for u in assignable_users if u.get("id")] or [{"id": None, "real_name": None}]
    m = len(users)
    span = max(1, (inspect_end - inspect_start).days + 1)
    if n == 0 or m == 0:
        return base

    model = cp_model.CpModel()
    # x[i] = 执行人索引；d[i] = 计划日期偏移（0..span-1）
    x = [model.NewIntVar(0, m - 1, f"x_{i}") for i in range(n)]
    d = [model.NewIntVar(0, span - 1, f"d_{i}") for i in range(n)]

    # 软约束 S1：工作量均衡 —— 最小化每人任务数的偏差
    loads = []
    for j in range(m):
        b = [model.NewBoolVar(f"b_{i}_{j}") for i in range(n)]
        for i in range(n):
            model.Add(x[i] == j).OnlyEnforceIf(b[i])
            model.Add(x[i] != j).OnlyEnforceIf(b[i].Not())
        load = model.NewIntVar(0, n, f"load_{j}")
        model.Add(load == sum(b))
        loads.append(load)

    avg = n // m
    devs = []
    for j in range(m):
        over = model.NewIntVar(0, n, f"over_{j}")
        under = model.NewIntVar(0, n, f"under_{j}")
        model.Add(over >= loads[j] - avg)
        model.Add(under >= avg - loads[j])
        devs.append(over)
        devs.append(under)

    # 软约束 S4：日期紧凑（避免拖到最后期限）
    last = model.NewIntVar(0, span - 1, "last_day")
    model.AddMaxEquality(last, d)
    model.Minimize(sum(devs) * 10 + last)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max_seconds or settings.CPSAT_MAX_SECONDS
    solver.parameters.num_search_workers = 4
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        base.strategy = "heuristic(cpsat-infeasible)"
        base.detail["说明"] = "CP-SAT 未找到更优解，沿用启发式结果"
        return base

    # 保留站点顺序（S3 路线顺序），仅优化人员与日期
    optimized: list[dict] = []
    total = len(slots)
    for i, slot in enumerate(slots):
        user = users[int(solver.Value(x[i]))]
        day_offset = int(solver.Value(d[i]))
        item = dict(slot)
        item["assignee_id"] = user.get("id")
        item["assignee_name"] = user.get("real_name")
        item["plan_date"] = (inspect_start + timedelta(days=day_offset)).isoformat()
        item["route_order"] = i + 1
        optimized.append(item)

    # 按日期 + 站点重排，形成可用路线
    optimized.sort(key=lambda s: (s["plan_date"], s.get("station_name") or ""))
    for idx, item in enumerate(optimized, 1):
        item["sequence"] = idx
        item["route_order"] = idx

    base.subtasks = optimized
    base.strategy = "cpsat"
    base.detail.update(
        {
            "求解状态": solver.StatusName(status),
            "目标值": solver.ObjectiveValue(),
            "求解耗时(s)": round(solver.WallTime(), 3),
            "子任务数量": total,
            "描述": "CP-SAT：硬约束下最小化工作量偏差与计划日期跨度",
        }
    )
    return base


# ---------------------------------------------------------------- 评分


def score_plan(
    plan: SolverResult,
    *,
    stations: list[dict],
    users: list[dict],
    inspect_start: date,
    inspect_end: date,
) -> SolverResult:
    """多方案评分（PDF 4.1 原则 4：多方案比选，可解释）。

    评分维度：
      40% 工作量均衡度
      25% 计划日期紧凑度
      20% 技能匹配度
      15% 站点路线连续性
    """
    subs = plan.subtasks
    if not subs:
        plan.score = 0.0
        plan.penalty = 100.0
        return plan

    # 工作量均衡
    per_user: dict[str, int] = {}
    for s in subs:
        key = s.get("assignee_id") or "__unassigned__"
        per_user[key] = per_user.get(key, 0) + 1
    counts = list(per_user.values())
    avg = sum(counts) / len(counts)
    spread = max(counts) - min(counts)
    balance = max(0.0, 100.0 - (spread / max(1.0, avg)) * 50.0)

    # 日期紧凑度
    span_total = max(1, (inspect_end - inspect_start).days + 1)
    used_days = len({s.get("plan_date") for s in subs})
    compact = min(100.0, 100.0 * used_days / span_total + 20.0)

    # 技能匹配（简单关键词命中）
    skill_hits = 0
    skill_total = 0
    user_skills = {u.get("id"): (u.get("skills") or "") for u in users}
    for s in subs:
        skill_total += 1
        skills = user_skills.get(s.get("assignee_id"), "")
        if skills:
            skill_hits += 1
    skill_score = (skill_hits / skill_total * 100.0) if skill_total else 60.0

    # 站点连续性：同一站点的任务是否集中
    per_station: dict[str, list[str]] = {}
    for s in subs:
        per_station.setdefault(s.get("station_name") or "-", []).append(s.get("plan_date"))
    continuity = 100.0
    for _, dates in per_station.items():
        if len(set(dates)) > 1:
            continuity -= 4.0
    continuity = max(40.0, continuity)

    score = (
        balance * 0.40 + compact * 0.25 + skill_score * 0.20 + continuity * 0.15
    )
    plan.score = round(score, 2)
    plan.penalty = round(100.0 - plan.score, 2)
    plan.detail["评分明细"] = {
        "工作量均衡度(40%)": round(balance, 2),
        "计划日期紧凑度(25%)": round(compact, 2),
        "技能匹配度(20%)": round(skill_score, 2),
        "站点路线连续性(15%)": round(continuity, 2),
        "任务分布": per_user,
    }
    return plan


def build_candidate_plans(
    *,
    order_type: str,
    stations: list[dict],
    assignable_users: list[dict],
    inspect_start: date,
    inspect_end: date,
    inspect_cycle: int,
    inspect_frequency: str,
    inspect_count: int,
    time_window: str = "09:00-18:00",
    allow_cpsat: bool = True,
) -> list[SolverResult]:
    """生成多方案：A 启发式（尽早开工）、B CP-SAT（均衡优先）、C 启发式（按站点集中）。"""
    plans: list[SolverResult] = []

    plan_a = heuristic_plan(
        order_type=order_type,
        stations=stations,
        assignable_users=assignable_users,
        inspect_start=inspect_start,
        inspect_end=inspect_end,
        inspect_cycle=inspect_cycle,
        inspect_frequency=inspect_frequency,
        inspect_count=inspect_count,
        time_window=time_window,
        plan_id="A",
    )
    plan_a.detail["方案名"] = "方案A · 启发式尽早开工"
    plan_a.detail["策略说明"] = "优先按站点顺序铺开，人员轮转，尽快开工"
    plans.append(plan_a)

    if allow_cpsat and cpsat_available():
        plan_b = cpsat_plan(
            order_type=order_type,
            stations=stations,
            assignable_users=assignable_users,
            inspect_start=inspect_start,
            inspect_end=inspect_end,
            inspect_cycle=inspect_cycle,
            inspect_frequency=inspect_frequency,
            inspect_count=inspect_count,
            time_window=time_window,
            plan_id="B",
        )
        plan_b.detail["方案名"] = "方案B · CP-SAT 均衡优化"
        plan_b.detail["策略说明"] = "在硬约束下最小化工作量偏差与计划日期跨度"
        plans.append(plan_b)

    # 方案 C：按站点集中（同站点任务尽量连续、同一人执行）
    plan_c = heuristic_plan(
        order_type=order_type,
        stations=stations,
        assignable_users=assignable_users,
        inspect_start=inspect_start,
        inspect_end=inspect_end,
        inspect_cycle=inspect_cycle,
        inspect_frequency=inspect_frequency,
        inspect_count=inspect_count,
        time_window=time_window,
        plan_id="C",
    )
    if plan_c.subtasks and assignable_users:
        by_station: dict[str, list[dict]] = {}
        for s in plan_c.subtasks:
            by_station.setdefault(s["station_id"], []).append(s)
        counter = 0
        for idx, (station_id, items) in enumerate(by_station.items()):
            user = assignable_users[idx % len(assignable_users)]
            for item in items:
                item["assignee_id"] = user.get("id")
                item["assignee_name"] = user.get("real_name")
                counter += 1
                item["sequence"] = counter
        plan_c.detail["描述"] = "按站点集中：同一站点由固定人员连续执行，减少路途切换"
    plan_c.detail["方案名"] = "方案C · 站点集中作业"
    plan_c.detail["策略说明"] = "同一站点任务集中给同一人，降低往返成本"
    plan_c.plan_id = "C"
    plans.append(plan_c)

    for plan in plans:
        score_plan(
            plan,
            stations=stations,
            users=assignable_users,
            inspect_start=inspect_start,
            inspect_end=inspect_end,
        )
    return plans


def plan_to_dict(plan: SolverResult) -> dict:
    return {
        "plan_id": plan.plan_id,
        "name": plan.detail.get("方案名", f"方案{plan.plan_id}"),
        "strategy": plan.strategy,
        "feasible": plan.feasible,
        "score": plan.score,
        "penalty": plan.penalty,
        "subtask_count": len(plan.subtasks),
        "detail": plan.detail,
        "violations": plan.violations,
        "subtasks": plan.subtasks,
    }
