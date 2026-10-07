"""关联表：user_roles 与 role_permissions。

这两张表是 RBAC 的两条边：
    User ──(user_roles)──> Role ──(role_permissions)──> Permission

用「关联对象」（association object）而不是裸 Table，原因有二：
  1. 需要在关联上放时间戳（谁在什么时候被授予的），便于审计；
  2. 绑定/解绑时可以按对象操作，代码比操作裸 Table 清晰。
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, now_default

if TYPE_CHECKING:
    from app.models.permission import Permission
    from app.models.role import Role
    from app.models.user import User


class UserRole(Base):
    """用户-角色关联表。

    ★ R3 的数据库级兜底就藏在 role_id 的外键行为上：
        ondelete="RESTRICT"
      应用层会先 COUNT 引用数并返回 409；万一应用层漏判，MySQL 也会用
      外键错误拒绝删除，双保险，绝不可能出现「角色被删、绑定关系悬空」。
    """

    __tablename__ = "user_roles"
    __table_args__ = (
        UniqueConstraint("user_id", "role_id", name="uq_user_role"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # 用户被删 → 绑定关系跟着删（用户侧的级联是合理的，与 R3 的角色侧保护不冲突）
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE", name="fk_ur_user"),
        nullable=False,
        index=True,
    )
    # 角色被删 → 数据库直接拒绝（RESTRICT）
    role_id: Mapped[int] = mapped_column(
        ForeignKey("roles.id", ondelete="RESTRICT", name="fk_ur_role"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=now_default()
    )

    user: Mapped["User"] = relationship("User", back_populates="user_roles")
    role: Mapped["Role"] = relationship("Role", back_populates="user_roles")

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<UserRole user_id={self.user_id} role_id={self.role_id}>"


class RolePermission(Base):
    """角色-权限点关联表。

    角色被删或权限点被删时，关联行跟着删（CASCADE）：
    角色没了，它的权限绑定自然没有意义。
    """

    __tablename__ = "role_permissions"
    __table_args__ = (
        UniqueConstraint("role_id", "permission_id", name="uq_role_permission"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    role_id: Mapped[int] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE", name="fk_rp_role"),
        nullable=False,
        index=True,
    )
    permission_id: Mapped[int] = mapped_column(
        ForeignKey("permissions.id", ondelete="CASCADE", name="fk_rp_permission"),
        nullable=False,
        index=True,
    )

    role: Mapped["Role"] = relationship("Role", back_populates="role_permissions")
    permission: Mapped["Permission"] = relationship(
        "Permission", back_populates="role_permissions"
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<RolePermission role_id={self.role_id} permission_id={self.permission_id}>"
