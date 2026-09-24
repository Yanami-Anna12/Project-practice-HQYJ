"""调度任务接口。

对应需求文档 五.1「调度任务接口」：
    POST   /api/v1/scheduling/tasks              创建并执行调度
    GET    /api/v1/scheduling/tasks              任务列表
    GET    /api/v1/scheduling/tasks/{id}         任务详情（含多方案）
    GET    /api/v1/scheduling/plans/{id}/details 方案明细
    POST   /api/v1/scheduling/tasks/{id}/confirm 人工确认
    POST   /api/v1/scheduling/tasks/{id}/dispatch 下发执行
    POST   /api/v1/scheduling/tasks/{id}/replan  异常重排
    GET    /api/v1/scheduling/tasks/{id}/report  调度报告
"""

from __future__ import annotations

import json
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func

from app.config import settings
from app.deps import DbSession, require_permission
from app.errors import AppError, ConflictError, NotFoundError
from app.models import (
    DispatchRecord,
    ExceptionEvent,
    ReplanRecord,
    SchedulingConfirmation,
    SchedulingPlan,
    SchedulingPlanDetail,
    SchedulingReport,
    SchedulingTask,
    Store,
    SysParam,
    SysUser,
)
from app.schemas import (
    ConfirmRequest,
    ConfirmResult,
    DispatchResult,
    ExceptionCreate,
    ExceptionOut,
    FeasibilityOut,
    PlanDetailOut,
    PlanOut,
    ReplanResult,
    ReportOut,
    SchedulingRunRequest,
    TaskDetailOut,
    TaskOut,
)
from app.services import scheduling as sched
from app.services.audit import append_audit
from app.services.solver import check_assignable

router = APIRouter(prefix="/scheduling", tags=["智能调度"])

Reader = Annotated[SysUser, Depends(require_permission("scheduling:read"))]
Creator = Annotated[SysUser, Depends(require_permission("scheduling:create"))]
Confirmer = Annotated[SysUser, Depends(require_permission("scheduling:confirm"))]
Replanner = Annotated[SysUser, Depends(require_permission("scheduling:replan"))]


def _param_int(db, key: str, default: int) -> int:
    """读取系统参数（页面上可改），读不到就用默认值。"""
    row = db.query(SysParam).filter(SysParam.key == key, SysParam.is_active.is_(True)).one_or_none()
    if row is None:
        return default
    try:
        return int(row.value)
    except (TypeError, ValueError):
        return default


def _param_str(db, key: str, default: str) -> str:
    row = db.query(SysParam).filter(SysParam.key == key, SysParam.is_active.is_(True)).one_or_none()
    return row.value if row else default


def _param_bool(db, key: str, default: bool) -> bool:
    row = db.query(SysParam).filter(SysParam.key == key, SysParam.is_active.is_(True)).one_or_none()
    if row is None:
        return default
    return row.value.strip().lower() == "true"


@router.get("/feasibility", response_model=FeasibilityOut, summary="调度可行性预检")
def feasibility(
    db: DbSession,
    actor: Reader,
    schedule_date: date = Query(..., description="调度日期"),
    time_window: str = Query(default="FULL"),
) -> FeasibilityOut:
    """在真正跑调度前先看「能不能跑」，避免提交后才发现没数据。"""
    data = sched.build_solve_input(db, schedule_date, time_window)
    problems = check_assignable(data.stores, data.vehicles)
    return FeasibilityOut(
        schedule_date=schedule_date,
        store_count=len(data.stores),
        vehicle_count=len(data.vehicles),
        total_demand=round(sum(s.quantity for s in data.stores), 2),
        total_capacity=sum(v.max_load * v.trips_per_day for v in data.vehicles),
        problems=problems,
        ready=not problems,
    )


@router.post("/tasks", response_model=TaskDetailOut, summary="创建并执行调度任务")
def create_task(payload: SchedulingRunRequest, db: DbSession, actor: Creator) -> TaskDetailOut:
    """创建调度任务并同步执行求解。

    ★ 本项目按「同步执行」实现：门店与车辆规模（16 店 / 40 车）下求解在
      百毫秒级，同步返回的体验更好（前端不用轮询）。需求文档里的
      WebSocket 进度推送是为更大规模设计的，属于后续优化项。
    """
    timeout = payload.timeout_seconds or _param_int(db, "scheduling.solver.timeout_seconds", 5)

    result = sched.run_scheduling(
        db,
        schedule_date=payload.schedule_date,
        time_window=payload.time_window,
        created_by=actor.username,
        timeout_seconds=timeout,
        use_cp_sat=payload.use_cp_sat,
        rule_version=_param_str(db, "rule.version.current", "v1.0.0"),
    )

    task = result["task"]
    append_audit(
        db,
        actor=actor,
        action="scheduling.create",
        target_type="task",
        target_name=task.code,
        detail={
            "调度日期": str(payload.schedule_date),
            "时段": payload.time_window,
            "状态": task.status,
            "方案数": len(result["plans"]),
            "耗时ms": task.duration_ms,
        },
    )

    return _task_detail(db, task, result["problems"], result["validations"])


