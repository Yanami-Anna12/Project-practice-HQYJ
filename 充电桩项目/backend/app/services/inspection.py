"""巡检领域服务 —— PDF 3.4 巡检情况录入 / 巡检详情。

支持巡视、设备检查、消缺、特巡、其他五类工单的巡检录入，
多图上传、分类显示、正常/异常勾选、200 字备注。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import InspectItemResult, SubtaskStatus, WorkOrderStatus
from app.core.errors import BizError, NotFoundError
from app.models import (
    ChargingPile,
    InspectionItem,
    InspectionRecord,
    Station,
    User,
    WorkOrder,
    WorkOrderSubtask,
)

MAX_REMARK_LEN = 200  # PDF 3.4：200 字备注

# 分类巡检项模板（PDF 3.4：支持多图上传、分类显示、正常/异常勾选）
INSPECTION_TEMPLATES: dict[str, list[dict]] = {
    "通用": [
        {"group": "外观与环境", "name": "桩体外观无破损、无变形"},
        {"group": "外观与环境", "name": "站台清洁，无杂物堆积"},
        {"group": "外观与环境", "name": "标识标牌清晰完整"},
        {"group": "电气安全", "name": "急停按钮功能正常"},
        {"group": "电气安全", "name": "接地线连接可靠"},
        {"group": "电气安全", "name": "线缆无破损、无过热痕迹"},
        {"group": "电气安全", "name": "配电箱无异常声响与异味"},
        {"group": "充电功能", "name": "充电枪头无烧蚀、卡扣正常"},
        {"group": "充电功能", "name": "刷卡/扫码启动正常"},
        {"group": "充电功能", "name": "充电功率与显示一致"},
        {"group": "消防设施", "name": "灭火器在有效期内、压力正常"},
        {"group": "消防设施", "name": "烟感/温感装置工作正常"},
        {"group": "监控与通信", "name": "摄像头画面清晰、角度正确"},
        {"group": "监控与通信", "name": "通信模块在线，无离线告警"},
    ],
    "特巡": [
        {"group": "特巡专项", "name": "极端天气后桩体无进水、无倾斜"},
        {"group": "特巡专项", "name": "节假日高负荷后枪线温升正常"},
        {"group": "特巡专项", "name": "站台排水通畅，无积水"},
    ],
    "消缺": [
        {"group": "消缺验证", "name": "缺陷现象已消除"},
        {"group": "消缺验证", "name": "复测数据恢复正常范围"},
        {"group": "消缺验证", "name": "现场已清理，无遗留工器具"},
    ],
}


def template_for(order_type: str) -> list[dict]:
    base = list(INSPECTION_TEMPLATES["通用"])
    if order_type == "特巡":
        base += INSPECTION_TEMPLATES["特巡"]
    elif order_type == "消缺":
        base = INSPECTION_TEMPLATES["消缺"] + base
    elif order_type == "设备检查":
        base += [{"group": "设备检查", "name": "设备铭牌与台账信息一致"}]
    return base


async def get_subtask(db: AsyncSession, subtask_id: str) -> WorkOrderSubtask:
    subtask = await db.get(WorkOrderSubtask, subtask_id)
    if subtask is None:
        raise NotFoundError("子任务不存在")
    return subtask


async def get_or_create_subtask(
    db: AsyncSession, subtask_id: str
) -> WorkOrderSubtask:
    return await get_subtask(db, subtask_id)


async def save_inspection(
    db: AsyncSession,
    *,
    subtask_id: str,
    inspector: User,
    items: list[dict],
    images: list[str] | None,
    remark: str | None,
    checkin_location: str | None,
    checkin_lng: float | None,
    checkin_lat: float | None,
    checkout_location: str | None,
    checkout_lng: float | None,
    checkout_lat: float | None,
    finish: bool,
) -> InspectionRecord:
    """巡检情况录入（PDF 3.4）。

    - items: [{item_name, item_group, result, remark, images, pile_asset_code}]
    - 正常/异常勾选，异常项自动累计 abnormal_count
    - 备注限制 200 字
    - finish=True 时结单，联动子任务与工单进度
    """
    if remark and len(remark) > MAX_REMARK_LEN:
        raise BizError(f"巡检备注最多 {MAX_REMARK_LEN} 字")

    subtask = await get_subtask(db, subtask_id)
    order = await db.get(WorkOrder, subtask.work_order_id)
    if order is None:
        raise NotFoundError("工单不存在")
    if order.status in (WorkOrderStatus.CANCELLED.value, WorkOrderStatus.COMPLETED.value):
        raise BizError(f"工单当前状态为「{order.status}」，无法录入巡检")

    normal = sum(1 for i in items if i.get("result") == InspectItemResult.NORMAL.value)
    abnormal = sum(
        1 for i in items if i.get("result") == InspectItemResult.ABNORMAL.value
    )

    record = InspectionRecord(
        subtask_id=subtask.id,
        work_order_id=order.id,
        inspector_id=inspector.id,
        inspector_name=inspector.real_name,
        station_id=subtask.station_id,
        station_name=subtask.station_name,
        checkin_location=checkin_location,
        checkin_lng=checkin_lng,
        checkin_lat=checkin_lat,
        checkin_time=datetime.now(),
        checkout_location=checkout_location,
        checkout_lng=checkout_lng,
        checkout_lat=checkout_lat,
        checkout_time=datetime.now() if finish else None,
        content={
            "order_type": order.order_type,
            "items": items,
            "station_name": subtask.station_name,
            "pile_asset_code": subtask.pile_asset_code,
        },
        images=images or [],
        abnormal_count=abnormal,
        normal_count=normal,
        remark=remark,
        status="已完成" if finish else "巡检中",
    )
    db.add(record)
    await db.flush()

    for item in items:
        db.add(
            InspectionItem(
                inspection_id=record.id,
                work_order_id=order.id,
                pile_id=subtask.pile_id,
                pile_asset_code=item.get("pile_asset_code") or subtask.pile_asset_code,
                item_name=item.get("item_name") or "未命名巡检项",
                item_group=item.get("item_group") or "通用",
                result=item.get("result") or InspectItemResult.NORMAL.value,
                remark=(item.get("remark") or "")[:MAX_REMARK_LEN],
                images=item.get("images") or [],
            )
        )

    subtask.status = (
        SubtaskStatus.COMPLETED.value if finish else SubtaskStatus.IN_PROGRESS.value
    )
    subtask.item_summary = f"正常 {normal} 项 / 异常 {abnormal} 项"
    if finish:
        subtask.completed_at = datetime.now()

    # 回填图片附件的业务归属（PDF 3.2 附件管理：
    # 前端先调 /uploads/images 拿到 URL，再随巡检表单提交）
    from app.services.upload import bind_attachments

    image_urls = list(images or [])
    for item in items:
        image_urls.extend(item.get("images") or [])
    await bind_attachments(
        db, file_urls=image_urls, biz_type="inspection", biz_id=record.id, commit=False
    )

    # 联动工单进度
    from app.services.work_order import recalc_subtask_progress

    await recalc_subtask_progress(db, order.id)
    await db.commit()
    await db.refresh(record)
    return record


async def list_inspections(
    db: AsyncSession,
    *,
    work_order_id: str | None = None,
    inspector_id: str | None = None,
    station_id: str | None = None,
    keyword: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[InspectionRecord], int]:
    conditions = []
    if work_order_id:
        conditions.append(InspectionRecord.work_order_id == work_order_id)
    if inspector_id:
        conditions.append(InspectionRecord.inspector_id == inspector_id)
    if station_id:
        conditions.append(InspectionRecord.station_id == station_id)
    if keyword:
        conditions.append(InspectionRecord.station_name.ilike(f"%{keyword}%"))

    base = select(InspectionRecord)
    count_stmt = select(func.count(InspectionRecord.id))
    for cond in conditions:
        base = base.where(cond)
        count_stmt = count_stmt.where(cond)

    total = int((await db.execute(count_stmt)).scalar() or 0)
    stmt = (
        base.order_by(InspectionRecord.created_at.desc()).limit(limit).offset(offset)
    )
    return list((await db.execute(stmt)).scalars().all()), total


async def inspection_overview(db: AsyncSession, order_type: str = "巡视") -> dict:
    """巡检录入页面初始化数据：工单类型对应的分类巡检项模板。"""
    return {
        "order_type": order_type,
        "template": template_for(order_type),
        "max_remark_length": MAX_REMARK_LEN,
        "result_options": [e.value for e in InspectItemResult],
    }


async def station_piles(db: AsyncSession, station_id: str) -> list[ChargingPile]:
    rows = await db.execute(
        select(ChargingPile).where(ChargingPile.station_id == station_id)
    )
    return list(rows.scalars().all())


async def inspection_statistics(db: AsyncSession, **filters) -> dict:
    conditions = []
    if filters.get("project_id"):
        conditions.append(InspectionRecord.station_id.in_(select(Station.id).where(Station.project_id == filters["project_id"])))

    def _apply(stmt):
        for c in conditions:
            stmt = stmt.where(c)
        return stmt

    total = int(
        (await db.execute(_apply(select(func.count(InspectionRecord.id))))).scalar() or 0
    )
    abnormal = int(
        (
            await db.execute(
                _apply(
                    select(func.count(InspectionRecord.id)).where(
                        InspectionRecord.abnormal_count > 0
                    )
                )
            )
        ).scalar()
        or 0
    )
    return {"total": total, "abnormal_records": abnormal}
