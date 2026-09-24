"""初始数据载入脚本。

用法：
    python seed.py            # 建表 + 载入初始数据（已存在的数据不重复插入）
    python seed.py --reset    # 先删表重建，再载入（会清空所有数据）

★ 数值来源：《需求文档.md》
  - 一.3 现有条件：四米二 28 台 630-800 日 2 趟 / 大包 3 台 300-420 日 2 趟 / 小包 9 台 1-300 日 4 趟
  - 一.5 需求明细：上午门店上午送、下午门店下午送、门店与线路多对多
  - 二.2.3 地形与通行规则：普通/中控/严控 × 全能去/大小包能去/小包能去
"""

from __future__ import annotations

import argparse
import logging
import sys

from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal, create_all_tables, drop_all_tables, ensure_database_exists
from app.models import (
    Driver,
    Route,
    Store,
    StoreRouteMapping,
    SysAttachment,
    SysDictItem,
    SysDictType,
    SysParam,
    SysPermission,
    SysRole,
    SysUser,
    TerrainRule,
    Vehicle,
    VehicleTerrainCapability,
    VehicleType,
)
from app.security import hash_password
from app.services.audit import append_audit

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
logger = logging.getLogger("seed")


# ---------------------------------------------------------------------------
# 权限点：模块 × 动作。与前端 src/api/mockDb.js 的清单保持一致。
# ---------------------------------------------------------------------------
PERMISSIONS: list[tuple[str, str, str, str]] = [
    # (code, name, module, action)
    ("users:read", "查看用户", "系统管理", "read"),
    ("users:manage", "维护用户", "系统管理", "manage"),
    ("roles:read", "查看角色", "系统管理", "read"),
    ("roles:manage", "维护角色", "系统管理", "manage"),
    ("permissions:read", "查看权限点", "系统管理", "read"),
    ("permissions:manage", "维护权限点", "系统管理", "manage"),
    ("dicts:read", "查看字典", "系统管理", "read"),
    ("dicts:manage", "维护字典", "系统管理", "manage"),
    ("params:read", "查看参数", "系统管理", "read"),
    ("params:manage", "维护参数", "系统管理", "manage"),
    ("attachments:read", "查看附件", "系统管理", "read"),
    ("attachments:manage", "维护附件", "系统管理", "manage"),
    ("logs:read", "查看日志", "系统管理", "read"),
    ("stores:read", "查看门店", "基础数据", "read"),
    ("stores:manage", "维护门店", "基础数据", "manage"),
    ("routes:read", "查看线路", "基础数据", "read"),
    ("routes:manage", "维护线路", "基础数据", "manage"),
    ("vehicles:read", "查看车辆", "基础数据", "read"),
    ("vehicles:manage", "维护车辆", "基础数据", "manage"),
    ("drivers:read", "查看司机", "基础数据", "read"),
    ("drivers:manage", "维护司机", "基础数据", "manage"),
    ("terrain:manage", "维护地形规则", "基础数据", "manage"),
    ("scheduling:read", "查看调度任务", "智能调度", "read"),
    ("scheduling:create", "创建调度任务", "智能调度", "create"),
    ("scheduling:confirm", "人工确认方案", "智能调度", "confirm"),
    ("scheduling:replan", "异常重排", "智能调度", "replan"),
    ("reports:view", "查看报表", "智能调度", "view"),
    ("integrations:manage", "维护接口集成", "集成监控", "manage"),
    ("monitor:read", "查看监控预警", "集成监控", "read"),
]

ROLES: list[tuple[str, str, str, list[str]]] = [
    # (code, name, description, 权限码；"*" 表示全部)
    ("admin", "系统管理员", "拥有全部权限，可维护系统管理与基础数据", ["*"]),
    (
        "dispatcher",
        "调度员",
        "创建调度任务、确认方案、处理异常重排",
        [
            "stores:read", "routes:read", "vehicles:read", "drivers:read",
            "scheduling:read", "scheduling:create", "scheduling:confirm",
            "scheduling:replan", "reports:view",
        ],
    ),
    (
        "data_admin",
        "基础数据管理员",
        "维护门店、线路、车辆、司机、地形规则",
        [
            "stores:read", "stores:manage", "routes:read", "routes:manage",
            "vehicles:read", "vehicles:manage", "drivers:read", "drivers:manage",
            "terrain:manage", "reports:view",
        ],
    ),
    (
        "viewer",
        "只读观察者",
        "只能查看，不能做任何修改",
        ["stores:read", "routes:read", "vehicles:read", "scheduling:read", "reports:view"],
    ),
]

