# -*- coding: utf-8 -*-
"""还原被自检脚本改动的参数值，并打印全部参数。"""

import pymysql

RESTORE = {
    "scheduling.solver.timeout_seconds": "30",
    "dispatch.idempotent.key": "task_id+plan_id+trip_id",
}

conn = pymysql.connect(
    host="127.0.0.1", port=3306, user="root", password="52misaka",
    database="logistics_db", charset="utf8mb4",
)
cur = conn.cursor()
for key, value in RESTORE.items():
    cur.execute("UPDATE sys_param SET value=%s WHERE `key`=%s", (value, key))
conn.commit()

cur.execute("SELECT `key`, value FROM sys_param ORDER BY id")
print("当前参数：")
for key, value in cur.fetchall():
    print(f"   {key:<38} = {value}")
conn.close()
