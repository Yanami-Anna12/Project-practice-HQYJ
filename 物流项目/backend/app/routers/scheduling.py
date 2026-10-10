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
import logging
from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy import func

from app.config import settings
from app.deps import DbSession, require_permission
from app.errors import ConflictError, NotFoundError
from app.models import (
    DispatchRecord,
    ExceptionEvent,
    MobileNotification,
    ReplanRecord,
    SchedulingConfirmation,
    SchedulingPlan,
    SchedulingPlanDetail,
    SchedulingReport,
    SchedulingTask,
    Store,
    SysParam,
    SysUser,
    TripStopRecord,
    Vehicle,
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
    UndoDispatchResult,
)
from app.services import mobile as mobile_service
from app.services import realtime
from app.services import scheduling as sched
from app.services.audit import append_audit
from app.services.solver import check_assignable

router = APIRouter(prefix="/scheduling", tags=["智能调度"])

logger = logging.getLogger(__name__)

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

    # ★ 司机端站内消息：下发成功后给相关司机各写一条。
    #   通知属于「下发之后的锦上添花」，任何异常都只记日志 ——
    #   绝不能让通知失败把一次成功的下发变成 500（那样司机反而看不到任务）。
    try:
        notified = mobile_service.notify_dispatch(db, task.id)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        notified = 0
        logger.exception("下发通知生成失败（不影响下发本身）：%s", exc)

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
            "通知司机": notified,
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


