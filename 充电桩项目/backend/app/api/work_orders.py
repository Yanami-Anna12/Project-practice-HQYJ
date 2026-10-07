"""工单接口 —— PDF 5.1 小程序/员工端核心接口 + 3.4 模块 3：工单管理。

/api/v1/work-orders                     工单列表（复杂模糊查询）
/api/v1/work-orders/home                工单首页（总数/待办/已办）
/api/v1/work-orders                     工单申请
/api/v1/work-orders/subtasks/mine       我的作业任务
/api/v1/work-orders/inspections         巡检录入 / 记录
/api/v1/work-orders/{id}                工单详情
/api/v1/work-orders/{id}/accept         接受工单
/api/v1/work-orders/{id}/reject         退回工单
/api/v1/work-orders/{id}/cancel         取消工单
/api/v1/work-orders/{id}/redispatch     重新下发
/api/v1/work-orders/{id}/subtasks       子任务列表
/api/v1/work-orders/{id}/inspection     巡检详情
/api/v1/work-orders/export              工单导出

注意：静态路径必须注册在 /{order_id} 之前，否则会被路径参数吞掉。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Query
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.deps import CurrentUser, DbSession, paginate, scope_of
from app.core.enums import (
    DataScope,
    MessageType,
    SubtaskStatus,
    TimeStatus,
    WorkOrderStatus,
    WorkOrderType,
)
from app.core.errors import BizError, NotFoundError
from app.core.response import ApiResponse, PageData
from app.core.utils import gen_no
from app.models import ChargingPile, Message, Station, User, WorkOrder, WorkOrderSubtask
from app.schemas import (
    InspectionCreate,
    InspectionOut,
    OrderActionRequest,
    SubtaskAssignRequest,
    SubtaskOut,
    WorkOrderCreate,
    WorkOrderOut,
    WorkOrderUpdate,
)
from app.services import audit as audit_service
from app.services import export as export_service
from app.services import inspection as inspection_service
from app.services import work_order as wo_service

router = APIRouter(prefix="/work-orders", tags=["工单管理"])


# ================================================================ 首页 / 列表


@router.get("/home", response_model=ApiResponse[dict], summary="工单首页统计")
async def work_order_home(
    db: DbSession,
    user: CurrentUser,
    project_id: str | None = None,
    station_id: str | None = None,
):
    """工单总数、待办工单、已办工单（PDF 3.4 工单首页，分权限显示）。"""
    scope = scope_of(user)
    filters: dict = {}
    if scope == DataScope.PROJECT.value:
        filters["project_id"] = user.project_id
    elif scope == DataScope.STATION.value:
        filters["station_id"] = user.station_id
    elif scope == DataScope.PERSONAL.value:
        filters["inspector_id"] = user.id
    else:
        filters["project_id"] = project_id
        filters["station_id"] = station_id

    stats = await wo_service.order_statistics(db, **filters)
    stats["data_scope"] = scope
    stats["scope_label"] = f"{scope}管理员" if scope != DataScope.PERSONAL.value else "个人视图"
    return ApiResponse.ok(stats)


@router.get("", response_model=ApiResponse[PageData[WorkOrderOut]], summary="工单列表")
async def list_work_orders(
    db: DbSession,
    user: CurrentUser,
    keyword: str | None = Query(default=None, description="工单编号/名称/站点名称 模糊查询"),
    order_no: str | None = None,
    order_name: str | None = None,
    station_name: str | None = None,
    order_type: str | None = Query(default=None, description="巡视/特巡/消缺/设备检查/其他"),
    status: str | None = Query(default=None, description="待接单/待完成/已完成/已取消/已退回"),
    time_status: str | None = Query(default=None, description="正常/紧急/逾期"),
    project_id: str | None = None,
    station_id: str | None = None,
    inspector_id: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    mine: bool = Query(default=False, description="只看与我相关"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
):
    limit, offset = paginate(page, page_size)

    scope = scope_of(user)
    if mine or scope == DataScope.PERSONAL.value:
        inspector_id = user.id
    if scope == DataScope.PROJECT.value:
        project_id = user.project_id
    elif scope == DataScope.STATION.value:
        station_id = station_id or user.station_id

    rows, total = await wo_service.list_orders(
        db,
        keyword=keyword,
        order_no=order_no,
        order_name=order_name,
        station_name=station_name,
        order_type=order_type,
        status=status,
        time_status=time_status,
        inspector_id=inspector_id,
        project_id=project_id,
        station_id=station_id,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
    )

    now = datetime.now()
    items = []
    dirty = False
    for r in rows:
        if wo_service.refresh_time_status(r, now):
            dirty = True
        items.append(WorkOrderOut.model_validate(r))
    if dirty:
        await db.commit()

    return ApiResponse.ok(PageData.build(items, total, page, page_size))


# ================================================================ 我的作业任务


@router.get(
    "/subtasks/mine",
    response_model=ApiResponse[PageData[SubtaskOut]],
    summary="我的作业任务（作业管理）",
)
async def my_subtasks(
    db: DbSession,
    user: CurrentUser,
    keyword: str | None = Query(default=None, description="工单编号/名称/站点 模糊查询"),
    status: str | None = None,
    order_type: str | None = None,
    scope_all: bool = Query(default=False, description="管理员查看全部"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
):
    """作业任务列表（PDF 3.6 模块 5：复杂模糊查询 + 任务卡片展示）。"""
    assignee_id = None
    if not (scope_all and scope_of(user) != DataScope.PERSONAL.value):
        assignee_id = user.id
    rows, total = await wo_service.list_subtasks(
        db,
        assignee_id=assignee_id,
        status=status,
        order_type=order_type,
        keyword=keyword,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    return ApiResponse.ok(
        PageData.build([SubtaskOut.model_validate(s) for s in rows], total, page, page_size)
    )


@router.put(
    "/subtasks/{subtask_id}",
    response_model=ApiResponse[SubtaskOut],
    summary="更新子任务（分配 / 状态 / 计划日期）",
)
async def update_subtask(subtask_id: str, payload: dict, db: DbSession, user: CurrentUser):
    subtask = await db.get(WorkOrderSubtask, subtask_id)
    if subtask is None:
        raise NotFoundError("子任务不存在")

    changed: dict = {}
    if payload.get("assignee_id"):
        assignee = await db.get(User, payload["assignee_id"])
        if assignee is None:
            raise NotFoundError("执行人不存在")
        subtask.assignee_id = assignee.id
        subtask.assignee_name = assignee.real_name
        changed["执行人"] = assignee.real_name
    if payload.get("status"):
        status_value = payload["status"]
        if status_value not in {e.value for e in SubtaskStatus}:
            raise BizError(f"非法子任务状态：{status_value}")
        subtask.status = status_value
        changed["状态"] = status_value
        if status_value == SubtaskStatus.COMPLETED.value:
            subtask.completed_at = datetime.now()
    if payload.get("plan_date"):
        subtask.plan_date = date.fromisoformat(str(payload["plan_date"])[:10])
        changed["计划日期"] = str(subtask.plan_date)
    if payload.get("plan_time_window"):
        subtask.plan_time_window = payload["plan_time_window"]

    order = await wo_service.recalc_subtask_progress(db, subtask.work_order_id)
    await db.commit()
    await db.refresh(subtask)

    await audit_service.log_operation(
        db,
        module="作业管理",
        action="更新子任务",
        user=user,
        target_type="subtask",
        target_id=subtask_id,
        description=f"更新子任务 #{subtask.sequence}：{changed}",
        after=changed,
    )
    if order.status == WorkOrderStatus.COMPLETED.value:
        return ApiResponse.ok(
            SubtaskOut.model_validate(subtask), message="该工单全部子任务已完成，工单已自动结单"
        )
    return ApiResponse.ok(SubtaskOut.model_validate(subtask))


# ================================================================ 巡检


@router.get("/inspections/template", response_model=ApiResponse[dict], summary="巡检项模板")
async def inspection_template(
    db: DbSession, user: CurrentUser, order_type: str = Query(default="巡视")
):
    """分类巡检项模板（PDF 3.4：分类显示、正常/异常勾选、200 字备注）。"""
    return ApiResponse.ok(await inspection_service.inspection_overview(db, order_type))


@router.post("/inspections", response_model=ApiResponse[InspectionOut], summary="巡检情况录入")
async def create_inspection(payload: InspectionCreate, db: DbSession, user: CurrentUser):
    record = await inspection_service.save_inspection(
        db,
        subtask_id=payload.subtask_id,
        inspector=user,
        items=[i.model_dump() for i in payload.items],
        images=payload.images,
        remark=payload.remark,
        checkin_location=payload.checkin_location,
        checkin_lng=payload.checkin_lng,
        checkin_lat=payload.checkin_lat,
        checkout_location=payload.checkout_location,
        checkout_lng=payload.checkout_lng,
        checkout_lat=payload.checkout_lat,
        finish=payload.finish,
    )
    await audit_service.log_operation(
        db,
        module="巡检管理",
        action="巡检录入",
        user=user,
        target_type="inspection",
        target_id=record.id,
        description=(
            f"站点 {record.station_name or '-'} 巡检录入：正常 {record.normal_count} 项，"
            f"异常 {record.abnormal_count} 项，状态 {record.status}"
        ),
    )
    return ApiResponse.ok(InspectionOut.model_validate(record))


@router.get(
    "/inspections",
    response_model=ApiResponse[PageData[InspectionOut]],
    summary="巡检记录列表",
)
async def list_inspections(
    db: DbSession,
    user: CurrentUser,
    work_order_id: str | None = None,
    station_id: str | None = None,
    keyword: str | None = None,
    mine: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
):
    rows, total = await inspection_service.list_inspections(
        db,
        work_order_id=work_order_id,
        inspector_id=user.id if mine else None,
        station_id=station_id,
        keyword=keyword,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    return ApiResponse.ok(
        PageData.build([InspectionOut.model_validate(r) for r in rows], total, page, page_size)
    )


# ================================================================ 工单导出


@router.post("/export", response_model=ApiResponse[dict], summary="工单导出（创建任务）")
async def export_work_orders(
    db: DbSession,
    user: CurrentUser,
    background: BackgroundTasks,
    payload: dict | None = None,
):
    """工单导出（PDF 3.4）：返回任务 ID，前端轮询进度并展示加载动画与提示。"""
    payload = payload or {}
    order_ids = payload.get("order_ids") or None
    task = export_service.create_task("work_order", "工单导出报表", operator=user.real_name)
    task_id = task["task_id"]
    operator = user.real_name

    async def _run() -> None:
        async with AsyncSessionLocal() as bg_db:
            try:
                await export_service.export_work_orders(
                    bg_db, task_id=task_id, operator=operator, order_ids=order_ids
                )
            except Exception as exc:  # pragma: no cover
                export_service.update_task(
                    task_id, status="failed", message=f"导出失败：{exc}", error=str(exc)
                )

    background.add_task(_run)
    await audit_service.log_operation(
        db,
        module="工单管理",
        action="工单导出",
        user=user,
        description="发起工单导出任务",
        target_type="export",
        target_id=task_id,
    )
    return ApiResponse.ok(task, message="导出任务已创建，请轮询进度")


# ================================================================ 工单申请


@router.post("", response_model=ApiResponse[WorkOrderOut], summary="工单申请")
async def create_work_order(
    payload: WorkOrderCreate,
    db: DbSession,
    user: CurrentUser,
    background: BackgroundTasks,
):
    """工单申请（PDF 3.4）：巡视/特巡/消缺/设备检查/其他，按公式自动生成子任务。"""
    inspector: User | None = None
    if payload.inspector_id:
        inspector = await db.get(User, payload.inspector_id)
        if inspector is None:
            raise NotFoundError("指定的巡检人员不存在")

    stations: list[Station] = []
    if payload.station_ids:
        stations = list(
            (
                await db.execute(select(Station).where(Station.id.in_(payload.station_ids)))
            ).scalars().all()
        )
        missing = set(payload.station_ids) - {s.id for s in stations}
        if missing:
            raise BizError(f"以下站点不存在：{', '.join(missing)}")
    elif payload.project_id:
        stations = list(
            (
                await db.execute(
                    select(Station).where(
                        Station.project_id == payload.project_id, Station.status.is_(True)
                    )
                )
            ).scalars().all()
        )
    if not stations:
        raise BizError("请至少选择一个站点")

    today = date.today()
    start = payload.inspect_start_date or today
    if payload.order_type == WorkOrderType.DEFECT.value:
        end = payload.inspect_end_date or (start + timedelta(days=1))
    elif payload.order_type == WorkOrderType.SPECIAL.value:
        end = payload.inspect_end_date or (
            start + timedelta(days=max(1, payload.inspect_count))
        )
    else:
        end = payload.inspect_end_date or (
            start + timedelta(days=max(1, payload.inspect_cycle) * 30)
        )
    if end < start:
        raise BizError("巡检结束日期不能早于开始日期")

    total_subtasks = wo_service.calc_subtask_count(
        payload.order_type,
        len(stations),
        payload.inspect_cycle,
        payload.inspect_frequency,
        payload.inspect_count,
    )

    piles_by_station: dict[str, list[ChargingPile]] = {}
    pile_rows = (
        await db.execute(
            select(ChargingPile).where(ChargingPile.station_id.in_([s.id for s in stations]))
        )
    ).scalars().all()
    for pile in pile_rows:
        piles_by_station.setdefault(pile.station_id or "", []).append(pile)

    order = WorkOrder(
        order_no=gen_no("WO"),
        order_name=payload.order_name,
        order_type=payload.order_type,
        project_id=payload.project_id or stations[0].project_id,
        station_id=stations[0].id if len(stations) == 1 else None,
        station_name="、".join(s.name for s in stations[:3]),
        station_address=stations[0].address if len(stations) == 1 else None,
        station_ids=[s.id for s in stations],
        station_names=[s.name for s in stations],
        status=WorkOrderStatus.PENDING_ACCEPT.value,
        time_status=TimeStatus.NORMAL.value,
        inspector_id=inspector.id if inspector else None,
        inspector_name=inspector.real_name if inspector else None,
        inspect_start_date=start,
        inspect_end_date=end,
        inspect_frequency=payload.inspect_frequency,
        inspect_count=payload.inspect_count,
        inspect_cycle=payload.inspect_cycle,
        subtask_total=total_subtasks,
        remark=payload.remark,
        source="手工",
        created_by=user.id,
    )
    db.add(order)
    await db.flush()

    plan = wo_service.build_subtask_plan(
        order_type=payload.order_type,
        stations=stations,
        inspect_start=start,
        inspect_end=end,
        inspect_cycle=payload.inspect_cycle,
        inspect_frequency=payload.inspect_frequency,
        inspect_count=payload.inspect_count,
        assignee=inspector,
        piles_by_station=piles_by_station,
    )
    for item in plan:
        db.add(
            WorkOrderSubtask(
                work_order_id=order.id,
                order_no=order.order_no,
                order_name=order.order_name,
                order_type=order.order_type,
                station_id=item["station_id"],
                station_name=item["station_name"],
                pile_id=item["pile_id"],
                pile_asset_code=item["pile_asset_code"],
                sequence=item["sequence"],
                plan_date=item["plan_date"],
                plan_time_window=item["plan_time_window"],
                status=SubtaskStatus.PENDING.value,
                assignee_id=item["assignee_id"],
                assignee_name=item["assignee_name"],
                route_order=item["route_order"],
            )
        )

    if inspector:
        db.add(
            Message(
                receiver_id=inspector.id,
                msg_type=MessageType.ORDER_ASSIGNED.value,
                title=f"新工单待接单：{order.order_name}",
                content=(
                    f"工单 {order.order_no}（{order.order_type}）共 {total_subtasks} 个子任务，"
                    f"巡检周期 {start} ~ {end}。"
                ),
                detail=wo_service.order_detail_payload(order),
                work_order_id=order.id,
                link=f"/work-orders/{order.id}",
            )
        )

    await db.commit()
    await db.refresh(order)

    await audit_service.log_operation(
        db,
        module="工单管理",
        action="工单申请",
        user=user,
        target_type="work_order",
        target_id=order.id,
        description=(
            f"创建{order.order_type}工单 {order.order_no}，站点 {len(stations)} 个，"
            f"按公式生成 {total_subtasks} 个子任务"
        ),
        after={
            "order_no": order.order_no,
            "order_type": order.order_type,
            "subtask_total": total_subtasks,
            "formula": (
                f"站点数 {len(stations)} × 周期 {payload.inspect_cycle} "
                f"× 频率 {payload.inspect_frequency}"
            ),
        },
    )

    if payload.auto_dispatch:
        from app.ai.agent_service import create_agent_task, run_task_async

        agent_payload = {
            "order_type": payload.order_type,
            "station_ids": [s.id for s in stations],
            "inspect_cycle": payload.inspect_cycle,
            "inspect_frequency": payload.inspect_frequency,
            "inspect_count": payload.inspect_count,
            "order_name": f"{payload.order_name}（AI 优化排期）",
            "use_llm": True,
            "created_by": user.id,
        }
        task = await create_agent_task(
            db,
            agent_type="智能工单调度",
            request_payload=agent_payload,
            user=user,
            task_name=f"工单 {order.order_no} 排期优化",
            project_id=order.project_id,
            schedule_date=start,
        )
        background.add_task(run_task_async, task.id, agent_payload)
        return ApiResponse.ok(
            WorkOrderOut.model_validate(order),
            message=f"工单创建成功，已提交 AI 排期优化任务（{task.task_no}）",
        )

    return ApiResponse.ok(
        WorkOrderOut.model_validate(order),
        message=f"工单创建成功，按公式生成 {total_subtasks} 个子任务",
    )


# ================================================================ 详情 / 操作（含路径参数，须最后注册）


@router.get("/{order_id}", response_model=ApiResponse[dict], summary="工单详情")
async def get_work_order(order_id: str, db: DbSession, user: CurrentUser):
    order = await wo_service.get_order(db, order_id)
    if wo_service.refresh_time_status(order):
        await db.commit()

    subtasks = (
        await db.execute(
            select(WorkOrderSubtask)
            .where(WorkOrderSubtask.work_order_id == order_id)
            .order_by(WorkOrderSubtask.sequence)
        )
    ).scalars().all()

    station_names = {
        s.id: s.name for s in (await db.execute(select(Station))).scalars().all()
    }
    return ApiResponse.ok(
        {
            "work_order": WorkOrderOut.model_validate(order).model_dump(),
            "subtasks": [SubtaskOut.model_validate(s).model_dump() for s in subtasks],
            "subtask_stats": {
                "total": len(subtasks),
                "pending": sum(1 for s in subtasks if s.status == SubtaskStatus.PENDING.value),
                "in_progress": sum(
                    1 for s in subtasks if s.status == SubtaskStatus.IN_PROGRESS.value
                ),
                "completed": sum(
                    1 for s in subtasks if s.status == SubtaskStatus.COMPLETED.value
                ),
            },
            "stations": [
                station_names.get(sid)
                for sid in (order.station_ids or [])
                if station_names.get(sid)
            ],
            "permissions": {
                "can_accept": order.status == WorkOrderStatus.PENDING_ACCEPT.value,
                "can_reject": order.status == WorkOrderStatus.PENDING_ACCEPT.value,
                "can_cancel": order.status
                in (
                    WorkOrderStatus.PENDING_ACCEPT.value,
                    WorkOrderStatus.PENDING_DONE.value,
                    WorkOrderStatus.RETURNED.value,
                ),
                "can_redispatch": order.status == WorkOrderStatus.RETURNED.value,
                "can_inspect": order.status
                in (
                    WorkOrderStatus.PENDING_ACCEPT.value,
                    WorkOrderStatus.PENDING_DONE.value,
                ),
            },
        }
    )


@router.put("/{order_id}", response_model=ApiResponse[WorkOrderOut], summary="编辑工单")
async def update_work_order(
    order_id: str, payload: WorkOrderUpdate, db: DbSession, user: CurrentUser
):
    order = await wo_service.get_order(db, order_id)
    if order.status == WorkOrderStatus.COMPLETED.value:
        raise BizError("已完成的工单不允许修改")

    before = {
        "order_name": order.order_name,
        "inspector_id": order.inspector_id,
        "inspect_frequency": order.inspect_frequency,
        "inspect_cycle": order.inspect_cycle,
        "inspect_count": order.inspect_count,
        "subtask_total": order.subtask_total,
    }

    if payload.order_name is not None:
        order.order_name = payload.order_name
    if payload.inspector_id is not None:
        inspector = await db.get(User, payload.inspector_id)
        if inspector is None:
            raise NotFoundError("巡检人员不存在")
        order.inspector_id = inspector.id
        order.inspector_name = inspector.real_name
    if payload.inspect_start_date is not None:
        order.inspect_start_date = payload.inspect_start_date
    if payload.inspect_end_date is not None:
        order.inspect_end_date = payload.inspect_end_date
    if payload.remark is not None:
        order.remark = payload.remark
    if payload.priority is not None:
        order.priority = payload.priority

    recount = False
    if payload.inspect_frequency is not None:
        order.inspect_frequency = payload.inspect_frequency
        recount = True
    if payload.inspect_cycle is not None:
        order.inspect_cycle = payload.inspect_cycle
        recount = True
    if payload.inspect_count is not None:
        order.inspect_count = payload.inspect_count
        recount = True

    if recount:
        station_count = len(
            order.station_ids or ([order.station_id] if order.station_id else [])
        )
        order.subtask_total = wo_service.calc_subtask_count(
            order.order_type,
            station_count,
            order.inspect_cycle,
            order.inspect_frequency,
            order.inspect_count,
        )

    await db.commit()
    await db.refresh(order)
    await audit_service.log_operation(
        db,
        module="工单管理",
        action="编辑工单",
        user=user,
        target_type="work_order",
        target_id=order.id,
        description=f"编辑工单 {order.order_no}" + ("（已重算子任务数量）" if recount else ""),
        before=before,
        after={"order_name": order.order_name, "subtask_total": order.subtask_total},
    )
    return ApiResponse.ok(WorkOrderOut.model_validate(order))


@router.post("/{order_id}/accept", response_model=ApiResponse[dict], summary="接受工单")
async def accept_work_order(order_id: str, db: DbSession, user: CurrentUser):
    order = await wo_service.get_order(db, order_id)
    wo_service.ensure_transition(order.status, WorkOrderStatus.PENDING_DONE.value)
    order.status = WorkOrderStatus.PENDING_DONE.value
    order.accepted_at = datetime.now()
    if not order.inspector_id:
        order.inspector_id = user.id
        order.inspector_name = user.real_name
    await db.commit()
    await audit_service.log_operation(
        db,
        module="工单管理",
        action="接受工单",
        user=user,
        target_type="work_order",
        target_id=order.id,
        description=f"接受工单 {order.order_no}",
        after={"status": order.status},
    )
    return ApiResponse.ok({"status": order.status, "accepted_at": order.accepted_at})


@router.post("/{order_id}/reject", response_model=ApiResponse[dict], summary="退回工单")
async def reject_work_order(
    order_id: str, payload: OrderActionRequest, db: DbSession, user: CurrentUser
):
    order = await wo_service.get_order(db, order_id)
    wo_service.ensure_transition(order.status, WorkOrderStatus.RETURNED.value)
    order.status = WorkOrderStatus.RETURNED.value
    order.reject_reason = payload.reason or "未填写退回原因"

    if order.created_by:
        db.add(
            Message(
                receiver_id=order.created_by,
                msg_type=MessageType.ORDER_RETURNED.value,
                title=f"工单退回提醒：{order.order_name}",
                content=f"工单 {order.order_no} 已被退回，原因：{order.reject_reason}",
                detail={
                    **wo_service.order_detail_payload(order),
                    "退回原因": order.reject_reason,
                },
                work_order_id=order.id,
                link=f"/work-orders/{order.id}",
            )
        )
    await db.commit()

    await audit_service.log_operation(
        db,
        module="工单管理",
        action="退回工单",
        user=user,
        target_type="work_order",
        target_id=order.id,
        description=f"退回工单 {order.order_no}，原因：{order.reject_reason}",
        after={"status": order.status, "reason": order.reject_reason},
    )
    return ApiResponse.ok({"status": order.status, "reject_reason": order.reject_reason})


@router.post("/{order_id}/cancel", response_model=ApiResponse[dict], summary="取消工单")
async def cancel_work_order(
    order_id: str, payload: OrderActionRequest, db: DbSession, user: CurrentUser
):
    order = await wo_service.get_order(db, order_id)
    wo_service.ensure_transition(order.status, WorkOrderStatus.CANCELLED.value)
    order.status = WorkOrderStatus.CANCELLED.value
    order.cancel_reason = payload.reason or "未填写取消原因"

    subtasks = (
        await db.execute(
            select(WorkOrderSubtask).where(WorkOrderSubtask.work_order_id == order_id)
        )
    ).scalars().all()
    for sub in subtasks:
        if sub.status != SubtaskStatus.COMPLETED.value:
            sub.status = SubtaskStatus.CANCELLED.value

    receivers = {sub.assignee_id for sub in subtasks if sub.assignee_id}
    if order.inspector_id:
        receivers.add(order.inspector_id)
    for rid in receivers:
        db.add(
            Message(
                receiver_id=rid,
                msg_type=MessageType.ORDER_CANCELLED.value,
                title=f"工单取消提醒：{order.order_name}",
                content=f"工单 {order.order_no} 已取消，原因：{order.cancel_reason}",
                detail={
                    **wo_service.order_detail_payload(order),
                    "取消原因": order.cancel_reason,
                },
                work_order_id=order.id,
                link=f"/work-orders/{order.id}",
            )
        )

    await db.commit()
    await audit_service.log_operation(
        db,
        module="工单管理",
        action="取消工单",
        user=user,
        target_type="work_order",
        target_id=order.id,
        description=f"取消工单 {order.order_no}，原因：{order.cancel_reason}",
        after={"status": order.status, "reason": order.cancel_reason},
    )
    return ApiResponse.ok({"status": order.status, "cancel_reason": order.cancel_reason})


@router.post("/{order_id}/redispatch", response_model=ApiResponse[dict], summary="重新下发工单")
async def redispatch_work_order(
    order_id: str, payload: SubtaskAssignRequest, db: DbSession, user: CurrentUser
):
    """已退回的工单可重新下发（PDF 3.4：已退回取消 / 重新下发）。"""
    order = await wo_service.get_order(db, order_id)
    if order.status != WorkOrderStatus.RETURNED.value:
        raise BizError(f"仅「已退回」状态的工单可重新下发，当前状态：{order.status}")

    assignee = await db.get(User, payload.assignee_id)
    if assignee is None:
        raise NotFoundError("执行人不存在")

    order.status = WorkOrderStatus.PENDING_ACCEPT.value
    order.inspector_id = assignee.id
    order.inspector_name = assignee.real_name
    order.reject_reason = None

    subtasks = (
        await db.execute(
            select(WorkOrderSubtask).where(
                WorkOrderSubtask.work_order_id == order_id,
                WorkOrderSubtask.status != SubtaskStatus.COMPLETED.value,
            )
        )
    ).scalars().all()
    for sub in subtasks:
        sub.assignee_id = assignee.id
        sub.assignee_name = assignee.real_name
        sub.status = SubtaskStatus.PENDING.value
        if payload.plan_date:
            sub.plan_date = payload.plan_date
        if payload.plan_time_window:
            sub.plan_time_window = payload.plan_time_window

    db.add(
        Message(
            receiver_id=assignee.id,
            msg_type=MessageType.ORDER_ASSIGNED.value,
            title=f"工单重新下发：{order.order_name}",
            content=f"工单 {order.order_no} 已重新下发给你，请及时接单。",
            detail=wo_service.order_detail_payload(order),
            work_order_id=order.id,
            link=f"/work-orders/{order.id}",
        )
    )
    await db.commit()
    await audit_service.log_operation(
        db,
        module="工单管理",
        action="重新下发工单",
        user=user,
        target_type="work_order",
        target_id=order.id,
        description=f"工单 {order.order_no} 重新下发给 {assignee.real_name}",
    )
    return ApiResponse.ok(
        {
            "status": order.status,
            "inspector_name": order.inspector_name,
            "subtasks": len(subtasks),
        }
    )


@router.get(
    "/{order_id}/subtasks",
    response_model=ApiResponse[PageData[SubtaskOut]],
    summary="子任务列表（待完成子任务）",
)
async def list_order_subtasks(
    order_id: str,
    db: DbSession,
    user: CurrentUser,
    status: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    await wo_service.get_order(db, order_id)
    rows, total = await wo_service.list_subtasks(
        db,
        work_order_id=order_id,
        status=status,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    return ApiResponse.ok(
        PageData.build([SubtaskOut.model_validate(s) for s in rows], total, page, page_size)
    )


@router.get("/{order_id}/inspection", response_model=ApiResponse[dict], summary="巡检详情")
async def inspection_detail(order_id: str, db: DbSession, user: CurrentUser):
    """巡检详情（PDF 3.4：任务情况显示、导出任务详情、动态显示）。"""
    return ApiResponse.ok(await wo_service.inspection_detail(db, order_id))
