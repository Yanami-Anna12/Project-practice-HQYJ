"""模型公共基类与混入。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def new_uuid() -> str:
    """统一使用 36 位字符串主键，兼容 SQLite 与 PostgreSQL。"""
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class UUIDMixin:
    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=new_uuid, sort_order=-100
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, server_default=func.now(), sort_order=100
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utcnow,
        onupdate=utcnow,
        server_default=func.now(),
        sort_order=101,
    )


class BaseModel(Base, UUIDMixin, TimestampMixin):
    """所有业务表的基类：UUID 主键 + 创建/更新时间。"""

    __abstract__ = True
