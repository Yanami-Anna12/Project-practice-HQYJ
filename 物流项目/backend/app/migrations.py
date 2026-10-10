"""轻量加列迁移。

★ 为什么需要这个模块？

  `Base.metadata.create_all()` 只会「建缺失的表」，**不会给已存在的表加列**。
  而 SQLite（本项目在没有 MySQL 的机器上会自动回退到 SQLite）**不支持
  `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`**，只能靠「先查列、再决定加不加」
  这种笨办法做到幂等。MySQL 8.0 也不支持 `ADD COLUMN IF NOT EXISTS`。

  所以本模块做一件很小的事：把 ORM 里新增的可空列，补到已经存在的物理表上。
  它**不是** Alembic 的替代品 —— 只能加「可空 / 有默认值」的列，不能改类型、
  不能删列、不能迁移数据。正式项目请上 Alembic。

已知增量列（新增时在这里登记）：
  - md_driver.user_id          司机 → 登录账号（司机端小程序登录场景）
  - md_store.latitude/longitude 门店坐标（司机端一键导航）
  - dispatch_record.accepted_at / accepted_by  司机确认接单（趟次级确认事实）
"""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text

from app.database import engine

logger = logging.getLogger(__name__)

# (表名, 列名, 列定义) —— 列定义必须是两种后端都能接受的写法
ADDED_COLUMNS: list[tuple[str, str, str]] = [
    ("md_driver", "user_id", "INTEGER NULL"),
    ("md_store", "latitude", "NUMERIC(10, 6) NULL"),
    ("md_store", "longitude", "NUMERIC(10, 6) NULL"),
    # 司机确认接单：老库（表已存在但缺列）靠这里补齐，新库由 create_all 直接带上。
    # 两列都可空，所以历史记录自动是「未确认」，不需要数据回填。
    ("dispatch_record", "accepted_at", "DATETIME NULL"),
    ("dispatch_record", "accepted_by", "INTEGER NULL"),
]

# 需要补的索引（新表由 create_all 建，这里是给「表已存在但缺索引」兜底）
ADDED_INDEXES: list[tuple[str, str, str]] = [
    ("md_driver", "ix_md_driver_user_id", "user_id"),
]


def apply_lightweight_migrations() -> list[str]:
    """补齐已存在表上缺失的可空列，返回本次实际执行的 DDL 列表。

    幂等：列已存在则跳过，可以放心在每次 seed / 启动时调用。
    在 `create_all_tables()` 之后调用 —— 新库的表已经带上了这些列，
    所以新库这里通常什么都不做。
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    applied: list[str] = []

    with engine.begin() as conn:
        for table, column, ddl_type in ADDED_COLUMNS:
            if table not in existing_tables:
                continue  # 表还不存在，create_all 会带上完整列
            columns = {c["name"] for c in inspector.get_columns(table)}
            if column in columns:
                continue
            # 表名/列名来自本模块的常量，非用户输入；标识符无法参数化，用反引号包裹
            # （MySQL 必须、SQLite 也兼容这种引法）
            statement = f"ALTER TABLE `{table}` ADD COLUMN `{column}` {ddl_type}"
            conn.execute(text(statement))
            applied.append(statement)

        for table, index_name, column in ADDED_INDEXES:
            if table not in existing_tables:
                continue
            indexes = {i["name"] for i in inspector.get_indexes(table)}
            if index_name in indexes or column not in {
                c["name"] for c in inspector.get_columns(table)
            }:
                continue
            statement = f"CREATE INDEX `{index_name}` ON `{table}` (`{column}`)"
            conn.execute(text(statement))
            applied.append(statement)

    if applied:
        logger.warning("轻量迁移：补齐 %d 处结构差异（%s）", len(applied), "；".join(applied))
    return applied
