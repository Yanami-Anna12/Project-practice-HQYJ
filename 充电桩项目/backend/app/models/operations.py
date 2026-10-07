"""工单、子任务、巡检、故障、台账（PDF 6.1 核心表 + 3.4~3.7 模块设计）。"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import (
    FaultLevel,
    FaultStatus,
    InspectFrequency,
    SubtaskStatus,
    TimeStatus,
    WorkOrderStatus,
    WorkOrderType,
)
from app.models.mixins import BaseModel


class WorkOrder(BaseModel):
    """工单主表（PDF 6.2 关键字段示例，字段名与方案保持一致）。"""

    __tablename__ = "work_order"
    __table_args__ = (
        Index("ix_work_order_status_date", "status", "inspect_start_date"),
        Index("ix_work_order_scope", "project_id", "station_id"),
    )

    order_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    order_name: Mapped[str] = mapped_column(String(128), index=True)
    # 巡视 / 特巡 / 消缺 / 设备检查 / 其他
    order_type: Mapped[str] = mapped_column(
        String(32), default=WorkOrderType.PATROL.value, index=True
    )
    project_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("project.id"), index=True, nullable=True
    )
    station_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("station.id"), index=True, nullable=True
    )
    station_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    station_address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # 多站点工单：数组形式的站点 ID 与名称
    station_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    station_names: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # 待接单 / 待完成 / 已完成 / 已取消 / 已退回
    status: Mapped[str] = mapped_column(
        String(32), default=WorkOrderStatus.PENDING_ACCEPT.value, index=True
    )
    # 正常 / 紧急 / 逾期
    time_status: Mapped[str] = mapped_column(
        String(32), default=TimeStatus.NORMAL.value, index=True
    )
    inspector_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("user.id"), index=True, nullable=True
    )
    inspector_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    inspect_start_date: Mapped[date | None] = mapped_column(Date, index=True, nullable=True)
    inspect_end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    inspect_frequency: Mapped[str] = mapped_column(
        String(16), default=InspectFrequency.MONTH.value
    )
    inspect_count: Mapped[int] = mapped_column(Integer, default=1)
    # 巡检周期（与巡检频率共同决定子任务数量）
    inspect_cycle: Mapped[int] = mapped_column(Integer, default=1)
    subtask_total: Mapped[int] = mapped_column(Integer, default=0)
    subtask_done: Mapped[int] = mapped_column(Integer, default=0)
    # 工单 tag 冗余字段，便于列表快速筛选（PDF 3.4 工单 tag）
    priority: Mapped[str] = mapped_column(String(16), default="正常")
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
    reject_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 来源：手工 / AI 生成（PDF 3.11 智能工单调度）
    source: Mapped[str] = mapped_column(String(16), default="手工")
    ai_plan_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    due_soon_notified: Mapped[bool] = mapped_column(Boolean, default=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("user.id"), nullable=True
    )

    subtasks: Mapped[list["WorkOrderSubtask"]] = relationship(
        back_populates="work_order", cascade="all, delete-orphan"
    )


class WorkOrderSubtask(BaseModel):
    """工单子任务表（PDF 6.2）。"""

    __tablename__ = "work_order_subtask"
    __table_args__ = (Index("ix_subtask_work_order_seq", "work_order_id", "sequence"),)

    work_order_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("work_order.id", ondelete="CASCADE"), index=True
    )
    order_no: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    order_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    order_type: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    station_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("station.id"), index=True, nullable=True
    )
    station_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    pile_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("charging_pile.id"), nullable=True
    )
    pile_asset_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sequence: Mapped[int] = mapped_column(Integer, default=1)
    plan_date: Mapped[date | None] = mapped_column(Date, index=True, nullable=True)
    plan_time_window: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), default=SubtaskStatus.PENDING.value, index=True
    )
    assignee_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("user.id"), index=True, nullable=True
    )
    assignee_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 巡检项明细（PDF 3.4 巡检情况录入：正常/异常勾选 + 200 字备注）
    item_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    route_order: Mapped[int] = mapped_column(Integer, default=0)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    work_order: Mapped[WorkOrder] = relationship(back_populates="subtasks")
    inspections: Mapped[list["InspectionRecord"]] = relationship(
        back_populates="subtask", cascade="all, delete-orphan"
    )


class InspectionRecord(BaseModel):
    """巡检记录表（PDF 6.2）。"""

    __tablename__ = "inspection_record"
    __table_args__ = (Index("ix_inspection_subtask_status", "subtask_id", "status"),)

    subtask_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("work_order_subtask.id", ondelete="CASCADE"), index=True
    )
    work_order_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    inspector_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("user.id"), index=True, nullable=True
    )
    inspector_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    station_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    station_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # GPS 签到签退（PDF 7.2 GPS 签到、签退、轨迹）
    checkin_location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    checkin_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    checkin_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    checkin_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    checkout_location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    checkout_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    checkout_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    checkout_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    content: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    images: Mapped[list | None] = mapped_column(JSON, nullable=True)
    abnormal_count: Mapped[int] = mapped_column(Integer, default=0)
    normal_count: Mapped[int] = mapped_column(Integer, default=0)
    remark: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="已完成", index=True)

    subtask: Mapped[WorkOrderSubtask] = relationship(back_populates="inspections")


class InspectionItem(BaseModel):
    """巡检项表（PDF 6.1）。"""

    __tablename__ = "inspection_item"

    inspection_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("inspection_record.id", ondelete="CASCADE"), index=True, nullable=True
    )
    work_order_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    pile_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    pile_asset_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    item_name: Mapped[str] = mapped_column(String(128))
    item_group: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 正常 / 异常
    result: Mapped[str] = mapped_column(String(16), default="正常")
    remark: Mapped[str | None] = mapped_column(String(200), nullable=True)
    images: Mapped[list | None] = mapped_column(JSON, nullable=True)


class FaultReport(BaseModel):
    """故障上报表（PDF 6.2）。"""

    __tablename__ = "fault_report"
    __table_args__ = (Index("ix_fault_status_level", "status", "fault_level"),)

    fault_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    project_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("project.id"), index=True, nullable=True
    )
    station_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("station.id"), index=True, nullable=True
    )
    station_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    pile_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("charging_pile.id"), index=True, nullable=True
    )
    pile_asset_code: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    reporter_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("user.id"), index=True, nullable=True
    )
    reporter_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reporter_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    fault_type: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    # 一般 / 严重 / 危急
    fault_level: Mapped[str] = mapped_column(
        String(16), default=FaultLevel.GENERAL.value, index=True
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    images: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # 待上报（草稿）/ 待核查 / 核查通过 / 核查驳回
    status: Mapped[str] = mapped_column(
        String(32), default=FaultStatus.PENDING_REPORT.value, index=True
    )
    is_draft: Mapped[bool] = mapped_column(Boolean, default=False)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reported_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # AI 诊断结果（PDF 3.11 智能故障诊断）
    ai_diagnosis: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    ai_level_suggestion: Mapped[str | None] = mapped_column(String(16), nullable=True)

    verifications: Mapped[list["FaultVerification"]] = relationship(
        back_populates="fault", cascade="all, delete-orphan"
    )


class FaultVerification(BaseModel):
    """故障核查表（PDF 6.2）。"""

    __tablename__ = "fault_verification"

    fault_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("fault_report.id", ondelete="CASCADE"), index=True
    )
    verifier_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("user.id"), index=True, nullable=True
    )
    verifier_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verify_status: Mapped[str] = mapped_column(String(32), default="核查通过")
    verify_level: Mapped[str | None] = mapped_column(String(16), nullable=True)
    verify_desc: Mapped[str | None] = mapped_column(Text, nullable=True)
    images: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # 核查结论是否需要转消缺工单
    need_defect_order: Mapped[bool] = mapped_column(Boolean, default=False)

    fault: Mapped[FaultReport] = relationship(back_populates="verifications")


class AssetLedger(BaseModel):
    """台账表（PDF 6.1 / 3.7：站台台账 + 充电桩台账 + 导出）。

    station / pile 台账条目在此表统一沉淀，便于复杂查询与导出。
    """

    __tablename__ = "asset_ledger"
    __table_args__ = (Index("ix_ledger_type_code", "ledger_type", "asset_code"),)

    ledger_type: Mapped[str] = mapped_column(String(16), index=True)  # station / pile
    asset_code: Mapped[str] = mapped_column(String(64), index=True)
    asset_name: Mapped[str] = mapped_column(String(128), index=True)
    project_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    project_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    station_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    station_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    pile_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # 通用扩展字段：充电枪数量、灭火器、摄像头等台账属性
    attributes: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="正常")
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)
