"""调度规则配置模块：规则版本快照。

对应需求文档 二.2.7「规则配置与治理」与技术方案文档 3.3「规则版本管理、
生效时间、规则优先级、规则冲突检测、规则试算、发布/回滚、变更日志」。

★ 设计取舍：
  规则的**内容**分散在各自的表里（车辆类型管装载量、趟次、参数表管开关、
  地形矩阵管通行），避免为「统一规则表」造一套 EAV 结构 —— 那会让
  每次读取规则都变成一次解析，得不偿失。

  本表只做**版本快照与发布记录**：
    · snapshot_json 存发布时刻的完整规则快照（便于回溯与审计）
    · 调度任务记录 rule_version，保证「这次方案是按哪版规则算的」可追溯
    · 回滚 = 用历史快照重新写入各规则表 + 生成一个新版本记录

  这样规则读写仍走各自强类型的表，版本治理只负责「冻结」与「追溯」。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, now_default


class RuleVersion(Base):
    """规则版本快照。"""

    __tablename__ = "sys_rule_version"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    description: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # 发布时刻的完整规则快照（JSON 文本）
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    # 规则变更内容摘要（人类可读）
    change_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    published_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    published_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=now_default()
    )
