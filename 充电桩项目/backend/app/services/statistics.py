"""统计分析与看板服务 —— PDF 3.9 模块 8：统计分析与看板。

工单统计（总数/待办/已办/完成率）、5 种工单数量分布、逾期率、
项目工单排名、站点消缺工单排名、数据导出，以及统计日报落库。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import FaultStatus, TimeStatus, WorkOrderStatus, WorkOrderType
from app.core.utils import month_range, safe_rate, week_range
from app.models import (
    FaultReport,
    InspectionRecord,
    Project,
    Station,
    StatisticsDaily,
    WorkOrder,
)


def resolve_period(
    period: str | None, year: int | None, month: int | None
) -> tuple[date, date]:
    """下拉框联动年月选择框（PDF 3.9）。"""
    today = date.today()
    if year and month:
        anchor = date(year, month, 1)
        if period == "week":
            return week_range(anchor)
        if period == "day":
            return anchor, anchor
        return month_range(anchor)
    if period == "week":
        return week_range(today)
    if period == "day":
        return today, today
    if period == "quarter":
        q_start_month = ((today.month - 1) // 3) * 3 + 1
        start = date(today.year, q_start_month, 1)
        end_anchor = date(today.year, q_start_month + 2, 1)
        return start, month_range(end_anchor)[1]
    if period == "year":
        return date(today.year, 1, 1), date(today.year, 12, 31)
    return month_range(today)


def _scope_conditions(
    project_id: str | None, station_id: str | None
) -> list:
    conds = []
    if project_id:
        conds.append(WorkOrder.project_id == project_id)
    if station_id:
        conds.append(WorkOrder.station_id == station_id)
    return conds


async def dashboard_overview(
    db: AsyncSession,
    *,
    period: str | None = "month",
    year: int | None = None,
    month: int | None = None,
    project_id: str | None = None,
    station_id: str | None = None,
) -> dict:
    """统计看板主数据（PDF 3.9）。"""
    start, end = resolve_period(period, year, month)
    start_dt = datetime.combine(start, datetime.min.time())
    end_dt = datetime.combine(end, datetime.max.time())

    conds = _scope_conditions(project_id, station_id)
    conds.append(WorkOrder.created_at >= start_dt)
    conds.append(WorkOrder.created_at <= end_dt)

    def _apply(stmt):
        for c in conds:
            stmt = stmt.where(c)
        return stmt

    total = int((await db.execute(_apply(select(func.count(WorkOrder.id))))).scalar() or 0)
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

    # 5 种工单数量分布（PDF 3.9）
    type_rows = (
        await db.execute(
            _apply(
                select(WorkOrder.order_type, func.count(WorkOrder.id)).group_by(
                    WorkOrder.order_type
                )
            )
        )
    ).all()
    type_map = {t: int(c) for t, c in type_rows}
    order_type_dist = [
        {"name": t.value, "value": type_map.get(t.value, 0)} for t in WorkOrderType
    ]

    # 时间状态分布
    time_rows = (
        await db.execute(
            _apply(
                select(WorkOrder.time_status, func.count(WorkOrder.id)).group_by(
                    WorkOrder.time_status
                )
            )
        )
    ).all()

    # 项目工单排名
    project_rows = (
        await db.execute(
            _apply(
                select(
                    WorkOrder.project_id,
                    func.count(WorkOrder.id).label("cnt"),
                )
                .group_by(WorkOrder.project_id)
                .order_by(func.count(WorkOrder.id).desc())
                .limit(10)
            )
        )
    ).all()
    project_names = {
        p.id: p.name for p in (await db.execute(select(Project))).scalars().all()
    }
    project_rank = [
        {
            "project_id": pid,
            "name": project_names.get(pid or "", "未分配项目"),
            "value": int(cnt),
        }
        for pid, cnt in project_rows
    ]

    # 站点消缺工单排名
    defect_rows = (
        await db.execute(
            _apply(
                select(
                    WorkOrder.station_name,
                    func.count(WorkOrder.id).label("cnt"),
                )
                .where(WorkOrder.order_type == WorkOrderType.DEFECT.value)
                .group_by(WorkOrder.station_name)
                .order_by(func.count(WorkOrder.id).desc())
                .limit(10)
            )
        )
    ).all()
    defect_rank = [
        {"name": name or "未知站点", "value": int(cnt)} for name, cnt in defect_rows
    ]

    # 趋势：按天统计工单创建量
    trend_rows = (
        await db.execute(
            _apply(
                select(
                    func.date(WorkOrder.created_at).label("d"),
                    func.count(WorkOrder.id),
                )
                .group_by(func.date(WorkOrder.created_at))
                .order_by(func.date(WorkOrder.created_at))
            )
        )
    ).all()
    trend = [{"date": str(d), "value": int(c)} for d, c in trend_rows]

    fault_conds = []
    if project_id:
        fault_conds.append(FaultReport.project_id == project_id)
    if station_id:
        fault_conds.append(FaultReport.station_id == station_id)

    def _apply_fault(stmt):
        for c in fault_conds:
            stmt = stmt.where(c)
        return stmt

    fault_total = int(
        (await db.execute(_apply_fault(select(func.count(FaultReport.id))))).scalar() or 0
    )
    fault_verified = int(
        (
            await db.execute(
                _apply_fault(
                    select(func.count(FaultReport.id)).where(
                        FaultReport.status == FaultStatus.VERIFIED.value
                    )
                )
            )
        ).scalar()
        or 0
    )
    inspection_total = int(
        (await db.execute(select(func.count(InspectionRecord.id)))).scalar() or 0
    )
    inspection_abnormal = int(
        (
            await db.execute(
                select(func.count(InspectionRecord.id)).where(
                    InspectionRecord.abnormal_count > 0
                )
            )
        ).scalar()
        or 0
    )

    return {
        "period": {"start": start.isoformat(), "end": end.isoformat(), "type": period},
        "work_order": {
            "total": total,
            "pending": pending,
            "done": done,
            "overdue": overdue,
            "urgent": urgent,
            "completion_rate": safe_rate(done, total),
            "overdue_rate": safe_rate(overdue, total),
        },
        "order_type_dist": order_type_dist,
        "time_status_dist": [{"name": t or "未知", "value": int(c)} for t, c in time_rows],
        "project_rank": project_rank,
        "defect_station_rank": defect_rank,
        "trend": trend,
        "fault": {
            "total": fault_total,
            "verified": fault_verified,
            "pending": fault_total - fault_verified,
            "verify_rate": safe_rate(fault_verified, fault_total),
        },
        "inspection": {
            "total": inspection_total,
            "abnormal_records": inspection_abnormal,
            "abnormal_rate": safe_rate(inspection_abnormal, inspection_total),
        },
    }


async def build_daily_statistics(db: AsyncSession, stat_date: date | None = None) -> list[StatisticsDaily]:
    """生成/更新统计日报（PDF 6.1 statistics_daily + 报告 Agent 数据源）。"""
    stat_date = stat_date or (date.today() - timedelta(days=1))  # T+1
    start_dt = datetime.combine(stat_date, datetime.min.time())
    end_dt = datetime.combine(stat_date, datetime.max.time())

    stations = (await db.execute(select(Station))).scalars().all()
    created: list[StatisticsDaily] = []

    async def _upsert(project_id: str | None, station_id: str | None, name: str | None):
        existing = (
            await db.execute(
                select(StatisticsDaily).where(
                    StatisticsDaily.stat_date == stat_date,
                    StatisticsDaily.project_id == project_id,
                    StatisticsDaily.station_id == station_id,
                )
            )
        ).scalar_one_or_none()

        conds = [
            WorkOrder.created_at >= start_dt,
            WorkOrder.created_at <= end_dt,
        ]
        if project_id:
            conds.append(WorkOrder.project_id == project_id)
        if station_id:
            conds.append(WorkOrder.station_id == station_id)

        def _apply(stmt):
            for c in conds:
                stmt = stmt.where(c)
            return stmt

        total = int((await db.execute(_apply(select(func.count(WorkOrder.id))))).scalar() or 0)
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
        defect = int(
            (
                await db.execute(
                    _apply(
                        select(func.count(WorkOrder.id)).where(
                            WorkOrder.order_type == WorkOrderType.DEFECT.value
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

        fault_conds = [FaultReport.created_at >= start_dt, FaultReport.created_at <= end_dt]
        if project_id:
            fault_conds.append(FaultReport.project_id == project_id)
        if station_id:
            fault_conds.append(FaultReport.station_id == station_id)

        def _apply_fault(stmt):
            for c in fault_conds:
                stmt = stmt.where(c)
            return stmt

        fault_total = int(
            (await db.execute(_apply_fault(select(func.count(FaultReport.id))))).scalar() or 0
        )
        fault_verified = int(
            (
                await db.execute(
                    _apply_fault(
                        select(func.count(FaultReport.id)).where(
                            FaultReport.status == FaultStatus.VERIFIED.value
                        )
                    )
                )
            ).scalar()
            or 0
        )

        insp_conds = [
            InspectionRecord.created_at >= start_dt,
            InspectionRecord.created_at <= end_dt,
        ]
        if station_id:
            insp_conds.append(InspectionRecord.station_id == station_id)

        def _apply_insp(stmt):
            for c in insp_conds:
                stmt = stmt.where(c)
            return stmt

        insp_total = int(
            (await db.execute(_apply_insp(select(func.count(InspectionRecord.id))))).scalar()
            or 0
        )
        insp_abnormal = int(
            (
                await db.execute(
                    _apply_insp(
                        select(func.count(InspectionRecord.id)).where(
                            InspectionRecord.abnormal_count > 0
                        )
                    )
                )
            ).scalar()
            or 0
        )

        payload = dict(
            order_total=total,
            order_pending=pending,
            order_done=done,
            order_overdue=overdue,
            order_urgent=urgent,
            defect_order_count=defect,
            completion_rate=safe_rate(done, total),
            overdue_rate=safe_rate(overdue, total),
            fault_total=fault_total,
            fault_pending_verify=fault_total - fault_verified,
            fault_verified=fault_verified,
            inspection_total=insp_total,
            inspection_abnormal=insp_abnormal,
            order_type_dist=[{"name": t or "未分类", "value": int(c)} for t, c in type_rows],
        )

        if existing:
            for k, v in payload.items():
                setattr(existing, k, v)
            created.append(existing)
        else:
            row = StatisticsDaily(
                stat_date=stat_date,
                project_id=project_id,
                station_id=station_id,
                station_name=name,
                **payload,
            )
            db.add(row)
            created.append(row)

    projects = (await db.execute(select(Project))).scalars().all()
    for project in projects:
        await _upsert(project.id, None, project.name)
    for station in stations:
        await _upsert(station.project_id, station.id, station.name)
    await _upsert(None, None, "全平台")

    await db.commit()
    return created
