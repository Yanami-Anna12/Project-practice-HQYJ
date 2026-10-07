"""数据库引擎与会话管理（SQLAlchemy 2.0 异步）。

本地开发默认 SQLite，生产按 PDF 2.2 切换 PostgreSQL 15+，
只需修改 DATABASE_URL，模型与业务代码无需改动。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy import MetaData, event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.core.config import settings

# 统一命名约定，便于后续 Alembic 迁移与 PostgreSQL 索引管理
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _engine_kwargs() -> dict:
    kwargs: dict = {"echo": settings.DB_ECHO, "future": True}
    if settings.is_sqlite:
        # SQLite 使用 NullPool：每个会话用完即关，避免长事务持锁；
        # timeout 让并发写入排队等待而不是直接报 "database is locked"。
        kwargs["poolclass"] = NullPool
        kwargs["connect_args"] = {
            "check_same_thread": False,
            "timeout": settings.SQLITE_BUSY_TIMEOUT,
        }
    else:
        kwargs.update(
            {
                "pool_size": 20,  # PDF 2.3 千人级并发
                "max_overflow": 40,
                "pool_pre_ping": True,
                "pool_recycle": 1800,
            }
        )
    return kwargs


engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs())

if settings.is_sqlite:

    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record):  # pragma: no cover - 驱动回调
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()


AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI 依赖：每请求一个会话。"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """建表（开发环境）。生产环境使用 Alembic 迁移。"""
    from app import models  # noqa: F401  确保所有模型已注册到 metadata

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
