"""消息中心与统计看板接口 —— PDF 3.8 模块 7 + 3.9 模块 8。

/api/v1/messages                 消息卡片列表（未读小红点）
/api/v1/messages/types           消息类型区分统计
/api/v1/messages/{id}/read       标记已读
/api/v1/messages/read-all        全部已读
/api/v1/statistics/dashboard     统计看板
/api/v1/statistics/trend         统计日报趋势
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.core.deps import CurrentUser, DbSession, scope_of
from app.core.enums import DataScope
from app.core.response import ApiResponse, PageData
from app.models import User
from app.schemas import MessageOut
from app.services import message as message_service
from app.services import statistics as statistics_service

router = APIRouter(prefix="/messages", tags=["消息中心"])
stats_router = APIRouter(prefix="/statistics", tags=["统计分析"])


# ================================================================ 消息中心


@router.get("", response_model=ApiResponse[dict], summary="消息列表（卡片 + 未读数）")
async def list_messages(
    db: DbSession,
    user: CurrentUser,
    msg_type: str | None = Query(
        default=None,
        description="工单退回提醒/紧急工单提醒/逾期工单提醒/工单取消提醒/工单下发提醒/故障待核查提醒/报告生成提醒/系统消息",
    ),
    is_read: bool | None = None,
    keyword: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
):
    rows, total, unread = await message_service.list_messages(
        db,
        receiver_id=user.id,
        msg_type=msg_type,
        is_read=is_read,
        keyword=keyword,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    page_data = PageData.build(
        [MessageOut.model_validate(r) for r in rows], total, page, page_size
    )
    return ApiResponse.ok({**page_data.model_dump(), "unread_count": unread})


@router.get("/types", response_model=ApiResponse[list[dict]], summary="消息类型区分统计")
async def message_types(db: DbSession, user: CurrentUser):
    return ApiResponse.ok(await message_service.message_type_summary(db, user.id))


@router.post("/read-all", response_model=ApiResponse[dict], summary="全部标记已读")
async def read_all(db: DbSession, user: CurrentUser):
    count = await message_service.mark_all_read(db, receiver_id=user.id)
    return ApiResponse.ok({"updated": count})


@router.get("/{message_id}", response_model=ApiResponse[dict], summary="消息详情")
async def message_detail(message_id: str, db: DbSession, user: CurrentUser):
    """消息详情（PDF 3.8）：工单类型、编号、名称、项目、站点、巡检人员、日期、频率、次数、备注。"""
    message = await message_service.mark_read(db, message_id=message_id, receiver_id=user.id)
    return ApiResponse.ok(
        {
            "id": message.id,
            "msg_type": message.msg_type,
            "title": message.title,
            "content": message.content,
            "detail": message.detail,
            "work_order_id": message.work_order_id,
            "fault_id": message.fault_id,
            "report_id": message.report_id,
            "link": message.link,
            "is_read": message.is_read,
            "read_at": message.read_at,
            "channel": message.channel,
            "created_at": message.created_at,
        }
    )


@router.post("/{message_id}/read", response_model=ApiResponse[dict], summary="标记已读")
async def mark_read(message_id: str, db: DbSession, user: CurrentUser):
    message = await message_service.mark_read(db, message_id=message_id, receiver_id=user.id)
    return ApiResponse.ok({"id": message.id, "is_read": message.is_read})


# ================================================================ 统计分析


@stats_router.get("/dashboard", response_model=ApiResponse[dict], summary="统计看板")
async def dashboard(
    db: DbSession,
    user: CurrentUser,
    period: str | None = Query(default="month", description="day/week/month/quarter/year"),
    year: int | None = None,
    month: int | None = Query(default=None, ge=1, le=12),
    project_id: str | None = None,
    station_id: str | None = None,
):
    """工单统计、完成率、逾期率、5 种工单分布、项目排名、站点消缺排名（PDF 3.9）。"""
    scope = scope_of(user)
    if scope == DataScope.PROJECT.value:
        project_id = user.project_id
    elif scope == DataScope.STATION.value:
        station_id = user.station_id

    data = await statistics_service.dashboard_overview(
        db,
        period=period,
        year=year,
        month=month,
        project_id=project_id,
        station_id=station_id,
    )
    data["data_scope"] = scope
    return ApiResponse.ok(data)


@stats_router.get("/trend", response_model=ApiResponse[dict], summary="统计日报趋势")
async def statistics_trend(
    db: DbSession,
    user: CurrentUser,
    days: int = Query(default=30, ge=1, le=365),
    project_id: str | None = None,
):
    from app.ai.report_service import report_statistics_trend

    return ApiResponse.ok(
        await report_statistics_trend(db, days=days, project_id=project_id)
    )


@stats_router.post("/build-daily", response_model=ApiResponse[dict], summary="生成统计日报")
async def build_daily(
    db: DbSession,
    user: CurrentUser,
    payload: dict | None = None,
):
    """生成统计日报（PDF 6.1 statistics_daily，供报告 Agent 使用）。"""
    from datetime import date as _date

    payload = payload or {}
    stat_date = payload.get("stat_date")
    target = _date.fromisoformat(str(stat_date)[:10]) if stat_date else None
    rows = await statistics_service.build_daily_statistics(db, target)
    return ApiResponse.ok(
        {
            "generated": len(rows),
            "stat_date": (target or (_date.today())).isoformat(),
        }
    )


@stats_router.get("/rankings", response_model=ApiResponse[dict], summary="排名数据")
async def rankings(
    db: DbSession,
    user: CurrentUser,
    period: str | None = "month",
    year: int | None = None,
    month: int | None = Query(default=None, ge=1, le=12),
):
    data = await statistics_service.dashboard_overview(
        db, period=period, year=year, month=month
    )
    return ApiResponse.ok(
        {
            "project_rank": data["project_rank"],
            "defect_station_rank": data["defect_station_rank"],
            "order_type_dist": data["order_type_dist"],
        }
    )
