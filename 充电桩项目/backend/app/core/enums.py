"""枚举与常量：全部来自《充电桩运维管理 AI Agent 项目技术方案》。

PDF 4.1 原则 1「硬约束代码化」——工单类型、巡检频率、子任务计算、
故障等级、权限、报告周期由确定性代码保证，因此这些取值集中在此处定义，
数据库与 API 层共用，避免出现魔法字符串。
"""

from __future__ import annotations

from enum import Enum


class StrEnum(str, Enum):
    """Python 3.11+ StrEnum 的兼容实现，便于直接做 Pydantic 校验。"""

    def __str__(self) -> str:  # pragma: no cover - 展示用
        return str(self.value)


# ---------------------------------------------------------------- 工单（PDF 3.4）
class WorkOrderType(StrEnum):
    PATROL = "巡视"  # 巡视工单
    SPECIAL = "特巡"  # 特巡工单
    DEFECT = "消缺"  # 消缺工单
    EQUIPMENT = "设备检查"  # 设备检查工单
    OTHER = "其他"  # 其他工单


class WorkOrderStatus(StrEnum):
    PENDING_ACCEPT = "待接单"
    PENDING_DONE = "待完成"
    COMPLETED = "已完成"
    CANCELLED = "已取消"
    RETURNED = "已退回"


class TimeStatus(StrEnum):
    NORMAL = "正常"
    URGENT = "紧急"
    OVERDUE = "逾期"


class InspectFrequency(StrEnum):
    MONTH = "月"
    WEEK = "周"
    DAY = "日"


class SubtaskStatus(StrEnum):
    PENDING = "待完成"
    IN_PROGRESS = "巡检中"
    COMPLETED = "已完成"
    CANCELLED = "已取消"


# ---------------------------------------------------------------- 故障（PDF 3.5）
class FaultLevel(StrEnum):
    GENERAL = "一般"
    SERIOUS = "严重"
    CRITICAL = "危急"


class FaultStatus(StrEnum):
    PENDING_REPORT = "待上报"
    PENDING_VERIFY = "待核查"
    VERIFIED = "核查通过"
    REJECTED = "核查驳回"


class VerifyResult(StrEnum):
    PASS = "核查通过"
    REJECT = "核查驳回"


# ---------------------------------------------------------------- 巡检（PDF 3.4）
class InspectItemResult(StrEnum):
    NORMAL = "正常"
    ABNORMAL = "异常"


# ---------------------------------------------------------------- 消息（PDF 3.8）
class MessageType(StrEnum):
    ORDER_RETURNED = "工单退回提醒"
    ORDER_URGENT = "紧急工单提醒"
    ORDER_OVERDUE = "逾期工单提醒"
    ORDER_CANCELLED = "工单取消提醒"
    ORDER_ASSIGNED = "工单下发提醒"
    FAULT_PENDING = "故障待核查提醒"
    REPORT_READY = "报告生成提醒"
    SYSTEM = "系统消息"


# ---------------------------------------------------------------- 权限（PDF 3.3）
class DataScope(StrEnum):
    PERSONAL = "个人数据"
    STATION = "站点数据"
    PROJECT = "项目数据"
    PLATFORM = "平台数据"


# 数据权限可见范围由大到小，用于越权判断
DATA_SCOPE_ORDER = {
    DataScope.PERSONAL: 0,
    DataScope.STATION: 1,
    DataScope.PROJECT: 2,
    DataScope.PLATFORM: 3,
}


# ---------------------------------------------------------------- AI Agent（PDF 3.11 / 5.3）
class AgentType(StrEnum):
    WORK_ORDER = "智能工单调度"
    FAULT_DIAGNOSIS = "智能故障诊断"
    INSPECTION_REPORT = "智能巡检报告"
    MAINTENANCE_SUGGEST = "智能运维建议"
    RISK_CONTROL = "智能风控"
    REPORT = "智能报告"
    DATA_ANALYSIS = "智能数据分析"
    ORCHESTRATOR = "编排"


class AgentTaskStatus(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    WAITING_CONFIRMATION = "waiting_confirmation"
    CONFIRMED = "confirmed"
    DISPATCHED = "dispatched"
    COMPLETED = "completed"
    FAILED = "failed"
    REPLANNING = "replanning"
    CANCELLED = "cancelled"


class ReportType(StrEnum):
    DAILY = "daily"  # 日运营简报
    WEEKLY = "weekly"  # 周运维分析
    MONTHLY = "monthly"  # 月度深度报告
    INSTANT = "instant"  # 即时分析运营报告


REPORT_TYPE_LABEL = {
    ReportType.DAILY: "日运营简报",
    ReportType.WEEKLY: "周运维分析",
    ReportType.MONTHLY: "月度深度报告",
    ReportType.INSTANT: "即时分析运营报告",
}


# PDF 3.12：数据更新策略
REPORT_CRON_HOUR = {
    ReportType.DAILY: 2,
    ReportType.WEEKLY: 3,
    ReportType.MONTHLY: 4,
}


# ---------------------------------------------------------------- 工单子任务公式（PDF 3.4）
# 巡视 / 设备检查 / 其他：子任务数 = 站点数量 × 巡检周期 × 巡检频率
# 特巡：子任务数 = 站点数量 × 巡检次数
# 消缺：固定 1 个子任务
SUBTASK_FORMULA = {
    WorkOrderType.PATROL: "站点数量 × 巡检周期 × 巡检频率",
    WorkOrderType.EQUIPMENT: "站点数量 × 巡检周期 × 巡检频率",
    WorkOrderType.OTHER: "站点数量 × 巡检周期 × 巡检频率",
    WorkOrderType.SPECIAL: "站点数量 × 巡检次数",
    WorkOrderType.DEFECT: "固定 1 个子任务",
}
