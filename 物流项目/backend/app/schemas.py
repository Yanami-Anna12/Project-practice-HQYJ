"""Pydantic v2 请求/响应模型。

约定：
  - 输入模型用 XxxCreate / XxxUpdate，输出统一用 XxxOut
  - 写接口的「更新」一律用可选字段，未传即不改
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# 认证
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class UserProfile(BaseModel):
    id: int
    username: str
    nickname: str
    dept: str
    phone: str
    is_active: bool
    roles: list[str]
    role_names: list[str]
    permissions: list[str]


class LoginResponse(BaseModel):
    token: str
    user: UserProfile


class MenuNode(BaseModel):
    key: str
    title: str
    icon: str | None = None
    path: str | None = None
    permission: str | None = None
    children: list["MenuNode"] | None = None


MenuNode.model_rebuild()


# ---------------------------------------------------------------------------
# 用户
# ---------------------------------------------------------------------------


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    nickname: str
    dept: str
    phone: str
    is_active: bool
    roles: list[str] = []
    permissions: list[str] = []
    created_at: datetime | None = None
    is_self: bool = False


class AssignRolesRequest(BaseModel):
    roles: list[str] = []


class AssignRolesResponse(BaseModel):
    id: int
    roles: list[str]
    permissions: list[str]


class ResetPasswordResponse(BaseModel):
    id: int
    password: str


class ToggleResponse(BaseModel):
    id: int
    is_active: bool
    affected_roles: int | None = None


# ---------------------------------------------------------------------------
# 角色
# ---------------------------------------------------------------------------


class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    description: str
    is_active: bool
    permission_codes: list[str] = []
    user_count: int = 0


class RoleCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=1, max_length=64)
    description: str = ""
    permission_codes: list[str] = []


class RoleUpdate(BaseModel):
    """角色码是审计与代码里的稳定标识，不允许修改。"""

    name: str = Field(min_length=1, max_length=64)
    description: str = ""
    permission_codes: list[str] = []
    is_active: bool | None = None


class DeletedResponse(BaseModel):
    deleted: str


# ---------------------------------------------------------------------------
# 权限点
# ---------------------------------------------------------------------------


class PermissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    module: str
    action: str
    is_active: bool
    role_count: int = 0


class PermissionCreate(BaseModel):
    code: str = Field(
        min_length=3, max_length=64, pattern=r"^[a-z][a-z0-9_]*:[a-z][a-z0-9_]*$"
    )
    name: str = Field(min_length=1, max_length=64)
    module: str = "未分组"
    action: str = "custom"


# ---------------------------------------------------------------------------
# 字典
# ---------------------------------------------------------------------------


class DictTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    description: str
    is_active: bool
    item_count: int = 0


class DictTypeCreate(BaseModel):
    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=1, max_length=64)
    description: str = ""


class DictItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type_code: str
    label: str
    value: str
    sort: int
    remark: str
    is_active: bool


class DictItemCreate(BaseModel):
    label: str = Field(min_length=1, max_length=64)
    value: str = Field(min_length=1, max_length=64)
    sort: int = 99
    remark: str = ""


class DictItemUpdate(BaseModel):
    label: str = Field(min_length=1, max_length=64)
    value: str = Field(min_length=1, max_length=64)
    sort: int = 99
    remark: str = ""
    is_active: bool | None = None


# ---------------------------------------------------------------------------
# 参数
# ---------------------------------------------------------------------------


class ParamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    key: str
    name: str
    value: str
    type: str
    group: str
    remark: str
    is_active: bool


class ParamUpdate(BaseModel):
    value: str = Field(max_length=255)


# ---------------------------------------------------------------------------
# 附件
# ---------------------------------------------------------------------------


class AttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    biz_type: str
    size: int
    uploader: str
    uploaded_at: datetime | None = None


class AttachmentCreate(BaseModel):
    """演示模式：只登记元信息。"""

    name: str = Field(min_length=1, max_length=255)
    biz_type: str = "未分类"
    size: int = 0


# ---------------------------------------------------------------------------
# 审计日志
# ---------------------------------------------------------------------------


class AuditLogOut(BaseModel):
    id: int
    actor_id: int | None
    actor_name: str
    action: str
    target_type: str
    target_name: str
    detail: dict[str, Any] = {}
    created_at: datetime


# ---------------------------------------------------------------------------
# 基础主数据
# ---------------------------------------------------------------------------


class StoreOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    terrain_type: str
    delivery_window: str
    priority: int
    area: str
    address: str
    contact: str
    phone: str
    is_intersection: bool
    is_active: bool
    route_codes: list[str] = []


class StoreCreate(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=128)
    terrain_type: str = "normal"
    delivery_window: str = "AM"
    priority: int = 100
    area: str = ""
    address: str = ""
    contact: str = ""
    phone: str = ""


class StoreUpdate(BaseModel):
    name: str | None = None
    terrain_type: str | None = None
    delivery_window: str | None = None
    priority: int | None = None
    area: str | None = None
    address: str | None = None
    contact: str | None = None
    phone: str | None = None
    is_active: bool | None = None


class RouteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    terrain_scope: str
    area: str
    is_restricted: bool
    remark: str
    is_active: bool
    store_count: int = 0


class RouteCreate(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=128)
    terrain_scope: str = ""
    area: str = ""
    is_restricted: bool = False
    remark: str = ""


class RouteUpdate(BaseModel):
    name: str | None = None
    terrain_scope: str | None = None
    area: str | None = None
    is_restricted: bool | None = None
    remark: str | None = None
    is_active: bool | None = None


class MappingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    store_id: int
    store_code: str = ""
    store_name: str = ""
    route_id: int
    route_code: str = ""
    route_name: str = ""
    priority: int
    is_primary: bool


class MappingCreate(BaseModel):
    store_id: int
    route_id: int
    priority: int = 100
    is_primary: bool = False


class VehicleTypeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    min_load: int
    max_load: int
    trips_per_day: int
    am_trips: int
    pm_trips: int
    planned_count: int
    remark: str
    is_active: bool
    vehicle_count: int = 0


class VehicleTypeUpdate(BaseModel):
    name: str | None = None
    min_load: int | None = None
    max_load: int | None = None
    trips_per_day: int | None = None
    am_trips: int | None = None
    pm_trips: int | None = None
    planned_count: int | None = None
    remark: str | None = None
    is_active: bool | None = None


class VehicleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    plate_no: str
    vehicle_type_code: str
    vehicle_type_name: str = ""
    terrain_capability: str
    route_scope: str
    status: str
    driver_id: int | None = None
    driver_name: str = ""
    remark: str
    is_active: bool


class VehicleCreate(BaseModel):
    plate_no: str = Field(min_length=1, max_length=32)
    vehicle_type_code: str
    terrain_capability: str = "all"
    route_scope: str = ""
    status: str = "idle"
    driver_id: int | None = None
    remark: str = ""


class VehicleUpdate(BaseModel):
    vehicle_type_code: str | None = None
    terrain_capability: str | None = None
    route_scope: str | None = None
    status: str | None = None
    driver_id: int | None = None
    remark: str | None = None
    is_active: bool | None = None


class DriverOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    phone: str
    shift: str
    status: str
    remark: str
    is_active: bool


class DriverCreate(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=64)
    phone: str = ""
    shift: str = "FULL"
    status: str = "available"
    remark: str = ""


class DriverUpdate(BaseModel):
    name: str | None = None
    phone: str | None = None
    shift: str | None = None
    status: str | None = None
    remark: str | None = None
    is_active: bool | None = None


class TerrainRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    level: int
    description: str
    is_active: bool


class TerrainMatrixOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    terrain_type: str
    capability: str
    allowed: bool
    remark: str


class TerrainMatrixUpdate(BaseModel):
    allowed: bool
    remark: str = ""


# ---------------------------------------------------------------------------
# 门店货量需求（调度的输入）
# ---------------------------------------------------------------------------


class DemandOut(BaseModel):
    id: int
    schedule_date: date
    store_id: int
    store_code: str = ""
    store_name: str = ""
    terrain_type: str = ""
    delivery_window: str = ""
    route_codes: list[str] = []
    quantity: float
    remark: str = ""
    # 该货量在当前车型下至少需要几趟（按最大车型算），供页面提示用
    min_trips_4_2m: int = 0


class DemandUpsert(BaseModel):
    schedule_date: date
    store_id: int
    quantity: float = Field(ge=0, le=999999)
    remark: str = ""


class DemandGenerateRequest(BaseModel):
    schedule_date: date
    overwrite: bool = False


class DemandGenerateResult(BaseModel):
    date: str
    created: int
    updated: int
    skipped: int
    stores: int
    total_quantity: float


class DemandSummary(BaseModel):
    date: str
    store_count: int
    total_quantity: float
    am_stores: int
    pm_stores: int
    max_store: str | None = None
    max_quantity: float | None = None


# ---------------------------------------------------------------------------
# 调度任务与方案
# ---------------------------------------------------------------------------


class SchedulingRunRequest(BaseModel):
    schedule_date: date
    time_window: str = "FULL"
    # CP-SAT 对每套方案单独求解，4 套方案 × 超时时间 = 最坏耗时。
    # 默认 5 秒（合计最坏 ~20 秒）；追求更快可关掉或调小。
    use_cp_sat: bool = True
    timeout_seconds: int = Field(default=5, ge=1, le=120)


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    schedule_date: date
    time_window: str
    status: str
    rule_version: str
    duration_ms: int
    solver_note: str
    replan_count: int
    created_by: str
    created_at: datetime | None = None


class PlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    plan_code: str
    strategy: str
    four_two_usage: float
    avg_load_rate: float
    trip_achievement: float
    total_load: float
    vehicle_count: int
    trip_count: int
    total_cost: float
    soft_violation: float
    score: float
    uncovered_stores: str
    is_recommended: bool
    explanation: str = ""


class PlanDetailOut(BaseModel):
    id: int
    vehicle_id: int
    plate_no: str
    driver_name: str = ""
    vehicle_type: str
    trip_no: int
    time_window: str
    store_id: int
    store_code: str
    store_name: str
    terrain_type: str
    load_amount: float
    sequence: int
    status: str


class TaskDetailOut(BaseModel):
    """任务详情：任务 + 多方案 + 各方案校验结果。"""

    task: TaskOut
    plans: list[PlanOut]
    problems: list[str] = []
    validations: dict[str, list[str]] = {}
    input_summary: dict[str, Any] = {}


class ConfirmRequest(BaseModel):
    plan_id: int
    approved: bool = True
    remark: str = ""
    adjustments: list[dict[str, Any]] = []


class ConfirmResult(BaseModel):
    task_id: int
    plan_id: int
    status: str
    message: str


class DispatchResult(BaseModel):
    task_id: int
    plan_id: int
    dispatched_trips: int
    skipped_duplicated: int
    message: str


class ExceptionCreate(BaseModel):
    task_id: int
    event_type: str
    source: str = ""
    payload: dict[str, Any] = {}


class ExceptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    event_type: str
    source: str
    payload: str
    status: str
    occurred_at: datetime | None = None


class ReplanResult(BaseModel):
    task_id: int
    replan_count: int
    scope: str
    message: str
    new_plan_ids: list[int] = []


class ReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    plan_id: int | None = None
    content: str
    generated_at: datetime | None = None


class FeasibilityOut(BaseModel):
    """调度前的可行性预检结果。"""

    schedule_date: date
    store_count: int
    vehicle_count: int
    total_demand: float
    total_capacity: float
    problems: list[str] = []
    ready: bool = True
