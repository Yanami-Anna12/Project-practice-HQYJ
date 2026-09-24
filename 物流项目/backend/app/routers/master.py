"""业务基础主数据接口：门店、线路、映射、车辆类型、车辆、司机、地形规则。

对应需求文档 二.2.1「基础主数据管理」与 二.2.2/2.2.3 的规则配置。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import func

from app.deps import DbSession, require_permission
from app.errors import AppError, ConflictError, NotFoundError
from app.models import (
    Driver,
    Route,
    Store,
    StoreRouteMapping,
    SysUser,
    TerrainRule,
    Vehicle,
    VehicleTerrainCapability,
    VehicleType,
)
from app.schemas import (
    DeletedResponse,
    DriverCreate,
    DriverOut,
    DriverUpdate,
    MappingCreate,
    MappingOut,
    RouteCreate,
    RouteOut,
    RouteUpdate,
    StoreCreate,
    StoreOut,
    StoreUpdate,
    TerrainMatrixOut,
    TerrainMatrixUpdate,
    TerrainRuleOut,
    ToggleResponse,
    VehicleCreate,
    VehicleOut,
    VehicleTypeOut,
    VehicleTypeUpdate,
    VehicleUpdate,
)
from app.services.audit import append_audit

router = APIRouter(tags=["基础数据"])

# 各资源的读写权限依赖
StoreReader = Annotated[SysUser, Depends(require_permission("stores:read"))]
StoreManager = Annotated[SysUser, Depends(require_permission("stores:manage"))]
RouteReader = Annotated[SysUser, Depends(require_permission("routes:read"))]
RouteManager = Annotated[SysUser, Depends(require_permission("routes:manage"))]
VehicleReader = Annotated[SysUser, Depends(require_permission("vehicles:read"))]
VehicleManager = Annotated[SysUser, Depends(require_permission("vehicles:manage"))]
DriverReader = Annotated[SysUser, Depends(require_permission("drivers:read"))]
DriverManager = Annotated[SysUser, Depends(require_permission("drivers:manage"))]
TerrainManager = Annotated[SysUser, Depends(require_permission("terrain:manage"))]

# 字典值校验：避免写入字典里不存在的枚举
VALID_TERRAIN = {"normal", "medium", "strict"}
VALID_WINDOW = {"AM", "PM"}
VALID_CAPABILITY = {"all", "big_small", "small_only"}


def _check_enum(value: str, allowed: set[str], field: str) -> None:
    if value not in allowed:
        raise AppError(f"{field} 取值必须是 {'/'.join(sorted(allowed))} 之一，收到 {value}")


# ---------------------------------------------------------------------------
# 门店
# ---------------------------------------------------------------------------
def _store_out(db, store: Store) -> StoreOut:
    codes = [
        r.code
        for r in db.query(Route)
        .join(StoreRouteMapping, StoreRouteMapping.route_id == Route.id)
        .filter(StoreRouteMapping.store_id == store.id)
        .order_by(StoreRouteMapping.priority)
        .all()
    ]
    return StoreOut(
        id=store.id,
        code=store.code,
        name=store.name,
        terrain_type=store.terrain_type,
        delivery_window=store.delivery_window,
        priority=store.priority,
        area=store.area,
        address=store.address,
        contact=store.contact,
        phone=store.phone,
        is_intersection=store.is_intersection,
        is_active=store.is_active,
        route_codes=codes,
    )


@router.get("/stores", response_model=list[StoreOut], summary="门店列表")
def list_stores(db: DbSession, actor: StoreReader) -> list[StoreOut]:
    stores = db.query(Store).order_by(Store.id).all()
    return [_store_out(db, s) for s in stores]


@router.post("/stores", response_model=StoreOut, summary="新建门店")
def create_store(payload: StoreCreate, db: DbSession, actor: StoreManager) -> StoreOut:
    if db.query(Store).filter(Store.code == payload.code).one_or_none():
        raise ConflictError(f"门店编码 {payload.code} 已存在")
    _check_enum(payload.terrain_type, VALID_TERRAIN, "terrain_type")
    _check_enum(payload.delivery_window, VALID_WINDOW, "delivery_window")

    store = Store(**payload.model_dump())
    db.add(store)
    db.commit()
    db.refresh(store)

    append_audit(
        db,
        actor=actor,
        action="store.create",
        target_type="store",
        target_name=store.code,
        detail={"名称": store.name, "地形": store.terrain_type, "时段": store.delivery_window},
    )
    return _store_out(db, store)


@router.put("/stores/{store_id}", response_model=StoreOut, summary="更新门店")
def update_store(
    store_id: int, payload: StoreUpdate, db: DbSession, actor: StoreManager
) -> StoreOut:
    store = db.get(Store, store_id)
    if store is None:
        raise NotFoundError("门店不存在")

    data = payload.model_dump(exclude_unset=True)
    if "terrain_type" in data:
        _check_enum(data["terrain_type"], VALID_TERRAIN, "terrain_type")
    if "delivery_window" in data:
        _check_enum(data["delivery_window"], VALID_WINDOW, "delivery_window")

    changed = {k: v for k, v in data.items()}
    for key, value in data.items():
        setattr(store, key, value)
    db.commit()
    db.refresh(store)

    append_audit(
        db,
        actor=actor,
        action="store.update",
        target_type="store",
        target_name=store.code,
        detail={"变更字段": list(changed)},
    )
    return _store_out(db, store)


@router.delete("/stores/{store_id}", response_model=DeletedResponse, summary="删除门店")
def delete_store(store_id: int, db: DbSession, actor: StoreManager) -> DeletedResponse:
    store = db.get(Store, store_id)
    if store is None:
        raise NotFoundError("门店不存在")

    # 删除保护：仍被线路映射引用时拒绝
    mapped = (
        db.query(StoreRouteMapping).filter(StoreRouteMapping.store_id == store.id).count()
    )
    if mapped:
        raise ConflictError(f"门店 {store.code} 仍被 {mapped} 条线路映射引用，请先解除映射")

    code, name = store.code, store.name
    db.delete(store)
    db.commit()
    append_audit(
        db, actor=actor, action="store.delete", target_type="store",
        target_name=code, detail={"名称": name},
    )
    return DeletedResponse(deleted=code)


# ---------------------------------------------------------------------------
# 线路
# ---------------------------------------------------------------------------
def _route_out(db, route: Route) -> RouteOut:
    count = db.query(StoreRouteMapping).filter(StoreRouteMapping.route_id == route.id).count()
    return RouteOut(
        id=route.id,
        code=route.code,
        name=route.name,
        terrain_scope=route.terrain_scope,
        area=route.area,
        is_restricted=route.is_restricted,
        remark=route.remark,
        is_active=route.is_active,
        store_count=count,
    )


@router.get("/routes", response_model=list[RouteOut], summary="线路列表")
def list_routes(db: DbSession, actor: RouteReader) -> list[RouteOut]:
    routes = db.query(Route).order_by(Route.id).all()
    return [_route_out(db, r) for r in routes]


@router.post("/routes", response_model=RouteOut, summary="新建线路")
def create_route(payload: RouteCreate, db: DbSession, actor: RouteManager) -> RouteOut:
    if db.query(Route).filter(Route.code == payload.code).one_or_none():
        raise ConflictError(f"线路编码 {payload.code} 已存在")

    route = Route(**payload.model_dump())
    db.add(route)
    db.commit()
    db.refresh(route)

    append_audit(
        db, actor=actor, action="route.create", target_type="route",
        target_name=route.code, detail={"名称": route.name},
    )
    return _route_out(db, route)


@router.put("/routes/{route_id}", response_model=RouteOut, summary="更新线路")
def update_route(
    route_id: int, payload: RouteUpdate, db: DbSession, actor: RouteManager
) -> RouteOut:
    route = db.get(Route, route_id)
    if route is None:
        raise NotFoundError("线路不存在")

    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(route, key, value)
    db.commit()
    db.refresh(route)

    append_audit(
        db, actor=actor, action="route.update", target_type="route",
        target_name=route.code, detail={"变更字段": list(data)},
    )
    return _route_out(db, route)


@router.delete("/routes/{route_id}", response_model=DeletedResponse, summary="删除线路")
def delete_route(route_id: int, db: DbSession, actor: RouteManager) -> DeletedResponse:
    route = db.get(Route, route_id)
    if route is None:
        raise NotFoundError("线路不存在")

    mapped = db.query(StoreRouteMapping).filter(StoreRouteMapping.route_id == route.id).count()
    if mapped:
        raise ConflictError(f"线路 {route.code} 仍关联 {mapped} 个门店，请先解除映射")

    code, name = route.code, route.name
    db.delete(route)
    db.commit()
    append_audit(
        db, actor=actor, action="route.delete", target_type="route",
        target_name=code, detail={"名称": name},
    )
    return DeletedResponse(deleted=code)


# ---------------------------------------------------------------------------
# 门店线路映射
# ---------------------------------------------------------------------------
@router.get("/mappings", response_model=list[MappingOut], summary="门店线路映射列表")
def list_mappings(db: DbSession, actor: RouteReader) -> list[MappingOut]:
    rows = db.query(StoreRouteMapping).order_by(StoreRouteMapping.id).all()
    stores = {s.id: s for s in db.query(Store).all()}
    routes = {r.id: r for r in db.query(Route).all()}
    return [
        MappingOut(
            id=m.id,
            store_id=m.store_id,
            store_code=stores[m.store_id].code if m.store_id in stores else "",
            store_name=stores[m.store_id].name if m.store_id in stores else "",
            route_id=m.route_id,
            route_code=routes[m.route_id].code if m.route_id in routes else "",
            route_name=routes[m.route_id].name if m.route_id in routes else "",
            priority=m.priority,
            is_primary=m.is_primary,
        )
        for m in rows
    ]


@router.post("/mappings", response_model=MappingOut, summary="新建门店线路映射")
def create_mapping(
    payload: MappingCreate, db: DbSession, actor: RouteManager
) -> MappingOut:
    if db.get(Store, payload.store_id) is None:
        raise NotFoundError("门店不存在")
    if db.get(Route, payload.route_id) is None:
        raise NotFoundError("线路不存在")

    exists = (
        db.query(StoreRouteMapping)
        .filter(
            StoreRouteMapping.store_id == payload.store_id,
            StoreRouteMapping.route_id == payload.route_id,
        )
        .one_or_none()
    )
    if exists is not None:
        raise ConflictError("该门店与线路的映射已存在")

    mapping = StoreRouteMapping(**payload.model_dump())
    db.add(mapping)
    db.flush()

    # 交界门店判定：一个门店挂到 >=2 条线路即为交界
    total = (
        db.query(func.count(StoreRouteMapping.id))
        .filter(StoreRouteMapping.store_id == payload.store_id)
        .scalar()
    )
    store = db.get(Store, payload.store_id)
    if store is not None:
        store.is_intersection = bool(total and total >= 2)

    db.commit()
    db.refresh(mapping)

    append_audit(
        db, actor=actor, action="mapping.create", target_type="store_route",
        target_name=f"{store.code}->{db.get(Route, payload.route_id).code}",
        detail={"优先级": mapping.priority, "主线路": mapping.is_primary},
    )
    return next(m for m in list_mappings(db, actor) if m.id == mapping.id)


@router.delete("/mappings/{mapping_id}", response_model=DeletedResponse, summary="删除映射")
def delete_mapping(
    mapping_id: int, db: DbSession, actor: RouteManager
) -> DeletedResponse:
    mapping = db.get(StoreRouteMapping, mapping_id)
    if mapping is None:
        raise NotFoundError("映射不存在")

    store_id = mapping.store_id
    db.delete(mapping)
    db.flush()

    total = (
        db.query(func.count(StoreRouteMapping.id))
        .filter(StoreRouteMapping.store_id == store_id)
        .scalar()
    )
    store = db.get(Store, store_id)
    if store is not None:
        store.is_intersection = bool(total and total >= 2)

    db.commit()
    append_audit(
        db, actor=actor, action="mapping.delete", target_type="store_route",
        target_name=str(mapping_id), detail={},
    )
    return DeletedResponse(deleted=str(mapping_id))


# ---------------------------------------------------------------------------
# 车辆类型
# ---------------------------------------------------------------------------
@router.get("/vehicle-types", response_model=list[VehicleTypeOut], summary="车辆类型列表")
def list_vehicle_types(db: DbSession, actor: VehicleReader) -> list[VehicleTypeOut]:
    types = db.query(VehicleType).order_by(VehicleType.id).all()
    counts = dict(
        db.query(Vehicle.vehicle_type_code, func.count(Vehicle.id))
        .group_by(Vehicle.vehicle_type_code)
        .all()
    )
    return [
        VehicleTypeOut(
            id=t.id,
            code=t.code,
            name=t.name,
            min_load=t.min_load,
            max_load=t.max_load,
            trips_per_day=t.trips_per_day,
            am_trips=t.am_trips,
            pm_trips=t.pm_trips,
            planned_count=t.planned_count,
            remark=t.remark,
            is_active=t.is_active,
            vehicle_count=counts.get(t.code, 0),
        )
        for t in types
    ]


@router.put("/vehicle-types/{type_id}", response_model=VehicleTypeOut, summary="更新车辆类型规则")
def update_vehicle_type(
    type_id: int, payload: VehicleTypeUpdate, db: DbSession, actor: VehicleManager
) -> VehicleTypeOut:
    vt = db.get(VehicleType, type_id)
    if vt is None:
        raise NotFoundError("车辆类型不存在")

    data = payload.model_dump(exclude_unset=True)
    if "min_load" in data and "max_load" in data and data["min_load"] > data["max_load"]:
        raise AppError("最低装载量不能大于最高装载量")

    for key, value in data.items():
        setattr(vt, key, value)

    # 趟次一致性：上午+下午 应等于每日趟次（需求里的硬约束）
    if vt.am_trips + vt.pm_trips != vt.trips_per_day:
        raise AppError(
            f"上午趟次({vt.am_trips}) + 下午趟次({vt.pm_trips}) "
            f"必须等于每日趟次({vt.trips_per_day})"
        )

    db.commit()
    db.refresh(vt)
    append_audit(
        db, actor=actor, action="vehicle_type.update", target_type="vehicle_type",
        target_name=vt.code, detail={"变更字段": list(data)},
    )
    return next(t for t in list_vehicle_types(db, actor) if t.id == vt.id)


# ---------------------------------------------------------------------------
# 车辆
# ---------------------------------------------------------------------------
@router.get("/vehicles", response_model=list[VehicleOut], summary="车辆列表")
def list_vehicles(db: DbSession, actor: VehicleReader) -> list[VehicleOut]:
    vehicles = db.query(Vehicle).order_by(Vehicle.id).all()
    type_names = {t.code: t.name for t in db.query(VehicleType).all()}
    drivers = {d.id: d.name for d in db.query(Driver).all()}
    return [
        VehicleOut(
            id=v.id,
            plate_no=v.plate_no,
            vehicle_type_code=v.vehicle_type_code,
            vehicle_type_name=type_names.get(v.vehicle_type_code, ""),
            terrain_capability=v.terrain_capability,
            route_scope=v.route_scope,
            status=v.status,
            driver_id=v.driver_id,
            driver_name=drivers.get(v.driver_id, "") if v.driver_id else "",
            remark=v.remark,
            is_active=v.is_active,
        )
        for v in vehicles
    ]


@router.post("/vehicles", response_model=VehicleOut, summary="新建车辆")
def create_vehicle(payload: VehicleCreate, db: DbSession, actor: VehicleManager) -> VehicleOut:
    if db.query(Vehicle).filter(Vehicle.plate_no == payload.plate_no).one_or_none():
        raise ConflictError(f"车牌号 {payload.plate_no} 已存在")
    if not db.query(VehicleType).filter(VehicleType.code == payload.vehicle_type_code).one_or_none():
        raise NotFoundError(f"车辆类型 {payload.vehicle_type_code} 不存在")
    _check_enum(payload.terrain_capability, VALID_CAPABILITY, "terrain_capability")

    vehicle = Vehicle(**payload.model_dump())
    db.add(vehicle)
    db.commit()
    db.refresh(vehicle)

    append_audit(
        db, actor=actor, action="vehicle.create", target_type="vehicle",
        target_name=vehicle.plate_no, detail={"类型": vehicle.vehicle_type_code},
    )
    return next(v for v in list_vehicles(db, actor) if v.id == vehicle.id)


@router.put("/vehicles/{vehicle_id}", response_model=VehicleOut, summary="更新车辆")
def update_vehicle(
    vehicle_id: int, payload: VehicleUpdate, db: DbSession, actor: VehicleManager
) -> VehicleOut:
    vehicle = db.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise NotFoundError("车辆不存在")

    data = payload.model_dump(exclude_unset=True)
    if "terrain_capability" in data:
        _check_enum(data["terrain_capability"], VALID_CAPABILITY, "terrain_capability")
    for key, value in data.items():
        setattr(vehicle, key, value)
    db.commit()
    db.refresh(vehicle)

    append_audit(
        db, actor=actor, action="vehicle.update", target_type="vehicle",
        target_name=vehicle.plate_no, detail={"变更字段": list(data)},
    )
    return next(v for v in list_vehicles(db, actor) if v.id == vehicle.id)


@router.delete("/vehicles/{vehicle_id}", response_model=DeletedResponse, summary="删除车辆")
def delete_vehicle(
    vehicle_id: int, db: DbSession, actor: VehicleManager
) -> DeletedResponse:
    vehicle = db.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise NotFoundError("车辆不存在")

    plate = vehicle.plate_no
    db.delete(vehicle)
    db.commit()
    append_audit(
        db, actor=actor, action="vehicle.delete", target_type="vehicle",
        target_name=plate, detail={},
    )
    return DeletedResponse(deleted=plate)


# ---------------------------------------------------------------------------
# 司机
# ---------------------------------------------------------------------------
@router.get("/drivers", response_model=list[DriverOut], summary="司机列表")
def list_drivers(db: DbSession, actor: DriverReader) -> list[DriverOut]:
    drivers = db.query(Driver).order_by(Driver.id).all()
    return [DriverOut.model_validate(d) for d in drivers]


@router.post("/drivers", response_model=DriverOut, summary="新建司机")
def create_driver(payload: DriverCreate, db: DbSession, actor: DriverManager) -> DriverOut:
    if db.query(Driver).filter(Driver.code == payload.code).one_or_none():
        raise ConflictError(f"司机工号 {payload.code} 已存在")

    driver = Driver(**payload.model_dump())
    db.add(driver)
    db.commit()
    db.refresh(driver)

    append_audit(
        db, actor=actor, action="driver.create", target_type="driver",
        target_name=driver.code, detail={"姓名": driver.name},
    )
    return DriverOut.model_validate(driver)


@router.put("/drivers/{driver_id}", response_model=DriverOut, summary="更新司机")
def update_driver(
    driver_id: int, payload: DriverUpdate, db: DbSession, actor: DriverManager
) -> DriverOut:
    driver = db.get(Driver, driver_id)
    if driver is None:
        raise NotFoundError("司机不存在")

    data = payload.model_dump(exclude_unset=True)
    for key, value in data.items():
        setattr(driver, key, value)
    db.commit()
    db.refresh(driver)

    append_audit(
        db, actor=actor, action="driver.update", target_type="driver",
        target_name=driver.code, detail={"变更字段": list(data)},
    )
    return DriverOut.model_validate(driver)


@router.delete("/drivers/{driver_id}", response_model=DeletedResponse, summary="删除司机")
def delete_driver(driver_id: int, db: DbSession, actor: DriverManager) -> DeletedResponse:
    driver = db.get(Driver, driver_id)
    if driver is None:
        raise NotFoundError("司机不存在")

    bound = db.query(Vehicle).filter(Vehicle.driver_id == driver.id).count()
    if bound:
        raise ConflictError(f"司机 {driver.name} 仍绑定 {bound} 台车辆，请先解绑")

    code = driver.code
    db.delete(driver)
    db.commit()
    append_audit(
        db, actor=actor, action="driver.delete", target_type="driver",
        target_name=code, detail={},
    )
    return DeletedResponse(deleted=code)


# ---------------------------------------------------------------------------
# 地形规则与通行矩阵
# ---------------------------------------------------------------------------
@router.get("/terrain-rules", response_model=list[TerrainRuleOut], summary="地形规则列表")
def list_terrain_rules(db: DbSession, actor: TerrainManager) -> list[TerrainRuleOut]:
    rules = db.query(TerrainRule).order_by(TerrainRule.level).all()
    return [TerrainRuleOut.model_validate(r) for r in rules]


@router.get("/terrain-matrix", response_model=list[TerrainMatrixOut], summary="地形-车辆通行矩阵")
def list_terrain_matrix(db: DbSession, actor: TerrainManager) -> list[TerrainMatrixOut]:
    rows = (
        db.query(VehicleTerrainCapability)
        .order_by(VehicleTerrainCapability.terrain_type, VehicleTerrainCapability.capability)
        .all()
    )
    return [TerrainMatrixOut.model_validate(r) for r in rows]


@router.put(
    "/terrain-matrix/{matrix_id}",
    response_model=TerrainMatrixOut,
    summary="修改通行矩阵单元格",
)
def update_terrain_matrix(
    matrix_id: int, payload: TerrainMatrixUpdate, db: DbSession, actor: TerrainManager
) -> TerrainMatrixOut:
    cell = db.get(VehicleTerrainCapability, matrix_id)
    if cell is None:
        raise NotFoundError("通行矩阵单元格不存在")

    before = cell.allowed
    cell.allowed = payload.allowed
    if payload.remark:
        cell.remark = payload.remark
    db.commit()
    db.refresh(cell)

    append_audit(
        db, actor=actor, action="terrain_matrix.update", target_type="terrain",
        target_name=f"{cell.terrain_type}/{cell.capability}",
        detail={"变更": f"{'允许' if before else '禁止'} → {'允许' if cell.allowed else '禁止'}"},
    )
    return TerrainMatrixOut.model_validate(cell)
