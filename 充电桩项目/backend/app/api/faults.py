"""故障接口 —— PDF 5.1 + 3.5 模块 4：故障管理。

/api/v1/faults                故障列表（站点/桩资产码模糊搜索 + 全部/待核查/已核查 tab）
/api/v1/faults/home           故障首页统计
/api/v1/faults/cards          故障卡片
/api/v1/faults                故障上报
/api/v1/faults/{id}           故障详情
/api/v1/faults/{id}/confirm   草稿确认上报
/api/v1/faults/verify         故障核查
/api/v1/faults/statistics     故障统计
/api/v1/faults/levels         故障等级字典
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.core.deps import CurrentUser, DbSession, paginate, scope_of
from app.core.enums import DataScope, FaultLevel, FaultStatus, VerifyResult
from app.core.errors import BizError
from app.core.response import ApiResponse, PageData
from app.models import ChargingPile, FaultReport, FaultVerification, Station
from app.schemas import (
    FaultCreate,
    FaultOut,
    FaultVerificationOut,
    FaultVerifyRequest,
)
from app.services import audit as audit_service
from app.services import fault as fault_service

router = APIRouter(prefix="/faults", tags=["故障管理"])


@router.get("/levels", response_model=ApiResponse[dict], summary="故障等级与状态字典")
async def fault_dicts(db: DbSession, user: CurrentUser):
    return ApiResponse.ok(
        {
            "levels": [e.value for e in FaultLevel],
            "statuses": [e.value for e in FaultStatus],
            "verify_results": [e.value for e in VerifyResult],
            "level_sla_hours": fault_service.LEVEL_SLA_HOURS,
            "level_color": {
                FaultLevel.GENERAL.value: "#52c41a",
                FaultLevel.SERIOUS.value: "#faad14",
                FaultLevel.CRITICAL.value: "#f5222d",
            },
        }
    )


@router.get("/home", response_model=ApiResponse[dict], summary="故障首页统计")
async def fault_home(
    db: DbSession, user: CurrentUser, project_id: str | None = None, station_id: str | None = None
):
    """累计已上报故障总数、已核查数、待核查数（PDF 3.5 故障首页）。"""
    scope = scope_of(user)
    filters: dict = {}
    if scope == DataScope.PROJECT.value:
        filters["project_id"] = user.project_id
    elif scope == DataScope.STATION.value:
        filters["station_id"] = user.station_id
    else:
        filters["project_id"] = project_id
        filters["station_id"] = station_id

    stats = await fault_service.fault_statistics(db, **filters)
    cards = await fault_service.fault_card_list(db, limit=8)
    return ApiResponse.ok({**stats, "cards": cards, "data_scope": scope})


@router.get("/cards", response_model=ApiResponse[list[dict]], summary="故障卡片列表")
async def fault_cards(db: DbSession, user: CurrentUser, limit: int = Query(default=10, ge=1, le=50)):
    return ApiResponse.ok(await fault_service.fault_card_list(db, limit=limit))


@router.get("/statistics", response_model=ApiResponse[dict], summary="故障统计")
async def fault_statistics(
    db: DbSession, user: CurrentUser, project_id: str | None = None, station_id: str | None = None
):
    return ApiResponse.ok(
        await fault_service.fault_statistics(
            db, project_id=project_id, station_id=station_id
        )
    )


@router.get("/piles/options", response_model=ApiResponse[list[dict]], summary="充电桩下拉选项（级联联动）")
async def pile_options(
    db: DbSession,
    user: CurrentUser,
    project_id: str | None = Query(default=None, description="按项目联动"),
    station_id: str | None = None,
    keyword: str | None = Query(default=None, description="资产码模糊查询"),
):
    """级联下拉框联动项目与站点名称展示充电桩资产码（PDF 3.5 故障上报）。"""
    stmt = select(ChargingPile)
    if station_id:
        stmt = stmt.where(ChargingPile.station_id == station_id)
    elif project_id:
        station_ids = [
            s.id
            for s in (
                await db.execute(select(Station).where(Station.project_id == project_id))
            ).scalars().all()
        ]
        stmt = stmt.where(ChargingPile.station_id.in_(station_ids or [""]))
    if keyword:
        stmt = stmt.where(ChargingPile.asset_code.ilike(f"%{keyword}%"))

    rows = (await db.execute(stmt.order_by(ChargingPile.asset_code).limit(200))).scalars().all()
    station_names = {
        s.id: s.name for s in (await db.execute(select(Station))).scalars().all()
    }
    return ApiResponse.ok(
        [
            {
                "id": p.id,
                "asset_code": p.asset_code,
                "name": p.name,
                "station_id": p.station_id,
                "station_name": station_names.get(p.station_id or ""),
                "status": p.status,
            }
            for p in rows
        ]
    )


@router.get("", response_model=ApiResponse[PageData[FaultOut]], summary="故障列表")
async def list_faults(
    db: DbSession,
    user: CurrentUser,
    keyword: str | None = Query(default=None, description="故障编号/站点/桩资产码 模糊搜索"),
    status: str | None = None,
    fault_level: str | None = None,
    fault_type: str | None = None,
    station_id: str | None = None,
    project_id: str | None = None,
    tab: str | None = Query(default=None, description="全部/待核查/已核查"),
    mine: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
):
    limit, offset = paginate(page, page_size)
    scope = scope_of(user)
    if scope == DataScope.PROJECT.value:
        project_id = user.project_id
    elif scope == DataScope.STATION.value:
        station_id = station_id or user.station_id

    rows, total = await fault_service.list_faults(
        db,
        keyword=keyword,
        status=status,
        fault_level=fault_level,
        fault_type=fault_type,
        station_id=station_id,
        project_id=project_id,
        reporter_id=user.id if mine else None,
        tab=tab,
        limit=limit,
        offset=offset,
    )
    return ApiResponse.ok(
        PageData.build([FaultOut.model_validate(r) for r in rows], total, page, page_size)
    )


@router.post("", response_model=ApiResponse[FaultOut], summary="故障上报（支持保存草稿）")
async def report_fault(payload: FaultCreate, db: DbSession, user: CurrentUser):
    """故障上报（PDF 3.5）：级联下拉、多图上传、保存草稿、确认上报。"""
    fault = await fault_service.create_fault(
        db,
        reporter=user,
        project_id=payload.project_id,
        station_id=payload.station_id,
        pile_id=payload.pile_id,
        fault_type=payload.fault_type,
        fault_level=payload.fault_level,
        description=payload.description,
        images=payload.images,
        occurred_at=payload.occurred_at,
        is_draft=payload.is_draft,
    )
    await audit_service.log_operation(
        db,
        module="故障管理",
        action="故障上报" if not payload.is_draft else "故障草稿保存",
        user=user,
        target_type="fault",
        target_id=fault.id,
        description=(
            f"{'保存草稿' if payload.is_draft else '上报'}故障 {fault.fault_no}"
            f"（等级 {fault.fault_level}，站点 {fault.station_name or '-'}）"
        ),
        after={
            "fault_no": fault.fault_no,
            "fault_level": fault.fault_level,
            "status": fault.status,
        },
    )
    return ApiResponse.ok(
        FaultOut.model_validate(fault),
        message="故障草稿已保存" if payload.is_draft else "故障上报成功，等待核查",
    )


@router.post(
    "/{fault_id}/verify",
    response_model=ApiResponse[FaultVerificationOut],
    summary="故障核查（PDF 3.5）",
)
async def verify_fault(
    fault_id: str, payload: FaultVerifyRequest, db: DbSession, user: CurrentUser
):
    """故障核查（PDF 3.5）：核查录入、核查状态、核查等级、核查描述、多图上传。"""
    if not payload.verify_desc:
        raise BizError("请填写核查描述")
    verification = await fault_service.verify_fault(
        db,
        fault_id=fault_id,
        verifier=user,
        verify_status=payload.verify_status,
        verify_level=payload.verify_level,
        verify_desc=payload.verify_desc,
        images=payload.images,
        need_defect_order=payload.need_defect_order,
    )
    await audit_service.log_operation(
        db,
        module="故障管理",
        action="故障核查",
        user=user,
        target_type="fault_verification",
        target_id=verification.id,
        description=(
            f"故障 {fault_id} 核查结论：{verification.verify_status}，"
            f"等级 {verification.verify_level}"
        ),
        after={
            "verify_status": verification.verify_status,
            "verify_level": verification.verify_level,
        },
    )
    return ApiResponse.ok(FaultVerificationOut.model_validate(verification))


@router.get("/{fault_id}", response_model=ApiResponse[dict], summary="故障详情")
async def get_fault(fault_id: str, db: DbSession, user: CurrentUser):
    fault = await fault_service.get_fault(db, fault_id)
    verifications = (
        await db.execute(
            select(FaultVerification)
            .where(FaultVerification.fault_id == fault_id)
            .order_by(FaultVerification.created_at.desc())
        )
    ).scalars().all()

    station = await db.get(Station, fault.station_id) if fault.station_id else None
    pile = await db.get(ChargingPile, fault.pile_id) if fault.pile_id else None

    return ApiResponse.ok(
        {
            "fault": FaultOut.model_validate(fault).model_dump(),
            "verifications": [
                FaultVerificationOut.model_validate(v).model_dump() for v in verifications
            ],
            "station": {"id": station.id, "name": station.name, "address": station.address}
            if station
            else None,
            "pile": {
                "id": pile.id,
                "asset_code": pile.asset_code,
                "name": pile.name,
                "gun_count": pile.gun_count,
            }
            if pile
            else None,
            "sla_hours": fault_service.LEVEL_SLA_HOURS.get(fault.fault_level, 72),
            "permissions": {
                "can_verify": fault.status
                in (FaultStatus.PENDING_VERIFY.value, FaultStatus.REJECTED.value),
                "can_confirm": fault.status == FaultStatus.PENDING_REPORT.value,
            },
        }
    )


@router.post("/{fault_id}/confirm", response_model=ApiResponse[FaultOut], summary="草稿确认上报")
async def confirm_fault(fault_id: str, db: DbSession, user: CurrentUser):
    fault = await fault_service.confirm_fault_draft(db, fault_id)
    await audit_service.log_operation(
        db,
        module="故障管理",
        action="草稿确认上报",
        user=user,
        target_type="fault",
        target_id=fault.id,
        description=f"故障草稿 {fault.fault_no} 确认上报",
        after={"status": fault.status},
    )
    return ApiResponse.ok(FaultOut.model_validate(fault), message="已确认上报，等待核查")