USERS: list[tuple[str, str, str, str, str, list[str]]] = [
    # (username, nickname, dept, phone, 密码字段名, 角色码)
    ("admin", "系统管理员", "信息部", "13800000001", "ADMIN_INIT_PASSWORD", ["admin"]),
    ("dispatcher", "张调度", "调度中心", "13800000002", "DEMO_PASSWORD", ["dispatcher"]),
    ("dataadmin", "李数据", "运营部", "13800000003", "DEMO_PASSWORD", ["data_admin"]),
    ("viewer", "王观察", "财务部", "13800000004", "DEMO_PASSWORD", ["viewer"]),
    ("multi", "多角色用户", "调度中心", "13800000005", "DEMO_PASSWORD", ["dispatcher", "viewer"]),
    ("disabled", "已停用账号", "运营部", "13800000006", "DEMO_PASSWORD", ["viewer"]),
]

# 字典：车辆类型 / 地形 / 能力 / 时段 / 任务状态 / 方案 / 班次
DICT_TYPES: list[tuple[str, str, str]] = [
    ("vehicle_type", "车辆类型", "四米二 / 大包 / 小包"),
    ("terrain_type", "地形限制", "普通 / 中控 / 严控"),
    ("terrain_capability", "车辆地形能力", "全能去 / 大小包能去 / 小包能去"),
    ("time_window", "配送时段", "上午 / 下午"),
    ("task_status", "调度任务状态", "调度任务的流转状态"),
    ("plan_code", "方案编号", "A/B/C/D 四套方案"),
    ("driver_shift", "司机班次", "上午班 / 下午班 / 全天"),
]

DICT_ITEMS: list[tuple[str, str, str, int, str]] = [
    # (type_code, label, value, sort, remark)
    ("vehicle_type", "四米二", "4.2m", 1, "28 台，装载 630-800，日 2 趟"),
    ("vehicle_type", "大包", "big", 2, "3 台，装载 300-420，日 2 趟"),
    ("vehicle_type", "小包", "small", 3, "9 台，装载 1-300，日 4 趟"),
    ("terrain_type", "普通", "normal", 1, "通行限制较少"),
    ("terrain_type", "中控", "medium", 2, "中等管控"),
    ("terrain_type", "严控", "strict", 3, "严格管控"),
    ("terrain_capability", "全能去", "all", 1, "三种地形都能通行"),
    ("terrain_capability", "大小包能去", "big_small", 2, "普通 / 中控可通行"),
    ("terrain_capability", "小包能去", "small_only", 3, "仅普通地形可通行"),
    ("time_window", "上午", "AM", 1, "上午门店只能上午趟"),
    ("time_window", "下午", "PM", 2, "下午门店只能下午趟"),
    ("task_status", "待调度", "created", 1, "任务已创建"),
    ("task_status", "求解中", "running", 2, "正在生成方案"),
    ("task_status", "待确认", "pending_confirm", 3, "等待人工确认"),
    ("task_status", "已下发", "dispatched", 4, "已下发 TMS"),
    ("task_status", "已完成", "completed", 5, "执行完成"),
    ("plan_code", "方案 A · 四米二优先", "A", 1, "CP-SAT 求解"),
    ("plan_code", "方案 B · 成本最低", "B", 2, "启发式"),
    ("plan_code", "方案 C · 大包小包趟次保障优先", "C", 3, "启发式"),
    ("plan_code", "方案 D · 装载率均衡", "D", 4, "CP-SAT 求解"),
    ("driver_shift", "上午班", "AM", 1, "上午 1-2 趟"),
    ("driver_shift", "下午班", "PM", 2, "下午 1-2 趟"),
    ("driver_shift", "全天", "FULL", 3, "上午 + 下午"),
]

