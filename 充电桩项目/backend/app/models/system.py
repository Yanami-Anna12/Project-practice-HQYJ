"""消息、通知、统计日报、操作日志、规则配置（PDF 6.1 / 3.8 / 3.9 / 3.2）。"""

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
from sqlalchemy.orm import Mapped, mapped_column

from app.models.mixins import BaseModel


class Message(BaseModel):
    """消息表（PDF 6.1 / 3.8 消息中心：卡片、类型区分、详情、未读小红点）。"""

    __tablename__ = "message"
    __table_args__ = (Index("ix_message_receiver_read", "receiver_id", "is_read"),)

    receiver_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("user.id", ondelete="CASCADE"), index=True
    )
    receiver_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 工单退回提醒 / 紧急工单提醒 / 逾期工单提醒 / 工单取消提醒 ...
    msg_type: Mapped[str] = mapped_column(
        String(32), default="系统消息", index=True
    )
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 消息详情所需字段（PDF 3.8）
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    work_order_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    fault_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    report_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    link: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    channel: Mapped[str] = mapped_column(String(16), default="站内信")  # 站内信/微信/飞书/邮件


class Notification(BaseModel):
    """通知表（PDF 6.1）：面向多通道推送的投递记录。"""

    __tablename__ = "notification"

    channel: Mapped[str] = mapped_column(String(16), index=True)  # wechat/feishu/email/sms
    target: Mapped[str] = mapped_column(String(255))
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending/sent/failed
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    related_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    related_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class StatisticsDaily(BaseModel):
    """统计日报表（PDF 6.1）：支撑 3.9 统计分析与看板 + 报告 Agent。"""

    __tablename__ = "statistics_daily"
    __table_args__ = (
        Index("ix_stat_daily_scope", "stat_date", "project_id", "station_id"),
    )

    stat_date: Mapped[date] = mapped_column(Date, index=True)
    project_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    project_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    station_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    station_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    order_total: Mapped[int] = mapped_column(Integer, default=0)
    order_pending: Mapped[int] = mapped_column(Integer, default=0)
    order_done: Mapped[int] = mapped_column(Integer, default=0)
    order_overdue: Mapped[int] = mapped_column(Integer, default=0)
    order_urgent: Mapped[int] = mapped_column(Integer, default=0)
    defect_order_count: Mapped[int] = mapped_column(Integer, default=0)
    completion_rate: Mapped[float] = mapped_column(Float, default=0.0)
    overdue_rate: Mapped[float] = mapped_column(Float, default=0.0)
    fault_total: Mapped[int] = mapped_column(Integer, default=0)
    fault_pending_verify: Mapped[int] = mapped_column(Integer, default=0)
    fault_verified: Mapped[int] = mapped_column(Integer, default=0)
    inspection_total: Mapped[int] = mapped_column(Integer, default=0)
    inspection_abnormal: Mapped[int] = mapped_column(Integer, default=0)
    # PDF 3.9：5 种工单数量分布
    order_type_dist: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class OperationLog(BaseModel):
    """操作日志表（PDF 6.1 / 8.4 日志与审计）。"""

    __tablename__ = "operation_log"
    __table_args__ = (Index("ix_oplog_user_time", "user_id", "created_at"),)

    user_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    user_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    module: Mapped[str] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(64))
    target_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    method: Mapped[str | None] = mapped_column(String(8), nullable=True)
    path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    before: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class LoginLog(BaseModel):
    """登录日志。"""

    __tablename__ = "login_log"

    user_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    user_name: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    login_type: Mapped[str] = mapped_column(String(16), default="password")  # password/wechat
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    message: Mapped[str | None] = mapped_column(String(255), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)


class SystemConfig(BaseModel):
    """系统参数（PDF 3.2：工单类型、巡检频率、提醒规则、报告周期、AI 开关）。

    规则变更走本表 + RuleVersion 记录，支持热更新（PDF 9.3）。
    """

    __tablename__ = "system_config"

    config_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    config_name: Mapped[str] = mapped_column(String(128))
    config_group: Mapped[str] = mapped_column(String(64), default="basic", index=True)
    config_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_type: Mapped[str] = mapped_column(String(16), default="string")  # string/int/bool/json
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    editable: Mapped[bool] = mapped_column(Boolean, default=True)


class RuleVersion(BaseModel):
    """规则版本（PDF 4.1 原则 5：每次调度记录规则版本，保证可追溯）。"""

    __tablename__ = "rule_version"

    version: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    rule_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    hard_constraints: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    soft_constraints: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    change_log: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    effective_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Attachment(BaseModel):
    """附件管理（PDF 3.2 附件管理 + 2.2 对象存储）。"""

    __tablename__ = "attachment"

    biz_type: Mapped[str] = mapped_column(String(32), index=True)  # inspection/fault/report
    biz_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    file_name: Mapped[str] = mapped_column(String(255))
    file_path: Mapped[str] = mapped_column(String(500))
    file_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size: Mapped[int] = mapped_column(Integer, default=0)
    storage: Mapped[str] = mapped_column(String(16), default="local")  # local/minio/oss
    uploader_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
