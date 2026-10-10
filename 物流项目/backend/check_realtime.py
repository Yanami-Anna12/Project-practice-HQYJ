# -*- coding: utf-8 -*-
"""实时推送（WebSocket）端到端验证脚本 —— 真跑一遍「下发 → 司机端当场收到」。

用法（后端需已启动）：

    python run.py                  # 另开一个终端先起服务
    python check_realtime.py                       # 默认 http://127.0.0.1:8000
    python check_realtime.py http://127.0.0.1:8001

做四件事：

  1. driver1 ~ driverN 依次登录（顺带验证「每个司机都有登录账号」这条修复：
     修复前只有 driver1/2/3 能登录成功）；
  2. 每个司机连一条 WebSocket：`GET /api/ws/notifications?token=<JWT>`；
  3. 走**真实下发链路**触发一次下发 —— 生成货量 → 建调度任务 → 人工确认
     → `POST /api/scheduling/tasks/{id}/dispatch`（也就是管理员在网页端
     点「下发执行」调的那个接口）；
  4. 打印每个司机**实际收到**的原始报文（JSON）。

★ 为什么走 HTTP 而不是直接写库：下发链路里包含权限校验、审计、
  站内消息生成与推送，直接插 `mobile_notification` 只能验证后半段。
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections import defaultdict
from datetime import date, timedelta

import httpx
from websockets.asyncio.client import connect

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
WS_BASE = BASE.replace("https://", "wss://").replace("http://", "ws://")

# trust_env=False：开着系统代理（Clash 等）的机器上，httpx 会把 127.0.0.1
# 的请求也发给代理，脚本会误报成 502。绕过代理只是本机环境问题，与接口无关。
C = httpx.Client(base_url=BASE, timeout=300.0, trust_env=False)

DRIVERS = [f"driver{i}" for i in range(1, 9)]
PASSWORD = "123456"

# 收到的报文：username -> [payload, ...]
received: dict[str, list[dict]] = defaultdict(list)


def call(method: str, path: str, **kw):
    r = C.request(method, path, **kw)
    try:
        body = r.json()
    except ValueError:
        body = r.text[:400]
    return r.status_code, body


def login(username: str, password: str) -> str:
    code, body = call(
        "POST", "/api/auth/login", json={"username": username, "password": password}
    )
    if code != 200:
        raise RuntimeError(f"登录失败（{username}）：{code} {body}")
    return body["token"]


def trigger_dispatch(day: date) -> tuple[dict, dict, dict]:
    """走真实下发链路，返回 (task, plan, dispatch_result)。"""
    admin = login("admin", "admin123")
    dispatcher = login("dispatcher", PASSWORD)
    ha = {"Authorization": f"Bearer {admin}"}
    hd = {"Authorization": f"Bearer {dispatcher}"}

    code, body = call(
        "POST",
        "/api/demands/generate",
        json={"schedule_date": day.isoformat(), "overwrite": True},
        headers=ha,
    )
    print(f"[触发 1/4] 生成 {day} 门店货量：HTTP {code} {body}")

    code, detail = call(
        "POST",
        "/api/scheduling/tasks",
        json={"schedule_date": day.isoformat(), "time_window": "FULL"},
        headers=hd,
    )
    if code != 200:
        raise RuntimeError(f"建调度任务失败：{code} {detail}")
    task = detail["task"]
    plans = detail.get("plans") or []
    if not plans:
        raise RuntimeError(f"调度没有产出方案：{detail.get('problems')}")
    plan = next((p for p in plans if p.get("is_recommended")), plans[0])
    print(
        f"[触发 2/4] 新建调度任务：{task['code']}（id={task['id']}，状态 {task['status']}），"
        f"选用方案 {plan['plan_code']}（id={plan['id']}）"
    )

    code, body = call(
        "POST",
        f"/api/scheduling/tasks/{task['id']}/confirm",
        json={"plan_id": plan["id"], "approved": True, "remark": "实时推送验证"},
        headers=hd,
    )
    print(f"[触发 3/4] 人工确认方案：HTTP {code} {body}")

    code, result = call(
        "POST",
        f"/api/scheduling/tasks/{task['id']}/dispatch",
        params={"plan_id": plan["id"]},
        headers=hd,
    )
    print(f"[触发 4/4] 下发执行：HTTP {code} {result}")
    if code != 200:
        raise RuntimeError(f"下发失败：{code} {result}")
    return task, plan, result


async def listen(username: str, token: str, ready: asyncio.Event) -> None:
    """一条 WebSocket 连接：打印收到的每一帧。"""
    url = f"{WS_BASE}/api/ws/notifications?token={token}"
    try:
        async with connect(url, open_timeout=10, close_timeout=5) as ws:
            ready.set()
            while True:
                raw = await ws.recv()
                try:
                    payload = json.loads(raw)
                except ValueError:
                    payload = {"raw": raw}
                if payload.get("type") == "ping":
                    await ws.send("pong")
                    continue
                received[username].append(payload)
                print(
                    f"  ← [{username}] {json.dumps(payload, ensure_ascii=False)}",
                    flush=True,
                )
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"  !! [{username}] 连接结束：{type(exc).__name__}: {exc}", flush=True)


async def main() -> int:
    print(f"后端：{BASE}    WebSocket：{WS_BASE}/api/ws/notifications")

    # ---------- 1. 登录 ----------
    tokens: dict[str, str] = {}
    for name in DRIVERS:
        try:
            tokens[name] = login(name, PASSWORD)
        except RuntimeError as exc:
            print(f"  !! {exc}")
    print(f"[1/4] 登录成功 {len(tokens)}/{len(DRIVERS)} 个司机账号：{', '.join(tokens)}")
    if "driver1" not in tokens:
        print("driver1 无法登录，无法继续")
        return 1

    # ---------- 2. 建立连接 ----------
    ready = asyncio.Event()
    tasks = [
        asyncio.create_task(listen(name, token, ready)) for name, token in tokens.items()
    ]
    await asyncio.sleep(2.0)
    print(f"[2/4] 已为 {len(tasks)} 个司机建立 WebSocket 连接，等待下发…")

    # ---------- 3. 真实下发 ----------
    day = date.today()
    try:
        await asyncio.to_thread(trigger_dispatch, day)
    except Exception as exc:  # noqa: BLE001
        print(f"触发下发失败：{exc}")
        for t in tasks:
            t.cancel()
        return 1

    # ---------- 4. 收推送 ----------
    await asyncio.sleep(3.0)
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    pushes = {name: [p for p in frames if p.get("type") == "notification"]
              for name, frames in received.items()}
    total = sum(len(v) for v in pushes.values())
    print(f"[4/4] 收到 notification 推送共 {total} 条，涉及司机："
          f"{', '.join(n for n, v in pushes.items() if v) or '（无）'}")

    d1 = pushes.get("driver1") or []
    print()
    print("=" * 78)
    if d1:
        print("driver1 收到的原始报文：")
        print(json.dumps(d1[0], ensure_ascii=False, indent=2))
    else:
        print("driver1 没有收到推送 —— 需要检查（本次计划的车辆里可能没有 driver1 的车）")
        for name, items in pushes.items():
            if items:
                print(f"{name} 收到的原始报文：")
                print(json.dumps(items[0], ensure_ascii=False, indent=2))
                break
    print("=" * 78)
    return 0 if total else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