PARAMS: list[tuple[str, str, str, str, str, str]] = [
    # (key, name, value, type, group, remark)
    ("scheduling.solver.timeout_seconds", "求解超时（秒）", "30", "int", "调度", "超过则回退到启发式解"),
    ("scheduling.replan.max_count", "最大重排次数", "3", "int", "调度", "防止异常重排死循环"),
    ("scheduling.plan.candidate_count", "候选方案数", "4", "int", "调度", "A/B/C/D 四套方案"),
    ("scheduling.confirm.required", "是否必须人工确认", "true", "bool", "调度", "关闭后将自动下发"),
    ("rule.version.current", "当前规则版本", "v1.0.0", "string", "规则", "每次调度记录该版本"),
    ("dispatch.idempotent.key", "下发幂等键", "task_id+plan_id+trip_id", "string", "下发", "避免重复下发"),
    ("llm.explain.enabled", "启用 LLM 方案解释", "true", "bool", "智能", "硬约束不交给 LLM"),
    ("vehicle.dynamic.enabled", "动态车辆调节", "true", "bool", "业务", "不保障 28/3/9 台满勤"),
]

VEHICLE_TYPES: list[tuple[str, str, int, int, int, int, int, int, str]] = [
    # (code, name, min_load, max_load, trips_per_day, am_trips, pm_trips, planned_count, remark)
    ("4.2m", "四米二", 630, 800, 2, 1, 1, 28, "主力车型，多种派车方案优先使用"),
    ("big", "大包", 300, 420, 2, 1, 1, 3, "货量不足时优先保障日出车次数"),
    ("small", "小包", 1, 300, 4, 2, 2, 9, "货量不足时优先保障日出车次数"),
]

TERRAIN_RULES: list[tuple[str, str, int, str]] = [
    ("normal", "普通", 1, "通行限制较少，所有车型均可进入"),
    ("medium", "中控", 2, "中等管控，仅全能去与大小包能去的车辆可进入"),
    ("strict", "严控", 3, "严格管控，仅全能去的车辆可进入"),
]

# 地形-车辆通行矩阵（需求 2.2.3）
TERRAIN_MATRIX: list[tuple[str, str, bool, str]] = [
    # (terrain_type, capability, allowed, remark)
    ("normal", "all", True, "全能去可进普通地形"),
    ("normal", "big_small", True, "大小包能去可进普通地形"),
    ("normal", "small_only", True, "小包能去可进普通地形"),
    ("medium", "all", True, "全能去可进中控地形"),
    ("medium", "big_small", True, "大小包能去可进中控地形"),
    ("medium", "small_only", False, "小包能去不可进中控地形"),
    ("strict", "all", True, "全能去可进严控地形"),
    ("strict", "big_small", False, "大小包能去不可进严控地形"),
    ("strict", "small_only", False, "小包能去不可进严控地形"),
]

ROUTES: list[tuple[str, str, str, str, bool, str]] = [
    # (code, name, terrain_scope, area, is_restricted, remark)
    ("R01", "城东线", "normal,medium", "城东片区", False, "覆盖城东 6 个门店"),
    ("R02", "城西线", "normal", "城西片区", False, "覆盖城西 5 个门店"),
    ("R03", "城南线", "normal,medium,strict", "城南片区", False, "含严控地形门店"),
    ("R04", "城北线", "normal,medium", "城北片区", False, "覆盖城北 5 个门店"),
    ("R05", "开发区线", "normal", "经济开发区", True, "部分时段限行"),
]

STORES: list[tuple[str, str, str, str, int, str, str, str, str]] = [
    # (code, name, terrain_type, delivery_window, priority, area, address, contact, phone)
    ("S001", "城东旗舰店", "normal", "AM", 10, "城东片区", "城东大道 1 号", "刘店长", "13900000001"),
    ("S002", "城东社区店", "normal", "AM", 20, "城东片区", "城东二路 18 号", "陈店长", "13900000002"),
    ("S003", "东湖便利店", "medium", "AM", 30, "城东片区", "东湖路 7 号", "赵店长", "13900000003"),
    ("S004", "城西中心店", "normal", "PM", 10, "城西片区", "城西大道 88 号", "孙店长", "13900000004"),
    ("S005", "西城仓储店", "normal", "PM", 20, "城西片区", "西城工业路 5 号", "周店长", "13900000005"),
    ("S006", "城南大卖场", "medium", "AM", 10, "城南片区", "城南大道 200 号", "吴店长", "13900000006"),
    ("S007", "南苑严控店", "strict", "PM", 40, "城南片区", "南苑路 12 号", "郑店长", "13900000007"),
    ("S008", "城南新区店", "normal", "PM", 30, "城南片区", "新区一路 3 号", "冯店长", "13900000008"),
    ("S009", "城北批发店", "normal", "AM", 10, "城北片区", "城北大道 66 号", "蒋店长", "13900000009"),
    ("S010", "北环中控店", "medium", "AM", 30, "城北片区", "北环路 21 号", "沈店长", "13900000010"),
    ("S011", "北苑社区店", "normal", "PM", 20, "城北片区", "北苑街 9 号", "韩店长", "13900000011"),
    ("S012", "开发区店", "normal", "AM", 20, "经济开发区", "开发大道 100 号", "杨店长", "13900000012"),
    ("S013", "开发二路店", "normal", "PM", 30, "经济开发区", "开发二路 15 号", "朱店长", "13900000013"),
    ("S014", "高铁站店", "medium", "AM", 40, "城东片区", "高铁站广场 B1", "秦店长", "13900000014"),
    ("S015", "老城区店", "strict", "AM", 50, "城北片区", "老城正街 2 号", "尤店长", "13900000015"),
    ("S016", "滨江店", "normal", "PM", 20, "城南片区", "滨江路 33 号", "许店长", "13900000016"),
]

