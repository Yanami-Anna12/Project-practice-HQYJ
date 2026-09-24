# -*- coding: utf-8 -*-
"""直接查库，确认浏览器操作真的落库了（不是内存态）。

★ 数据库连接参数从 app.config 读（即 .env），**不在代码里硬编码密码**。
  早先这里写死了明文密码，提交到仓库后造成泄露，已修正。

用法：
    python check_db.py
"""

from __future__ import annotations

import sys

import pymysql

from app.config import settings


def connect():
    return pymysql.connect(
        host=settings.DB_HOST,
        port=settings.DB_PORT,
        user=settings.DB_USER,
        password=settings.DB_PASSWORD,
        database=settings.DB_NAME,
        charset="utf8mb4",
    )


def main() -> int:
    try:
        conn = connect()
    except Exception as exc:  # noqa: BLE001
        print(f"数据库连接失败：{exc}")
        print(f"请检查 backend/.env 里的 DB_* 配置（当前 {settings.url_safe()}）")
        return 1

    cur = conn.cursor()

    print("--- 1. 参数值 ---")
    cur.execute(
        "SELECT `key`, value, updated_at FROM sys_param WHERE `key`=%s",
        ("scheduling.solver.timeout_seconds",),
    )
    for row in cur.fetchall():
        print("   ", row)

    print("\n--- 2. 最新 8 条审计日志 ---")
    cur.execute(
        "SELECT id, actor_name, action, target_name, created_at "
        "FROM sys_audit_log ORDER BY id DESC LIMIT 8"
    )
    for row in cur.fetchall():
        print("   ", row)

    print("\n--- 3. 各表数据量 ---")
    tables = [
        ("sys_user", "用户"),
        ("sys_role", "角色"),
        ("sys_permission", "权限点"),
        ("sys_dict_type", "字典类型"),
        ("sys_dict_item", "字典项"),
        ("sys_param", "参数"),
        ("sys_attachment", "附件"),
        ("md_store", "门店"),
        ("md_route", "线路"),
        ("md_store_route", "映射"),
        ("md_vehicle_type", "车辆类型"),
        ("md_vehicle", "车辆"),
        ("md_driver", "司机"),
        ("md_store_demand", "货量"),
        ("md_terrain_matrix", "通行矩阵"),
        ("scheduling_task", "调度任务"),
        ("scheduling_plan", "调度方案"),
        ("dispatch_record", "下发记录"),
        ("exception_event", "异常事件"),
        ("sys_rule_version", "规则版本"),
        ("sys_audit_log", "审计日志"),
    ]
    for table, label in tables:
        try:
            cur.execute(f"SELECT COUNT(*) FROM {table}")
            print(f"    {label:<10} {cur.fetchone()[0]:>5}")
        except Exception:  # noqa: BLE001
            print(f"    {label:<10}   (表不存在)")

    print("\n--- 4. 交界门店（挂 >=2 条线路）---")
    cur.execute(
        """
        SELECT s.code, s.name, COUNT(m.id) AS routes
        FROM md_store s JOIN md_store_route m ON m.store_id = s.id
        GROUP BY s.id HAVING routes >= 2 ORDER BY routes DESC
        """
    )
    for row in cur.fetchall():
        print("   ", row)

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
