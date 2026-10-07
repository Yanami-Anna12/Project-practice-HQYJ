"""模型包：集中导出所有 ORM 模型，确保 metadata 完整注册。

对应 PDF 6.1 核心表清单：
user / role / role_permission / project / station / charging_pile /
work_order / work_order_subtask / inspection_record / inspection_item /
fault_report / fault_verification / asset_ledger / message / notification /
statistics_daily / ai_agent_task / ai_agent_trace / ai_prompt_template /
ai_knowledge_base / ai_report / ai_exception_event / ai_feedback /
operation_log
另按方案 3.x 模块设计补充：schedule_shift / login_log / system_config /
rule_version / attachment / ai_report_follow_up / ai_scheduled_job。
"""

from app.models.ai import (
    AIAgentTask,
    AIAgentTrace,
    AIExceptionEvent,
    AIFeedback,
    AIKnowledgeBase,
    AIPromptTemplate,
    AIReport,
    AIReportFollowUp,
    AIScheduledJob,
)
from app.models.mixins import BaseModel, TimestampMixin, UUIDMixin, new_uuid, utcnow
from app.models.operations import (
    AssetLedger,
    FaultReport,
    FaultVerification,
    InspectionItem,
    InspectionRecord,
    WorkOrder,
    WorkOrderSubtask,
)
from app.models.rbac import (
    ChargingPile,
    Permission,
    Project,
    Role,
    RolePermission,
    ScheduleShift,
    Station,
    User,
)
from app.models.system import (
    Attachment,
    LoginLog,
    Message,
    Notification,
    OperationLog,
    RuleVersion,
    StatisticsDaily,
    SystemConfig,
)

__all__ = [
    # mixins
    "BaseModel",
    "UUIDMixin",
    "TimestampMixin",
    "new_uuid",
    "utcnow",
    # rbac
    "Permission",
    "Role",
    "RolePermission",
    "Project",
    "Station",
    "ChargingPile",
    "User",
    "ScheduleShift",
    # operations
    "WorkOrder",
    "WorkOrderSubtask",
    "InspectionRecord",
    "InspectionItem",
    "FaultReport",
    "FaultVerification",
    "AssetLedger",
    # system
    "Message",
    "Notification",
    "StatisticsDaily",
    "OperationLog",
    "LoginLog",
    "SystemConfig",
    "RuleVersion",
    "Attachment",
    # ai
    "AIAgentTask",
    "AIAgentTrace",
    "AIPromptTemplate",
    "AIKnowledgeBase",
    "AIReport",
    "AIReportFollowUp",
    "AIExceptionEvent",
    "AIFeedback",
    "AIScheduledJob",
]
