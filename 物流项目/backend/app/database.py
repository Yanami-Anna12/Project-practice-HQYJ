"""数据库连接与会话管理（SQLAlchemy 2.0）。

职责边界：
  - 本模块只负责「连接」和「会话生命周期」，不含任何业务或权限逻辑。
  - 权限计算逻辑放在 services/rbac.py，鉴权依赖放在 deps.py。
"""

from __future__ import annotations

import logging
from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.sql.elements import TextClause

from app.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 可移植的时间戳默认值
# ---------------------------------------------------------------------------
def now_default() -> TextClause:
    """返回可移植的「当前时间」服务端默认值。

    为什么不用 func.now()：SQLAlchemy 2.0 会把 func.now() 当成表达式默认值渲染，
    在 MySQL 上生成 `DEFAULT (now())`。写成 TEXT 形式则渲染为
    `DEFAULT CURRENT_TIMESTAMP`，MySQL 与 PostgreSQL 都能接受。
    """
    return text("CURRENT_TIMESTAMP")


class Base(DeclarativeBase):
    """所有 ORM 模型的基类（SQLAlchemy 2.0 风格）。"""


# ---------------------------------------------------------------------------
# Engine / Session
# ---------------------------------------------------------------------------
# pool_pre_ping=True：MySQL 的 wait_timeout 默认 8 小时，长空闲连接会被服务端
# 单方面掐断。pre_ping 在借出连接前先探活，避免 "MySQL server has gone away"。
if settings.db_backend == "sqlite":
    # 回退到 SQLite 时：先确保目录存在，并关闭跨线程检查
    # （FastAPI 在线程池里跑同步 Session，SQLite 默认禁止跨线程复用连接）
    settings.sqlite_file.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        settings.database_url,
        echo=False,
        future=True,
        connect_args={"check_same_thread": False},
    )
    logger.warning("MySQL 不可用，已自动回退到本地 SQLite：%s", settings.sqlite_file)
else:
    engine = create_engine(
        settings.database_url,
        echo=False,
        pool_pre_ping=True,
        pool_recycle=3600,
        future=True,
    )

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,  # commit 后对象仍可读，方便返回给 FastAPI 序列化
    future=True,
)


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：每个请求一个 Session，请求结束自动关闭。

    这里「不」做 commit —— 写操作由各 router / service 显式提交，
    保证事务边界清晰。
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 建库工具
# ---------------------------------------------------------------------------
def ensure_database_exists() -> bool:
    """确保目标数据库存在，不存在则创建。返回 True 表示本次新建了库。

    MySQL 不允许在 USE 之前 CREATE DATABASE，而 engine 已经绑定了库名，
    所以必须用 server_url 另开一次无库名连接。
    """
    if settings.db_backend != "mysql":
        # SQLite 等文件型后端没有「建库」这一步，表由 create_all_tables() 直接建
        logger.info("当前数据库后端为 %s，跳过建库步骤", settings.db_backend)
        return False

    server_engine = create_engine(settings.server_url, future=True, pool_pre_ping=True)
    try:
        with server_engine.connect() as conn:
            exists = conn.execute(
                text(
                    "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA "
                    "WHERE SCHEMA_NAME = :name"
                ),
                {"name": settings.DB_NAME},
            ).scalar()
            if exists:
                logger.info("数据库已存在：%s", settings.DB_NAME)
                return False

            # 库名来自配置文件可信来源；标识符无法参数化，用反引号包裹。
            conn.execute(
                text(
                    f"CREATE DATABASE `{settings.DB_NAME}` "
                    "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
                )
            )
            conn.commit()
            logger.info("已创建数据库：%s（utf8mb4）", settings.DB_NAME)
            return True
    finally:
        server_engine.dispose()


def create_all_tables() -> None:
    """按 ORM 元数据建表（IF NOT EXISTS，幂等）。

    ★ 建表之后必须再补一次「已存在表的增量列」：create_all 只建缺失的表，
      不会给老表加列（SQLite / MySQL 都没有 ADD COLUMN IF NOT EXISTS）。
      详见 app/migrations.py。
    """
    from app import models  # noqa: F401  （副作用导入，注册元数据）

    Base.metadata.create_all(bind=engine)
    logger.info("数据表已就绪：%d 张", len(Base.metadata.tables))

    from app.migrations import apply_lightweight_migrations

    apply_lightweight_migrations()


def drop_all_tables() -> None:
    """删表。仅供开发期重建数据库使用。"""
    from app import models  # noqa: F401

    Base.metadata.drop_all(bind=engine)
    logger.warning("已删除全部数据表")
