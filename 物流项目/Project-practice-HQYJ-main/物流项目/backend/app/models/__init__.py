"""ORM 模型统一导出。

★ 这里集中 import 所有模型子模块，目的是让 `Base.metadata` 在任何
   `from app import models` 之后都是完整的 —— 建表、测试、迁移都依赖这一点。
"""

from app.models.audit import SysAuditLog
from app.models.master import (
    Driver,
    Route,
    Store,
    StoreRouteMapping,
    TerrainRule,
    Vehicle,
    VehicleTerrainCapability,
    VehicleType,
)
from app.models.rbac import (
    SysPermission,
    SysRole,
    SysUser,
    role_permissions,
    user_roles,
)
from app.models.rule import RuleVersion
from app.models.scheduling import (
    DispatchRecord,
    ExceptionEvent,
    ReplanRecord,
    SchedulingConfirmation,
    SchedulingPlan,
    SchedulingPlanDetail,
    SchedulingReport,
    SchedulingTask,
    StoreDemand,
)
from app.models.sys import SysAttachment, SysDictItem, SysDictType, SysParam

__all__ = [
    # RBAC
    "SysUser",
    "SysRole",
    "SysPermission",
    "user_roles",
    "role_permissions",
    # 系统配置
    "SysDictType",
    "SysDictItem",
    "SysParam",
    "SysAttachment",
    # 审计
    "SysAuditLog",
    # 规则版本
    "RuleVersion",
    # 基础主数据
    "Store",
    "Route",
    "StoreRouteMapping",
    "VehicleType",
    "Vehicle",
    "VehicleTerrainCapability",
    "Driver",
    "TerrainRule",
    # 调度业务
    "StoreDemand",
    "SchedulingTask",
    "SchedulingPlan",
    "SchedulingPlanDetail",
    "SchedulingConfirmation",
    "DispatchRecord",
    "ExceptionEvent",
    "ReplanRecord",
    "SchedulingReport",
]