# (store_code, route_code, priority, is_primary) —— 含交界门店（挂多条线路）
MAPPINGS: list[tuple[str, str, int, bool]] = [
    ("S001", "R01", 10, True),
    ("S002", "R01", 20, True),
    ("S003", "R01", 30, True),
    ("S014", "R01", 40, False),
    ("S014", "R04", 40, True),   # 交界：高铁站店同时属于城东线与城北线
    ("S004", "R02", 10, True),
    ("S005", "R02", 20, True),
    ("S016", "R02", 30, True),
    ("S006", "R03", 10, True),
    ("S007", "R03", 40, True),
    ("S008", "R03", 30, True),
    ("S016", "R03", 50, False),  # 交界：滨江店同时属于城西线与城南线
    ("S009", "R04", 10, True),
    ("S010", "R04", 30, True),
    ("S011", "R04", 20, True),
    ("S015", "R04", 50, False),
    ("S015", "R03", 60, False),  # 交界：老城区店同时属于城北线与城南线
    ("S012", "R05", 20, True),
    ("S013", "R05", 30, True),
]

ATTACHMENTS: list[tuple[str, str, int, str]] = [
    ("车辆智能调度 Agent 项目技术方案.pdf", "技术方案", 719991, "admin"),
    ("随堂笔记.pdf", "需求资料", 502736, "admin"),
    ("需求文档.md", "需求资料", 30412, "admin"),
    ("车辆档案导入模板.xlsx", "导入模板", 24128, "dataadmin"),
]

DRIVERS: list[tuple[str, str, str, str, str]] = [
    # (code, name, phone, shift, status)
    ("D001", "赵师傅", "13700000001", "FULL", "available"),
    ("D002", "钱师傅", "13700000002", "FULL", "available"),
    ("D003", "孙师傅", "13700000003", "AM", "available"),
    ("D004", "李师傅", "13700000004", "PM", "available"),
    ("D005", "周师傅", "13700000005", "FULL", "available"),
    ("D006", "吴师傅", "13700000006", "AM", "leave"),
    ("D007", "郑师傅", "13700000007", "PM", "available"),
    ("D008", "王师傅", "13700000008", "FULL", "available"),
]


def _seed_permissions(db: Session) -> dict[str, SysPermission]:
    created = {}
    for code, name, module, action in PERMISSIONS:
        perm = db.query(SysPermission).filter(SysPermission.code == code).one_or_none()
        if perm is None:
            perm = SysPermission(code=code, name=name, module=module, action=action, is_active=True)
            db.add(perm)
            db.flush()
        created[code] = perm
    db.commit()
    logger.info("权限点：%d 个", len(created))
    return created


def _seed_roles(db: Session, perms: dict[str, SysPermission]) -> dict[str, SysRole]:
    created = {}
    for code, name, description, codes in ROLES:
        role = db.query(SysRole).filter(SysRole.code == code).one_or_none()
        if role is None:
            role = SysRole(code=code, name=name, description=description, is_active=True)
            db.add(role)
            db.flush()
        # "*" 表示全部权限
        wanted = list(perms.values()) if codes == ["*"] else [perms[c] for c in codes]
        role.permissions = wanted
        created[code] = role
    db.commit()
    logger.info("角色：%d 个", len(created))
    return created


