"""API 请求 / 响应模型（Pydantic v2）。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.enums import (
    DataScope,
    FaultLevel,
    FaultStatus,
    InspectFrequency,
    InspectItemResult,
    ReportType,
    SubtaskStatus,
    TimeStatus,
    WorkOrderStatus,
    WorkOrderType,
)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------- 认证
class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: "UserOut"


class WechatLoginRequest(BaseModel):
    code: str | None = Field(default=None, description="微信登录 code")
    phone: str | None = Field(default=None, description="微信授权手机号")
    nickname: str | None = None
    openid: str | None = Field(default=None, description="联调时可直接传 openid")


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str = Field(min_length=6, max_length=128)


# ---------------------------------------------------------------- 用户 / 角色
class RoleOut(ORMModel):
    id: str
    code: str
    name: str
    data_scope: str
    sort_order: int
    status: bool
    remark: str | None = None
    is_builtin: bool = False
    created_at: datetime | None = None


class RoleCreate(BaseModel):
    code: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=1, max_length=64)
    data_scope: str = DataScope.PERSONAL.value
    sort_order: int = 0
    remark: str | None = None
    permission_codes: list[str] = Field(default_factory=list)

    @field_validator("data_scope")
    @classmethod
    def _scope(cls, v: str) -> str:
        if v not in {e.value for e in DataScope}:
            raise ValueError(f"数据权限必须是：{'、'.join(e.value for e in DataScope)}")
        return v


class RoleUpdate(BaseModel):
    name: str | None = None
    data_scope: str | None = None
    sort_order: int | None = None
    remark: str | None = None
    status: bool | None = None
    permission_codes: list[str] | None = None


class PermissionOut(ORMModel):
    id: str
    code: str
    name: str
    perm_type: str
    parent_code: str | None = None
    route_path: str | None = None
    component: str | None = None
    icon: str | None = None
    sort_order: int = 0
    visible: bool = True
    data_scope: str | None = None
    description: str | None = None


class PermissionTreeNode(BaseModel):
    code: str
    name: str
    perm_type: str = "menu"
    route_path: str | None = None
    icon: str | None = None
    data_scope: str | None = None
    children: list["PermissionTreeNode"] = Field(default_factory=list)


class UserOut(ORMModel):
    id: str
    username: str
    real_name: str
    phone: str | None = None
    email: str | None = None
    avatar: str | None = None
    project_id: str | None = None
    station_id: str | None = None
    role_id: str | None = None
    user_type: str
    status: bool
    skills: str | None = None
    on_duty: bool = True
    last_login_at: datetime | None = None
    created_at: datetime | None = None
    role: RoleOut | None = None
    project_name: str | None = None
    station_name: str | None = None
    data_scope: str | None = None


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    real_name: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    phone: str | None = None
    email: str | None = None
    role_id: str | None = None
    project_id: str | None = None
    station_id: str | None = None
    user_type: Literal["admin", "staff", "miniapp"] = "admin"
    skills: str | None = None


class UserUpdate(BaseModel):
    real_name: str | None = None
    phone: str | None = None
    email: str | None = None
    role_id: str | None = None
    project_id: str | None = None
    station_id: str | None = None
    status: bool | None = None
    password: str | None = None
    skills: str | None = None
    on_duty: bool | None = None


class ProfileUpdate(BaseModel):
    real_name: str | None = None
    phone: str | None = None
    email: str | None = None
    avatar: str | None = None


# ---------------------------------------------------------------- 项目 / 站点 / 桩
class ProjectOut(ORMModel):
    id: str
    code: str
    name: str
    owner: str | None = None
    region: str | None = None
    status: bool
    remark: str | None = None


class StationOut(ORMModel):
    id: str
    code: str
    name: str
    project_id: str | None = None
    address: str | None = None
    longitude: float | None = None
    latitude: float | None = None
    terrain: str | None = None
    extinguisher_type: str | None = None
    extinguisher_spec: str | None = None
    extinguisher_produced_at: datetime | None = None
    dome_camera_count: int = 0
    bullet_camera_count: int = 0
    contact_name: str | None = None
    contact_phone: str | None = None
    status: bool = True
    project_name: str | None = None
    pile_count: int = 0


class StationExtensionUpdate(BaseModel):
    """PDF 3.10 二期：灭火器（含「无」选项）与摄像头字段。"""

    extinguisher_type: str | None = None
    extinguisher_spec: str | None = None
    extinguisher_produced_at: datetime | None = None
    dome_camera_count: int | None = Field(default=None, ge=0)
    bullet_camera_count: int | None = Field(default=None, ge=0)
    camera_password: str | None = None


class ChargingPileOut(ORMModel):
    id: str
    asset_code: str
    name: str
    station_id: str | None = None
    station_name: str | None = None
    model: str | None = None
    rated_power: float | None = None
    gun_count: int = 1
    gun_types: str | None = None
    manufacturer: str | None = None
    install_date: datetime | None = None
    warranty_until: datetime | None = None
    status: str
    online: bool = True


class LedgerOut(ORMModel):
    id: str
    ledger_type: str
    asset_code: str
    asset_name: str
    project_name: str | None = None
    station_name: str | None = None
    attributes: dict | None = None
    status: str
    remark: str | None = None
    updated_at: datetime | None = None


# ---------------------------------------------------------------- 工单
class WorkOrderOut(ORMModel):
    id: str
    order_no: str
    order_name: str
    order_type: str
    project_id: str | None = None
    station_id: str | None = None
    station_name: str | None = None
    station_address: str | None = None
    station_names: list | None = None
    status: str
    time_status: str
    inspector_id: str | None = None
    inspector_name: str | None = None
    inspect_start_date: date | None = None
    inspect_end_date: date | None = None
    inspect_frequency: str
    inspect_count: int
    inspect_cycle: int = 1
    subtask_total: int = 0
    subtask_done: int = 0
    priority: str = "正常"
    remark: str | None = None
    reject_reason: str | None = None
    cancel_reason: str | None = None
    source: str = "手工"
    created_at: datetime | None = None
    accepted_at: datetime | None = None
    completed_at: datetime | None = None


class SubtaskOut(ORMModel):
    id: str
    work_order_id: str
    order_no: str | None = None
    order_name: str | None = None
    order_type: str | None = None
    station_id: str | None = None
    station_name: str | None = None
    pile_id: str | None = None
    pile_asset_code: str | None = None
    sequence: int
    plan_date: date | None = None
    plan_time_window: str | None = None
    status: str
    assignee_id: str | None = None
    assignee_name: str | None = None
    item_summary: str | None = None
    completed_at: datetime | None = None


class WorkOrderCreate(BaseModel):
    """工单申请（PDF 3.4）。"""

    order_name: str = Field(min_length=1, max_length=128)
    order_type: str = WorkOrderType.PATROL.value
    project_id: str | None = None
    station_ids: list[str] = Field(default_factory=list)
    inspector_id: str | None = None
    inspect_start_date: date | None = None
    inspect_end_date: date | None = None
    inspect_frequency: str = InspectFrequency.MONTH.value
    inspect_cycle: int = Field(default=1, ge=1, le=24)
    inspect_count: int = Field(default=1, ge=1, le=50)
    remark: str | None = None
    auto_dispatch: bool = Field(
        default=False, description="是否调用智能工单调度 Agent 生成方案"
    )

    @field_validator("order_type")
    @classmethod
    def _type(cls, v: str) -> str:
        if v not in {e.value for e in WorkOrderType}:
            raise ValueError(f"工单类型必须是：{'、'.join(e.value for e in WorkOrderType)}")
        return v

    @field_validator("inspect_frequency")
    @classmethod
    def _freq(cls, v: str) -> str:
        if v not in {e.value for e in InspectFrequency}:
            raise ValueError(f"巡检频率必须是：{'、'.join(e.value for e in InspectFrequency)}")
        return v


class WorkOrderUpdate(BaseModel):
    order_name: str | None = None
    inspector_id: str | None = None
    inspect_start_date: date | None = None
    inspect_end_date: date | None = None
    inspect_frequency: str | None = None
    inspect_cycle: int | None = Field(default=None, ge=1, le=24)
    inspect_count: int | None = Field(default=None, ge=1, le=50)
    remark: str | None = None
    priority: str | None = None


class OrderActionRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class SubtaskAssignRequest(BaseModel):
    assignee_id: str
    plan_date: date | None = None
    plan_time_window: str | None = None


class SubtaskStatusUpdate(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def _status(cls, v: str) -> str:
        if v not in {e.value for e in SubtaskStatus}:
            raise ValueError(f"子任务状态必须是：{'、'.join(e.value for e in SubtaskStatus)}")
        return v


# ---------------------------------------------------------------- 巡检
class InspectionItemIn(BaseModel):
    item_name: str = Field(min_length=1, max_length=128)
    item_group: str | None = "通用"
    result: str = InspectItemResult.NORMAL.value
    remark: str | None = Field(default=None, max_length=200)
    images: list[str] = Field(default_factory=list)
    pile_asset_code: str | None = None

    @field_validator("result")
    @classmethod
    def _result(cls, v: str) -> str:
        if v not in {e.value for e in InspectItemResult}:
            raise ValueError("巡检结果只能是「正常」或「异常」")
        return v


class InspectionCreate(BaseModel):
    """巡检情况录入（PDF 3.4）。"""

    subtask_id: str
    items: list[InspectionItemIn] = Field(default_factory=list)
    images: list[str] = Field(default_factory=list)
    remark: str | None = Field(default=None, max_length=200, description="最多 200 字")
    checkin_location: str | None = None
    checkin_lng: float | None = None
    checkin_lat: float | None = None
    checkout_location: str | None = None
    checkout_lng: float | None = None
    checkout_lat: float | None = None
    finish: bool = True


class InspectionOut(ORMModel):
    id: str
    subtask_id: str
    work_order_id: str | None = None
    inspector_name: str | None = None
    station_name: str | None = None
    checkin_location: str | None = None
    checkin_time: datetime | None = None
    checkout_location: str | None = None
    checkout_time: datetime | None = None
    content: dict | None = None
    images: list | None = None
    abnormal_count: int = 0
    normal_count: int = 0
    remark: str | None = None
    status: str
    created_at: datetime | None = None


# ---------------------------------------------------------------- 故障
class FaultCreate(BaseModel):
    """故障上报（PDF 3.5）。"""

    project_id: str | None = None
    station_id: str | None = None
    pile_id: str | None = None
    fault_type: str | None = Field(default=None, max_length=64)
    fault_level: str | None = None
    description: str | None = None
    images: list[str] = Field(default_factory=list)
    occurred_at: datetime | None = None
    is_draft: bool = False

    @field_validator("fault_level")
    @classmethod
    def _level(cls, v: str | None) -> str | None:
        if v is not None and v not in {e.value for e in FaultLevel}:
            raise ValueError(f"故障等级必须是：{'、'.join(e.value for e in FaultLevel)}")
        return v


class FaultVerifyRequest(BaseModel):
    """故障核查（PDF 3.5）。"""

    verify_status: str
    verify_level: str | None = None
    verify_desc: str | None = None
    images: list[str] = Field(default_factory=list)
    need_defect_order: bool = False

    @field_validator("verify_status")
    @classmethod
    def _status(cls, v: str) -> str:
        if v not in (FaultStatus.VERIFIED.value, FaultStatus.REJECTED.value):
            raise ValueError("核查状态只能是「核查通过」或「核查驳回」")
        return v

    @field_validator("verify_level")
    @classmethod
    def _level(cls, v: str | None) -> str | None:
        if v is not None and v not in {e.value for e in FaultLevel}:
            raise ValueError(f"故障等级必须是：{'、'.join(e.value for e in FaultLevel)}")
        return v


class FaultOut(ORMModel):
    id: str
    fault_no: str
    project_id: str | None = None
    station_id: str | None = None
    station_name: str | None = None
    pile_id: str | None = None
    pile_asset_code: str | None = None
    reporter_id: str | None = None
    reporter_name: str | None = None
    fault_type: str | None = None
    fault_level: str
    description: str | None = None
    images: list | None = None
    status: str
    is_draft: bool = False
    occurred_at: datetime | None = None
    reported_at: datetime | None = None
    ai_diagnosis: dict | None = None
    ai_level_suggestion: str | None = None
    created_at: datetime | None = None


class FaultVerificationOut(ORMModel):
    id: str
    fault_id: str
    verifier_name: str | None = None
    verify_status: str
    verify_level: str | None = None
    verify_desc: str | None = None
    images: list | None = None
    need_defect_order: bool = False
    created_at: datetime | None = None


# ---------------------------------------------------------------- 消息
class MessageOut(ORMModel):
    id: str
    msg_type: str
    title: str
    content: str | None = None
    detail: dict | None = None
    work_order_id: str | None = None
    fault_id: str | None = None
    report_id: str | None = None
    link: str | None = None
    is_read: bool
    channel: str = "站内信"
    created_at: datetime | None = None


# ---------------------------------------------------------------- 统计
class DashboardQuery(BaseModel):
    period: str | None = "month"
    year: int | None = None
    month: int | None = Field(default=None, ge=1, le=12)
    project_id: str | None = None
    station_id: str | None = None


# ---------------------------------------------------------------- AI Agent（PDF 5.3）
class WorkOrderGenerateRequest(BaseModel):
    """POST /api/v1/ai/work-order/generate"""

    project_id: str | None = None
    station_ids: list[str] = Field(default_factory=list)
    order_type: str = WorkOrderType.PATROL.value
    schedule_date: date | None = None
    time_window: str | None = "09:00-18:00"
    inspect_frequency: str = InspectFrequency.MONTH.value
    inspect_cycle: int = Field(default=1, ge=1, le=24)
    inspect_count: int = Field(default=1, ge=1, le=50)
    inspector_ids: list[str] = Field(default_factory=list)
    auto_start: bool = True
    explain_with_llm: bool = True


class FaultDiagnoseRequest(BaseModel):
    """POST /api/v1/ai/fault/diagnose"""

    fault_id: str | None = None
    fault_type: str | None = None
    fault_level: str | None = None
    description: str | None = None
    pile_asset_code: str | None = None
    station_id: str | None = None


class InspectionReportRequest(BaseModel):
    """POST /api/v1/ai/inspection/report"""

    work_order_id: str | None = None
    inspection_ids: list[str] = Field(default_factory=list)
    subtask_ids: list[str] = Field(default_factory=list)
    use_llm: bool = True


class MaintenanceSuggestRequest(BaseModel):
    """POST /api/v1/ai/maintenance/suggest"""

    fault_id: str | None = None
    diagnosis: str | None = None
    fault_type: str | None = None
    use_llm: bool = True


class RiskCheckRequest(BaseModel):
    """POST /api/v1/ai/risk/check"""

    scope: Literal["work_order", "fault", "inspection", "whole"] = "whole"
    target_id: str | None = None
    days: int = Field(default=7, ge=1, le=90)


class ReportGenerateRequest(BaseModel):
    """POST /api/v1/ai/report/generate"""

    report_type: ReportType = ReportType.DAILY
    project_id: str | None = None
    station_id: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    use_llm: bool = True
    push_channels: list[str] = Field(default_factory=list)
    async_run: bool = False


class AssistantAskRequest(BaseModel):
    """POST /api/v1/ai/assistant/ask（追问下钻）"""

    question: str = Field(min_length=1, max_length=2000)
    report_id: str | None = None
    work_order_id: str | None = None
    fault_id: str | None = None
    use_llm: bool = True


class AgentConfirmRequest(BaseModel):
    """PDF 4.8 人工确认接口。"""

    approved: bool = True
    plan_id: str | None = None
    adjustments: list[dict] = Field(default_factory=list)
    comment: str | None = None
    auto_dispatch: bool = True


class AgentReplanRequest(BaseModel):
    """PDF 5.3 异常重排。"""

    exception_type: str = "工单逾期"
    description: str | None = None
    target_id: str | None = None
    lock_executed: bool = True
    strategy: Literal["local_first", "global"] = "local_first"
    confirmed: bool = False


class AgentTaskOut(ORMModel):
    id: str
    task_no: str
    agent_type: str
    task_name: str | None = None
    thread_id: str
    status: str
    project_id: str | None = None
    schedule_date: date | None = None
    time_window: str | None = None
    candidate_plans: list | None = None
    scored_plans: list | None = None
    selected_plan: dict | None = None
    plan_explanation: str | None = None
    confirmation: dict | None = None
    rule_version: str | None = None
    replan_count: int = 0
    current_node: str | None = None
    progress: int = 0
    llm_used: bool = False
    degraded: bool = False
    error: str | None = None
    created_at: datetime | None = None
    finished_at: datetime | None = None


class KnowledgeDocCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    category: str = Field(default="故障案例", max_length=64)
    content: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    project_id: str | None = None
    role_codes: list[str] = Field(default_factory=list)
    source_type: str = "text"


class KnowledgeAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    category: str | None = None
    top_k: int = Field(default=5, ge=1, le=20)


class FeedbackCreate(BaseModel):
    task_id: str | None = None
    report_id: str | None = None
    agent_type: str | None = None
    rating: int = Field(default=5, ge=1, le=5)
    accurate: bool = True
    comment: str | None = None
    corrected_output: str | None = None


TokenResponse.model_rebuild()
PermissionTreeNode.model_rebuild()
