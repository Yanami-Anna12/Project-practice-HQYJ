# -*- coding: utf-8 -*-
"""还原被自检脚本改动的参数值，并打印全部参数。

★ 数据库连接参数从 app.config 读（即 .env），**不在代码里硬编码密码**。
  早先这里写死了明文密码，提交到仓库后造成泄露，已修正。

用法：
    python restore_params.py
"""

from __future__ import annotations

import sys

import pymysql

from app.config import settings

# 自检可能改动的参数及其正确值
RESTORE = {
    "scheduling.solver.timeout_seconds": "30",
    "scheduling.replan.max_count": "3",
    "dispatch.idempotent.key": "task_id+plan_id+trip_id",
}


def main() -> int:
    try:
        conn = pymysql.connect(
            host=settings.DB_HOST,
            port=settings.DB_PORT,
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
            database=settings.DB_NAME,
            charset="utf8mb4",
        )
    except Exception as exc:  # noqa: BLE001
        print(f"数据库连接失败：{exc}")
        print(f"请检查 backend/.env 里的 DB_* 配置（当前 {settings.url_safe()}）")
        return 1

    cur = conn.cursor()
    for key, value in RESTORE.items():
        cur.execute("UPDATE sys_param SET value=%s WHERE `key`=%s", (value, key))
    conn.commit()

    cur.execute("SELECT `key`, value FROM sys_param ORDER BY id")
    print("当前参数：")
    for key, value in cur.fetchall():
        print(f"   {key:<38} = {value}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