def _seed_users(db: Session, roles: dict[str, SysRole]) -> None:
    for username, nickname, dept, phone, pwd_attr, role_codes in USERS:
        user = db.query(SysUser).filter(SysUser.username == username).one_or_none()
        if user is None:
            user = SysUser(
                username=username,
                password_hash=hash_password(getattr(settings, pwd_attr)),
                nickname=nickname,
                dept=dept,
                phone=phone,
                is_active=True,
            )
            db.add(user)
            db.flush()
        user.roles = [roles[c] for c in role_codes]

    # 演示用：把 disabled 账号置为停用
    disabled = db.query(SysUser).filter(SysUser.username == "disabled").one_or_none()
    if disabled is not None:
        disabled.is_active = False

    db.commit()
    logger.info("用户：%d 个", len(USERS))


def _seed_dicts(db: Session) -> None:
    for code, name, description in DICT_TYPES:
        if db.query(SysDictType).filter(SysDictType.code == code).one_or_none() is None:
            db.add(SysDictType(code=code, name=name, description=description, is_active=True))
    db.flush()

    for type_code, label, value, sort, remark in DICT_ITEMS:
        exists = (
            db.query(SysDictItem)
            .filter(SysDictItem.type_code == type_code, SysDictItem.value == value)
            .one_or_none()
        )
        if exists is None:
            db.add(
                SysDictItem(
                    type_code=type_code, label=label, value=value, sort=sort,
                    remark=remark, is_active=True,
                )
            )
    db.commit()
    logger.info("字典：%d 类型 / %d 字典项", len(DICT_TYPES), len(DICT_ITEMS))


def _seed_params(db: Session) -> None:
    for key, name, value, ptype, group, remark in PARAMS:
        if db.query(SysParam).filter(SysParam.key == key).one_or_none() is None:
            db.add(
                SysParam(
                    key=key, name=name, value=value, type=ptype,
                    group=group, remark=remark, is_active=True,
                )
            )
    db.commit()
    logger.info("参数：%d 个", len(PARAMS))


def _seed_master(db: Session) -> None:
    # 车辆类型
    for code, name, mn, mx, trips, am, pm, planned, remark in VEHICLE_TYPES:
        if db.query(VehicleType).filter(VehicleType.code == code).one_or_none() is None:
            db.add(
                VehicleType(
                    code=code, name=name, min_load=mn, max_load=mx, trips_per_day=trips,
                    am_trips=am, pm_trips=pm, planned_count=planned, remark=remark,
                    is_active=True,
                )
            )

    # 地形规则
    for code, name, level, description in TERRAIN_RULES:
        if db.query(TerrainRule).filter(TerrainRule.code == code).one_or_none() is None:
            db.add(
                TerrainRule(
                    code=code, name=name, level=level, description=description, is_active=True
                )
            )

    # 通行矩阵
    for terrain_type, capability, allowed, remark in TERRAIN_MATRIX:
        exists = (
            db.query(VehicleTerrainCapability)
            .filter(
                VehicleTerrainCapability.terrain_type == terrain_type,
                VehicleTerrainCapability.capability == capability,
            )
            .one_or_none()
        )
        if exists is None:
            db.add(
                VehicleTerrainCapability(
                    terrain_type=terrain_type, capability=capability,
                    allowed=allowed, remark=remark,
                )
            )

    # 线路
    for code, name, scope, area, restricted, remark in ROUTES:
        if db.query(Route).filter(Route.code == code).one_or_none() is None:
            db.add(
                Route(
                    code=code, name=name, terrain_scope=scope, area=area,
                    is_restricted=restricted, remark=remark, is_active=True,
                )
            )
    db.flush()

    # 门店
    for code, name, terrain, window, priority, area, address, contact, phone in STORES:
        if db.query(Store).filter(Store.code == code).one_or_none() is None:
            db.add(
                Store(
                    code=code, name=name, terrain_type=terrain, delivery_window=window,
                    priority=priority, area=area, address=address, contact=contact,
                    phone=phone, is_intersection=False, is_active=True,
                )
            )
    db.flush()

    # 门店线路映射 + 交界标记
    store_by_code = {s.code: s for s in db.query(Store).all()}
    route_by_code = {r.code: r for r in db.query(Route).all()}
    for store_code, route_code, priority, is_primary in MAPPINGS:
        store = store_by_code.get(store_code)
        route = route_by_code.get(route_code)
        if store is None or route is None:
            continue
        exists = (
            db.query(StoreRouteMapping)
            .filter(
                StoreRouteMapping.store_id == store.id,
                StoreRouteMapping.route_id == route.id,
            )
            .one_or_none()
        )
        if exists is None:
            db.add(
                StoreRouteMapping(
                    store_id=store.id, route_id=route.id,
                    priority=priority, is_primary=is_primary,
                )
            )
    db.flush()

    # 交界门店标记：一个门店挂 >=2 条线路
    from sqlalchemy import func as sa_func

    counts = dict(
        db.query(StoreRouteMapping.store_id, sa_func.count(StoreRouteMapping.id))
        .group_by(StoreRouteMapping.store_id)
        .all()
    )
    for store in store_by_code.values():
        store.is_intersection = counts.get(store.id, 0) >= 2

    # 司机
    for code, name, phone, shift, status in DRIVERS:
        if db.query(Driver).filter(Driver.code == code).one_or_none() is None:
            db.add(
                Driver(
                    code=code, name=name, phone=phone, shift=shift,
                    status=status, is_active=True,
                )
            )
    db.flush()

    # 车辆：按 planned_count 批量生成（四米二 28 / 大包 3 / 小包 9）
    drivers = db.query(Driver).order_by(Driver.id).all()
    terrain_by_type = {"4.2m": "all", "big": "big_small", "small": "small_only"}
    plates_by_prefix = {"4.2m": "沪A", "big": "沪B", "small": "沪C"}
    seq = 0
    for (
        code,
        _name,
        _mn,
        _mx,
        _trips,
        _am,
        _pm,
        planned,
        _remark,
    ) in VEHICLE_TYPES:
        prefix = plates_by_prefix[code]
        for i in range(1, planned + 1):
            plate = f"{prefix}{1000 + i}"
            if db.query(Vehicle).filter(Vehicle.plate_no == plate).one_or_none() is not None:
                continue
            driver = drivers[seq % len(drivers)] if drivers else None
            db.add(
                Vehicle(
                    plate_no=plate,
                    vehicle_type_code=code,
                    terrain_capability=terrain_by_type[code],
                    route_scope="",  # 空 = 不限制线路
                    status="idle",
                    driver_id=driver.id if driver else None,
                    remark="",
                    is_active=True,
                )
            )
            seq += 1

    db.commit()
    logger.info(
        "主数据：门店 %d / 线路 %d / 映射 %d / 车辆类型 %d / 车辆 %d / 司机 %d",
        db.query(Store).count(),
        db.query(Route).count(),
        db.query(StoreRouteMapping).count(),
        db.query(VehicleType).count(),
        db.query(Vehicle).count(),
        db.query(Driver).count(),
    )


