"""业务演示表：products / orders。

这两张表不是 RBAC 的一部分，只是「被保护资源」—— 用来验证权限点确实起作用。
字段刻意保持精简，重点在接口上的权限挂载，而不是业务复杂度。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, now_default


class Product(Base):
    """商品表：受 products:read / products:edit 保护。"""

    __tablename__ = "products"
    # 给唯一约束显式命名，避免 MySQL 自动取名（匿名唯一索引在重建表时不好引用）
    __table_args__ = (UniqueConstraint("sku", name="uq_products_sku"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    # 注意：唯一性只在 __table_args__ 的 UniqueConstraint 里声明。
    # 若这里再加 unique=True，会生成两个重复的唯一索引（既浪费写入性能又容易误判）。
    sku: Mapped[str] = mapped_column(String(50), nullable=False)
    price: Mapped[float] = mapped_column(
        Numeric(10, 2), nullable=False, default=0, server_default=text("0")
    )
    stock: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    # 创建人：记录「谁通过 products:edit 写的」，演示鉴权后身份可透传到业务层
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL", name="fk_product_creator"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=now_default()
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<Product id={self.id} sku={self.sku!r}>"


class Order(Base):
    """订单表：受 orders:read 保护（只读接口，不提供写接口）。"""

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_no: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    customer: Mapped[str] = mapped_column(String(80), nullable=False)
    amount: Mapped[float] = mapped_column(
        Numeric(10, 2), nullable=False, default=0, server_default=text("0")
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default=text("'pending'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=now_default()
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<Order id={self.id} order_no={self.order_no!r}>"
