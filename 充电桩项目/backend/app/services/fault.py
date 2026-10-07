"""故障领域服务 —— PDF 3.5 模块 4：故障管理。

包含故障上报（草稿/确认上报）、故障核查、故障等级与状态流转、故障统计。
故障等级与核查状态流转为硬约束，AI 仅提供等级建议与根因分析。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import FaultLevel, FaultStatus, MessageType, VerifyResult
from app.core.errors import BizError, NotFoundError
from app.core.utils import gen_no, like_filter, safe_rate
from app.models import (
    ChargingPile,
    FaultReport,
    FaultVerification,
    Message,
    Station,
    User,
)

# 故障状态合法迁移（PDF 3.5 核查状态：待上报/待核查/核查通过/核查驳回）
FAULT_TRANSITIONS: dict[str, set[str]] = {
    FaultStatus.PENDING_REPORT.value: {FaultStatus.PENDING_VERIFY.value},
    FaultStatus.PENDING_VERIFY.value: {
        FaultStatus.VERIFIED.value,
        FaultStatus.REJECTED.value,
    },
    FaultStatus.VERIFIED.value: set(),
    FaultStatus.REJECTED.value: {FaultStatus.PENDING_VERIFY.value},
}

# 故障等级对应的响应时限（小时），用于风控与超期提醒
LEVEL_SLA_HOURS: dict[str, int] = {
    FaultLevel.GENERAL.value: 72,
    FaultLevel.SERIOUS.value: 24,
    FaultLevel.CRITICAL.value: 4,
}


def ensure_fault_transition(current: str, target: str) -> None:
    if target not in FAULT_TRANSITIONS.get(current, set()):
        raise BizError(f"故障状态不允许从「{current}」变更为「{target}」")


def suggest_level(fault_type: str | None, description: str | None) -> str:
    """基于规则的故障等级建议（硬约束，AI 可复核但不覆盖）。"""
    text = f"{fault_type or ''} {description or ''}"
    critical_kw = ["起火", "冒烟", "漏电", "触电", "爆炸", "无法急停", "绝缘失效", "烧毁"]
    serious_kw = ["跳闸", "断电", "故障停机", "通信中断", "无法充电", "枪头损坏", "过温"]
    if any(k in text for k in critical_kw):
        return FaultLevel.CRITICAL.value
    if any(k in text for k in serious_kw):
        return FaultLevel.SERIOUS.value
    return FaultLevel.GENERAL.value


async def create_fault(
    db: AsyncSession,
    *,
    reporter: User,
    project_id: str | None,
    station_id: str | None,
    pile_id: str | None,
    fault_type: str | None,
    fault_level: str | None,
    description: str | None,
    images: list | None,
    occurred_at: datetime | None,
    is_draft: bool,
) -> FaultReport:
    """故障上报（PDF 3.5：级联下拉联动项目与站点，支持多图上传、保存草稿、确认上报）。"""
    station_name = None
    pile_asset_code = None
    if station_id:
        station = await db.get(Station, station_id)
        station_name = station.name if station else None
    if pile_id:
        pile = await db.get(ChargingPile, pile_id)
        if pile:
            pile_asset_code = pile.asset_code
            if not station_id:
                station_id = pile.station_id

    level = fault_level or suggest_level(fault_type, description)
    if level not in {e.value for e in FaultLevel}:
        raise BizError(f"非法故障等级：{level}")

    fault = FaultReport(
        fault_no=gen_no("FT"),
        project_id=project_id,
        station_id=station_id,
        station_name=station_name,
        pile_id=pile_id,
        pile_asset_code=pile_asset_code,
        reporter_id=reporter.id,
        reporter_name=reporter.real_name,
        reporter_phone=reporter.phone,
        fault_type=fault_type,
        fault_level=level,
        description=description,
        images=images or [],
        status=(
            FaultStatus.PENDING_REPORT.value
            if is_draft
            else FaultStatus.PENDING_VERIFY.value
        ),
        is_draft=is_draft,
        occurred_at=occurred_at or datetime.now(),
        reported_at=None if is_draft else datetime.now(),
        ai_level_suggestion=suggest_level(fault_type, description),
    )
    db.add(fault)
    await db.flush()

    # 回填故障照片的附件归属（PDF 3.2 附件管理 + 3.5 多图上传）
    if images:
        from app.services.upload import bind_attachments

        await bind_attachments(
            db, file_urls=list(images), biz_type="fault", biz_id=fault.id, commit=False
        )

    # 紧急故障立即生成待核查提醒（PDF 3.8）
    if not is_draft and level in (FaultLevel.SERIOUS.value, FaultLevel.CRITICAL.value):
        db.add(
            Message(
                receiver_id=reporter.id,
                msg_type=MessageType.FAULT_PENDING.value,
                title=f"故障已上报待核查：{fault.fault_no}",
                content=f"等级「{level}」，站点「{station_name or '-'}」，请尽快安排核查。",
                fault_id=fault.id,
                detail={"故障编号": fault.fault_no, "故障等级": level, "站点": station_name},
                link=f"/faults/{fault.id}",
            )
        )

    await db.commit()
    await db.refresh(fault)
    return fault


async def confirm_fault_draft(db: AsyncSession, fault_id: str) -> FaultReport:
    """把草稿提交为待核查。"""
    fault = await get_fault(db, fault_id)
    ensure_fault_transition(fault.status, FaultStatus.PENDING_VERIFY.value)
    fault.status = FaultStatus.PENDING_VERIFY.value
    fault.is_draft = False
    fault.reported_at = datetime.now()
    await db.commit()
    await db.refresh(fault)
    return fault


async def verify_fault(
    db: AsyncSession,
    *,
    fault_id: str,
    verifier: User,
    verify_status: str,
    verify_level: str | None,
    verify_desc: str | None,
    images: list | None,
    need_defect_order: bool,
) -> FaultVerification:
    """故障核查（PDF 3.5：故障信息、多图、核查录入、核查状态、核查等级、核查描述）。"""
    fault = await get_fault(db, fault_id)
    if verify_status not in {e.value for e in VerifyResult}:
        raise BizError(f"非法核查状态：{verify_status}")
    if len(verify_desc or "") > 2000:
        raise BizError("核查描述过长")

    ensure_fault_transition(fault.status, verify_status)

    verification = FaultVerification(
        fault_id=fault.id,
        verifier_id=verifier.id,
        verifier_name=verifier.real_name,
        verify_status=verify_status,
        verify_level=verify_level or fault.fault_level,
        verify_desc=verify_desc,
        images=images or [],
        need_defect_order=need_defect_order,
    )
    db.add(verification)
    await db.flush()

    # 回填核查照片的附件归属（PDF 3.5 核查多图上传）
    if images:
        from app.services.upload import bind_attachments

        await bind_attachments(
            db,
            file_urls=list(images),
            biz_type="verify",
            biz_id=verification.id,
            commit=False,
        )

    fault.status = verify_status
    if verify_level:
        fault.fault_level = verify_level

    db.add(
        Message(
            receiver_id=fault.reporter_id or verifier.id,
            msg_type=MessageType.SYSTEM.value,
            title=f"故障核查结果：{fault.fault_no}",
            content=f"核查状态「{verify_status}」，核查等级「{verification.verify_level}」。",
            fault_id=fault.id,
            detail={
                "故障编号": fault.fault_no,
                "核查状态": verify_status,
                "核查等级": verification.verify_level,
                "核查描述": verify_desc,
            },
            link=f"/faults/{fault.id}",
        )
    )
    await db.commit()
    await db.refresh(verification)
    return verification


async def get_fault(db: AsyncSession, fault_id: str) -> FaultReport:
    fault = await db.get(FaultReport, fault_id)
    if fault is None:
        raise NotFoundError("故障记录不存在")
    return fault


async def list_faults(
    db: AsyncSession,
    *,
    keyword: str | None = None,
    status: str | None = None,
    fault_level: str | None = None,
    fault_type: str | None = None,
    station_id: str | None = None,
    project_id: str | None = None,
    reporter_id: str | None = None,
    tab: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[FaultReport], int]:
    """故障列表 + 站点/桩资产码模糊搜索 + 全部/待核查/已核查 tab（PDF 3.5）。"""
    conditions = []
    kw_cond = like_filter(
        [
            FaultReport.fault_no,
            FaultReport.station_name,
            FaultReport.pile_asset_code,
            FaultReport.fault_type,
        ],
        keyword,
    )
    if kw_cond is not None:
        conditions.append(kw_cond)
    if status:
        conditions.append(FaultReport.status == status)
    if tab == "待核查":
        conditions.append(FaultReport.status == FaultStatus.PENDING_VERIFY.value)
    elif tab in ("已核查", "核查通过"):
        conditions.append(FaultReport.status == FaultStatus.VERIFIED.value)
    if fault_level:
        conditions.append(FaultReport.fault_level == fault_level)
    if fault_type:
        conditions.append(FaultReport.fault_type == fault_type)
    if station_id:
        conditions.append(FaultReport.station_id == station_id)
    if project_id:
        conditions.append(FaultReport.project_id == project_id)
    if reporter_id:
        conditions.append(FaultReport.reporter_id == reporter_id)

    base = select(FaultReport)
    count_stmt = select(func.count(FaultReport.id))
    for cond in conditions:
        base = base.where(cond)
        count_stmt = count_stmt.where(cond)

    total = int((await db.execute(count_stmt)).scalar() or 0)
    stmt = base.order_by(FaultReport.created_at.desc()).limit(limit).offset(offset)
    return list((await db.execute(stmt)).scalars().all()), total


async def fault_statistics(db: AsyncSession, **filters) -> dict:
    """故障首页统计（PDF 3.5：累计已上报故障总数、已核查数、待核查数）。"""
    conditions = []
    if filters.get("project_id"):
        conditions.append(FaultReport.project_id == filters["project_id"])
    if filters.get("station_id"):
        conditions.append(FaultReport.station_id == filters["station_id"])

    def _apply(stmt):
        for c in conditions:
            stmt = stmt.where(c)
        return stmt

    total = int((await db.execute(_apply(select(func.count(FaultReport.id))))).scalar() or 0)
    verified = int(
        (
            await db.execute(
                _apply(
                    select(func.count(FaultReport.id)).where(
                        FaultReport.status == FaultStatus.VERIFIED.value
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
                    select(func.count(FaultReport.id)).where(
                        FaultReport.status == FaultStatus.PENDING_VERIFY.value
                    )
                )
            )
        ).scalar()
        or 0
    )
    rejected = int(
        (
            await db.execute(
                _apply(
                    select(func.count(FaultReport.id)).where(
                        FaultReport.status == FaultStatus.REJECTED.value
                    )
                )
            )
        ).scalar()
        or 0
    )
    level_rows = (
        await db.execute(
            _apply(
                select(FaultReport.fault_level, func.count(FaultReport.id)).group_by(
                    FaultReport.fault_level
                )
            )
        )
    ).all()
    type_rows = (
        await db.execute(
            _apply(
                select(FaultReport.fault_type, func.count(FaultReport.id))
                .group_by(FaultReport.fault_type)
                .order_by(func.count(FaultReport.id).desc())
                .limit(10)
            )
        )
    ).all()

    return {
        "total": total,
        "verified": verified,
        "pending": pending,
        "rejected": rejected,
        "verify_rate": safe_rate(verified, total),
        "level_dist": [{"name": lv or "未分级", "value": int(c)} for lv, c in level_rows],
        "type_rank": [{"name": t or "未分类", "value": int(c)} for t, c in type_rows],
    }


async def fault_card_list(db: AsyncSession, limit: int = 10) -> list[dict]:
    """故障卡片信息（PDF 3.5 故障卡片）。"""
    rows = (
        await db.execute(
            select(FaultReport).order_by(FaultReport.created_at.desc()).limit(limit)
        )
    ).scalars().all()
    out = []
    now = datetime.now()
    for f in rows:
        sla = LEVEL_SLA_HOURS.get(f.fault_level, 72)
        deadline = (f.reported_at or f.created_at) + timedelta(hours=sla)
        out.append(
            {
                "id": f.id,
                "fault_no": f.fault_no,
                "fault_type": f.fault_type,
                "fault_level": f.fault_level,
                "status": f.status,
                "station_name": f.station_name,
                "pile_asset_code": f.pile_asset_code,
                "reporter_name": f.reporter_name,
                "description": (f.description or "")[:120],
                "images": (f.images or [])[:3],
                "created_at": f.created_at,
                "sla_deadline": deadline,
                "sla_overdue": deadline < now
                and f.status == FaultStatus.PENDING_VERIFY.value,
            }
        )
    return out
