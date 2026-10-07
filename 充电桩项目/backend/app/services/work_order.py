"""工单领域服务 —— PDF 3.4 模块 3：工单管理。

本模块是「硬约束代码化」的核心实现：
1. 子任务数量计算公式（PDF 3.4 子任务计算）由确定性代码保证；
2. 工单状态机（待接单/待完成/已完成/已取消/已退回）合法迁移由代码校验；
3. 逾期 / 紧急判定与定时提醒（PDF 3.4 定时任务检测、消息推送）由代码计算；
4. AI 只负责解释与建议（见 app/ai/nodes.py），不参与上述判定。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import (
    InspectFrequency,
    MessageType,
    SubtaskStatus,
    TimeStatus,
    WorkOrderStatus,
    WorkOrderType,
)
from app.core.errors import BizError, NotFoundError
from app.core.utils import daterange, gen_no, like_filter, safe_rate
from app.models import (
    ChargingPile,
    InspectionItem,
    InspectionRecord,
    Message,
    Station,
    User,
    WorkOrder,
    WorkOrderSubtask,
)

# 巡检频率 -> 每个巡检周期内的巡检次数（PDF 3.4 子任务公式中的“巡检频率”）
FREQUENCY_PER_CYCLE: dict[str, int] = {
    InspectFrequency.DAY.value: 30,
    InspectFrequency.WEEK.value: 4,
    InspectFrequency.MONTH.value: 1,
}

# 工单状态合法迁移图（PDF 3.4 工单处理 + 工单 tag）
STATUS_TRANSITIONS: dict[str, set[str]] = {
    WorkOrderStatus.PENDING_ACCEPT.value: {
        WorkOrderStatus.PENDING_DONE.value,
        WorkOrderStatus.RETURNED.value,
        WorkOrderStatus.CANCELLED.value,
    },
    WorkOrderStatus.PENDING_DONE.value: {
        WorkOrderStatus.COMPLETED.value,
        WorkOrderStatus.CANCELLED.value,
    },
    WorkOrderStatus.RETURNED.value: {
        WorkOrderStatus.PENDING_ACCEPT.value,  # 重新下发
        WorkOrderStatus.CANCELLED.value,
    },
    WorkOrderStatus.COMPLETED.value: set(),
    WorkOrderStatus.CANCELLED.value: set(),
}


# ---------------------------------------------------------------- 子任务计算


def calc_subtask_count(
    order_type: str,
    station_count: int,
    inspect_cycle: int,
    inspect_frequency: str,
    inspect_count: int = 1,
) -> int:
    """按 PDF 3.4 计算子任务数量。

    - 巡视 / 设备检查 / 其他：站点数量 × 巡检周期 × 巡检频率
    - 特巡：站点数量 × 巡检次数
    - 消缺：固定 1 个子任务
    """
    station_count = max(0, int(station_count))
    inspect_cycle = max(1, int(inspect_cycle))
    inspect_count = max(1, int(inspect_count))

    if order_type == WorkOrderType.DEFECT.value:
        return 1
    if order_type == WorkOrderType.SPECIAL.value:
        return station_count * inspect_count
    per_cycle = FREQUENCY_PER_CYCLE.get(inspect_frequency, 1)
    return station_count * inspect_cycle * per_cycle


def build_subtask_plan(
    order_type: str,
    stations: list[Station],
    inspect_start: date,
    inspect_end: date,
    inspect_cycle: int,
    inspect_frequency: str,
    inspect_count: int,
    assignee: User | None = None,
    piles_by_station: dict[str, list[ChargingPile]] | None = None,
) -> list[dict]:
    """生成子任务明细（含站点、计划日期、序号、执行人）。"""
    total = calc_subtask_count(
        order_type, len(stations), inspect_cycle, inspect_frequency, inspect_count
    )
    if total <= 0:
        return []

    plan: list[dict] = []
    if order_type == WorkOrderType.DEFECT.value:
        station = stations[0] if stations else None
        plan.append(
            {
                "sequence": 1,
                "station_id": station.id if station else None,
                "station_name": station.name if station else None,
                "pile_id": None,
                "pile_asset_code": None,
                "plan_date": inspect_start,
                "assignee_id": assignee.id if assignee else None,
                "assignee_name": assignee.real_name if assignee else None,
                "plan_time_window": "09:00-12:00",
                "route_order": 1,
            }
        )
        return plan

    if order_type == WorkOrderType.SPECIAL.value:
        # 站点 × 巡检次数：每个站点安排 inspect_count 次特巡
        seq = 0
        for station in stations:
            for n in range(inspect_count):
                seq += 1
                plan.append(
                    {
                        "sequence": seq,
                        "station_id": station.id,
                        "station_name": station.name,
                        "pile_id": None,
                        "pile_asset_code": None,
                        "plan_date": inspect_start + timedelta(days=n),
                        "assignee_id": assignee.id if assignee else None,
                        "assignee_name": assignee.real_name if assignee else None,
                        "plan_time_window": "09:00-12:00" if n % 2 == 0 else "14:00-17:00",
                        "route_order": seq,
                    }
                )
        return plan

    # 巡视 / 设备检查 / 其他：站点 × 周期 × 频率，按周期均匀铺开
    per_cycle = FREQUENCY_PER_CYCLE.get(inspect_frequency, 1)
    span_days = max(1, (inspect_end - inspect_start).days + 1)
    seq = 0
    for station in stations:
        piles = (piles_by_station or {}).get(station.id, [])
        for cycle_idx in range(max(1, inspect_cycle)):
            for freq_idx in range(per_cycle):
                seq += 1
                if total and total > 1:
                    offset = int(round((seq - 1) * (span_days - 1) / (total - 1)))
                else:
                    offset = 0
                pile = piles[(seq - 1) % len(piles)] if piles else None
                plan.append(
                    {
                        "sequence": seq,
                        "station_id": station.id,
                        "station_name": station.name,
                        "pile_id": pile.id if pile else None,
                        "pile_asset_code": pile.asset_code if pile else None,
                        "plan_date": inspect_start + timedelta(days=offset),
                        "assignee_id": assignee.id if assignee else None,
                        "assignee_name": assignee.real_name if assignee else None,
                        "plan_time_window": "09:00-12:00" if freq_idx % 2 == 0 else "14:00-17:00",
                        "route_order": seq,
                    }
                )
    return plan


# ---------------------------------------------------------------- 时间状态


def evaluate_time_status(order: WorkOrder, now: datetime | None = None) -> str:
    """判定工单时间状态：正常 / 紧急 / 逾期（PDF 3.4 工单 tag）。

    已完成的工单不再标记逾期。
    """
    now = now or datetime.now()
    if order.status == WorkOrderStatus.COMPLETED.value:
        return TimeStatus.NORMAL.value
    end = order.inspect_end_date
    if end is None:
        return TimeStatus.NORMAL.value
    end_dt = datetime.combine(end, datetime.max.time())
    if end_dt < now:
        return TimeStatus.OVERDUE.value
    if end_dt - now <= timedelta(hours=24):
        return TimeStatus.URGENT.value
    return TimeStatus.NORMAL.value


def refresh_time_status(order: WorkOrder, now: datetime | None = None) -> bool:
    """刷新工单时间状态，返回是否发生变化。"""
    new_status = evaluate_time_status(order, now)
    if order.time_status != new_status:
        order.time_status = new_status
        order.priority = "紧急" if new_status != TimeStatus.NORMAL.value else "正常"
        return True
    return False


def ensure_transition(current: str, target: str) -> None:
    """校验状态迁移合法性（硬约束）。"""
    allowed = STATUS_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise BizError(f"工单状态不允许从「{current}」变更为「{target}」")


# ---------------------------------------------------------------- 查询


async def list_orders(
    db: AsyncSession,
    *,
    keyword: str | None = None,
    order_no: str | None = None,
    order_name: str | None = None,
    station_name: str | None = None,
    order_type: str | None = None,
    status: str | None = None,
    time_status: str | None = None,
    inspector_id: str | None = None,
    project_id: str | None = None,
    station_id: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[WorkOrder], int]:
    """工单列表 + 复杂模糊查询 + 总数（PDF 3.4）。"""
    conditions = []
    kw_cond = like_filter(
        [WorkOrder.order_no, WorkOrder.order_name, WorkOrder.station_name], keyword
    )
    if kw_cond is not None:
        conditions.append(kw_cond)
    if order_no:
        conditions.append(WorkOrder.order_no.ilike(f"%{order_no}%"))
    if order_name:
        conditions.append(WorkOrder.order_name.ilike(f"%{order_name}%"))
    if station_name:
        conditions.append(WorkOrder.station_name.ilike(f"%{station_name}%"))
    if order_type:
        conditions.append(WorkOrder.order_type == order_type)
    if status:
        conditions.append(WorkOrder.status == status)
    if time_status:
        conditions.append(WorkOrder.time_status == time_status)
    if inspector_id:
        conditions.append(WorkOrder.inspector_id == inspector_id)
    if project_id:
        conditions.append(WorkOrder.project_id == project_id)
    if station_id:
        conditions.append(WorkOrder.station_id == station_id)
    if start_date:
        conditions.append(WorkOrder.inspect_start_date >= start_date)
    if end_date:
        conditions.append(WorkOrder.inspect_end_date <= end_date)

    base = select(WorkOrder)
    count_stmt = select(func.count(WorkOrder.id))
    for cond in conditions:
        base = base.where(cond)
        count_stmt = count_stmt.where(cond)

    total = int((await db.execute(count_stmt)).scalar() or 0)
    stmt = base.order_by(WorkOrder.created_at.desc()).limit(limit).offset(offset)
    rows = list((await db.execute(stmt)).scalars().all())
    return rows, total


async def get_order(db: AsyncSession, order_id: str) -> WorkOrder:
    order = await db.get(WorkOrder, order_id)
    if order is None:
        raise NotFoundError("工单不存在")
    return order


async def order_statistics(db: AsyncSession, **filters) -> dict:
    """工单首页统计：工单总数、待办工单、已办工单（PDF 3.4）。"""
    conditions = []
    if filters.get("project_id"):
        conditions.append(WorkOrder.project_id == filters["project_id"])
    if filters.get("station_id"):
        conditions.append(WorkOrder.station_id == filters["station_id"])
    if filters.get("inspector_id"):
        conditions.append(WorkOrder.inspector_id == filters["inspector_id"])

    def _apply(stmt):
        for c in conditions:
            stmt = stmt.where(c)
        return stmt

    total = int(
        (await db.execute(_apply(select(func.count(WorkOrder.id))))).scalar() or 0
    )
    done = int(
        (
            await db.execute(
                _apply(
                    select(func.count(WorkOrder.id)).where(
                        WorkOrder.status == WorkOrderStatus.COMPLETED.value
                    )
                )
            )
        ).scalar()
        or 0
    )
    pending = int(
        (
            await db.execute(
                _apply(
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
    overdue = int(
        (
            await db.execute(
                _apply(
                    select(func.count(WorkOrder.id)).where(
                        WorkOrder.time_status == TimeStatus.OVERDUE.value
                    )
                )
            )
        ).scalar()
        or 0
    )
    urgent = int(
        (
            await db.execute(
                _apply(
                    select(func.count(WorkOrder.id)).where(
                        WorkOrder.time_status == TimeStatus.URGENT.value
                    )
                )
            )
        ).scalar()
        or 0
    )
    type_rows = (
        await db.execute(
            _apply(
                select(WorkOrder.order_type, func.count(WorkOrder.id)).group_by(
                    WorkOrder.order_type
                )
            )
        )
    ).all()

    return {
        "total": total,
        "pending": pending,
        "done": done,
        "overdue": overdue,
        "urgent": urgent,
        "completion_rate": safe_rate(done, total),
        "overdue_rate": safe_rate(overdue, total),
        "order_type_dist": [
            {"name": t or "未分类", "value": int(c)} for t, c in type_rows
        ],
    }


# ---------------------------------------------------------------- 提醒


async def push_due_soon_messages(db: AsyncSession) -> dict:
    """定时任务：检测快过期工单并推送到运维人员消息列表（PDF 3.4）。"""
    now = datetime.now()
    threshold = now + timedelta(hours=24)

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
            )
        )
    ).scalars().all()

    created = 0
    for order in rows:
        changed = refresh_time_status(order, now)
        end_dt = (
            datetime.combine(order.inspect_end_date, datetime.max.time())
            if order.inspect_end_date
            else None
        )
        if end_dt is None:
            continue

        msg_type = None
        if end_dt < now:
            msg_type = MessageType.ORDER_OVERDUE.value
        elif end_dt <= threshold:
            msg_type = MessageType.ORDER_URGENT.value
        if msg_type is None:
            continue

        receiver_id = order.inspector_id or order.created_by
        if not receiver_id:
            continue

        # 同一工单同一类型只提醒一次
        exists = (
            await db.execute(
                select(func.count(Message.id)).where(
                    Message.work_order_id == order.id, Message.msg_type == msg_type
                )
            )
        ).scalar()
        if exists:
            continue

        db.add(
            Message(
                receiver_id=receiver_id,
                msg_type=msg_type,
                title=f"{msg_type}：{order.order_name}",
                content=(
                    f"工单 {order.order_no} 计划结束日期为 "
                    f"{order.inspect_end_date}，当前状态「{order.status}」。"
                ),
                detail=order_detail_payload(order),
                work_order_id=order.id,
                link=f"/work-orders/{order.id}",
            )
        )
        order.due_soon_notified = True
        created += 1

    if created:
        await db.commit()
    return {"scanned": len(rows), "messages_created": created}


def order_detail_payload(order: WorkOrder) -> dict:
    """消息详情字段（PDF 3.8：工单类型、编号、名称、项目、站点、巡检人员、日期、频率、次数）。"""
    return {
        "工单类型": order.order_type,
        "工单编号": order.order_no,
        "工单名称": order.order_name,
        "项目名称": order.project_id,
        "站点名称": order.station_name,
        "巡检人员": order.inspector_name,
        "巡检日期": (
            f"{order.inspect_start_date} ~ {order.inspect_end_date}"
            if order.inspect_start_date and order.inspect_end_date
            else None
        ),
        "巡检频率": order.inspect_frequency,
        "巡检次数": order.inspect_count,
        "备注": order.remark,
    }


# ---------------------------------------------------------------- 子任务 / 巡检


async def recalc_subtask_progress(db: AsyncSession, work_order_id: str) -> WorkOrder:
    """重算子任务完成进度，必要时把工单置为已完成。"""
    order = await get_order(db, work_order_id)
    rows = (
        await db.execute(
            select(WorkOrderSubtask.status, func.count(WorkOrderSubtask.id))
            .where(WorkOrderSubtask.work_order_id == work_order_id)
            .group_by(WorkOrderSubtask.status)
        )
    ).all()
    counts = {status: int(c) for status, c in rows}
    total = sum(counts.values())
    done = counts.get(SubtaskStatus.COMPLETED.value, 0)
    order.subtask_total = total
    order.subtask_done = done

    if total > 0 and done >= total and order.status in (
        WorkOrderStatus.PENDING_DONE.value,
        WorkOrderStatus.PENDING_ACCEPT.value,
    ):
        order.status = WorkOrderStatus.COMPLETED.value
        order.completed_at = datetime.now()
        order.time_status = TimeStatus.NORMAL.value
    return order


async def list_subtasks(
    db: AsyncSession,
    *,
    work_order_id: str | None = None,
    assignee_id: str | None = None,
    status: str | None = None,
    order_type: str | None = None,
    keyword: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[WorkOrderSubtask], int]:
    """子任务列表 —— 支撑 PDF 3.6 作业管理（作业任务列表 + 复杂模糊查询）。"""
    conditions = []
    if work_order_id:
        conditions.append(WorkOrderSubtask.work_order_id == work_order_id)
    if assignee_id:
        conditions.append(WorkOrderSubtask.assignee_id == assignee_id)
    if status:
        conditions.append(WorkOrderSubtask.status == status)
    if order_type:
        conditions.append(WorkOrderSubtask.order_type == order_type)
    kw_cond = like_filter(
        [
            WorkOrderSubtask.order_no,
            WorkOrderSubtask.order_name,
            WorkOrderSubtask.station_name,
        ],
        keyword,
    )
    if kw_cond is not None:
        conditions.append(kw_cond)

    base = select(WorkOrderSubtask)
    count_stmt = select(func.count(WorkOrderSubtask.id))
    for cond in conditions:
        base = base.where(cond)
        count_stmt = count_stmt.where(cond)

    total = int((await db.execute(count_stmt)).scalar() or 0)
    stmt = base.order_by(
        WorkOrderSubtask.plan_date.asc().nulls_last(),
        WorkOrderSubtask.sequence.asc(),
    ).limit(limit).offset(offset)
    return list((await db.execute(stmt)).scalars().all()), total


async def export_rows(db: AsyncSession, order_ids: list[str] | None = None) -> list[dict]:
    """工单导出数据（PDF 3.4 工单导出：根据 Excel 模板导出整个工单）。"""
    stmt = select(WorkOrder).order_by(WorkOrder.created_at.desc())
    if order_ids:
        stmt = stmt.where(WorkOrder.id.in_(order_ids))
    orders = list((await db.execute(stmt)).scalars().all())

    rows: list[dict] = []
    for order in orders:
        subtasks = (
            await db.execute(
                select(WorkOrderSubtask)
                .where(WorkOrderSubtask.work_order_id == order.id)
                .order_by(WorkOrderSubtask.sequence.asc())
            )
        ).scalars().all()
        if not subtasks:
            rows.append(
                {
                    "工单编号": order.order_no,
                    "工单名称": order.order_name,
                    "工单类型": order.order_type,
                    "站点名称": order.station_name,
                    "工单状态": order.status,
                    "时间状态": order.time_status,
                    "巡检人员": order.inspector_name,
                    "巡检开始日期": order.inspect_start_date,
                    "巡检结束日期": order.inspect_end_date,
                    "巡检频率": order.inspect_frequency,
                    "巡检次数": order.inspect_count,
                    "子任务序号": "",
                    "子任务状态": "",
                    "计划日期": "",
                }
            )
            continue
        for st in subtasks:
            rows.append(
                {
                    "工单编号": order.order_no,
                    "工单名称": order.order_name,
                    "工单类型": order.order_type,
                    "站点名称": st.station_name or order.station_name,
                    "工单状态": order.status,
                    "时间状态": order.time_status,
                    "巡检人员": st.assignee_name or order.inspector_name,
                    "巡检开始日期": order.inspect_start_date,
                    "巡检结束日期": order.inspect_end_date,
                    "巡检频率": order.inspect_frequency,
                    "巡检次数": order.inspect_count,
                    "子任务序号": st.sequence,
                    "子任务状态": st.status,
                    "计划日期": st.plan_date,
                }
            )
    return rows


async def inspection_detail(db: AsyncSession, order_id: str) -> dict:
    """巡检详情（PDF 3.4 巡检详情：任务情况显示、导出任务详情、动态显示）。"""
    order = await get_order(db, order_id)
    subtasks = (
        await db.execute(
            select(WorkOrderSubtask)
            .where(WorkOrderSubtask.work_order_id == order_id)
            .order_by(WorkOrderSubtask.sequence.asc())
        )
    ).scalars().all()

    details = []
    for st in subtasks:
        records = (
            await db.execute(
                select(InspectionRecord).where(InspectionRecord.subtask_id == st.id)
            )
        ).scalars().all()
        items = (
            await db.execute(
                select(InspectionItem).where(InspectionItem.work_order_id == order_id)
            )
        ).scalars().all()
        details.append(
            {
                "subtask_id": st.id,
                "sequence": st.sequence,
                "station_name": st.station_name,
                "pile_asset_code": st.pile_asset_code,
                "status": st.status,
                "plan_date": st.plan_date,
                "assignee_name": st.assignee_name,
                "records": [
                    {
                        "id": r.id,
                        "checkin_time": r.checkin_time,
                        "checkout_time": r.checkout_time,
                        "checkin_location": r.checkin_location,
                        "checkout_location": r.checkout_location,
                        "images": r.images or [],
                        "normal_count": r.normal_count,
                        "abnormal_count": r.abnormal_count,
                        "remark": r.remark,
                        "status": r.status,
                        "content": r.content or {},
                    }
                    for r in records
                ],
                "items": [
                    {
                        "id": i.id,
                        "item_name": i.item_name,
                        "item_group": i.item_group,
                        "result": i.result,
                        "remark": i.remark,
                        "pile_asset_code": i.pile_asset_code,
                        "images": i.images or [],
                    }
                    for i in items
                ],
            }
        )

    return {
        "work_order": {
            "id": order.id,
            "order_no": order.order_no,
            "order_name": order.order_name,
            "order_type": order.order_type,
            "status": order.status,
            "time_status": order.time_status,
            "station_names": order.station_names or ([order.station_name] if order.station_name else []),
            "inspect_start_date": order.inspect_start_date,
            "inspect_end_date": order.inspect_end_date,
            "inspect_frequency": order.inspect_frequency,
            "inspect_count": order.inspect_count,
            "subtask_total": order.subtask_total,
            "subtask_done": order.subtask_done,
        },
        "subtasks": details,
    }
