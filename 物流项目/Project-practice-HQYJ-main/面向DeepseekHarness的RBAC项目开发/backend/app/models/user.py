"""用户表 users。"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base, now_default

if TYPE_CHECKING:
    from app.models.associations import UserRole
    from app.models.role import Role


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    # 只存 bcrypt 哈希，永远不存明文，也永远不出现在任何响应模型里
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    nickname: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # 停用后登录一律 401；已签发的 Token 也会在下一次请求被拒（因为每次都查库）
    # server_default 让裸 SQL 插入也能走通（只有 default= 时，DB 侧无默认值，会报 1364）
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("1")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=now_default()
    )

    # ---- 关系 ----
    # 用户不直接持有权限，只通过 user_roles 持有角色（RBAC 的核心约束）
    user_roles: Mapped[list["UserRole"]] = relationship(
        "UserRole",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    @property
    def roles(self) -> list["Role"]:
        """便捷访问：该用户绑定的角色对象列表。"""
        return [ur.role for ur in self.user_roles if ur.role is not None]

    @property
    def role_codes(self) -> list[str]:
        return sorted({ur.role.code for ur in self.user_roles if ur.role is not None})

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<User id={self.id} username={self.username!r} active={self.is_active}>"
