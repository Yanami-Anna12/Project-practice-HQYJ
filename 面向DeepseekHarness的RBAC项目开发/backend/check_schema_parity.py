"""阶段 1 结构一致性校验：ORM 产物 vs 参考 SQL 脚本 vs R3 数据库兜底。

为什么需要这个脚本：
    项目里有两份「表结构定义」——ORM 模型（app/models/）和参考 SQL（sql/01_schema.sql）。
    两份定义最容易在后期悄悄漂移（改了模型忘记改 SQL，或反之），
    而这种漂移往往要到很晚才以「莫名奇妙的 SQL 错误」的形式暴露出来。

    本脚本用程序化对比代替肉眼核对：
      1. 按 ORM 元数据重建 rbac_db，导出「列定义」与「外键/唯一约束」两份清单；
      2. 用 sql/01_schema.sql 建一个临时库，导出同样两份清单；
      3. 逐行对比，任何差异都打印出来并以非 0 退出码结束；
      4. 最后实测 R3 的数据库级兜底（ON DELETE RESTRICT）确实会拦截删除。

运行：  python check_schema_parity.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from sqlalchemy import text

from app import models  # noqa: F401  （副作用导入，注册所有表）
from app.config import settings
from app.database import Base, create_all_tables, engine, ensure_database_exists

SCRATCH_DB = "rbac_sqlref_test"
MYSQL_CLI = r"C:\MySQL\MySQL Server 8.0\bin\mysql.exe"
SCHEMA_SQL = Path(__file__).resolve().parent / "sql" / "01_schema.sql"

COLUMNS_QUERY = """
SELECT CONCAT(TABLE_NAME,'|',COLUMN_NAME,'|',COLUMN_TYPE,'|',IS_NULLABLE,'|',
              IFNULL(COLUMN_DEFAULT,'<null>'))
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = '{db}'
ORDER BY TABLE_NAME, COLUMN_NAME
"""

CONSTRAINTS_QUERY = """
SELECT CONCAT(tc.TABLE_NAME,'|',tc.CONSTRAINT_NAME,'|',tc.CONSTRAINT_TYPE,'|',
              IFNULL(k.REFERENCED_TABLE_NAME,'-'),'|',IFNULL(k.COLUMN_NAME,'-'),'|',
              IFNULL(k.REFERENCED_COLUMN_NAME,'-'))
FROM information_schema.TABLE_CONSTRAINTS tc
LEFT JOIN information_schema.KEY_COLUMN_USAGE k
       ON k.CONSTRAINT_SCHEMA = tc.CONSTRAINT_SCHEMA
      AND k.CONSTRAINT_NAME   = tc.CONSTRAINT_NAME
      AND k.TABLE_NAME        = tc.TABLE_NAME
WHERE tc.TABLE_SCHEMA = '{db}'
  AND tc.CONSTRAINT_TYPE IN ('FOREIGN KEY','UNIQUE')
