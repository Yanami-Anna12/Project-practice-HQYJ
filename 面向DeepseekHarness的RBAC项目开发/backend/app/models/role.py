"""角色表 roles。"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, now_default

if TYPE_CHECKING:
    from app.models.associations import RolePermission, UserRole


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # 角色的稳定标识：admin / operator / supplier / readonly
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # 角色停用 → 它的全部权限点整体退出用户权限并集（R4 实时生效）
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=now_default()
    )

    # ---- 关系 ----
    role_permissions: Mapped[list["RolePermission"]] = relationship(
        "RolePermission",
        back_populates="role",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    # 注意三点：
    #   1. 「不要」加 cascade delete —— 用户绑定关系必须由应用层显式检查并返回 409（R3）。
    #   2. passive_deletes=True —— 删除角色时交给数据库判定，SQLAlchemy 不要抢先
    #      把 user_roles.role_id 置 NULL（RESTRICT 外键会被置 NULL 触发错误）。
    #   3. 数据库层还有 ON DELETE RESTRICT 兜底（见 models/associations.py）。
    user_roles: Mapped[list["UserRole"]] = relationship(
        "UserRole",
        back_populates="role",
        passive_deletes=True,
    )

    @property
    def permission_codes(self) -> list[str]:
        return sorted(
            rp.permission.code for rp in self.role_permissions if rp.permission is not None
        )

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<Role id={self.id} code={self.code!r} active={self.is_active}>"