@router.post(
    "/tasks/{task_id}/undo-dispatch",
    response_model=UndoDispatchResult,
    summary="撤销下发（收回下发给司机的任务）",
)
def undo_dispatch(
    task_id: int, db: DbSession, actor: Confirmer, background: BackgroundTasks
) -> UndoDispatchResult:
    """把一次下发**收回来**，任务退回「已确认」，可重新选方案下发。

    ★ 为什么是「撤销下发」而不是「删除任务」：

      下错方案的正确处置是**撤回这一版安排**，而不是抹掉调度成果。
      所以这里只清「下发这个动作产生的数据」，任务 / 方案 / 计划明细
      **一律保留** —— 它们仍然是可追溯的调度结果，撤销后随时能重发。

    ★ 撤销清单（全部在一个事务里，失败整体回滚）：

      1. `dispatch_record`：该任务的下发记录（司机端趟次的来源，
         也是司机「确认接单」事实的载体）
      2. `mobile_notification`：发给司机的下发站内消息（biz_type=dispatch
         且 biz_id=本任务）。biz_id 是任务号，所以只撤本任务的通知，
         不会误伤别的任务下发的消息。
      3. `scheduling_plan_detail.status`：该任务所有明细从 dispatched 退回
         planned（未执行的趟次），让这些趟次从「我的趟次」里消失。

    ★ 什么**不会**被撤销 —— 现场执行是既成事实，收回不了：

      · `trip_stop_record`（司机到店/离店打卡）与状态已推进到
        arrived/done 的明细**原样保留**；
      · 已接单（accepted_at）但还没执行的趟次，下发记录会被收回，
        但司机端留下的接单记录不删 —— 与上面同理，发生过的事不抹除。

    ★ 幂等：对没下发过的任务调用不报错，返回 revoked_trips=0。
    """
    task = db.get(SchedulingTask, task_id)
    if task is None:
        raise NotFoundError("调度任务不存在")

    if task.status not in ("dispatched", "completed"):
        return UndoDispatchResult(
            task_id=task.id,
            task_code=task.code,
            status=task.status,
            revoked_trips=0,
            revoked_notifications=0,
            drivers=0,
            executed_kept=0,
            accepted_trips=0,
            message=f"任务 {task.code} 当前状态为 {task.status}，没有已下发的趟次需要撤销",
        )

    plan_ids = [
        row[0]
        for row in db.query(SchedulingPlan.id)
        .filter(SchedulingPlan.task_id == task.id)
        .all()
    ]

    # 已经动过的趟次：状态已推进（arrived/done）或已有现场打卡记录。
    # 这些趟次从「待收回」里排除 —— 收回一个司机正在跑的趟次，
    # 只会让他在路上失去任务。
    executed: set[tuple[int, int]] = {
        (vehicle_id, trip_no)
        for vehicle_id, trip_no in db.query(
            SchedulingPlanDetail.vehicle_id, SchedulingPlanDetail.trip_no
        )
        .filter(
            SchedulingPlanDetail.plan_id.in_(plan_ids),
            SchedulingPlanDetail.status.notin_(["planned", "dispatched"]),
        )
        .all()
    }
    if plan_ids:
        executed |= {
            (row.vehicle_id, row.trip_no)
            for row in db.query(SchedulingPlanDetail.vehicle_id, SchedulingPlanDetail.trip_no)
            .join(TripStopRecord, TripStopRecord.plan_detail_id == SchedulingPlanDetail.id)
            .filter(SchedulingPlanDetail.plan_id.in_(plan_ids))
            .distinct()
            .all()
        }

    # 待收回的下发记录（排除已动过的趟次），顺带统计两类「收不回来」的趟次
    accepted_trips = 0
    executed_kept = 0
    revocable: list[DispatchRecord] = []
    for record in (
        db.query(DispatchRecord)
        .filter(DispatchRecord.task_id == task.id)
        .order_by(DispatchRecord.id)
        .all()
    ):
        parts = record.trip_id.split(":")
        trip_no = int(parts[3]) if len(parts) == 4 and parts[3].isdigit() else 0
        # 确认接单是「司机已经收到了」的事实，只统计不抹除
        if record.accepted_at is not None:
            accepted_trips += 1
        if (record.vehicle_id, trip_no) in executed:
            executed_kept += 1
            continue
        revocable.append(record)

    # 通知必须与真正收回去的趟次对应：先看这次收回了哪些车，
    # 再按 notify_dispatch 的标题规则（含车牌）精确命中，
    # 避免把「同一辆车、别的任务」的通知一起删掉。
    vehicle_ids = {r.vehicle_id for r in revocable}
    vehicles = (
        db.query(Vehicle).filter(Vehicle.id.in_(vehicle_ids)).all() if vehicle_ids else []
    )
    notifications: list[MobileNotification] = []
    for vehicle in vehicles:
        notifications += (
            db.query(MobileNotification)
            .filter(
                MobileNotification.biz_type == mobile_service.BIZ_DISPATCH,
                MobileNotification.biz_id == task.id,
                MobileNotification.title == f"新任务下发：{task.code}（{vehicle.plate_no}）",
            )
            .all()
        )
    # 兜底：老数据可能没有 biz_id，此时只按「任务号 + dispatch 类型」命中，
    # 不然任务撤回了、消息还留在司机手机上点不动。
    notifications += (
        db.query(MobileNotification)
        .filter(
            MobileNotification.biz_type == mobile_service.BIZ_DISPATCH,
            MobileNotification.biz_id.is_(None),
            MobileNotification.title.like(f"新任务下发：{task.code}（%"),
        )
        .all()
    )
    # 老数据兜底可能与上面的精确命中重复，按 id 去重
    notifications = list({row.id: row for row in notifications}.values())

    for record in revocable:
        db.delete(record)
    for row in notifications:
        db.delete(row)

    # 未执行的明细退回 planned：它们从此不再出现在司机端「我的趟次」里
    # （「我的趟次」只认 status=dispatched，见 services/mobile.py）。
    reverted = 0
    if plan_ids:
        reverted = (
            db.query(SchedulingPlanDetail)
            .filter(
                SchedulingPlanDetail.plan_id.in_(plan_ids),
                SchedulingPlanDetail.status == "dispatched",
            )
            .update({"status": "planned"})
        )

    task.status = "confirmed"
    db.commit()

    # ★ 必须在删除之后、commit 之后再取收件人与未读数：撤销就是把消息删掉，
    #   未读数要反映「删完」的结果，否则司机端红点会多出一条。
    revoked_user_ids = sorted({row.user_id for row in notifications})
    unread_by_user = {
        user_id: mobile_service.unread_count_for_user(db, user_id)
        for user_id in revoked_user_ids
    }
    drivers = len(revoked_user_ids)

    # 尽力而为的实时告知：在线的司机端立刻把任务从列表里摘掉。
    # 推不到（司机离线）不影响撤销本身 —— 消息记录已经删了，刷新即消失。
    # 报文保持与「新消息」同一个外壳（type=notification + notification.biz_type），
    # 这样小程序不需要为撤回单开一条分支：biz_type=revoked 走「任务被撤回」的处理。
    #
    # ★★ 为什么用 BackgroundTasks 而不是直接调 publish_to_users()：
    #
    #   `publish_to_users()` 内部走 `asyncio.run_coroutine_threadsafe(...)`，
    #   把协程丢回事件循环后**本线程立即返回** —— 听起来不阻塞，
    #   但这里踩过一次真实的坑：撤销接口是在「事务提交之后」才推送的，
    #   一旦事件循环里有连接处于「已断开但还没被摘除」的状态，
    #   投递就会卡住，于是**HTTP 请求迟迟不返回**：
    #   库里数据其实已经改完了（任务已退回 confirmed、记录已删），
    #   可前端却在转圈，用户以为撤销失败而重复点击。
    #
    #   放进 BackgroundTasks：FastAPI 在**响应发出之后**才执行它，
    #   推送再慢也只影响那条后台任务，绝不可能拖住这次请求。
    #   这与 realtime 模块「推送绝不能影响主流程」的设计约束是一致的。
    background.add_task(
        realtime.publish_to_users,
        revoked_user_ids,
        {
            "type": "notification",
            "notification": {
                "biz_type": "revoked",
                "biz_id": task.id,
                "title": f"任务已撤回：{task.code}",
                "content": "该任务已被调度撤回，趟次已从「我的趟次」中移除。",
            },
            "unread": None,
            "unread_by_user": unread_by_user,
            "task_id": task.id,
            "task_code": task.code,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        },
    )

    message = f"已撤销 {len(revocable)} 个趟次的下发，任务 {task.code} 退回「已确认」"
    if reverted:
        message += f"，{reverted} 行计划明细退回 planned"
    if notifications:
        message += f"，收回 {len(notifications)} 条司机通知"
    if accepted_trips:
        message += f"；其中 {accepted_trips} 个趟次司机已确认接单（接单记录保留）"
    if executed_kept:
        message += f"；{executed_kept} 个趟次已有现场执行记录，未收回"

    append_audit(
        db,
        actor=actor,
        action="scheduling.undo_dispatch",
        target_type="task",
        target_name=task.code,
        detail={
            "撤销趟次": len(revocable),
            "退回明细": reverted,
            "收回通知": len(notifications),
            "已接单未执行": accepted_trips,
            "已有执行记录未收回": executed_kept,
            "任务新状态": task.status,
        },
    )

    return UndoDispatchResult(
        task_id=task.id,
        task_code=task.code,
        status=task.status,
        revoked_trips=len(revocable),
        revoked_notifications=len(notifications),
        drivers=drivers,
        executed_kept=executed_kept,
        accepted_trips=accepted_trips,
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