ORDER BY tc.TABLE_NAME, tc.CONSTRAINT_NAME
"""


def mysql_cli(sql: str, database: str | None = None, batch: bool = True) -> str:
    """调用 mysql.exe 执行 SQL 并返回输出。

    用 CLI 而不是 SQLAlchemy，是为了能执行 `source` 和多语句脚本，
    并让 R3 的 RESTRICT 以「真实错误码」形式暴露出来。
    """
    cmd = [MYSQL_CLI, "-u", settings.DB_USER, "--default-character-set=utf8mb4"]
    if batch:
        cmd.append("-N")
        cmd.append("-B")
    if database:
        cmd.append(database)
    cmd += ["-e", sql]

    env = {**os.environ, "MYSQL_PWD": settings.DB_PASSWORD}
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", env=env)
    return (proc.stdout or "") + (proc.stderr or "")


def fetch(db: str, query: str) -> list[str]:
    out = mysql_cli(query.format(db=db))
    return [line.strip() for line in out.splitlines() if line.strip()]


def install_reference_schema() -> tuple[bool, str]:
    """用参考 SQL 脚本建临时库。"""
    mysql_cli(f"DROP DATABASE IF EXISTS `{SCRATCH_DB}`", batch=False)
    sql = SCHEMA_SQL.read_text(encoding="utf-8").replace("rbac_db", SCRATCH_DB)
    # 去掉 BOM，写成 utf-8 无 BOM，否则 mysql CLI 可能报语法错
    tmp = Path(tempfile.gettempdir()) / "rbac_sqlref_test.sql"
    tmp.write_text(sql, encoding="utf-8")
    out = mysql_cli(f"source {tmp.as_posix()}", batch=False)
    ok = "ERROR" not in out.upper()
    return ok, out


def diff(label: str, left: list[str], right: list[str]) -> bool:
    print(f"\n── {label}")
    only_orm = [x for x in left if x not in right]
    only_sql = [x for x in right if x not in left]
    if not only_orm and not only_sql:
        print(f"   一致 ✓（{len(left)} 项）")
        return True
    print(f"   存在差异 ✗")
    for x in only_orm:
        print(f"     仅 ORM 有 : {x}")
    for x in only_sql:
        print(f"     仅 SQL 有 : {x}")
    return False


def test_r3_restrict() -> bool:
    """实测 R3：删除仍被引用的角色，数据库必须拒绝。"""
    print("\n── R3 数据库级兜底实测（ON DELETE RESTRICT）")
    db = "rbac_db"
    mysql_cli(
        "DELETE FROM user_roles; DELETE FROM roles; DELETE FROM users;"
        "INSERT INTO roles (code,name) VALUES ('tmp_probe','探针角色');"
        "INSERT INTO users (username,password_hash) VALUES ('tmp_user','x');"
        "INSERT INTO user_roles (user_id,role_id)"
        "  SELECT (SELECT id FROM users WHERE username='tmp_user'),"
        "         (SELECT id FROM roles WHERE code='tmp_probe');",
        database=db,
        batch=False,
    )
    out = mysql_cli("DELETE FROM roles WHERE code='tmp_probe';", database=db, batch=False)
    blocked = "1451" in out or "Cannot delete or update a parent row" in out
    print(f"   DELETE 被引用的角色 -> {'已拦截 ✓ (ERROR 1451)' if blocked else '未拦截 ✗'}")

    # 清理探针数据
    mysql_cli(
        "DELETE FROM user_roles; DELETE FROM roles; DELETE FROM users;",
        database=db,
        batch=False,
    )
    return blocked


def main() -> int:
    print("=" * 78)
    print("阶段 1 结构一致性校验：ORM 产物 == 参考 SQL 脚本")
    print("=" * 78)
    print(f"库名        : {settings.DB_NAME}")
    print(f"参考脚本    : {SCHEMA_SQL}")
    print(f"临时对照库  : {SCRATCH_DB}")

    # 1) 重建 ORM 库
    ensure_database_exists()
    Base.metadata.drop_all(bind=engine)
    create_all_tables()
    print("\n已按 ORM 元数据重建 rbac_db")

    # 2) 用参考 SQL 建临时库
    ok, out = install_reference_schema()
    if not ok:
        print("\n参考 SQL 执行失败：")
        print(out)
        return 1
    print("已按 sql/01_schema.sql 建立临时对照库")

    # 3) 对比
    same_cols = diff(
        "列定义（名称|类型|可空|默认值）",
        fetch(settings.DB_NAME, COLUMNS_QUERY),
        fetch(SCRATCH_DB, COLUMNS_QUERY),
    )
    same_cons = diff(
        "外键与唯一约束",
        fetch(settings.DB_NAME, CONSTRAINTS_QUERY),
        fetch(SCRATCH_DB, CONSTRAINTS_QUERY),
    )

    # 4) R3 兜底实测
    r3_ok = test_r3_restrict()

    # 5) 清理临时库
    mysql_cli(f"DROP DATABASE IF EXISTS `{SCRATCH_DB}`", batch=False)
    print(f"\n已清理临时库 {SCRATCH_DB}")

    passed = same_cols and same_cons and r3_ok
    print("\n" + "=" * 78)
    print("校验结果    : " + ("全部通过 ✓" if passed else "存在差异 ✗，请修正后重跑"))
    print("=" * 78)
    return 0 if passed else 1


if __name__ == "__main__":
    with engine.connect() as _c:
        _c.execute(text("SELECT 1"))
    raise SystemExit(main())
