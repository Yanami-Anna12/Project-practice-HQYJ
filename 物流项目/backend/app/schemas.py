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
    # 坐标：司机端「一键导航」用；没有坐标时为 None
    latitude: float | None = None
    longitude: float | None = None
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
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class StoreUpdate(BaseModel):
    name: str | None = None
    terrain_type: str | None = None
    delivery_window: str | None = None
    priority: int | None = None
    area: str | None = None
    address: str | None = None
    contact: str | None = None
    phone: str | None = None
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
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
    # 司机是否已确认接单（来源 dispatch_record.accepted_at，见 app/models/scheduling.py）。
    # 同一（方案, 车辆, 趟次）下的所有明细行取值一致 —— 确认是**趟次级**的事实。
    accepted: bool = False
    accepted_at: datetime | None = None


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


class UndoDispatchResult(BaseModel):
    """撤销下发的执行结果（见 routers/scheduling.py 的 undo_dispatch）。

    ★ 与 DispatchResult 对称：一个「发下去」，一个「收回来」。
      刻意**不删**任务、方案与计划明细 —— 撤销的是下发事实，
      不是调度成果，所以任务退回 confirmed 后可以重新选方案下发。
    """

    task_id: int
    task_code: str
    status: str
    # 收回来的趟次数（被删掉的 dispatch_record 行数）
    revoked_trips: int
    # 顺带撤掉的司机站内消息数
    revoked_notifications: int
    # 被通知过的司机人数
    drivers: int
    # 已有现场执行记录的趟次数。>0 表示这些趟次没被收回（见接口文档）
    executed_kept: int
    # 已接单但尚未执行的趟次数：下发记录会被收回，现场执行记录保留
    accepted_trips: int
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


# ---------------------------------------------------------------------------
# 司机端（小程序）执行层
# ---------------------------------------------------------------------------
# 说明：这些模型的字段刻意「扁平且自解释」—— 小程序端不做二次拼装，
#       门店地址、电话、坐标、执行状态一次给全，弱网下少发几次请求。


class MobileTripStopOut(BaseModel):
    """趟次里的一个门店站点。"""

    plan_detail_id: int
    store_id: int
    store_code: str
    store_name: str
    address: str = ""
    contact: str = ""
    phone: str = ""
    latitude: float | None = None
    longitude: float | None = None
    load_amount: float = 0
    sequence: int = 1
    # planned 未开始 / arrived 已到店 / done 已完成（含旧口径 completed）
    status: str = "planned"
    # 该站点最近一次现场动作与打卡时间（没有则为空）
    last_action: str = ""
    last_action_at: datetime | None = None
    photo_attachment_ids: list[int] = []


class MobileTripOut(BaseModel):
    """「我的趟次」列表项。trip_key 用于查询趟次详情。"""

    # trip_key 规则与 dispatch_record.trip_id 一致：task:plan:vehicle:trip
    trip_key: str
    task_id: int
    task_code: str
    plan_id: int
    plan_code: str = ""
    schedule_date: date
    time_window: str = "AM"
    trip_no: int = 1
    vehicle_id: int
    plate_no: str = ""
    vehicle_type: str = ""
    vehicle_type_name: str = ""
    store_count: int = 0
    total_load: float = 0
    done_stores: int = 0
    arrived_stores: int = 0
    # ★ 这辆车**当天一共要跑几趟**（同一天、同车、不同 trip_no 的个数）。
    #   为什么要有这个字段：`trip_no` 是「本车当天第几趟」，**不是全局序号**。
    #   一台车一天跑 4 趟时，司机会看到「第1趟…第4趟」；而一个司机名下可能有
    #   好几台车（例：赵师傅 D001 名下有 5 台），于是列表里会出现**多个第1趟** ——
    #   光看「第 1 趟」根本分不清是"这辆车的第1趟"还是"今天的第1趟"。
    #   带上总趟数，前端就能写成「本车今天第 1 趟 / 共 2 趟」，一眼看懂。
    vehicle_trip_count: int = 0
    # planned 未开始 / running 执行中 / done 已完成
    trip_status: str = "planned"
    # 司机确认接单：accepted 为真时 accepted_at 必有值（dispatch_record 上的首次确认时间）
    accepted: bool = False
    accepted_at: datetime | None = None


