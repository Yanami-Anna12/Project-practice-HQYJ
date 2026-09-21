"""权限点表 permissions。

权限点是 RBAC 的最小粒度，就是一个字符串，例如 "products:edit"。
这个字符串同时也是 authorize("products:edit") 的入参 —— 二者必须严格一致。
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, now_default

if TYPE_CHECKING:
    from app.models.associations import RolePermission


class Permission(Base):
    __tablename__ = "permissions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # 权限码："模块:动作"，全局唯一
    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    module: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    # ★ R4 的关键字段：置 0 后，所有引用它的角色立即失去该权限，无需重启、无需清缓存
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=now_default()
    )

    role_permissions: Mapped[list["RolePermission"]] = relationship(
        "RolePermission",
        back_populates="permission",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<Permission id={self.id} code={self.code!r} active={self.is_active}>"
