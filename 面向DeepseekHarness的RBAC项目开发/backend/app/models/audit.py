"""审计日志表 audit_logs。

★ R5：审计日志只追加，不修改、不删除。

这条规则在代码层面用四种手段共同保证：
  1. 全项目只有一个写入口 —— services/audit.py 的 append_audit()，它只做 INSERT；
  2. 不向任何路由暴露 UPDATE / DELETE audit_logs 的能力（/api/audit-logs 只有 GET）；
  3. actor_id 用 ON DELETE SET NULL 而不是 CASCADE —— 操作者被删，日志依然在；
  4. actor_name / actor_username 冗余存快照 —— 即使 actor_id 变成 NULL，日志仍可读。

验收时可执行以下命令证明没有「修改/删除日志」的代码：
    grep -rn "AuditLog" backend/app | grep -iE "delete|update|setattr"
    → 只应命中本文件的注释与 services/audit.py 的 INSERT 逻辑
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, String, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, now_default


class AuditLog(Base):
    __tablename__ = "audit_logs"

    # ★ 用 BigInteger 而不是默认的 INT：
    #   审计日志是只追加表，只增不减，是系统里增长最快的表。
    #   INT 上限约 21 亿，而这个表的主键一旦写满无法原地扩容（改主键类型要重建全表）。
    #   直接上 BIGINT，属于「零成本消除未来隐患」。
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # 操作者被删除时置 NULL（日志本身必须留下）
    actor_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL", name="fk_audit_actor"),
        nullable=True,
        index=True,
    )
    # 冗余快照：操作者改名或注销后，历史日志仍能读懂「是谁干的」
    # server_default 兜底，确保任何写入路径（含裸 SQL）都不会因缺字段而失败
    actor_name: Mapped[str] = mapped_column(
        String(50), nullable=False, default="system", server_default=text("'system'")
    )

    # 动作名，统一用 "资源.动作" 格式，便于过滤
    # role.create / role.update / role.delete / role.assign_permissions
    # user.assign_roles / permission.create / permission.toggle / auth.login
    action: Mapped[str] = mapped_column(String(50), nullable=False, index=True)

    target_type: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    target_id: Mapped[int | None] = mapped_column(nullable=True)
    target_name: Mapped[str | None] = mapped_column(String(80), nullable=True)

    # 变更详情（旧值 / 新值 / 影响范围），中文字段便于直接给人看
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=now_default(), index=True
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<AuditLog id={self.id} action={self.action!r} by={self.actor_name!r}>"
