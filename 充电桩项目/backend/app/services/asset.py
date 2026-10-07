"""台账与资产服务 —— PDF 3.7 模块 6：台账管理。

站台台账、充电桩台账、复杂查询、信息导出；
含 PDF 3.10 二期扩展：充电枪数量、灭火器字段（含「无」选项）、摄像头字段。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import BizError, NotFoundError
from app.core.utils import like_filter
from app.models import AssetLedger, ChargingPile, Project, Station

# 灭火器选项（PDF 3.10：增加「无」选项）
EXTINGUISHER_TYPES = ["无", "干粉", "二氧化碳", "水基", "洁净气体"]


async def sync_ledger(db: AsyncSession) -> dict:
    """把站点与充电桩同步进台账表，支撑统一复杂查询与导出。"""
    stations = (await db.execute(select(Station))).scalars().all()
    piles = (await db.execute(select(ChargingPile))).scalars().all()
    projects = {p.id: p.name for p in (await db.execute(select(Project))).scalars().all()}
    station_names = {s.id: s.name for s in stations}

    existing = {
        (row.ledger_type, row.asset_code): row
        for row in (await db.execute(select(AssetLedger))).scalars().all()
    }

    created = updated = 0
    for s in stations:
        key = ("station", s.code)
        attrs = {
            "站点地址": s.address,
            "地形": s.terrain,
            "经度": s.longitude,
            "纬度": s.latitude,
            "灭火器类型": s.extinguisher_type or "无",
            "灭火器规格": s.extinguisher_spec,
            "灭火器生产日期": (
                s.extinguisher_produced_at.date().isoformat()
                if s.extinguisher_produced_at
                else None
            ),
            "球机数量": s.dome_camera_count,
            "枪机数量": s.bullet_camera_count,
            "联系人": s.contact_name,
            "联系电话": s.contact_phone,
        }
        if key in existing:
            row = existing[key]
            row.asset_name = s.name
            row.project_id = s.project_id
            row.project_name = projects.get(s.project_id or "", None)
            row.attributes = attrs
            row.status = "正常" if s.status else "停用"
            updated += 1
        else:
            db.add(
                AssetLedger(
                    ledger_type="station",
                    asset_code=s.code,
                    asset_name=s.name,
                    project_id=s.project_id,
                    project_name=projects.get(s.project_id or ""),
                    station_id=s.id,
                    station_name=s.name,
                    attributes=attrs,
                    status="正常" if s.status else "停用",
                )
            )
            created += 1

    for p in piles:
        key = ("pile", p.asset_code)
        attrs = {
            "设备型号": p.model,
            "额定功率(kW)": p.rated_power,
            "充电枪数量": p.gun_count,
            "枪型": p.gun_types,
            "生产厂商": p.manufacturer,
            "安装日期": p.install_date.date().isoformat() if p.install_date else None,
            "质保到期": p.warranty_until.date().isoformat() if p.warranty_until else None,
        }
        if key in existing:
            row = existing[key]
            row.asset_name = p.name
            row.station_id = p.station_id
            row.station_name = station_names.get(p.station_id or "")
            row.attributes = attrs
            row.status = p.status
            updated += 1
        else:
            db.add(
                AssetLedger(
                    ledger_type="pile",
                    asset_code=p.asset_code,
                    asset_name=p.name,
                    station_id=p.station_id,
                    station_name=station_names.get(p.station_id or ""),
                    pile_id=p.id,
                    attributes=attrs,
                    status=p.status,
                )
            )
            created += 1

    await db.commit()
    return {"created": created, "updated": updated}


async def list_ledger(
    db: AsyncSession,
    *,
    ledger_type: str | None = None,
    keyword: str | None = None,
    project_id: str | None = None,
    station_id: str | None = None,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[AssetLedger], int]:
    """台账复杂模糊查询（PDF 3.7）。"""
    conditions = []
    if ledger_type:
        conditions.append(AssetLedger.ledger_type == ledger_type)
    kw = like_filter(
        [AssetLedger.asset_code, AssetLedger.asset_name, AssetLedger.station_name],
        keyword,
    )
    if kw is not None:
        conditions.append(kw)
    if project_id:
        conditions.append(AssetLedger.project_id == project_id)
    if station_id:
        conditions.append(AssetLedger.station_id == station_id)
    if status:
        conditions.append(AssetLedger.status == status)

    base = select(AssetLedger)
    count_stmt = select(func.count(AssetLedger.id))
    for cond in conditions:
        base = base.where(cond)
        count_stmt = count_stmt.where(cond)

    total = int((await db.execute(count_stmt)).scalar() or 0)
    stmt = (
        base.order_by(AssetLedger.ledger_type.asc(), AssetLedger.asset_code.asc())
        .limit(limit)
        .offset(offset)
    )
    return list((await db.execute(stmt)).scalars().all()), total


async def ledger_export_rows(db: AsyncSession, **filters) -> list[dict]:
    """台账导出数据（PDF 3.7 信息导出 + Excel）。"""
    rows, _ = await list_ledger(db, limit=100000, offset=0, **filters)
    out: list[dict] = []
    for row in rows:
        base = {
            "台账类型": "站台台账" if row.ledger_type == "station" else "充电桩台账",
            "资产编码": row.asset_code,
            "资产名称": row.asset_name,
            "所属项目": row.project_name,
            "所属站点": row.station_name,
            "状态": row.status,
        }
        for k, v in (row.attributes or {}).items():
            base[k] = v
        out.append(base)
    return out


async def update_station_extensions(
    db: AsyncSession,
    *,
    station_id: str,
    extinguisher_type: str | None = None,
    extinguisher_spec: str | None = None,
    extinguisher_produced_at: datetime | None = None,
    dome_camera_count: int | None = None,
    bullet_camera_count: int | None = None,
    camera_password: str | None = None,
) -> Station:
    """PDF 3.10 二期：灭火器动态表单（含「无」）+ 摄像头字段。"""
    station = await db.get(Station, station_id)
    if station is None:
        raise NotFoundError("站点不存在")

    if extinguisher_type is not None:
        if extinguisher_type not in EXTINGUISHER_TYPES:
            raise BizError(f"灭火器类型仅支持：{'、'.join(EXTINGUISHER_TYPES)}")
        station.extinguisher_type = extinguisher_type
        if extinguisher_type == "无":
            # 选择「无」时清空规格与生产日期
            station.extinguisher_spec = None
            station.extinguisher_produced_at = None
        else:
            station.extinguisher_spec = extinguisher_spec
            station.extinguisher_produced_at = extinguisher_produced_at
    else:
        if extinguisher_spec is not None:
            station.extinguisher_spec = extinguisher_spec
        if extinguisher_produced_at is not None:
            station.extinguisher_produced_at = extinguisher_produced_at

    if dome_camera_count is not None:
        station.dome_camera_count = max(0, dome_camera_count)
    if bullet_camera_count is not None:
        station.bullet_camera_count = max(0, bullet_camera_count)
    if camera_password is not None:
        station.camera_password = camera_password

    await db.commit()
    await db.refresh(station)
    return station


async def station_navigation(db: AsyncSession, station_id: str) -> dict:
    """站点导航（PDF 3.10：根据站点位置进行路线导航 + 地图跳转分享）。"""
    station = await db.get(Station, station_id)
    if station is None:
        raise NotFoundError("站点不存在")
    if station.longitude is None or station.latitude is None:
        raise BizError("该站点尚未维护经纬度，无法导航")
    lng, lat = station.longitude, station.latitude
    return {
        "station_id": station.id,
        "station_name": station.name,
        "address": station.address,
        "longitude": lng,
        "latitude": lat,
        # 高德 / 百度通用 URI，可直接被微信分享打开
        "amap_uri": f"https://uri.amap.com/marker?position={lng},{lat}&name={station.name}",
        "baidu_uri": f"https://api.map.baidu.com/marker?location={lat},{lng}&title={station.name}&content={station.address or ''}&output=html",
        "navigation_uri": f"https://uri.amap.com/navigation?to={lng},{lat},{station.name}&mode=car",
        "share_text": f"{station.name} 充电站：{station.address or ''}（{lng},{lat}）",
    }


async def pile_status_summary(db: AsyncSession) -> dict:
    """充电桩状态汇总（充电枪数量等二期字段一并统计）。"""
    rows = (
        await db.execute(
            select(ChargingPile.status, func.count(ChargingPile.id)).group_by(
                ChargingPile.status
            )
        )
    ).all()
    gun_total = (
        await db.execute(select(func.coalesce(func.sum(ChargingPile.gun_count), 0)))
    ).scalar() or 0
    return {
        "status_dist": [{"name": s or "未知", "value": int(c)} for s, c in rows],
        "gun_total": int(gun_total),
    }
