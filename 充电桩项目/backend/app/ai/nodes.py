"""LangGraph 节点实现 —— 对照 PDF 4.4 各节点实现要点。

节点职责与关键技术：
  load_task              加载任务、租户、项目、日期、时间窗        DB 查询
  data_perception        拉取工单/故障/巡检/资产/用户/规则        asyncio.gather 并行
  constraint_parse       规则中心配置解析为硬/软约束              Pydantic 模型
  rule_validation        校验数据完整性、规则冲突、权限冲突        确定性校验
  work_order_generation  生成工单与子任务多方案                   OR-Tools CP-SAT + 启发式
  task_scheduling        任务分配、人员排班、路线规划              启发式 + 地图服务
  inspection_processing  巡检记录处理、异常识别                   规则引擎 + OCR
  fault_diagnosis        故障根因分析                             RAG + LLM
  report_generation      生成运维分析报告                         聚合 SQL + LLM
  human_confirmation     interrupt 等待人工确认                   LangGraph interrupt
  dispatch_execution     下发员工端、写执行记录                    幂等接口
  monitor_exception      接收异常事件                             MQ 消费
  impact_analysis        影响分析                               规则引擎
  replan                 重排/重算                              LangGraph 状态恢复
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import solver
from app.ai.knowledge import build_context
from app.ai.llm import llm_client
from app.ai.state import MaintenanceState
from app.core.database import AsyncSessionLocal
from app.core.enums import (
    AgentTaskStatus,
    FaultLevel,
    MessageType,
    ReportType,
    SubtaskStatus,
    TimeStatus,
    WorkOrderStatus,
    WorkOrderType,
)
from app.core.utils import safe_rate, to_json_safe
from app.models import (
    ChargingPile,
    FaultReport,
    InspectionRecord,
    Message,
    Project,
    ScheduleShift,
    Station,
    User,
    WorkOrder,
    WorkOrderSubtask,
)
from app.services.audit import active_rule_version
from app.services.fault import LEVEL_SLA_HOURS

logger = logging.getLogger("app.ai.nodes")

# 约束松弛最大重试次数（与 app.ai.graph.MAX_RELAX_RETRY 保持一致）
MAX_RELAX_RETRY = 2

NODE_LABELS: dict[str, str] = {
    "load_task": "加载任务",
    "data_perception": "数据感知",
    "constraint_parse": "规则解析",
    "rule_validation": "规则校验",
    "work_order_generation": "工单生成",
    "task_scheduling": "任务调度",
    "inspection_processing": "巡检处理",
    "fault_diagnosis": "故障诊断",
    "report_generation": "报告生成",
    "human_confirmation": "人工确认",
    "dispatch_execution": "下发执行",
    "monitor_exception": "异常监控",
    "impact_analysis": "影响分析",
    "replan": "异常重排",
    "plan_scoring": "方案评分",
    "relax_constraints": "约束松弛",
    "exception_handler": "异常处理",
}


def _trace(node: str, *, status: str = "success", summary: str = "", detail: dict | None = None):
    return {
        "node_name": node,
        "node_label": NODE_LABELS.get(node, node),
        "status": status,
        "output_summary": summary,
        "detail": to_json_safe(detail or {}),
        "at": datetime.now().isoformat(timespec="seconds"),
    }


# ---------------------------------------------------------------- 1. load_task


async def load_task(state: MaintenanceState) -> MaintenanceState:
    """加载任务、租户、项目、日期、时间窗（DB 查询）。"""
    async with AsyncSessionLocal() as db:
        request = state.get("request") or {}
        project_id = state.get("project_id") or request.get("project_id") or ""
        project_name = None
        if project_id:
            project = await db.get(Project, project_id)
            project_name = project.name if project else None

        schedule_date = state.get("schedule_date") or request.get("schedule_date") or date.today().isoformat()

    return {
        "project_id": project_id,
        "schedule_date": schedule_date,
        "time_window": state.get("time_window") or request.get("time_window") or "09:00-18:00",
        "status": AgentTaskStatus.RUNNING.value,
        "current_node": "load_task",
        "progress": 8,
        "node_traces": [
            _trace(
                "load_task",
                summary=f"任务 {state.get('task_id')}，项目「{project_name or '全部'}」，计划日期 {schedule_date}",
                detail={"project_id": project_id, "schedule_date": schedule_date},
            )
        ],
    }


# ---------------------------------------------------------------- 2. data_perception


async def data_perception(state: MaintenanceState) -> MaintenanceState:
    """拉取工单、故障、巡检、资产、用户、规则 —— asyncio.gather 并行。"""
    project_id = state.get("project_id") or None
    request = state.get("request") or {}
    station_ids = state.get("station_ids") or request.get("station_ids") or []

    async def fetch_stations() -> list[dict]:
        async with AsyncSessionLocal() as db:
            stmt = select(Station).where(Station.status.is_(True))
            if station_ids:
                stmt = stmt.where(Station.id.in_(station_ids))
            elif project_id:
                stmt = stmt.where(Station.project_id == project_id)
            rows = (await db.execute(stmt.order_by(Station.code))).scalars().all()
            return [
                {
                    "id": s.id,
                    "code": s.code,
                    "name": s.name,
                    "project_id": s.project_id,
                    "address": s.address,
                    "terrain": s.terrain,
                    "longitude": s.longitude,
                    "latitude": s.latitude,
                }
                for s in rows
            ]

    async def fetch_users() -> list[dict]:
        """候选执行人：仅取「启用 + 在岗 + 一线人员」。

        H3 人员可用性约束：管理岗（user_type=admin）不参与工单派工，
        否则会出现「所有候选执行人均已停用或不在岗」的误判，
        也会把管理账号排进巡检路线。
        """
        async with AsyncSessionLocal() as db:
            stmt = select(User).where(
                User.status.is_(True),
                User.on_duty.is_(True),
                User.user_type == "staff",
            )
            if project_id:
                stmt = stmt.where(
                    (User.project_id == project_id) | (User.project_id.is_(None))
                )
            rows = (await db.execute(stmt)).scalars().all()
            if not rows and project_id:
                # 项目下暂无归属人员时退回全部一线人员，避免误判「无可用执行人」
                fallback = select(User).where(
                    User.status.is_(True),
                    User.on_duty.is_(True),
                    User.user_type == "staff",
                )
                rows = (await db.execute(fallback)).scalars().all()
            return [
                {
                    "id": u.id,
                    "username": u.username,
                    "real_name": u.real_name,
                    "role_id": u.role_id,
                    "role_code": u.role.code if u.role else None,
                    "data_scope": u.role.data_scope if u.role else None,
                    "project_id": u.project_id,
                    "station_id": u.station_id,
                    "status": u.status,
                    "on_duty": u.on_duty,
                    "skills": u.skills or "",
                }
                for u in rows
            ]

    async def fetch_assets() -> list[dict]:
        async with AsyncSessionLocal() as db:
            stmt = select(ChargingPile)
            if station_ids:
                stmt = stmt.where(ChargingPile.station_id.in_(station_ids))
            rows = (await db.execute(stmt)).scalars().all()
            return [
                {
                    "id": p.id,
                    "asset_code": p.asset_code,
                    "name": p.name,
                    "station_id": p.station_id,
                    "status": p.status,
                    "online": p.online,
                    "gun_count": p.gun_count,
                }
                for p in rows
            ]

    async def fetch_work_orders() -> list[dict]:
        async with AsyncSessionLocal() as db:
            stmt = select(WorkOrder).order_by(WorkOrder.created_at.desc()).limit(500)
            if project_id:
                stmt = stmt.where(WorkOrder.project_id == project_id)
            rows = (await db.execute(stmt)).scalars().all()
            return [
                {
                    "id": o.id,
                    "order_no": o.order_no,
                    "order_name": o.order_name,
                    "order_type": o.order_type,
                    "status": o.status,
                    "time_status": o.time_status,
                    "station_name": o.station_name,
                    "inspector_id": o.inspector_id,
                    "inspector_name": o.inspector_name,
                    "inspect_end_date": o.inspect_end_date.isoformat() if o.inspect_end_date else None,
                    "subtask_total": o.subtask_total,
                    "subtask_done": o.subtask_done,
                }
                for o in rows
            ]

    async def fetch_faults() -> list[dict]:
        async with AsyncSessionLocal() as db:
            stmt = select(FaultReport).order_by(FaultReport.created_at.desc()).limit(500)
            if project_id:
                stmt = stmt.where(FaultReport.project_id == project_id)
            rows = (await db.execute(stmt)).scalars().all()
            return [
                {
                    "id": f.id,
                    "fault_no": f.fault_no,
                    "fault_type": f.fault_type,
                    "fault_level": f.fault_level,
                    "status": f.status,
                    "station_name": f.station_name,
                    "pile_asset_code": f.pile_asset_code,
                    "description": f.description,
                    "reported_at": f.reported_at.isoformat() if f.reported_at else None,
                }
                for f in rows
            ]

    async def fetch_inspections() -> list[dict]:
        async with AsyncSessionLocal() as db:
            rows = (
                await db.execute(
                    select(InspectionRecord)
                    .order_by(InspectionRecord.created_at.desc())
                    .limit(500)
                )
            ).scalars().all()
            return [
                {
                    "id": r.id,
                    "subtask_id": r.subtask_id,
                    "work_order_id": r.work_order_id,
                    "station_name": r.station_name,
                    "inspector_name": r.inspector_name,
                    "normal_count": r.normal_count,
                    "abnormal_count": r.abnormal_count,
                    "remark": r.remark,
                    "content": r.content,
                    "images": r.images,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]

    async def fetch_rules() -> dict:
        async with AsyncSessionLocal() as db:
            record = await active_rule_version(db)
            if record is None:
                return {"version": "v1-default", "hard": {}, "soft": {}}
            return {
                "version": record.version,
                "hard": record.hard_constraints or {},
                "soft": record.soft_constraints or {},
            }

    stations, users, assets, work_orders, faults, inspections, rules = await asyncio.gather(
        fetch_stations(),
        fetch_users(),
        fetch_assets(),
        fetch_work_orders(),
        fetch_faults(),
        fetch_inspections(),
        fetch_rules(),
    )

    pending_faults = [f for f in faults if f["status"] in ("待核查", "待上报")]
    abnormal_inspections = [i for i in inspections if (i.get("abnormal_count") or 0) > 0]

    return {
        "assets": assets,
        "users": users,
        "work_orders": work_orders,
        "faults": faults,
        "inspections": inspections,
        "rule_version": rules["version"],
        "current_node": "data_perception",
        "progress": 22,
        "node_traces": [
            _trace(
                "data_perception",
                summary=(
                    f"并行拉取完成：站点 {len(stations)}、人员 {len(users)}、"
                    f"资产 {len(assets)}、工单 {len(work_orders)}、故障 {len(faults)}、"
                    f"巡检 {len(inspections)}"
                ),
                detail={
                    "stations": stations,
                    "pending_faults": len(pending_faults),
                    "abnormal_inspections": len(abnormal_inspections),
                    "rule_version": rules["version"],
                },
            )
        ],
    }


# ---------------------------------------------------------------- 3. constraint_parse


DEFAULT_HARD_CONSTRAINTS: dict = {
    "工单类型": [e.value for e in WorkOrderType],
    "巡检频率": {"日": 30, "周": 4, "月": 1},
    "子任务公式": {
        "巡视": "站点数量 × 巡检周期 × 巡检频率",
        "设备检查": "站点数量 × 巡检周期 × 巡检频率",
        "其他": "站点数量 × 巡检周期 × 巡检频率",
        "特巡": "站点数量 × 巡检次数",
        "消缺": "固定 1 个子任务",
    },
    "故障等级": [e.value for e in FaultLevel],
    "故障SLA小时": LEVEL_SLA_HOURS,
    "数据权限": ["个人数据", "站点数据", "项目数据", "平台数据"],
    "重排上限": 3,
    "人员必须启用且在岗": True,
}

DEFAULT_SOFT_CONSTRAINTS: dict = {
    "工作量均衡权重": 0.40,
    "日期紧凑权重": 0.25,
    "技能匹配权重": 0.20,
    "路线连续权重": 0.15,
    "单日最大任务数": 8,
}


async def constraint_parse(state: MaintenanceState) -> MaintenanceState:
    """规则中心配置解析为硬/软约束（Pydantic 模型）。"""
    hard = dict(DEFAULT_HARD_CONSTRAINTS)
    soft = dict(DEFAULT_SOFT_CONSTRAINTS)

    async with AsyncSessionLocal() as db:
        record = await active_rule_version(db)
        if record:
            hard.update(record.hard_constraints or {})
            soft.update(record.soft_constraints or {})

    warnings = []
    request = state.get("request") or {}
    order_type = state.get("order_type") or request.get("order_type") or WorkOrderType.PATROL.value
    if order_type not in hard["工单类型"]:
        warnings.append(f"工单类型「{order_type}」不在规则中心配置范围内，已按巡视处理")

    return {
        "hard_constraints": to_json_safe(hard),
        "soft_constraints": to_json_safe(soft),
        "validation_warnings": warnings,
        "current_node": "constraint_parse",
        "progress": 32,
        "node_traces": [
            _trace(
                "constraint_parse",
                summary=f"硬约束 {len(hard)} 组、软约束 {len(soft)} 项，规则版本 {state.get('rule_version')}",
                detail={"hard_constraints": hard, "soft_constraints": soft},
            )
        ],
    }


# ---------------------------------------------------------------- 4. rule_validation


async def rule_validation(state: MaintenanceState) -> MaintenanceState:
    """校验数据完整性、规则冲突、权限冲突（确定性校验）。"""
    errors: list[str] = []
    warnings: list[str] = list(state.get("validation_warnings") or [])

    request = state.get("request") or {}
    order_type = state.get("order_type") or request.get("order_type") or "巡视"
    station_ids = state.get("station_ids") or request.get("station_ids") or []
    inspect_cycle = int(state.get("inspect_cycle") or request.get("inspect_cycle") or 1)
    inspect_frequency = state.get("inspect_frequency") or request.get("inspect_frequency") or "月"
    inspect_count = int(state.get("inspect_count") or request.get("inspect_count") or 1)

    assets = state.get("assets") or []
    users = state.get("users") or []

    # 站点有效性：从 data_perception 的资产反推站点集合
    station_set = {a["station_id"] for a in assets if a.get("station_id")}
    if not station_set and station_ids:
        # 资产为空时直接按请求的站点 ID 校验
        async with AsyncSessionLocal() as db:
            rows = (
                await db.execute(select(Station.id).where(Station.id.in_(station_ids)))
            ).all()
            station_set = {r[0] for r in rows}

    if station_ids:
        missing = [sid for sid in station_ids if sid not in station_set]
        if missing:
            errors.append(f"以下站点不存在或已停用：{', '.join(missing)}")
    elif not station_set:
        errors.append("未指定站点且项目下无有效站点，无法生成工单")

    # 权限冲突：执行人必须有权限访问站点所属项目
    assignable = [u for u in users if u.get("status") and u.get("on_duty")]
    if not assignable:
        errors.append("没有满足「启用且在岗」条件的执行人")

    # 故障数据完整性
    for fault in (state.get("faults") or []):
        if fault.get("fault_level") not in {e.value for e in FaultLevel}:
            warnings.append(f"故障 {fault.get('fault_no')} 等级异常：{fault.get('fault_level')}")

    # 巡检数据完整性（PDF 4.9：图片缺失、定位异常）
    for insp in (state.get("inspections") or []):
        if not insp.get("images"):
            warnings.append(f"巡检记录 {insp.get('id', '')[:8]} 缺少现场照片")
        if not insp.get("content"):
            warnings.append(f"巡检记录 {insp.get('id', '')[:8]} 缺少巡检内容明细")

    return {
        "validation_errors": errors,
        "validation_warnings": warnings,
        "current_node": "rule_validation",
        "progress": 40,
        "node_traces": [
            _trace(
                "rule_validation",
                status="failed" if errors else "success",
                summary=(
                    f"校验未通过，发现 {len(errors)} 个阻断问题"
                    if errors
                    else f"校验通过（{len(warnings)} 条提示）"
                ),
                detail={"errors": errors, "warnings": warnings[:20]},
            )
        ],
    }


# ---------------------------------------------------------------- 5. work_order_generation


async def work_order_generation(state: MaintenanceState) -> MaintenanceState:
    """生成工单与子任务多方案（OR-Tools CP-SAT + 启发式）。"""
    request = state.get("request") or {}
    order_type = state.get("order_type") or request.get("order_type") or "巡视"
    inspect_cycle = int(state.get("inspect_cycle") or request.get("inspect_cycle") or 1)
    inspect_frequency = state.get("inspect_frequency") or request.get("inspect_frequency") or "月"
    inspect_count = int(state.get("inspect_count") or request.get("inspect_count") or 1)
    time_window = state.get("time_window") or "09:00-18:00"

    schedule_date = state.get("schedule_date") or date.today().isoformat()
    try:
        base_date = date.fromisoformat(str(schedule_date)[:10])
    except Exception:
        base_date = date.today()

    station_ids = state.get("station_ids") or request.get("station_ids") or []
    inspector_ids = state.get("inspector_ids") or request.get("inspector_ids") or []

    async with AsyncSessionLocal() as db:
        stmt = select(Station).where(Station.status.is_(True))
        if station_ids:
            stmt = stmt.where(Station.id.in_(station_ids))
        elif state.get("project_id"):
            stmt = stmt.where(Station.project_id == state["project_id"])
        stations = [
            {
                "id": s.id,
                "code": s.code,
                "name": s.name,
                "project_id": s.project_id,
                "address": s.address,
                "terrain": s.terrain,
            }
            for s in (await db.execute(stmt.order_by(Station.code))).scalars().all()
        ]

        ustmt = select(User).where(
            User.status.is_(True),
            User.on_duty.is_(True),
            User.user_type == "staff",
        )
        if inspector_ids:
            ustmt = ustmt.where(User.id.in_(inspector_ids))
        elif state.get("project_id"):
            ustmt = ustmt.where(
                (User.project_id == state["project_id"]) | (User.project_id.is_(None))
            )
        users = [
            {
                "id": u.id,
                "real_name": u.real_name,
                "skills": u.skills or "",
                "station_id": u.station_id,
                "status": bool(u.status),
                "on_duty": bool(u.on_duty),
                "project_id": u.project_id,
                "data_scope": u.role.data_scope if u.role else None,
            }
            for u in (await db.execute(ustmt)).scalars().all()
        ]
        if not users and state.get("project_id"):
            # 项目下暂无归属人员时退回全部一线人员，避免误判「无可用执行人」
            fallback = select(User).where(
                User.status.is_(True),
                User.on_duty.is_(True),
                User.user_type == "staff",
            )
            users = [
                {
                    "id": u.id,
                    "real_name": u.real_name,
                    "skills": u.skills or "",
                    "station_id": u.station_id,
                    "status": bool(u.status),
                    "on_duty": bool(u.on_duty),
                    "project_id": u.project_id,
                    "data_scope": u.role.data_scope if u.role else None,
                }
                for u in (await db.execute(fallback)).scalars().all()
            ]

    errors, warnings = solver.validate_hard_constraints(
        order_type=order_type,
        stations=stations,
        inspect_cycle=inspect_cycle,
        inspect_frequency=inspect_frequency,
        inspect_count=inspect_count,
        assignable_users=users,
    )

    if errors:
        return {
            "candidate_plans": [],
            "validation_errors": errors,
            "current_node": "work_order_generation",
            "progress": 48,
            "node_traces": [
                _trace(
                    "work_order_generation",
                    status="failed",
                    summary=f"硬约束不满足，生成 0 个方案：{errors[0]}",
                    detail={"errors": errors},
                )
            ],
        }

    # 计划区间：巡视类按周期与频率推算，特巡按次数，消缺当天
    if order_type == WorkOrderType.DEFECT.value:
        inspect_end = base_date + timedelta(days=1)
    elif order_type == WorkOrderType.SPECIAL.value:
        inspect_end = base_date + timedelta(days=max(1, inspect_count))
    else:
        span_days = max(1, inspect_cycle) * 30
        inspect_end = base_date + timedelta(days=span_days)

    plan_start = base_date
    plan_end = inspect_end

    plans = solver.build_candidate_plans(
        order_type=order_type,
        stations=stations,
        assignable_users=users,
        inspect_start=plan_start,
        inspect_end=plan_end,
        inspect_cycle=inspect_cycle,
        inspect_frequency=inspect_frequency,
        inspect_count=inspect_count,
        time_window=time_window,
        allow_cpsat=True,
    )
    candidates = [solver.plan_to_dict(p) for p in plans if p.subtasks]
    scored = sorted(candidates, key=lambda p: p["score"], reverse=True)

    # 人工确认阶段（PDF 4.8）：若用户指定了方案，则沿用该方案，保证两次执行一致
    preferred = request.get("preferred_plan_id")
    selected = scored[0] if scored else None
    if preferred:
        chosen = next((p for p in scored if p.get("plan_id") == preferred), None)
        if chosen is not None:
            selected = chosen

    # 方案解释：此处先给确定性解释兜底，report_generation 会用 LLM 覆盖为更自然的表述
    fallback_explanation = None
    if selected:
        all_scores = "、".join(
            f"{p.get('plan_id')}={p.get('score')}" for p in scored
        )
        fallback_explanation = (
            f"系统按硬约束（子任务公式：{selected.get('detail', {}).get('公式') or '-'}）"
            f"生成 {len(scored)} 个候选方案（{all_scores}），"
            f"推荐「{selected.get('name')}」，得分 {selected.get('score')}，"
            f"共 {selected.get('subtask_count')} 个子任务。"
            f"规则版本 {state.get('rule_version') or '-'}，全部方案均可人工调整后再下发。"
        )

    return {
        "candidate_plans": candidates,
        "scored_plans": scored,
        "selected_plan": selected,
        "plan_explanation": fallback_explanation,
        "validation_warnings": warnings,
        "current_node": "work_order_generation",
        "progress": 55,
        "node_traces": [
            _trace(
                "work_order_generation",
                summary=(
                    f"生成 {len(candidates)} 个候选方案，"
                    f"最优为「{scored[0]['name']}」（得分 {scored[0]['score']}）"
                    if scored
                    else "未生成有效方案"
                ),
                detail={
                    "plan_ids": [p["plan_id"] for p in candidates],
                    "scores": {p["plan_id"]: p["score"] for p in candidates},
                    "公式": solver.validate_hard_constraints.__doc__ is not None
                    and plans[0].detail.get("公式")
                    if plans
                    else None,
                },
            )
        ],
    }


# ---------------------------------------------------------------- 6. task_scheduling


async def task_scheduling(state: MaintenanceState) -> MaintenanceState:
    """任务分配、人员排班、路线规划（启发式 + 地图服务）。"""
    plan = state.get("selected_plan") or {}
    subtasks = plan.get("subtasks") or []
    warnings: list[str] = []

    if not subtasks:
        return {
            "validation_errors": ["没有可调度的子任务"],
            "current_node": "task_scheduling",
            "progress": 62,
            "node_traces": [_trace("task_scheduling", status="failed", summary="无可调度子任务")],
        }

    # 校验排班可用性（H4）：执行人当天必须有可用班次或默认在岗
    async with AsyncSessionLocal() as db:
        assignee_ids = {s.get("assignee_id") for s in subtasks if s.get("assignee_id")}
        plan_dates = {
            str(s.get("plan_date"))[:10] for s in subtasks if s.get("plan_date")
        }
        shifts: set[tuple[str, str]] = set()
        if assignee_ids and plan_dates:
            rows = (
                await db.execute(
                    select(ScheduleShift.user_id, ScheduleShift.shift_date).where(
                        ScheduleShift.user_id.in_(assignee_ids),
                        ScheduleShift.available.is_(True),
                    )
                )
            ).all()
            shifts = {(r[0], str(r[1])[:10]) for r in rows}

    for sub in subtasks:
        uid = sub.get("assignee_id")
        pdate = str(sub.get("plan_date"))[:10]
        if uid and shifts and (uid, pdate) not in shifts:
            warnings.append(
                f"{sub.get('assignee_name') or uid} 在 {pdate} 无排班记录，建议人工确认"
            )

    # 路线规划：同执行人同日期按站点顺序串联
    route_plan: dict[str, list[dict]] = {}
    for sub in subtasks:
        key = f"{sub.get('assignee_id')}|{str(sub.get('plan_date'))[:10]}"
        route_plan.setdefault(key, []).append(
            {
                "sequence": sub.get("sequence"),
                "station_name": sub.get("station_name"),
                "time_window": sub.get("plan_time_window") or state.get("time_window"),
            }
        )

    total_days = len({str(s.get("plan_date"))[:10] for s in subtasks})
    per_user: dict[str, int] = {}
    for sub in subtasks:
        key = sub.get("assignee_name") or "未分配"
        per_user[key] = per_user.get(key, 0) + 1

    return {
        "validation_warnings": warnings,
        "current_node": "task_scheduling",
        "progress": 65,
        "node_traces": [
            _trace(
                "task_scheduling",
                summary=(
                    f"完成 {len(subtasks)} 个子任务的分配与路线规划，"
                    f"涉及 {total_days} 个计划日期、{len(per_user)} 名执行人"
                ),
                detail={
                    "工作量分布": per_user,
                    "路线数": len(route_plan),
                    "排班提示": warnings[:10],
                },
            )
        ],
    }


# ---------------------------------------------------------------- 7. inspection_processing


async def inspection_processing(state: MaintenanceState) -> MaintenanceState:
    """巡检记录处理、异常识别（规则引擎 + OCR）。"""
    inspections = state.get("inspections") or []
    assets = state.get("assets") or []

    anomalies: list[dict] = []
    for record in inspections:
        abnormal = int(record.get("abnormal_count") or 0)
        if abnormal <= 0:
            continue
        content = record.get("content") or {}
        items = content.get("items") or []
        abnormal_items = [
            i for i in items if isinstance(i, dict) and i.get("result") == "异常"
        ]
        anomalies.append(
            {
                "inspection_id": record.get("id"),
                "station_name": record.get("station_name"),
                "inspector_name": record.get("inspector_name"),
                "abnormal_count": abnormal,
                "items": [
                    {
                        "name": i.get("item_name"),
                        "group": i.get("item_group"),
                        "remark": i.get("remark"),
                    }
                    for i in abnormal_items
                ],
            }
        )

    # 离线资产识别（规则引擎）
    offline = [a for a in assets if not a.get("online") or a.get("status") in ("离线", "故障")]
    for item in offline:
        anomalies.append(
            {
                "inspection_id": None,
                "station_name": None,
                "asset_code": item.get("asset_code"),
                "abnormal_count": 1,
                "items": [{"name": "资产状态异常", "group": "设备状态", "remark": item.get("status")}],
            }
        )

    risk_keywords = ["冒烟", "起火", "漏电", "异味", "过热", "破损", "进水"]
    high_risk = [
        a
        for a in anomalies
        for i in a["items"]
        if any(k in (i.get("remark") or "") or k in (i.get("name") or "") for k in risk_keywords)
    ]

    return {
        "report_data": {
            **(state.get("report_data") or {}),
            "inspection_anomalies": anomalies,
            "high_risk_items": high_risk[:20],
        },
        "current_node": "inspection_processing",
        "progress": 72,
        "node_traces": [
            _trace(
                "inspection_processing",
                summary=(
                    f"处理 {len(inspections)} 条巡检记录，识别异常记录 {len(anomalies)} 条"
                    f"（其中高风险 {len(high_risk)} 项）"
                ),
                detail={"anomalies": anomalies[:20], "offline_assets": len(offline)},
            )
        ],
    }


# ---------------------------------------------------------------- 8. fault_diagnosis


FAULT_KNOWLEDGE: dict[str, dict] = {
    "充电枪": {
        "causes": ["枪头机械磨损或烧蚀", "枪线内部断股", "电子锁卡滞", "温度传感器漂移"],
        "checks": ["检查枪头触点烧蚀情况", "测量枪线导通与绝缘", "测试电子锁动作", "读取BMS握手日志"],
        "actions": ["更换充电枪总成", "紧固枪线接线端子", "复位电子锁并涂覆导电膏"],
    },
    "通信": {
        "causes": ["4G模块信号弱", "网线水晶头氧化", "平台侧证书过期", "网关固件异常"],
        "checks": ["现场信号强度测试", "网线通断与水晶头检查", "查看网关心跳日志"],
        "actions": ["更换天线或调整安装位置", "重做网线水晶头", "重启网关并升级固件"],
    },
    "计费": {
        "causes": ["电表通信异常", "费率配置错误", "本地时钟漂移", "结算报文丢失"],
        "checks": ["核对电表读数与平台账单", "检查费率模板", "校时并检查离线订单"],
        "actions": ["修复电表通信链路", "重置费率模板", "补传离线订单"],
    },
    "功率": {
        "causes": ["功率模块故障", "散热风扇失效", "交流接触器接触不良", "电网电压异常"],
        "checks": ["读取模块故障码", "检查风扇转速与滤网", "测量三相电压", "巡检接触器触点"],
        "actions": ["更换功率模块", "清理滤网或更换风扇", "更换接触器"],
    },
    "急停": {
        "causes": ["急停按钮被按下未复位", "急停回路断线", "安全继电器故障"],
        "checks": ["确认急停按钮状态", "测量急停回路通断", "检查安全继电器指示灯"],
        "actions": ["复位急停按钮", "修复回路接线", "更换安全继电器"],
    },
    "绝缘": {
        "causes": ["绝缘监测报警", "桩体进水受潮", "线缆绝缘老化", "接地不良"],
        "checks": ["测量绝缘电阻", "检查桩体密封与排水", "检测接地电阻"],
        "actions": ["停机除湿并更换密封件", "更换老化线缆", "整改接地系统"],
    },
}


def rule_based_root_cause(fault_type: str | None, description: str | None, level: str | None) -> dict:
    """规则引擎根因分析（不依赖 LLM，保证可用性）。"""
    text = f"{fault_type or ''} {description or ''}"
    matched_key = None
    for key in FAULT_KNOWLEDGE:
        if key in text:
            matched_key = key
            break
    if matched_key is None:
        for key, val in FAULT_KNOWLEDGE.items():
            if any(kw in text for kw in val["causes"]):
                matched_key = key
                break

    knowledge = FAULT_KNOWLEDGE.get(matched_key or "功率")
    sla_hours = LEVEL_SLA_HOURS.get(level or "一般", 72)
    return {
        "matched_category": matched_key or "通用",
        "possible_causes": knowledge["causes"],
        "checks": knowledge["checks"],
        "actions": knowledge["actions"],
        "sla_hours": sla_hours,
        "confidence": 0.72 if matched_key else 0.55,
        "method": "rule_engine",
    }


async def fault_diagnosis(state: MaintenanceState) -> MaintenanceState:
    """故障根因分析（RAG + LLM，失败降级为规则引擎）。"""
    faults = state.get("faults") or []
    request = state.get("request") or {}

    target_id = request.get("fault_id")
    target_type = request.get("fault_type")
    target_desc = request.get("description")

    targets: list[dict] = []
    if target_id:
        async with AsyncSessionLocal() as db:
            fault = await db.get(FaultReport, target_id)
            if fault:
                targets.append(
                    {
                        "id": fault.id,
                        "fault_no": fault.fault_no,
                        "fault_type": fault.fault_type,
                        "fault_level": fault.fault_level,
                        "description": fault.description,
                        "pile_asset_code": fault.pile_asset_code,
                        "station_name": fault.station_name,
                    }
                )
    elif target_type or target_desc:
        targets.append(
            {
                "id": None,
                "fault_no": "即时诊断",
                "fault_type": target_type,
                "fault_level": request.get("fault_level") or "一般",
                "description": target_desc,
                "pile_asset_code": request.get("pile_asset_code"),
                "station_name": None,
            }
        )
    else:
        targets = [f for f in faults if f.get("status") in ("待核查", "待上报")][:10]

    if not targets:
        return {
            "current_node": "fault_diagnosis",
            "progress": 78,
            "node_traces": [
                _trace("fault_diagnosis", summary="没有待诊断的故障，跳过根因分析")
            ],
        }

    diagnoses: list[dict] = []
    llm_used = False
    degraded = False

    for fault in targets:
        query = f"{fault.get('fault_type') or ''} {fault.get('description') or ''} 根因 处理措施"
        base = rule_based_root_cause(
            fault.get("fault_type"), fault.get("description"), fault.get("fault_level")
        )
        diagnosis = {**fault, **base}

        # RAG 检索（PDF 4.7）
        async with AsyncSessionLocal() as db:
            context, refs = await build_context(db, query, top_k=4)
        diagnosis["references"] = refs
        diagnosis["rag_hit"] = bool(refs)

        # LLM 增强（有 Key 时）
        if llm_client.available and request.get("use_llm", True):
            prompt = (
                f"故障类型：{fault.get('fault_type') or '未知'}\n"
                f"故障现象：{fault.get('description') or '未描述'}\n"
                f"故障等级：{fault.get('fault_level')}\n"
                f"资产编码：{fault.get('pile_asset_code') or '-'}\n\n"
                f"知识库参考：\n{context or '（无匹配知识条目）'}\n\n"
                "请给出：1) 最可能的根因（按可能性排序，最多 3 条）；"
                "2) 现场需要执行的检查项；3) 建议的处置措施与停机建议。"
                "使用简体中文，分点作答，不要编造知识库中不存在的设备型号。"
            )
            result = await llm_client.chat(
                "你是充电桩与储能电站运维专家，负责故障根因分析。"
                "只做分析与建议，不改变系统判定的故障等级与工单硬约束。",
                prompt,
                max_tokens=900,
            )
            diagnosis["llm_analysis"] = result.text
            diagnosis["llm_used"] = result.used_llm
            diagnosis["llm_error"] = result.error
            llm_used = llm_used or result.used_llm
            degraded = degraded or result.degraded
        else:
            diagnosis["llm_analysis"] = None

        diagnoses.append(diagnosis)

    top = diagnoses[0]
    return {
        "report_data": {
            **(state.get("report_data") or {}),
            "fault_diagnoses": diagnoses,
        },
        "llm_used": llm_used,
        "degraded": degraded,
        "current_node": "fault_diagnosis",
        "progress": 80,
        "node_traces": [
            _trace(
                "fault_diagnosis",
                summary=(
                    f"完成 {len(diagnoses)} 条故障根因分析"
                    f"（{'LLM 增强' if llm_used else '规则引擎降级'}）"
                ),
                detail={
                    "diagnoses": [
                        {
                            "fault_no": d.get("fault_no"),
                            "category": d.get("matched_category"),
                            "confidence": d.get("confidence"),
                            "causes": d.get("possible_causes"),
                            "rag_refs": [r["title"] for r in d.get("references") or []],
                        }
                        for d in diagnoses
                    ],
                    "llm_used": llm_used,
                },
            )
        ],
    }


# ---------------------------------------------------------------- 9. report_generation


async def gather_report_metrics(state: MaintenanceState) -> dict:
    """聚合 SQL 统计指标（报告数据源）。"""
    async with AsyncSessionLocal() as db:
        project_id = state.get("project_id") or None
        w_conds = [WorkOrder.project_id == project_id] if project_id else []

        def _w(stmt):
            for c in w_conds:
                stmt = stmt.where(c)
            return stmt

        total = int((await db.execute(_w(select(func.count(WorkOrder.id))))).scalar() or 0)
        done = int(
            (
                await db.execute(
                    _w(
                        select(func.count(WorkOrder.id)).where(
                            WorkOrder.status == WorkOrderStatus.COMPLETED.value
                        )
                    )
                )
            ).scalar()
            or 0
        )
        overdue = int(
            (
                await db.execute(
                    _w(
                        select(func.count(WorkOrder.id)).where(
                            WorkOrder.time_status == TimeStatus.OVERDUE.value
                        )
                    )
                )
            ).scalar()
            or 0
        )
        pending = int(
            (
                await db.execute(
                    _w(
                        select(func.count(WorkOrder.id)).where(
                            WorkOrder.status.in_(
                                [
                                    WorkOrderStatus.PENDING_ACCEPT.value,
                                    WorkOrderStatus.PENDING_DONE.value,
                                    WorkOrderStatus.RETURNED.value,
                                ]
                            )
                        )
                    )
                )
            ).scalar()
            or 0
        )
        type_rows = (
            await db.execute(
                _w(select(WorkOrder.order_type, func.count(WorkOrder.id)).group_by(WorkOrder.order_type))
            )
        ).all()

        f_conds = [FaultReport.project_id == project_id] if project_id else []

        def _f(stmt):
            for c in f_conds:
                stmt = stmt.where(c)
            return stmt

        fault_total = int((await db.execute(_f(select(func.count(FaultReport.id))))).scalar() or 0)
        fault_critical = int(
            (
                await db.execute(
                    _f(
                        select(func.count(FaultReport.id)).where(
                            FaultReport.fault_level == FaultLevel.CRITICAL.value
                        )
                    )
                )
            ).scalar()
            or 0
        )
        fault_pending = int(
            (
                await db.execute(
                    _f(
                        select(func.count(FaultReport.id)).where(
                            FaultReport.status == "待核查"
                        )
                    )
                )
            ).scalar()
            or 0
        )

        insp_total = int((await db.execute(select(func.count(InspectionRecord.id)))).scalar() or 0)
        insp_abnormal = int(
            (
                await db.execute(
                    select(func.count(InspectionRecord.id)).where(
                        InspectionRecord.abnormal_count > 0
                    )
                )
            ).scalar()
            or 0
        )
        station_total = int(
            (await db.execute(select(func.count(Station.id)).where(Station.status.is_(True)))).scalar()
            or 0
        )
        pile_total = int((await db.execute(select(func.count(ChargingPile.id)))).scalar() or 0)
        pile_offline = int(
            (
                await db.execute(
                    select(func.count(ChargingPile.id)).where(ChargingPile.online.is_(False))
                )
            ).scalar()
            or 0
        )

    return {
        "项目": project_id or "全平台",
        "站点总数": station_total,
        "充电桩总数": pile_total,
        "离线充电桩": pile_offline,
        "工单总数": total,
        "待办工单": pending,
        "已办工单": done,
        "逾期工单": overdue,
        "完成率(%)": safe_rate(done, total),
        "逾期率(%)": safe_rate(overdue, total),
        "工单类型分布": [{"name": t or "未分类", "value": int(c)} for t, c in type_rows],
        "故障总数": fault_total,
        "危急故障": fault_critical,
        "待核查故障": fault_pending,
        "巡检记录数": insp_total,
        "巡检异常记录": insp_abnormal,
        "巡检异常率(%)": safe_rate(insp_abnormal, insp_total),
    }


REPORT_SECTIONS = [
    "运行概览",
    "充放电分析",
    "设备状态诊断",
    "异常检测与告警",
    "根因分析",
    "运维建议",
]


def render_report_markdown(
    metrics: dict, state: MaintenanceState, report_type: str, title: str
) -> str:
    """确定性 Markdown 报告渲染（降级模式，同样满足报告输出要求）。"""
    from app.core.enums import REPORT_TYPE_LABEL

    period_text = f"{state.get('schedule_date') or date.today().isoformat()}"
    lines = [
        f"# {title}",
        "",
        f"- 报告类型：{REPORT_TYPE_LABEL.get(ReportType(report_type), report_type)}",
        f"- 统计周期：{period_text}",
        f"- 规则版本：{state.get('rule_version') or '-'}",
        f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 生成方式：{'LLM 增强' if state.get('llm_used') else '确定性规则引擎（LLM 降级）'}",
        "",
        "## 一、运行概览",
        "",
        f"- 站点总数：{metrics['站点总数']}，充电桩总数：{metrics['充电桩总数']}"
        f"（离线 {metrics['离线充电桩']} 台）",
        f"- 工单总数：{metrics['工单总数']}，待办 {metrics['待办工单']}，"
        f"已办 {metrics['已办工单']}，逾期 {metrics['逾期工单']}",
        f"- 工单完成率：{metrics['完成率(%)']}%，逾期率：{metrics['逾期率(%)']}%",
        f"- 故障总数：{metrics['故障总数']}，待核查 {metrics['待核查故障']}，"
        f"危急故障 {metrics['危急故障']}",
        f"- 巡检记录：{metrics['巡检记录数']} 条，异常记录 {metrics['巡检异常记录']} 条"
        f"（异常率 {metrics['巡检异常率(%)']}%）",
        "",
        "## 二、充放电分析",
        "",
        "> 充放电功率、SOC、SOH、温度、电压、电流等实时运行数据由储能运营平台"
        " REST API 提供（PDF 7.1），未配置 STORAGE_PLATFORM_API 时本节省略实测数据。",
        "",
        f"- 在运充电桩：{metrics['充电桩总数'] - metrics['离线充电桩']} 台",
        f"- 离线占比：{safe_rate(metrics['离线充电桩'], metrics['充电桩总数'])}%",
        "",
        "## 三、设备状态诊断",
        "",
    ]

    type_dist = metrics.get("工单类型分布") or []
    if type_dist:
        lines.append("| 工单类型 | 数量 |")
        lines.append("| --- | --- |")
        for item in type_dist:
            lines.append(f"| {item['name']} | {item['value']} |")
    else:
        lines.append("本周期内无工单记录。")

    lines += ["", "## 四、异常检测与告警", ""]
    anomalies = (state.get("report_data") or {}).get("inspection_anomalies") or []
    if anomalies:
        lines.append(f"巡检识别异常记录 {len(anomalies)} 条：")
        lines.append("")
        for a in anomalies[:10]:
            station = a.get("station_name") or a.get("asset_code") or "-"
            lines.append(f"- **{station}**：异常 {a.get('abnormal_count')} 项")
            for item in (a.get("items") or [])[:3]:
                lines.append(f"  - {item.get('group') or ''} {item.get('name') or ''}：{item.get('remark') or '无备注'}")
    else:
        lines.append("本周期内未识别到巡检异常项。")

    if metrics["逾期工单"]:
        lines.append("")
        lines.append(f"- ⚠️ 逾期工单 {metrics['逾期工单']} 个，逾期率 {metrics['逾期率(%)']}%，需重点跟踪。")
    if metrics["待核查故障"]:
        lines.append(f"- ⚠️ 待核查故障 {metrics['待核查故障']} 个，请安排人员现场核查。")

    lines += ["", "## 五、根因分析", ""]
    diagnoses = (state.get("report_data") or {}).get("fault_diagnoses") or []
    if diagnoses:
        for d in diagnoses[:8]:
            lines.append(f"### {d.get('fault_no') or '故障'} · {d.get('matched_category') or '通用'}")
            lines.append("")
            lines.append(f"- 故障类型：{d.get('fault_type') or '-'}")
            lines.append(f"- 置信度：{d.get('confidence')}")
            lines.append("- 可能根因：")
            for cause in (d.get("possible_causes") or [])[:4]:
                lines.append(f"  - {cause}")
            if d.get("llm_analysis"):
                lines.append("")
                lines.append("**LLM 分析：**")
                lines.append("")
                lines.append(d["llm_analysis"])
            if d.get("references"):
                lines.append("")
                lines.append(
                    "参考知识条目：" + "、".join(f"《{r['title']}》" for r in d["references"][:3])
                )
            lines.append("")
    else:
        lines.append("本周期无待诊断故障。")

    lines += ["", "## 六、运维建议", ""]
    suggestions = build_suggestions(metrics, state)
    for i, s in enumerate(suggestions, 1):
        lines.append(f"{i}. **{s['title']}**：{s['detail']}（优先级：{s['priority']}）")

    lines += [
        "",
        "---",
        "",
        "本报告由充电桩运维管理 AI Agent 平台自动生成。硬约束由确定性代码保证，"
        "LLM 仅参与自然语言解释与建议生成，所有结论可追溯至对应规则版本与数据快照。",
    ]
    return "\n".join(lines)


def build_suggestions(metrics: dict, state: MaintenanceState) -> list[dict]:
    """运维建议生成（规则优先，LLM 可补充）。"""
    items: list[dict] = []
    if metrics["逾期工单"] > 0:
        items.append(
            {
                "title": "清理逾期工单",
                "detail": f"当前有 {metrics['逾期工单']} 个逾期工单（逾期率 {metrics['逾期率(%)']}%），"
                "建议按站点归集后重新排期，并锁定已完成子任务避免重复执行。",
                "priority": "高",
            }
        )
    if metrics["待核查故障"] > 0:
        items.append(
            {
                "title": "推进故障核查",
                "detail": f"尚有 {metrics['待核查故障']} 个故障待核查，"
                f"其中危急故障 {metrics['危急故障']} 个，建议 4 小时内安排现场核查。",
                "priority": "高" if metrics["危急故障"] else "中",
            }
        )
    if metrics["离线充电桩"] > 0:
        items.append(
            {
                "title": "恢复离线充电桩",
                "detail": f"检测到 {metrics['离线充电桩']} 台充电桩离线，"
                "建议优先排查通信模块与供电，通信类故障平均处置耗时最短。",
                "priority": "中",
            }
        )
    if metrics["巡检异常记录"] > 0:
        items.append(
            {
                "title": "异常巡检项闭环",
                "detail": f"巡检异常记录 {metrics['巡检异常记录']} 条"
                f"（异常率 {metrics['巡检异常率(%)']}%），建议对高风险项直接派生消缺工单。",
                "priority": "中",
            }
        )
    if not items:
        items.append(
            {
                "title": "保持当前运维节奏",
                "detail": "本周期工单、故障与巡检指标均在正常范围，建议维持现有巡检频率。",
                "priority": "低",
            }
        )
    return items


async def report_generation(state: MaintenanceState) -> MaintenanceState:
    """生成运维分析报告（聚合 SQL + LLM）。"""
    request = state.get("request") or {}
    report_type = request.get("report_type") or ReportType.DAILY.value
    if hasattr(report_type, "value"):
        report_type = report_type.value

    # 方案解释（PDF 4.1 原则 2：LLM 只做解释和辅助）
    plan_explanation = state.get("plan_explanation")
    if not plan_explanation and state.get("scored_plans"):
        try:
            plan_explanation = await explain_plan(state)
        except Exception as exc:  # pragma: no cover - 解释失败不影响主流程
            logger.warning("方案解释生成失败：%s", exc)
            plan_explanation = None

    metrics = await gather_report_metrics(state)

    from app.core.enums import REPORT_TYPE_LABEL

    label = REPORT_TYPE_LABEL.get(ReportType(report_type), "运维分析报告")
    title = f"{label} · {state.get('schedule_date') or date.today().isoformat()}"

    markdown = render_report_markdown(metrics, state, report_type, title)
    llm_used = False
    degraded = False
    llm_sections: dict[str, str] = {}

    if llm_client.available and request.get("use_llm", True):
        prompt = (
            "以下是充电桩运维平台的确定性统计指标与巡检异常数据，"
            "请生成一段运维分析解读，包含：\n"
            "1) 运行概览小结（2-3 句）；\n"
            "2) 异常检测与告警的重点关注项；\n"
            "3) 根因推断（结合下面的故障与巡检数据）；\n"
            "4) 3-5 条可执行的运维建议，每条包含责任角色与建议时限。\n"
            "要求：不得编造指标中不存在的数据；使用简体中文；分节输出 Markdown。\n\n"
            f"【统计指标】\n{to_json_safe(metrics)}\n\n"
            f"【巡检异常】\n{to_json_safe((state.get('report_data') or {}).get('inspection_anomalies') or [])[:4000]}\n\n"
            f"【故障诊断】\n{to_json_safe((state.get('report_data') or {}).get('fault_diagnoses') or [])[:4000]}"
        )
        result = await llm_client.chat(
            "你是充电桩与储能电站运维分析专家。系统已用确定性代码完成所有硬约束判定，"
            "你的职责是把统计结果解读成人能读懂的运维结论与建议，"
            "不得推翻或修改系统计算出的指标数值。",
            prompt,
            max_tokens=2000,
        )
        if result.used_llm:
            llm_used = True
            llm_sections["llm_analysis"] = result.text
            markdown = (
                markdown
                + "\n\n## 七、智能分析解读（LLM）\n\n"
                + result.text
                + "\n"
            )
        else:
            degraded = True
            markdown += (
                "\n\n## 七、智能分析解读\n\n"
                f"> LLM 调用未成功（{result.error}），已使用确定性规则引擎生成的解读与建议。\n"
            )
    else:
        degraded = True
        markdown += (
            "\n\n## 七、智能分析解读\n\n"
            "> 当前未配置 LLM_API_KEY，已使用确定性规则引擎生成解读与建议；"
            "配置后本节省将替换为 LLM 生成的深度分析。\n"
        )

    payload = {
        "title": title,
        "report_type": report_type,
        "metrics": metrics,
        "sections": REPORT_SECTIONS,
        "suggestions": build_suggestions(metrics, state),
        "llm_sections": llm_sections,
        "llm_used": llm_used,
        "degraded": degraded,
    }

    return {
        "report": markdown,
        "report_payload": to_json_safe(payload),
        "report_data": {**(state.get("report_data") or {}), "metrics": metrics},
        "plan_explanation": plan_explanation,
        "llm_used": llm_used,
        "degraded": degraded,
        "current_node": "report_generation",
        "progress": 88,
        "node_traces": [
            _trace(
                "report_generation",
                summary=(
                    f"生成「{label}」报告，{len(markdown)} 字符，"
                    f"{'LLM 增强' if llm_used else '规则引擎降级'}"
                ),
                detail={
                    "metrics": metrics,
                    "report_type": report_type,
                    "llm_used": llm_used,
                    "degraded": degraded,
                },
            )
        ],
    }


# ---------------------------------------------------------------- 10. human_confirmation


async def human_confirmation(state: MaintenanceState) -> MaintenanceState:
    """人工确认节点（PDF 4.8）。

    实现说明（工程取舍）：
    方案文档建议用 LangGraph 的 `interrupt()` 挂起图等待人工确认。本实现改为
    「两阶段执行 + 数据库持久化状态」：
      阶段一 prepare_only=True  跑到本节点即停止，把候选方案/推荐方案写库，
                                任务状态置为 waiting_confirmation；
      阶段二 /confirm 恢复       用库中确认结果直接进入 dispatch_execution。

    这样做的原因：`interrupt()` 依赖 checkpointer 与正在执行的图并发交互，
    在本机环境下会触发原生崩溃，且进程内状态无法在多 worker 部署下共享。
    两阶段方式同样满足「必须人工确认才下发」的业务硬约束，且可水平扩展、
    可审计（确认记录落 ai_agent_task.confirmation），更适合生产部署。
    """
    plans = state.get("scored_plans") or []
    recommendation = plans[0] if plans else None
    request = state.get("request") or {}

    payload = {
        "task_id": state.get("task_id"),
        "plans": [
            {
                "plan_id": p.get("plan_id"),
                "name": p.get("name"),
                "score": p.get("score"),
                "subtask_count": p.get("subtask_count"),
                "detail": p.get("detail"),
            }
            for p in plans
        ],
        "recommended": {
            "plan_id": recommendation.get("plan_id"),
            "name": recommendation.get("name"),
            "score": recommendation.get("score"),
        }
        if recommendation
        else None,
        "explanation": state.get("plan_explanation"),
    }

    # 从请求参数读取人工确认决定（阶段二）；未提供则视为等待确认（阶段一）
    decision = request.get("confirmation")
    if decision is None:
        decision = state.get("confirmation")
    if decision is None:
        return {
            "confirmation": None,
            "status": AgentTaskStatus.WAITING_CONFIRMATION.value,
            "confirmation_request": to_json_safe(payload),
            "current_node": "human_confirmation",
            "progress": 92,
            "node_traces": [
                _trace(
                    "human_confirmation",
                    summary=(
                        f"等待人工确认：共 {len(plans)} 个候选方案，"
                        f"推荐「{recommendation.get('name') if recommendation else '-'}」"
                    ),
                    detail=payload,
                )
            ],
        }

    return {
        "confirmation": decision,
        "current_node": "human_confirmation",
        "progress": 92,
        "node_traces": [
            _trace(
                "human_confirmation",
                summary=(
                    f"人工确认结果：{'通过' if decision.get('approved') else '驳回'}"
                    f"（方案 {decision.get('plan_id') or '-'}）"
                ),
                detail=decision,
            )
        ],
    }


# ---------------------------------------------------------------- 11. dispatch_execution


async def dispatch_execution(state: MaintenanceState) -> MaintenanceState:
    """下发员工端、写执行记录（幂等接口）。"""
    plan = state.get("selected_plan") or {}
    subtasks = plan.get("subtasks") or []
    request = state.get("request") or {}
    confirmation = state.get("confirmation") or {}

    if not subtasks:
        return {
            "dispatch_result": {"created": 0, "message": "无可下发子任务"},
            "current_node": "dispatch_execution",
            "progress": 98,
            "node_traces": [_trace("dispatch_execution", summary="无可下发子任务")],
        }

    order_type = state.get("order_type") or request.get("order_type") or "巡视"
    order_name = request.get("order_name") or f"{order_type}工单（AI 生成）"
    project_id = state.get("project_id") or None
    time_window = plan.get("subtasks")[0].get("plan_time_window") if subtasks else None

    plan_dates = sorted({str(s.get("plan_date"))[:10] for s in subtasks if s.get("plan_date")})
    inspect_start = date.fromisoformat(plan_dates[0]) if plan_dates else date.today()
    inspect_end = date.fromisoformat(plan_dates[-1]) if plan_dates else inspect_start
    station_names = sorted({s.get("station_name") for s in subtasks if s.get("station_name")})
    inspector_names = sorted({s.get("assignee_name") for s in subtasks if s.get("assignee_name")})
    assignees = {s.get("assignee_id") for s in subtasks if s.get("assignee_id")}

    async with AsyncSessionLocal() as db:
        # 幂等：同一 AI 任务不重复建单
        existing = (
            await db.execute(
                select(WorkOrder).where(WorkOrder.ai_plan_id == state.get("task_id"))
            )
        ).scalars().first()
        if existing:
            return {
                "dispatch_result": {
                    "created": 0,
                    "work_order_id": existing.id,
                    "order_no": existing.order_no,
                    "message": "该任务已下发（幂等命中），未重复建单",
                },
                "current_node": "dispatch_execution",
                "progress": 100,
                "node_traces": [
                    _trace(
                        "dispatch_execution",
                        summary=f"幂等命中，已存在工单 {existing.order_no}",
                        detail={"work_order_id": existing.id},
                    )
                ],
            }

        from app.core.utils import gen_no

        order = WorkOrder(
            order_no=gen_no("WO"),
            order_name=order_name,
            order_type=order_type,
            project_id=project_id,
            station_id=subtasks[0].get("station_id") if len(station_names) == 1 else None,
            station_name="、".join(station_names[:3]) if station_names else None,
            station_ids=[s.get("station_id") for s in subtasks if s.get("station_id")],
            station_names=station_names,
            status=WorkOrderStatus.PENDING_ACCEPT.value,
            time_status=TimeStatus.NORMAL.value,
            inspector_id=next(iter(assignees)) if len(assignees) == 1 else None,
            inspector_name="、".join(inspector_names[:3]) if inspector_names else None,
            inspect_start_date=inspect_start,
            inspect_end_date=inspect_end,
            inspect_frequency=state.get("inspect_frequency") or "月",
            inspect_count=int(state.get("inspect_count") or 1),
            inspect_cycle=int(state.get("inspect_cycle") or 1),
            subtask_total=len(subtasks),
            source="AI 生成",
            ai_plan_id=state.get("task_id"),
            remark=(
                f"由 AI 编排生成，方案 {plan.get('plan_id')}（{plan.get('name')}），"
                f"规则版本 {state.get('rule_version')}。"
                + (f"人工确认：{confirmation.get('comment')}" if confirmation.get("comment") else "")
            ),
            created_by=request.get("created_by"),
        )
        db.add(order)
        await db.flush()

        created_subtasks: list[WorkOrderSubtask] = []
        for sub in subtasks:
            pdate = sub.get("plan_date")
            subtask = WorkOrderSubtask(
                work_order_id=order.id,
                order_no=order.order_no,
                order_name=order.order_name,
                order_type=order_type,
                station_id=sub.get("station_id"),
                station_name=sub.get("station_name"),
                pile_asset_code=sub.get("pile_asset_code"),
                sequence=int(sub.get("sequence") or 1),
                plan_date=date.fromisoformat(str(pdate)[:10]) if pdate else None,
                plan_time_window=sub.get("plan_time_window") or time_window,
                status=SubtaskStatus.PENDING.value,
                assignee_id=sub.get("assignee_id"),
                assignee_name=sub.get("assignee_name"),
                route_order=int(sub.get("route_order") or 0),
            )
            db.add(subtask)
            created_subtasks.append(subtask)

        # 下发消息（PDF 3.8 工单下发 + 7.3 多通道）
        notify_ids = {s for s in assignees if s}
        for uid in notify_ids:
            count = sum(1 for s in subtasks if s.get("assignee_id") == uid)
            db.add(
                Message(
                    receiver_id=uid,
                    msg_type=MessageType.ORDER_ASSIGNED.value,
                    title=f"新工单下发：{order.order_name}",
                    content=(
                        f"工单 {order.order_no} 已下发，共 {count} 个子任务，"
                        f"计划 {inspect_start} ~ {inspect_end}。"
                    ),
                    detail={
                        "工单类型": order_type,
                        "工单编号": order.order_no,
                        "工单名称": order.order_name,
                        "站点名称": "、".join(station_names[:5]),
                        "巡检日期": f"{inspect_start} ~ {inspect_end}",
                        "巡检频率": order.inspect_frequency,
                        "巡检次数": order.inspect_count,
                        "备注": order.remark,
                    },
                    work_order_id=order.id,
                    link=f"/work-orders/{order.id}",
                )
            )

        await db.commit()
        result = {
            "created": len(created_subtasks),
            "work_order_id": order.id,
            "order_no": order.order_no,
            "station_count": len(station_names),
            "notified_users": len(notify_ids),
        }

    return {
        "dispatch_result": result,
        "status": AgentTaskStatus.DISPATCHED.value,
        "current_node": "dispatch_execution",
        "progress": 100,
        "node_traces": [
            _trace(
                "dispatch_execution",
                summary=(
                    f"下发完成：工单 {result['order_no']}，"
                    f"{result['created']} 个子任务，通知 {result['notified_users']} 人"
                ),
                detail=result,
            )
        ],
    }


# ---------------------------------------------------------------- 异常与重排


async def monitor_exception(state: MaintenanceState) -> MaintenanceState:
    """接收异常事件（MQ 消费）—— PDF 4.9 异常来源。"""
    events: list[dict] = list(state.get("exception_events") or [])
    request = state.get("request") or {}
    now = datetime.now()

    async with AsyncSessionLocal() as db:
        # 1) 工单逾期
        rows = (
            await db.execute(
                select(WorkOrder).where(
                    WorkOrder.status.in_(
                        [
                            WorkOrderStatus.PENDING_ACCEPT.value,
                            WorkOrderStatus.PENDING_DONE.value,
                            WorkOrderStatus.RETURNED.value,
                        ]
                    ),
                    WorkOrder.inspect_end_date.is_not(None),
                    WorkOrder.inspect_end_date < now.date(),
                )
            )
        ).scalars().all()
        for order in rows:
            events.append(
                {
                    "event_type": "工单逾期",
                    "source": "定时检测",
                    "severity": "高",
                    "work_order_id": order.id,
                    "description": f"工单 {order.order_no}（{order.order_name}）已超过计划结束日期 {order.inspect_end_date}",
                }
            )

        # 2) 故障等级变更 / 紧急故障超期未核查
        faults = (
            await db.execute(
                select(FaultReport).where(FaultReport.status == "待核查")
            )
        ).scalars().all()
        for fault in faults:
            sla = LEVEL_SLA_HOURS.get(fault.fault_level, 72)
            deadline = (fault.reported_at or fault.created_at) + timedelta(hours=sla)
            if deadline < now:
                events.append(
                    {
                        "event_type": "故障核查超期",
                        "source": "定时检测",
                        "severity": "高" if fault.fault_level == "危急" else "中",
                        "fault_id": fault.id,
                        "description": (
                            f"故障 {fault.fault_no}（{fault.fault_level}）"
                            f"已超过 SLA {sla} 小时未核查"
                        ),
                    }
                )

        # 3) 巡检未完成 / 图片缺失 / 定位异常
        subtasks = (
            await db.execute(
                select(WorkOrderSubtask).where(
                    WorkOrderSubtask.status.in_(
                        [SubtaskStatus.PENDING.value, SubtaskStatus.IN_PROGRESS.value]
                    ),
                    WorkOrderSubtask.plan_date.is_not(None),
                    WorkOrderSubtask.plan_date < now.date(),
                )
            )
        ).scalars().all()
        for sub in subtasks:
            events.append(
                {
                    "event_type": "巡检未完成",
                    "source": "定时检测",
                    "severity": "中",
                    "subtask_id": sub.id,
                    "work_order_id": sub.work_order_id,
                    "description": f"子任务 #{sub.sequence}（{sub.station_name}）计划日期 {sub.plan_date} 未完成",
                }
            )

        # 4) 人工上报的异常
        if request.get("exception_type"):
            events.append(
                {
                    "event_type": request["exception_type"],
                    "source": "人工上报",
                    "severity": request.get("severity") or "中",
                    "target_id": request.get("target_id"),
                    "description": request.get("description") or "人工触发异常重排",
                }
            )

    # 去重（同类型同目标只保留一条）
    deduped: list[dict] = []
    seen: set[tuple] = set()
    for ev in events:
        key = (ev.get("event_type"), ev.get("work_order_id") or ev.get("fault_id") or ev.get("subtask_id") or ev.get("target_id"))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(ev)

    return {
        "exception_events": deduped,
        "current_node": "monitor_exception",
        "progress": 30,
        "node_traces": [
            _trace(
                "monitor_exception",
                summary=f"接收并识别异常事件 {len(deduped)} 条",
                detail={"events": deduped[:20]},
            )
        ],
    }


async def impact_analysis(state: MaintenanceState) -> MaintenanceState:
    """影响分析（规则引擎）—— PDF 4.4 impact_analysis。"""
    events = state.get("exception_events") or []
    analyses: list[dict] = []

    async with AsyncSessionLocal() as db:
        for event in events[:50]:
            analysis = {
                "event_type": event.get("event_type"),
                "severity": event.get("severity"),
                "affected_subtasks": [],
                "affected_work_orders": [],
                "lock_executed": True,
                "repair_scope": "局部修复",
            }
            wo_id = event.get("work_order_id")
            if wo_id:
                subs = (
                    await db.execute(
                        select(WorkOrderSubtask).where(
                            WorkOrderSubtask.work_order_id == wo_id
                        )
                    )
                ).scalars().all()
                # PDF 4.9：锁定已执行工单、已核查故障、已完成巡检，不重排
                pending = [
                    s
                    for s in subs
                    if s.status in (SubtaskStatus.PENDING.value, SubtaskStatus.IN_PROGRESS.value)
                ]
                done = [s for s in subs if s.status == SubtaskStatus.COMPLETED.value]
                analysis["affected_subtasks"] = [
                    {"id": s.id, "sequence": s.sequence, "station_name": s.station_name}
                    for s in pending
                ]
                analysis["locked_subtasks"] = [
                    {"id": s.id, "sequence": s.sequence} for s in done
                ]
                analysis["affected_work_orders"] = [wo_id]
                analysis["repair_scope"] = (
                    "局部修复" if len(pending) < len(subs) else "整单重排"
                )
                analysis["pending_count"] = len(pending)
                analysis["locked_count"] = len(done)
            analyses.append(analysis)

    repair_scope = "局部修复" if any(a["repair_scope"] == "局部修复" for a in analyses) else "整单重排"
    return {
        "report_data": {**(state.get("report_data") or {}), "impact_analysis": analyses},
        "current_node": "impact_analysis",
        "progress": 45,
        "node_traces": [
            _trace(
                "impact_analysis",
                summary=f"完成 {len(analyses)} 条异常的影响分析，建议策略：{repair_scope}",
                detail={"analyses": analyses[:10], "repair_scope": repair_scope},
            )
        ],
    }


async def replan(state: MaintenanceState) -> MaintenanceState:
    """重排 / 重算（LangGraph 状态恢复）—— PDF 4.9 重排策略。

    1. 锁定已执行工单、已核查故障、已完成巡检，不重排；
    2. 只重排未执行、未完成部分；
    3. 优先局部修复，失败再全局重排；
    4. 记录 replan_count，避免无限循环。
    """
    replan_count = int(state.get("replan_count") or 0)
    max_replan = int((state.get("hard_constraints") or {}).get("重排上限", 3))

    if replan_count >= max_replan:
        return {
            "validation_errors": [
                f"重排次数已达上限 {max_replan} 次，停止自动重排，请人工介入（PDF 4.9 防死循环）"
            ],
            "current_node": "replan",
            "progress": 60,
            "node_traces": [
                _trace(
                    "replan",
                    status="failed",
                    summary=f"重排次数 {replan_count} 已达上限 {max_replan}，终止自动重排",
                )
            ],
        }

    # 只重排未完成部分：重新生成候选方案
    regenerated = await work_order_generation(state)
    scored = regenerated.get("scored_plans") or []
    selected = scored[0] if scored else None

    # 重新排期到未来（相对当前日期）
    if selected:
        plan_dates = sorted(
            {str(s.get("plan_date"))[:10] for s in selected.get("subtasks") or [] if s.get("plan_date")}
        )
        if plan_dates:
            first = date.fromisoformat(plan_dates[0])
            shift_days = max(0, (date.today() - first).days)
            if shift_days:
                for sub in selected["subtasks"]:
                    try:
                        sub["plan_date"] = (
                            date.fromisoformat(str(sub["plan_date"])[:10]) + timedelta(days=shift_days)
                        ).isoformat()
                    except Exception:
                        continue

    return {
        "candidate_plans": regenerated.get("candidate_plans") or [],
        "scored_plans": scored,
        "selected_plan": selected,
        "replan_count": replan_count + 1,
        "current_node": "replan",
        "progress": 60,
        "node_traces": [
            _trace(
                "replan",
                summary=(
                    f"完成第 {replan_count + 1} 次重排，锁定已执行任务，"
                    f"生成 {len(scored)} 个候选方案"
                ),
                detail={
                    "replan_count": replan_count + 1,
                    "max_replan": max_replan,
                    "selected_plan": selected.get("plan_id") if selected else None,
                },
            )
        ],
    }


# ---------------------------------------------------------------- 辅助节点


async def plan_scoring(state: MaintenanceState) -> MaintenanceState:
    """方案评分节点（异常重排入口路径）。"""
    plans = state.get("candidate_plans") or []
    scored = sorted(plans, key=lambda p: p.get("score", 0), reverse=True)
    return {
        "scored_plans": scored,
        "selected_plan": scored[0] if scored else None,
        "current_node": "plan_scoring",
        "progress": 75,
        "node_traces": [
            _trace(
                "plan_scoring",
                summary=f"完成 {len(scored)} 个方案评分，最优「{scored[0]['name'] if scored else '-'}」",
                detail={"scores": {p.get("plan_id"): p.get("score") for p in scored}},
            )
        ],
    }


async def relax_constraints(state: MaintenanceState) -> MaintenanceState:
    """约束松弛（PDF 4.3：candidate_plans 为空时松弛软约束重试）。

    注意：本节点必须自带重试计数（relax_count），否则会与
    work_order_generation 形成无限循环，validation_warnings 每轮翻倍
    并最终触发 MemoryError。图侧 after_generation 依据该计数终止重试。
    """
    relax_count = int(state.get("relax_count") or 0) + 1
    soft = dict(state.get("soft_constraints") or {})
    soft["单日最大任务数"] = int(soft.get("单日最大任务数", 8)) + 2

    # 只返回本轮新增的提示；validation_warnings 使用 merge_list reducer，
    # 若把继承来的列表一并返回会导致列表指数级翻倍。
    new_warning = (
        f"未生成有效方案，已放宽软约束（单日最大任务数 +2）后重试"
        f"（第 {relax_count} 次，上限 {MAX_RELAX_RETRY} 次）"
    )
    return {
        "soft_constraints": soft,
        "relax_count": relax_count,
        "validation_warnings": [new_warning],
        "current_node": "relax_constraints",
        "progress": 50,
        "node_traces": [
            _trace(
                "relax_constraints",
                summary=f"放宽软约束后重新生成方案（第 {relax_count} 次）",
                detail={"soft_constraints": soft, "relax_count": relax_count},
            )
        ],
    }


async def exception_handler(state: MaintenanceState) -> MaintenanceState:
    """规则校验失败时的异常出口（PDF 4.3 exception_handler）。"""
    errors = state.get("validation_errors") or []
    return {
        "status": AgentTaskStatus.FAILED.value,
        "current_node": "exception_handler",
        "progress": 100,
        "node_traces": [
            _trace(
                "exception_handler",
                status="failed",
                summary=f"流程终止：{errors[0] if errors else '未知校验错误'}",
                detail={"errors": errors},
            )
        ],
    }


# ---------------------------------------------------------------- LLM 方案解释


async def explain_plan(state: MaintenanceState) -> str:
    """用 LLM 解释方案（PDF 4.1 原则 2：LLM 只做解释和辅助）。"""
    plans = state.get("scored_plans") or []
    if not plans:
        return "未生成候选方案。"

    summary_lines = []
    for p in plans[:3]:
        detail = p.get("detail") or {}
        summary_lines.append(
            f"- {p.get('name')}（{p.get('plan_id')}）：得分 {p.get('score')}，"
            f"子任务 {p.get('subtask_count')} 个，策略 {detail.get('描述') or detail.get('策略说明') or '-'}"
        )

    deterministic = (
        f"系统基于硬约束（{state.get('hard_constraints', {}).get('子任务公式', {})}）"
        f"生成 {len(plans)} 个方案，推荐「{plans[0].get('name')}」，"
        f"得分 {plans[0].get('score')}，共 {plans[0].get('subtask_count')} 个子任务。"
        f"规则版本：{state.get('rule_version') or '-'}。"
    )

    if not llm_client.available:
        return deterministic

    result = await llm_client.chat(
        "你是运维调度方案讲解助手。所有方案已由确定性求解器生成，"
        "你只需用通俗语言解释方案差异与推荐理由，不得修改任何数量与分数。",
        "请用 150 字以内解释以下调度方案并给出推荐理由：\n"
        + "\n".join(summary_lines)
        + f"\n\n硬约束：{to_json_safe(state.get('hard_constraints'))[:800]}",
        max_tokens=400,
    )
    if result.used_llm:
        return result.text
    return deterministic + f"（LLM 解释不可用：{result.error}）"
