"""门店货量需求服务。

★ 货量是调度的输入。需求文档里它由 OMS 推送，本项目按确认的方案支持
  系统内手工维护，并提供一个**可重复生成**的演示数据生成器（按门店编码
  哈希取量，同一天反复调用结果一致），方便演示与自测。

  接 OMS 时只需把 upsert_demand 的调用方换成接口导入，调度侧不用改。
"""

from __future__ import annotations

import hashlib
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Route, Store, StoreDemand, StoreRouteMapping


def list_demands(db: Session, schedule_date: date) -> list[tuple[StoreDemand, Store]]:
    """返回某天的货量需求（联表门店，便于前端直接展示门店信息）。"""
    rows = db.execute(
        select(StoreDemand, Store)
        .join(Store, Store.id == StoreDemand.store_id)
        .where(StoreDemand.schedule_date == schedule_date)
        .order_by(Store.id)
    ).all()
    return [(d, s) for d, s in rows]


def get_demand(db: Session, schedule_date: date, store_id: int) -> StoreDemand | None:
    return db.execute(
        select(StoreDemand).where(
            StoreDemand.schedule_date == schedule_date, StoreDemand.store_id == store_id
        )
    ).scalar_one_or_none()


def upsert_demand(
    db: Session,
    *,
    schedule_date: date,
    store_id: int,
    quantity: float,
    remark: str = "",
    commit: bool = True,
) -> StoreDemand:
    """新建或更新某门店某天的货量。"""
    demand = get_demand(db, schedule_date, store_id)
    if demand is None:
        demand = StoreDemand(
            schedule_date=schedule_date,
            store_id=store_id,
            quantity=quantity,
            remark=remark,
        )
        db.add(demand)
    else:
        demand.quantity = quantity
        if remark:
            demand.remark = remark

    if commit:
        db.commit()
        db.refresh(demand)
    return demand


def delete_demand(db: Session, demand_id: int, *, commit: bool = True) -> StoreDemand | None:
    demand = db.get(StoreDemand, demand_id)
    if demand is None:
        return None
    db.delete(demand)
    if commit:
        db.commit()
    return demand


# ---------------------------------------------------------------------------
# 演示数据生成
# ---------------------------------------------------------------------------
# 按门店编码哈希取一个稳定的系数，保证「同一天多次生成结果一致」。
# 这样自检脚本可以反复跑而不会让数据漂移。
_DEMO_BASE_MIN = 300
_DEMO_BASE_SPAN = 2200


def _stable_factor(store_code: str) -> float:
    """由门店编码导出一个 [0,1) 的稳定系数（不依赖随机数）。"""
    digest = hashlib.md5(store_code.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


def generate_demo_demands(
    db: Session, schedule_date: date, *, overwrite: bool = False
) -> dict:
    """为所有启用门店生成当日货量。

    · 货量按门店编码稳定取值（约 300 ~ 2500）
    · 地形越严控、门店越小，货量越低（模拟真实场景的分布）
    · overwrite=False 时只补缺失的门店，不动已有数据
    """
    stores = (
        db.query(Store)
        .filter(Store.is_active.is_(True))
        .order_by(Store.id)
        .all()
    )
    # 已有关联线路的门店优先（没有线路的门店在调度里本来也排不进去）
    mapped_ids = {
        row[0] for row in db.execute(select(StoreRouteMapping.store_id).distinct()).all()
    }

    created, updated, skipped = 0, 0, 0
    total = 0.0

    for store in stores:
        factor = _stable_factor(store.code)

        # 严控地形门店货量偏低（大车进不去，通常是小店）
        terrain_weight = {"normal": 1.0, "medium": 0.75, "strict": 0.5}.get(
            store.terrain_type, 1.0
        )
        # 没有映射线路的门店给很小的量，避免新店完全没有数据
        route_weight = 1.0 if store.id in mapped_ids else 0.2

        quantity = round(
            (_DEMO_BASE_MIN + factor * _DEMO_BASE_SPAN) * terrain_weight * route_weight
        )
        # 取整到 10，读起来干净
        quantity = max(0, int(round(quantity / 10.0)) * 10)

        existing = get_demand(db, schedule_date, store.id)
        if existing is not None and not overwrite:
            skipped += 1
            total += float(existing.quantity)
            continue

        if existing is None:
            created += 1
        else:
            updated += 1
        total += quantity

        upsert_demand(
            db,
            schedule_date=schedule_date,
            store_id=store.id,
            quantity=quantity,
            remark="演示数据（可手工调整）",
            commit=False,
        )

    db.commit()
    return {
        "date": str(schedule_date),
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "stores": len(stores),
        "total_quantity": total,
    }


def demand_summary(db: Session, schedule_date: date) -> dict:
    """某天货量汇总，用于页面顶部概览。"""
    rows = list_demands(db, schedule_date)
    if not rows:
        return {
            "date": str(schedule_date),
            "store_count": 0,
            "total_quantity": 0.0,
            "am_stores": 0,
            "pm_stores": 0,
        }

    total = sum(float(d.quantity) for d, _ in rows)
    return {
        "date": str(schedule_date),
        "store_count": len(rows),
        "total_quantity": total,
        "am_stores": sum(1 for _, s in rows if s.delivery_window == "AM"),
        "pm_stores": sum(1 for _, s in rows if s.delivery_window == "PM"),
        # 单店货量分布，帮助判断车辆是否够用
        "max_store": max(rows, key=lambda r: float(r[0].quantity))[1].name,
        "max_quantity": max(float(d.quantity) for d, _ in rows),
    }


def ensure_routes_mapped(db: Session) -> int:
    """兜底：确认有门店挂在线路上（没有映射的话调度会无解）。返回映射数。"""
    return db.query(StoreRouteMapping).count()


def list_routes(db: Session) -> list[Route]:
    return db.query(Route).filter(Route.is_active.is_(True)).order_by(Route.id).all()
