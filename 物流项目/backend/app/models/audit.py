"""审计日志模型。

★ 只追加、不修改、不删除。这条规则由四层共同保证：
   1. 代码层：全项目只有 services/audit.py 的 append_audit() 写日志，且只做 INSERT
   2. 接口层：对应的 API 只有 GET，其他方法一律 405
   3. 模型层：actor_id 用 ON DELETE SET NULL —— 操作者被删，日志必须留下
   4. 数据层：actor_name 冗余存快照，即使 actor_id 变 NULL 仍可读
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, now_default


class SysAuditLog(Base):
    __tablename__ = "sys_audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 操作者被删除后置 NULL，日志仍保留（快照机制）
    actor_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actor_name: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    target_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    # JSON 字符串。用 Text 而不是数据库原生 JSON 类型，保证 MySQL / PostgreSQL 可移植。
    detail_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=now_default(), index=True
    )
