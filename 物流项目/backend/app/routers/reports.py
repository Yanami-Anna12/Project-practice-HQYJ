"""报表与看板接口。

对应需求文档 二.5 的各类看板，以及 五.2 里的报表接口：
    GET /api/reports/attendance        车辆出勤
    GET /api/reports/trip-achievement  趟次达成
    GET /api/reports/load-rate         装载率
    GET /api/reports/store             门店配送达成 + 线路覆盖
    GET /api/reports/cost              成本与方案对比
    GET /api/reports/overview          汇总（页面一次拉全）
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.deps import DbSession, require_permission
from app.models import SysUser
from app.services import reports as report_service

router = APIRouter(prefix="/reports", tags=["报表与看板"])

Reader = Annotated[SysUser, Depends(require_permission("reports:view"))]


@router.get("/dates", response_model=list[str], summary="有调度数据的日期")
def report_dates(db: DbSession, actor: Reader) -> list[str]:
    return report_service.available_dates(db)


@router.get("/overview", summary="报表汇总（一次拉全）")
def report_overview(
    db: DbSession,
    actor: Reader,
    schedule_date: date | None = Query(default=None, description="留空表示统计全部日期"),
) -> dict[str, Any]:
    return report_service.overview(db, schedule_date)


@router.get("/attendance", summary="车辆出勤看板")
def attendance(
    db: DbSession, actor: Reader, schedule_date: date | None = Query(default=None)
) -> dict[str, Any]:
    return report_service.attendance_report(db, schedule_date)


@router.get("/trip-achievement", summary="趟次达成看板")
def trip_achievement(
    db: DbSession, actor: Reader, schedule_date: date | None = Query(default=None)
) -> dict[str, Any]:
    return report_service.trip_report(db, schedule_date)


@router.get("/load-rate", summary="装载率看板")
def load_rate(
    db: DbSession, actor: Reader, schedule_date: date | None = Query(default=None)
) -> dict[str, Any]:
    return report_service.load_rate_report(db, schedule_date)


@router.get("/store", summary="门店配送达成与线路覆盖")
def store_report(
    db: DbSession, actor: Reader, schedule_date: date | None = Query(default=None)
) -> dict[str, Any]:
    return report_service.store_report(db, schedule_date)


@router.get("/cost", summary="成本分析与方案对比")
def cost_report(
    db: DbSession, actor: Reader, schedule_date: date | None = Query(default=None)
) -> dict[str, Any]:
    return report_service.cost_report(db, schedule_date)