def _seed_attachments(db: Session) -> None:
    for name, biz_type, size, uploader in ATTACHMENTS:
        if db.query(SysAttachment).filter(SysAttachment.name == name).one_or_none() is None:
            db.add(
                SysAttachment(
                    name=name, biz_type=biz_type, size=size,
                    storage_path="", uploader=uploader,
                )
            )
    db.commit()
    logger.info("附件：%d 个", len(ATTACHMENTS))


def main() -> None:
    parser = argparse.ArgumentParser(description="载入初始数据")
    parser.add_argument("--reset", action="store_true", help="先删表重建（会清空数据）")
    args = parser.parse_args()

    ensure_database_exists()

    if args.reset:
        logger.warning("--reset：正在删除全部数据表…")
        drop_all_tables()

    create_all_tables()

    db = SessionLocal()
    try:
        perms = _seed_permissions(db)
        roles = _seed_roles(db, perms)
        _seed_users(db, roles)
        _seed_dicts(db)
        _seed_params(db)
        _seed_master(db)
        _seed_attachments(db)

        admin = db.query(SysUser).filter(SysUser.username == "admin").one_or_none()
        append_audit(
            db,
            actor=admin,
            action="system.seed",
            target_type="system",
            target_name="初始化",
            detail={
                "说明": "初始数据载入完成",
                "用户数": db.query(SysUser).count(),
                "角色数": db.query(SysRole).count(),
                "权限点数": db.query(SysPermission).count(),
            },
        )

        logger.info("=" * 58)
        logger.info("初始数据载入完成")
        logger.info("  管理员：admin / %s", settings.ADMIN_INIT_PASSWORD)
        logger.info("  调度员：dispatcher / %s", settings.DEMO_PASSWORD)
        logger.info("  只读：  viewer / %s", settings.DEMO_PASSWORD)
        logger.info("=" * 58)
    finally:
        db.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        logger.error("载入失败：%s", exc)
        sys.exit(1)
