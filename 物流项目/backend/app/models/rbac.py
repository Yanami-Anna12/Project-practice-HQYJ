"""RBAC 模型：用户、角色、权限点及其关联表。

设计要点：
  - 用户 ↔ 角色、角色 ↔ 权限点 都是多对多，用中间表。
  - 用户的「有效权限」= 其所有**启用**角色权限的**并集**，
    且权限点本身也必须处于启用状态（计算见 services/rbac.py）。
  - 刻意不建数据库外键级联：删除保护在 service 层显式判断并返回 409，
    这样能给出「仍被 N 个用户引用」这种可读的错误，而不是数据库层的完整性异常。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, now_default

# ---------------------------------------------------------------------------
# 中间表
# ---------------------------------------------------------------------------
user_roles = Table(
    "sys_user_role",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("sys_user.id"), primary_key=True),
    Column("role_id", Integer, ForeignKey("sys_role.id"), primary_key=True),
)

role_permissions = Table(
    "sys_role_permission",
    Base.metadata,
    Column("role_id", Integer, ForeignKey("sys_role.id"), primary_key=True),
    Column("permission_id", Integer, ForeignKey("sys_permission.id"), primary_key=True),
)


# ---------------------------------------------------------------------------
# 用户
# ---------------------------------------------------------------------------
class SysUser(Base):
    __tablename__ = "sys_user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    nickname: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    dept: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    phone: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=now_default()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=now_default(), onupdate=datetime.now
    )

    roles: Mapped[list["SysRole"]] = relationship(
        secondary=user_roles, back_populates="users", lazy="selectin"
    )


# ---------------------------------------------------------------------------
# 角色
# ---------------------------------------------------------------------------
class SysRole(Base):
    __tablename__ = "sys_role"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=now_default()
    )

    users: Mapped[list[SysUser]] = relationship(secondary=user_roles, back_populates="roles")
    permissions: Mapped[list["SysPermission"]] = relationship(
        secondary=role_permissions, back_populates="roles", lazy="selectin"
    )


# ---------------------------------------------------------------------------
# 权限点
# ---------------------------------------------------------------------------
class SysPermission(Base):
    __tablename__ = "sys_permission"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 格式：资源:动作，例如 vehicles:manage
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    module: Mapped[str] = mapped_column(String(64), nullable=False, default="未分组")
    action: Mapped[str] = mapped_column(String(32), nullable=False, default="custom")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=now_default()
    )

    roles: Mapped[list[SysRole]] = relationship(
        secondary=role_permissions, back_populates="permissions"
    )


# 供 schema 复用的说明文本（避免多处硬编码）
PERMISSION_CODE_HINT = Text("资源:动作，例如 stores:manage")
