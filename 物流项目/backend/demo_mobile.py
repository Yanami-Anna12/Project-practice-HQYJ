# -*- coding: utf-8 -*-
"""司机端（小程序）演示数据脚本 —— 跑一次，司机端接口就有真实数据。

背景：`seed.py` 只载入主数据（含司机账号与门店坐标）。而 `GET /api/mobile/my-trips`
要求「车辆在**已下发**的方案里有趟次」，所以还需要走一遍
「货量 → 调度 → 人工确认 → 下发」，本脚本就是把这一步自动化。

用法（后端需已启动）：

    python run.py                 # 另开一个终端先起服务
    python demo_mobile.py         # 默认 http://127.0.0.1:8000
    python demo_mobile.py http://127.0.0.1:8001

幂等：同一天重复执行不会重复建任务 —— 发现当天已有「已下发」的任务就直接复用。

★ 为什么走 HTTP 而不是直接写库：这是产品里真实的下发链路（含权限校验、
  审计、站内消息生成）。用接口造数据，等于顺带验证了这条链路是通的。
"""

from __future__ import annotations

import sys
from datetime import date

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
TODAY = date.today().isoformat()

# trust_env=False：开着系统代理（Clash 等）的机器上，httpx 会把 127.0.0.1
# 的请求也发给代理，脚本会误报成 502。绕过代理只是本机环境问题，与接口无关。
C = httpx.Client(base_url=BASE, timeout=180.0, trust_env=False)


def call(method: str, path: str, **kw):
    r = C.request(method, path, **kw)
    try:
        body = r.json()
    except ValueError:
        body = r.text[:300]
    return r.status_code, body


def login(username: str, password: str) -> dict:
    code, body = call("POST", "/api/auth/login", json={"username": username, "password": password})
    if code != 200:
        print(f"登录失败（{username}）：{code} {body}")
        print("后端是否已启动？是否已执行 python seed.py？")
        sys.exit(1)
    return {"Authorization": f"Bearer {body['token']}"}


def main() -> int:
    admin = login("admin", "admin123")
    dispatcher = login("dispatcher", "123456")

    # ---------- 1. 货量（调度的输入）----------
    code, body = call(
        "POST", "/api/demands/generate",
        json={"schedule_date": TODAY, "overwrite": True}, headers=admin,
    )
    print(f"[1/4] 生成演示货量：{code} {body}")

    # ---------- 2. 复用或创建调度任务 ----------
    task = None
    plan = None
    code, tasks = call("GET", "/api/scheduling/tasks", headers=dispatcher)
    for candidate in tasks or []:
        if candidate["schedule_date"] == TODAY and candidate["status"] in (
            "dispatched", "completed"
        ):
            task = candidate
            break

    if task is not None:
        # 当天已有已下发任务：直接复用（避免重复造数据）
        code, detail = call("GET", f"/api/scheduling/tasks/{task['id']}", headers=dispatcher)
        recommended = [p for p in detail.get("plans", []) if p["is_recommended"]]
        plan = recommended[0] if recommended else (detail.get("plans") or [None])[0]
        print(f"[2/4] 复用当天已下发任务：{task['code']}（方案 {plan['plan_code'] if plan else '—'}）")
    else:
        code, body = call(
            "POST", "/api/scheduling/tasks",
            json={"schedule_date": TODAY, "time_window": "FULL",
                  "use_cp_sat": True, "timeout_seconds": 5},
            headers=dispatcher,
        )
        if code != 200:
            print(f"[2/4] 创建调度任务失败：{code} {body}")
            return 1
        task = body["task"]
        plans = body["plans"]
        plan = next((p for p in plans if p["is_recommended"]), plans[0])
        print(f"[2/4] 创建调度任务：{task['code']} → 推荐方案 {plan['plan_code']} "
              f"（{plan['trip_count']} 趟 / {plan['vehicle_count']} 车）")

        # ---------- 3. 人工确认 + 下发 ----------
        code, body = call(
            "POST", f"/api/scheduling/tasks/{task['id']}/confirm",
            json={"plan_id": plan["id"], "approved": True, "remark": "演示数据"}, headers=dispatcher,
        )
        print(f"      人工确认：{code} {body.get('message') if isinstance(body, dict) else body}")
        code, body = call(
            "POST", f"/api/scheduling/tasks/{task['id']}/dispatch",
            params={"plan_id": plan["id"]}, headers=dispatcher,
        )
        print(f"      下发：{code} {body.get('message') if isinstance(body, dict) else body}")

    # ---------- 4. 打印司机端可用数据 ----------
    print("[3/4] 司机端账号与趟次：")
    for index in (1, 2, 3):
        username = f"driver{index}"
        headers = login(username, "123456")
        code, profile = call("GET", "/api/mobile/profile", headers=headers)
        code, trips = call(
            "GET", "/api/mobile/my-trips",
            params={"schedule_date": TODAY}, headers=headers,
        )
        plates = "、".join(v["plate_no"] for v in profile.get("vehicles", []))
        print(f"      {username} / 123456  →  {profile.get('driver_name')}"
              f"（{profile.get('shift')}）名下车辆：{plates}")
        for trip in (trips or [])[:3]:
            print(f"         趟次 {trip['trip_key']}  {trip['plate_no']}  "
                  f"{trip['time_window']}  第 {trip['trip_no']} 趟  "
                  f"{trip['store_count']} 店 / {trip['total_load']} 件  {trip['trip_status']}")
        if not trips:
            print("         （无趟次：该司机名下车辆未参与本次下发）")

    code, notes = call("GET", "/api/mobile/notifications", headers=login("driver1", "123456"))
    code, unread = call(
        "GET", "/api/mobile/notifications/unread-count", headers=login("driver1", "123456")
    )
    print(f"[4/4] driver1 站内消息 {len(notes or [])} 条，未读 {unread}")
    print()
    print(f"接口文档：{BASE}/docs  →  「司机端」分组")
    print("登录：POST /api/auth/login  {\"username\": \"driver1\", \"password\": \"123456\"}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