class MobileTripDetailOut(MobileTripOut):
    """趟次详情：在列表项基础上补上站点序列。"""

    driver_name: str = ""
    driver_phone: str = ""
    dispatch_status: str = ""
    stops: list[MobileTripStopOut] = []


class MobileCheckinRequest(BaseModel):
    """现场打卡。"""

    plan_detail_id: int
    # arrive 到店 / depart 离店 / complete 完成
    action: str = Field(default="arrive", pattern="^(arrive|depart|complete)$")
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    remark: str = Field(default="", max_length=255)
    photo_attachment_ids: list[int] = []


class MobileCheckinResult(BaseModel):
    """打卡结果：把「这条记录」和「明细/趟次的最新状态」一起返回，前端不必再查一次。"""

    record_id: int
    plan_detail_id: int
    trip_key: str
    action: str
    occurred_at: datetime
    # planned / dispatched / arrived / done
    plan_detail_status: str
    # planned 未开始 / running 执行中 / done 已完成
    trip_status: str = ""
    message: str = ""


class MobileExceptionCreate(BaseModel):
    """司机异常上报。"""

    # 关联调度任务（必填：异常最终要能触发重排/人工处理）
    task_id: int
    event_type: str = Field(default="traffic_control", max_length=32)
    plan_detail_id: int | None = None
    store_id: int | None = None
    # 趟次号，如 3:5:12:1
    trip_key: str = ""
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    remark: str = Field(default="", max_length=255)
    photo_attachment_ids: list[int] = []


class MobileExceptionOut(BaseModel):
    """异常上报结果（写入现有 exception_event 表）。"""

    id: int
    task_id: int
    event_type: str
    source: str
    status: str
    occurred_at: datetime | None = None
    message: str = ""


class MobileFileOut(BaseModel):
    """文件上传结果。url 可直接在小程序里 <image src>。"""

    attachment_id: int
    name: str
    size: int
    content_type: str = ""
    storage_path: str
    url: str


class MobileNotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    content: str = ""
    biz_type: str = "system"
    biz_id: int | None = None
    is_read: bool = False
    created_at: datetime | None = None


class MobileUnreadCountOut(BaseModel):
    unread: int = 0


class MobileNotificationReadOut(BaseModel):
    id: int
    is_read: bool
    unread: int = 0


class MobileProfileOut(BaseModel):
    """当前司机档案。管理员/调度员没有司机档案时 driver 为空。"""

    username: str
    nickname: str = ""
    phone: str = ""
    is_driver: bool = False
    driver_id: int | None = None
    driver_code: str = ""
    driver_name: str = ""
    driver_phone: str = ""
    # AM 上午班 / PM 下午班 / FULL 全天
    shift: str = ""
    driver_status: str = ""
    vehicle_count: int = 0
    vehicles: list["MobileVehicleOut"] = []


class MobileVehicleOut(BaseModel):
    """名下车辆。"""

    id: int
    plate_no: str
    vehicle_type_code: str
    vehicle_type_name: str = ""
    terrain_capability: str = ""
    status: str = "idle"


class MobileTripAcceptResult(BaseModel):
    """司机确认接单的结果。

    ★ 幂等语义：重复确认返回 200，`already_accepted=True`，且 `accepted_at`
      始终是**首次**确认时间（不覆盖）。
    """

    trip_key: str
    task_id: int
    task_code: str = ""
    vehicle_id: int
    plate_no: str = ""
    accepted: bool = True
    accepted_at: datetime
    already_accepted: bool = False
    notified: int = 0
    message: str = ""