def _task_detail(
    db, task: SchedulingTask, problems: list[str], validations: dict
) -> TaskDetailOut:
    plans = (
        db.query(SchedulingPlan)
        .filter(SchedulingPlan.task_id == task.id)
        .order_by(SchedulingPlan.is_recommended.desc(), SchedulingPlan.plan_code)
        .all()
    )
    input_summary = {}
    for plan in plans:
        if plan.total_load:
            input_summary = {"plan_total_load": float(plan.total_load)}
            break

    return TaskDetailOut(
        task=TaskOut.model_validate(task),
        plans=[PlanOut.model_validate(p) for p in plans],
        problems=problems,
        validations=validations,
        input_summary=input_summary,
    )


@router.get("/tasks", response_model=list[TaskOut], summary="调度任务列表")
def list_tasks(
    db: DbSession,
    actor: Reader,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[TaskOut]:
    tasks = (
        db.query(SchedulingTask)
        .order_by(SchedulingTask.id.desc())
        .limit(limit)
        .all()
    )
    return [TaskOut.model_validate(t) for t in tasks]


@router.get("/tasks/{task_id}", response_model=TaskDetailOut, summary="任务详情（含多方案）")
def get_task(task_id: int, db: DbSession, actor: Reader) -> TaskDetailOut:
    task = db.get(SchedulingTask, task_id)
    if task is None:
        raise NotFoundError("调度任务不存在")
    return _task_detail(db, task, [], {})


@router.get("/plans/{plan_id}/details", response_model=list[PlanDetailOut], summary="方案明细")
def plan_details(plan_id: int, db: DbSession, actor: Reader) -> list[PlanDetailOut]:
    plan = db.get(SchedulingPlan, plan_id)
    if plan is None:
        raise NotFoundError("方案不存在")
    return [PlanDetailOut(**row) for row in sched.get_plan_details(db, plan_id)]


@router.post("/tasks/{task_id}/confirm", response_model=ConfirmResult, summary="人工确认方案")
def confirm_task(
    task_id: int, payload: ConfirmRequest, db: DbSession, actor: Confirmer
) -> ConfirmResult:
    """人工确认。需求文档明确「真实商业项目必须有人工确认环节」。

    未确认前不允许下发（见 dispatch 接口的检查）。
    """
    task = db.get(SchedulingTask, task_id)
    if task is None:
        raise NotFoundError("调度任务不存在")

    plan = db.get(SchedulingPlan, payload.plan_id)
    if plan is None or plan.task_id != task.id:
        raise NotFoundError("方案不存在或不属于该任务")

    confirmation = SchedulingConfirmation(
        task_id=task.id,
        plan_id=plan.id,
        operator=actor.username,
        approved=1 if payload.approved else 0,
        adjustments=json.dumps(payload.adjustments, ensure_ascii=False),
        remark=payload.remark,
    )
    db.add(confirmation)

    if payload.approved:
        # 标记选中方案
        for p in db.query(SchedulingPlan).filter(SchedulingPlan.task_id == task.id).all():
            p.is_recommended = 1 if p.id == plan.id else 0
        task.status = "confirmed"
        message = f"已确认方案 {plan.plan_code}（{plan.strategy}），可执行下发"
    else:
        task.status = "pending_confirm"
        message = "已驳回，请重新生成方案"

    db.commit()
    append_audit(
        db,
        actor=actor,
        action="scheduling.confirm" if payload.approved else "scheduling.reject",
        target_type="task",
        target_name=task.code,
        detail={
            "方案": plan.plan_code,
            "结果": "通过" if payload.approved else "驳回",
            "备注": payload.remark,
        },
    )
    return ConfirmResult(
        task_id=task.id, plan_id=plan.id, status=task.status, message=message
    )


@router.post("/tasks/{task_id}/dispatch", response_model=DispatchResult, summary="下发执行")
def dispatch_task(
    task_id: int,
    db: DbSession,
    actor: Confirmer,
    plan_id: int = Query(..., description="要下发的方案 ID"),
) -> DispatchResult:
    """下发到 TMS / 司机端。

    ★ 两个关键点：
      1. 必须先人工确认（需求：未确认前不下发）
      2. 幂等：task_id + plan_id + trip_id 唯一，重复调用不会产生重复任务
         （对应需求文档「下发重复」风险的应对）
    """
    task = db.get(SchedulingTask, task_id)
    if task is None:
        raise NotFoundError("调度任务不存在")

    confirmed = (
        db.query(SchedulingConfirmation)
        .filter(
            SchedulingConfirmation.task_id == task.id,
            SchedulingConfirmation.plan_id == plan_id,
            SchedulingConfirmation.approved == 1,
        )
        .one_or_none()
    )
    if confirmed is None:
        raise ConflictError("该方案尚未人工确认，不允许下发")

    plan = db.get(SchedulingPlan, plan_id)
    if plan is None or plan.task_id != task.id:
        raise NotFoundError("方案不存在或不属于该任务")

    # 按 (车辆, 趟次) 聚合，幂等键 = task:plan:vehicle:trip
    trips = (
        db.query(
            SchedulingPlanDetail.vehicle_id,
            SchedulingPlanDetail.trip_no,
        )
        .filter(SchedulingPlanDetail.plan_id == plan_id)
        .distinct()
        .all()
    )

    dispatched, skipped = 0, 0
    for vehicle_id, trip_no in trips:
        trip_key = f"{task.id}:{plan_id}:{vehicle_id}:{trip_no}"
        exists = (
            db.query(DispatchRecord)
            .filter(
                DispatchRecord.task_id == task.id,
                DispatchRecord.plan_id == plan_id,
                DispatchRecord.trip_id == trip_key,
            )
            .one_or_none()
        )
        if exists is not None:
            skipped += 1
            continue
        db.add(
            DispatchRecord(
                task_id=task.id,
                plan_id=plan_id,
                vehicle_id=vehicle_id,
                trip_id=trip_key,
                target="TMS",
                status="accepted",
            )
        )
        db.query(SchedulingPlanDetail).filter(
            SchedulingPlanDetail.plan_id == plan_id,
            SchedulingPlanDetail.vehicle_id == vehicle_id,
            SchedulingPlanDetail.trip_no == trip_no,
        ).update({"status": "dispatched"})
        dispatched += 1

    if dispatched:
        task.status = "dispatched"
    db.commit()

    append_audit(
        db,
        actor=actor,
        action="scheduling.dispatch",
        target_type="task",
        target_name=task.code,
        detail={
            "方案": plan.plan_code,
            "下发趟次": dispatched,
            "重复跳过": skipped,
        },
    )

    message = f"已下发 {dispatched} 个趟次到 TMS"
    if skipped:
        message += f"，{skipped} 个趟次已存在（幂等跳过）"
    return DispatchResult(
        task_id=task.id,
        plan_id=plan_id,
        dispatched_trips=dispatched,
        skipped_duplicated=skipped,
        message=message,
    )


@router.post("/exceptions", response_model=ExceptionOut, summary="上报异常事件")
def create_exception(
    payload: ExceptionCreate, db: DbSession, actor: Replanner
) -> ExceptionOut:
    """异常来源：车辆故障、司机缺勤、门店临时加减货、交通管制、地形临时管控。"""
    task = db.get(SchedulingTask, payload.task_id)
    if task is None:
        raise NotFoundError("调度任务不存在")

    event = ExceptionEvent(
        task_id=task.id,
        event_type=payload.event_type,
        source=payload.source or actor.username,
        payload=json.dumps(payload.payload, ensure_ascii=False),
        status="pending",
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    append_audit(
        db,
        actor=actor,
        action="scheduling.exception",
        target_type="task",
        target_name=task.code,
        detail={"类型": payload.event_type, "来源": event.source},
    )
    return ExceptionOut.model_validate(event)


@router.get("/exceptions", response_model=list[ExceptionOut], summary="异常事件列表")
def list_exceptions(
    db: DbSession,
    actor: Reader,
    task_id: int | None = Query(default=None),
) -> list[ExceptionOut]:
    q = db.query(ExceptionEvent)
    if task_id is not None:
        q = q.filter(ExceptionEvent.task_id == task_id)
    rows = q.order_by(ExceptionEvent.id.desc()).limit(100).all()
    return [ExceptionOut.model_validate(r) for r in rows]


@router.post("/tasks/{task_id}/replan", response_model=ReplanResult, summary="异常重排")
def replan_task(
    task_id: int,
    db: DbSession,
    actor: Replanner,
    event_id: int | None = Query(default=None),
    scope: str = Query(default="local", pattern="^(local|global)$"),
) -> ReplanResult:
    """异常重排。

    ★ 需求文档的重排策略：
        1. 锁定已执行趟次，不重排
        2. 只重排未执行、未完成部分
        3. 优先局部修复，失败再全局重排
        4. 记录 replan_count，避免无限循环
    """
    task = db.get(SchedulingTask, task_id)
    if task is None:
        raise NotFoundError("调度任务不存在")

    max_replan = _param_int(db, "scheduling.replan.max_count", settings.REPLAN_MAX_COUNT)
    if task.replan_count >= max_replan:
        raise ConflictError(
            f"该任务已重排 {task.replan_count} 次，达到上限 {max_replan}，"
            f"请人工介入处理（防止无限重排）"
        )

    # 锁定已执行的趟次：状态为 dispatched / completed 的明细不参与重排
    executed_trips = {
        (row.vehicle_id, row.trip_no)
        for row in db.query(SchedulingPlanDetail)
        .filter(
            SchedulingPlanDetail.plan_id.in_(
                db.query(SchedulingPlan.id).filter(SchedulingPlan.task_id == task.id)
            ),
            SchedulingPlanDetail.status.in_(["dispatched", "completed"]),
        )
        .all()
    }

    event = db.get(ExceptionEvent, event_id) if event_id else None

    task.replan_count += 1
    db.add(
        ReplanRecord(
            task_id=task.id,
            trigger_event_id=event.id if event else None,
            scope=scope,
            replan_count=task.replan_count,
            result="pending",
        )
    )

    append_audit(
        db,
        actor=actor,
        action="scheduling.replan",
        target_type="task",
        target_name=task.code,
        detail={
            "范围": "局部" if scope == "local" else "全局",
            "第几次": task.replan_count,
            "上限": max_replan,
            "锁定已执行趟次": len(executed_trips),
            "触发事件": event.event_type if event else "（人工触发）",
        },
    )

    if event is not None:
        event.status = "handled"

    db.commit()

    return ReplanResult(
        task_id=task.id,
        replan_count=task.replan_count,
        scope=scope,
        message=(
            f"已登记第 {task.replan_count} 次重排（上限 {max_replan}）。"
            f"已锁定 {len(executed_trips)} 个已执行趟次不予改动。"
            f"请重新创建调度任务以生成新方案。"
        ),
        new_plan_ids=[],
    )


@router.get("/tasks/{task_id}/report", response_model=ReportOut, summary="调度报告")
def task_report(task_id: int, db: DbSession, actor: Reader) -> ReportOut:
    """获取调度报告。首次访问时按当前数据生成并落库。"""
    task = db.get(SchedulingTask, task_id)
    if task is None:
        raise NotFoundError("调度任务不存在")

    existing = (
        db.query(SchedulingReport)
        .filter(SchedulingReport.task_id == task.id)
        .order_by(SchedulingReport.id.desc())
        .first()
    )
    if existing is not None:
        return ReportOut.model_validate(existing)

    plan = (
        db.query(SchedulingPlan)
        .filter(SchedulingPlan.task_id == task.id, SchedulingPlan.is_recommended == 1)
        .first()
    )
    content = _build_report(db, task, plan)
    report = sched.save_report(db, task.id, plan.id if plan else None, content)
    return ReportOut.model_validate(report)


def _build_report(db, task: SchedulingTask, plan: SchedulingPlan | None) -> str:
    """生成调度报告文本。"""
    plans = (
        db.query(SchedulingPlan)
        .filter(SchedulingPlan.task_id == task.id)
        .order_by(SchedulingPlan.plan_code)
        .all()
    )
    store_count = db.query(func.count(Store.id)).scalar() or 0

    lines = [
        f"# 调度报告 {task.code}",
        "",
        f"- 调度日期：{task.schedule_date}",
        f"- 时段：{task.time_window}",
        f"- 状态：{task.status}",
        f"- 规则版本：{task.rule_version}",
        f"- 求解耗时：{task.duration_ms} ms",
        f"- 重排次数：{task.replan_count}",
        f"- 门店总数（系统内）：{store_count}",
        "",
        "## 方案对比",
        "",
        "| 方案 | 策略 | 趟次 | 用车 | 四米二使用率 | 装载率 | 相对成本 | 评分 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for p in plans:
        mark = " ★" if p.is_recommended else ""
        lines.append(
            f"| {p.plan_code}{mark} | {p.strategy} | {p.trip_count} | {p.vehicle_count} | "
            f"{float(p.four_two_usage):.1f}% | {float(p.avg_load_rate):.1f}% | "
            f"{float(p.total_cost):.2f} | {float(p.score):.1f} |"
        )

    if plan is not None:
        lines += ["", f"## 推荐方案 {plan.plan_code} 说明", "", plan.explanation]
        if plan.uncovered_stores:
            lines += [
                "",
                f"⚠ 未完全满足的门店：{plan.uncovered_stores}",
            ]

    lines += [
        "",
        "## 硬约束校验",
        "",
        "本报告对应的方案由 `app/services/solver.py` 的 `validate_solution()` 独立校验，",
        "覆盖：时段匹配、地形能力、线路匹配、装载量上下限、趟次上限、门店货量完整性。",
    ]
    return "\n".join(lines)
