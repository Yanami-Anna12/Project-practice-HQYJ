# -*- coding: utf-8 -*-
"""直接查 MySQL，确认浏览器操作真的落库了（不是内存态）。"""

import sys

import pymysql

conn = pymysql.connect(
    host="127.0.0.1", port=3306, user="root", password="52misaka",
    database="logistics_db", charset="utf8mb4",
)
cur = conn.cursor()

print("--- 1. 参数值（浏览器刚才改成过 999）---")
cur.execute("SELECT `key`, value, updated_at FROM sys_param WHERE `key`=%s",
            ("scheduling.solver.timeout_seconds",))
for row in cur.fetchall():
    print("   ", row)

print("\n--- 2. 最新 8 条审计日志（应含浏览器产生的记录）---")
cur.execute("SELECT id, actor_name, action, target_name, created_at "
            "FROM sys_audit_log ORDER BY id DESC LIMIT 8")
for row in cur.fetchall():
    print("   ", row)

print("\n--- 3. 各表数据量 ---")
tables = [
    ("sys_user", "用户"), ("sys_role", "角色"), ("sys_permission", "权限点"),
    ("sys_dict_type", "字典类型"), ("sys_dict_item", "字典项"), ("sys_param", "参数"),
    ("sys_attachment", "附件"), ("md_store", "门店"), ("md_route", "线路"),
    ("md_store_route", "映射"), ("md_vehicle_type", "车辆类型"), ("md_vehicle", "车辆"),
    ("md_driver", "司机"), ("md_terrain_matrix", "通行矩阵"), ("sys_audit_log", "日志"),
]
for table, label in tables:
    cur.execute(f"SELECT COUNT(*) FROM {table}")
    print(f"    {label:<10} {cur.fetchone()[0]:>4}")

print("\n--- 4. 交界门店（挂 >=2 条线路）---")
cur.execute("""
    SELECT s.code, s.name, COUNT(m.id) AS routes
    FROM md_store s JOIN md_store_route m ON m.store_id = s.id
    GROUP BY s.id HAVING routes >= 2 ORDER BY routes DESC
""")
for row in cur.fetchall():
    print("   ", row)

conn.close()