# ---------------------------------------------------------------------------
# 管理端只读首页（小程序「今日看板」）
# ---------------------------------------------------------------------------
# 说明：小程序端一次请求拿全首页数字，避免弱网下打 4 个接口。
#       本组接口全部只读，不写任何业务表。


class MobileTaskStatOut(BaseModel):
    """今日任务数与各状态计数。"""

    total: int = 0
    by_status: dict[str, int] = {}


class MobileTripStatOut(BaseModel):
    """趟次统计：**当日**已下发趟次 + 已接单/未接单（另有全表累计备查）。"""

    total: int = 0
    accepted: int = 0
    pending: int = 0
    dispatch_records: int = 0
    # 全表累计下发记录数（只作展示，不参与当日任何比率计算）
    all_time: int = 0


class MobileCompletionStatOut(BaseModel):
    """**执行完成情况**：看板上回答「今天跑完了多少」。

    ★ 为什么和 MobileTripStatOut 分开：那个只统计「司机有没有点确认接单」
      （接单是**响应**，不代表活干完了）。调度最关心的是进度，所以单独一组。
      两者必须分别算：一个司机可以确认了但一趟没跑，也可以没确认却已经跑完。

    口径（都能回溯到 `scheduling_plan_detail.status`）：
      · finished  = 该趟**所有门店**都 done —— 这趟收工
      · running   = 有门店 arrived/done，但还没全完 —— 正在跑
      · not_started = 门店全是 dispatched（一个都没打卡）—— 还没出车
      · stores_done / stores_total = 门店级完成度（趟次可能是「跑了 3 家还剩 1 家」，
        只看趟次粒度会看不到这种中间状态）
    """

    trips_total: int = 0
    finished: int = 0
    running: int = 0
    not_started: int = 0
    stores_done: int = 0
    stores_total: int = 0


class MobileVehicleStatOut(BaseModel):
    total: int = 0
    in_transit: int = 0


class MobileExceptionStatOut(BaseModel):
    pending: int = 0
    total: int = 0


class MobileExceptionBriefOut(BaseModel):
    """看板上的异常摘要（只取展示需要的几列）。"""

    id: int
    task_id: int
    task_code: str = ""
    event_type: str
    source: str = ""
    status: str = "pending"
    occurred_at: datetime | None = None
    summary: str = ""


class MobileTripBriefOut(BaseModel):
    """看板上的**趟次明细**（一行 = 一趟活，不是一家门店）。

    ★ 为什么用趟次粒度：一天几十家门店，逐店列出来会把看板撑爆；
      调度真正要盯的是「哪台车哪一趟跑到哪了」，所以一趟一行。
      门店数用 `done_stores / store_count` 表示，跑了一半也看得出来。

    state 取值（看板排序也按它：running → accepted → pending → done）：
      running  有门店到店/完成，但没全完 —— **正在跑**
      accepted 已接单，但一个门店都没打卡 —— 接了活还没出车
      pending  没接单、没打卡 —— 还没确认
      done     该趟所有门店都完成 —— 收工
    """

    trip_key: str
    task_id: int = 0
    task_code: str = ""
    plan_id: int = 0
    trip_no: int = 1
    time_window: str = "AM"
    vehicle_id: int = 0
    plate_no: str = ""
    driver_name: str = ""
    store_count: int = 0
    done_stores: int = 0
    arrived_stores: int = 0
    accepted: bool = False
    state: str = "pending"


class MobileManagerOverviewOut(BaseModel):
    """管理端只读首页聚合数据。"""

    schedule_date: date
    generated_at: datetime
    tasks: MobileTaskStatOut
    trips: MobileTripStatOut
    completion: MobileCompletionStatOut
    # 趟次明细：看板最上面那块（一行一趟）
    trip_briefs: list[MobileTripBriefOut] = []
    vehicles: MobileVehicleStatOut
    exceptions: MobileExceptionStatOut
    recent_exceptions: list[MobileExceptionBriefOut] = []


# MobileProfileOut 里引用了后面才定义的 MobileVehicleOut，前向引用在此解析
MobileProfileOut.model_rebuild()
