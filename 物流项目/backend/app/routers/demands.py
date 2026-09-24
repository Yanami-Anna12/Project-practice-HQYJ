"""门店货量需求接口（调度输入）。"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.deps import DbSession, require_permission
from app.errors import NotFoundError
from app.models import Route, Store, StoreDemand, StoreRouteMapping, SysUser, VehicleType
from app.schemas import (
    DeletedResponse,
    DemandGenerateRequest,
    DemandGenerateResult,
    DemandOut,
    DemandSummary,
    DemandUpsert,
)
from app.services import demand as demand_service
from app.services.audit import append_audit

router = APIRouter(prefix="/demands", tags=["门店货量"])

Reader = Annotated[SysUser, Depends(require_permission("stores:read"))]
Manager = Annotated[SysUser, Depends(require_permission("stores:manage"))]


def _to_out(db, demand: StoreDemand, store: Store) -> DemandOut:
    route_codes = [
        row[0]
        for row in db.query(Route.code)
        .join(StoreRouteMapping, StoreRouteMapping.route_id == Route.id)
        .filter(StoreRouteMapping.store_id == store.id)
        .order_by(StoreRouteMapping.priority)
        .all()
    ]
    # 四米二的最大装载量，用来估算至少需要几趟
    vt = (
        db.query(VehicleType)
        .filter(VehicleType.code == "4.2m")
        .one_or_none()
    )
    max_load = vt.max_load if vt else 800
    quantity = float(demand.quantity)
    min_trips = int(-(-quantity // max_load)) if max_load else 0

    return DemandOut(
        id=demand.id,
        schedule_date=demand.schedule_date,
        store_id=demand.store_id,
        store_code=store.code,
        store_name=store.name,
        terrain_type=store.terrain_type,
        delivery_window=store.delivery_window,
        route_codes=route_codes,
        quantity=quantity,
        remark=demand.remark,
        min_trips_4_2m=min_trips,
    )


@router.get("", response_model=list[DemandOut], summary="某日门店货量列表")
def list_demands(
    db: DbSession,
    actor: Reader,
    schedule_date: date = Query(..., description="调度日期，格式 YYYY-MM-DD"),
) -> list[DemandOut]:
    rows = demand_service.list_demands(db, schedule_date)
    return [_to_out(db, d, s) for d, s in rows]


@router.get("/summary", response_model=DemandSummary, summary="某日货量汇总")
def demand_summary(
    db: DbSession,
    actor: Reader,
    schedule_date: date = Query(..., description="调度日期"),
) -> DemandSummary:
    return DemandSummary(**demand_service.demand_summary(db, schedule_date))


@router.put("", response_model=DemandOut, summary="新增或修改门店货量")
def upsert_demand(payload: DemandUpsert, db: DbSession, actor: Manager) -> DemandOut:
    store = db.get(Store, payload.store_id)
    if store is None:
        raise NotFoundError("门店不存在")

    before = demand_service.get_demand(db, payload.schedule_date, payload.store_id)
    before_qty = float(before.quantity) if before else None

    demand = demand_service.upsert_demand(
        db,
        schedule_date=payload.schedule_date,
        store_id=payload.store_id,
        quantity=payload.quantity,
        remark=payload.remark,
    )

    append_audit(
        db,
        actor=actor,
        action="demand.upsert",
        target_type="demand",
        target_name=f"{payload.schedule_date}:{store.code}",
        detail={
            "门店": store.name,
            "变更": f"{before_qty} → {payload.quantity}"
            if before_qty is not None
            else f"新增 {payload.quantity}",
        },
    )
    return _to_out(db, demand, store)


@router.post("/generate", response_model=DemandGenerateResult, summary="生成演示货量")
def generate_demands(
    payload: DemandGenerateRequest, db: DbSession, actor: Manager
) -> DemandGenerateResult:
    """为所有门店生成当日货量。

    ★ 按门店编码哈希取量，同一天反复调用结果一致（不会让数据漂移），
      overwrite=False 时只补缺失的门店。
    """
    result = demand_service.generate_demo_demands(
        db, payload.schedule_date, overwrite=payload.overwrite
    )
    append_audit(
        db,
        actor=actor,
        action="demand.generate",
        target_type="demand",
        target_name=str(payload.schedule_date),
        detail={
            "新建": result["created"],
            "更新": result["updated"],
            "跳过": result["skipped"],
            "货量合计": result["total_quantity"],
        },
    )
    return DemandGenerateResult(**result)


@router.delete("/{demand_id}", response_model=DeletedResponse, summary="删除货量记录")
def delete_demand(demand_id: int, db: DbSession, actor: Manager) -> DeletedResponse:
    demand = demand_service.delete_demand(db, demand_id)
    if demand is None:
        raise NotFoundError("货量记录不存在")
    append_audit(
        db,
        actor=actor,
        action="demand.delete",
        target_type="demand",
        target_name=str(demand.schedule_date),
        detail={"门店ID": demand.store_id},
    )
    return DeletedResponse(deleted=str(demand_id))
