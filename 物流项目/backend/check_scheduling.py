# -*- coding: utf-8 -*-
"""调度全链路自检。

流程：生成货量 → 可行性预检 → 创建调度任务 → 校验方案 → 人工确认
      → 下发（含幂等） → 异常上报 → 重排（含次数上限） → 调度报告

用法：
    python check_scheduling.py
"""

from __future__ import annotations

import sys
from datetime import date, timedelta

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
PASS, FAIL = [], []


def check(name: str, ok: bool, note: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"{'OK  ' if ok else 'FAIL'} {name}{(' — ' + note) if note else ''}")


c = httpx.Client(base_url=BASE, timeout=180.0)

# 货量维护属于基础数据（stores:manage），调度员没有这个权限 —— 这是刻意的角色分离。
# 所以先用管理员准备货量，再用调度员跑调度链路。
r = c.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
if r.status_code != 200:
    print("管理员登录失败", r.text)
    sys.exit(1)
admin_auth = {"Authorization": f"Bearer {r.json()['token']}"}

r = c.post("/api/auth/login", json={"username": "dispatcher", "password": "123456"})
if r.status_code != 200:
    print("调度员登录失败", r.text)
    sys.exit(1)
auth = {"Authorization": f"Bearer {r.json()['token']}"}
print(f"调度员权限：{r.json()['user']['permissions']}\n")

# 用较远的日期，避免与页面演示数据互相干扰
D = str(date.today() + timedelta(days=5))

# ---------- 0. 角色边界：调度员不能维护货量 ----------
r = c.post("/api/demands/generate", json={"schedule_date": D}, headers=auth)
check("调度员维护货量被拒 403（角色分离）", r.status_code == 403, f"{r.status_code}")

# ---------- 1. 准备货量（管理员） ----------
r = c.post(
    "/api/demands/generate",
    json={"schedule_date": D, "overwrite": False},
    headers=admin_auth,
)
check("生成当日货量", r.status_code == 200, r.text[:80] if r.status_code != 200 else f"合计 {r.json().get('total_quantity')}")

# ---------- 2. 可行性预检 ----------
r = c.get("/api/scheduling/feasibility", params={"schedule_date": D}, headers=auth)
fe = r.json() if r.status_code == 200 else {}
check("可行性预检", r.status_code == 200, str(fe)[:120])
check("预检显示可调度", fe.get("ready") is True, f"problems={fe.get('problems')}")
print(f"     门店 {fe.get('store_count')} 个、车辆 {fe.get('vehicle_count')} 台、"
      f"货量 {fe.get('total_demand')}、运力 {fe.get('total_capacity')}")

# ---------- 3. 创建调度任务（含 CP-SAT） ----------
r = c.post(
    "/api/scheduling/tasks",
    json={"schedule_date": D, "time_window": "FULL", "use_cp_sat": True, "timeout_seconds": 15},
    headers=auth,
)
check("创建调度任务", r.status_code == 200, r.text[:200] if r.status_code != 200 else "")
if r.status_code != 200:
    print("\n无法继续，后续检查跳过")
    print(f"\n结果：{len(PASS)} 通过 / {len(FAIL)} 失败")
    sys.exit(1)

detail = r.json()
task = detail["task"]
plans = detail["plans"]
print(f"     任务 {task['code']}，状态 {task['status']}，耗时 {task['duration_ms']}ms，"
      f"方案 {len(plans)} 套")

check("任务状态为待确认", task["status"] == "pending_confirm", task["status"])
check("生成 4 套方案", len(plans) == 4, f"实际 {len(plans)}")
check("有且仅有一个推荐方案", sum(1 for p in plans if p["is_recommended"]) == 1)

# ---------- 4. 方案质量 ----------
print("\n方案对比：")
print(f"  {'编号':<5}{'策略':<22}{'趟次':>6}{'用车':>6}{'四米二':>8}{'装载率':>8}{'评分':>10}")
for p in plans:
    mark = "★" if p["is_recommended"] else " "
    print(f"  {mark}{p['plan_code']:<4}{p['strategy']:<20}{p['trip_count']:>6}"
          f"{p['vehicle_count']:>6}{p['four_two_usage']:>7.1f}%{p['avg_load_rate']:>7.1f}%"
          f"{p['score']:>10.1f}")

check("方案之间有差异", len({(p["trip_count"], p["vehicle_count"]) for p in plans}) >= 2)
check("所有方案都有趟次", all(p["trip_count"] > 0 for p in plans))
check("方案解释非空", all(p["explanation"] for p in plans))

recommended = next(p for p in plans if p["is_recommended"])
print(f"\n     推荐方案 {recommended['plan_code']}：{recommended['strategy']}")
print(f"     解释前两行：{recommended['explanation'].splitlines()[:2]}")

# ---------- 5. 方案明细 ----------
r = c.get(f"/api/scheduling/plans/{recommended['id']}/details", headers=auth)
details = r.json() if r.status_code == 200 else []
check("方案明细可查询", r.status_code == 200 and len(details) > 0, f"{len(details)} 条")
if details:
    d0 = details[0]
    check("明细含车辆与门店信息",
          bool(d0["plate_no"]) and bool(d0["store_code"]),
          f"{d0['plate_no']} → {d0['store_code']} {d0['load_amount']}")
    # 校验：同一 (车,趟) 的装载量之和不超过该车型上限
    by_trip: dict[tuple, float] = {}
    for d in details:
        by_trip.setdefault((d["plate_no"], d["trip_no"]), 0.0)
        by_trip[(d["plate_no"], d["trip_no"])] += d["load_amount"]
    caps = {"4.2m": 800, "big": 420, "small": 300}
    over = [
        (k, v) for k, v in by_trip.items() if v > caps.get(next(x["vehicle_type"] for x in details if x["plate_no"] == k[0]), 9999) + 0.01
    ]
    check("明细中无超载趟次", not over, str(over[:3]))
    check("明细时段合法", all(d["time_window"] in ("AM", "PM") for d in details))

# ---------- 6. 未确认不允许下发 ----------
r = c.post(f"/api/scheduling/tasks/{task['id']}/dispatch",
           params={"plan_id": recommended["id"]}, headers=auth)
check("未确认时下发被拒（409）", r.status_code == 409, f"{r.status_code} {r.text[:60]}")

# ---------- 7. 人工确认 ----------
r = c.post(
    f"/api/scheduling/tasks/{task['id']}/confirm",
    json={"plan_id": recommended["id"], "approved": True, "remark": "自检确认"},
    headers=auth,
)
check("人工确认成功", r.status_code == 200, r.text[:80] if r.status_code != 200 else r.json().get("message", ""))

# ---------- 8. 下发 ----------
r = c.post(f"/api/scheduling/tasks/{task['id']}/dispatch",
           params={"plan_id": recommended["id"]}, headers=auth)
dis = r.json() if r.status_code == 200 else {}
check("下发成功", r.status_code == 200 and dis.get("dispatched_trips", 0) > 0,
      f"{r.status_code} {str(dis)[:100]}")
first_dispatched = dis.get("dispatched_trips", 0)

# ---------- 9. 幂等：重复下发不产生重复 ----------
r = c.post(f"/api/scheduling/tasks/{task['id']}/dispatch",
           params={"plan_id": recommended["id"]}, headers=auth)
again = r.json() if r.status_code == 200 else {}
check("重复下发被幂等拦截",
      again.get("dispatched_trips") == 0 and again.get("skipped_duplicated") == first_dispatched,
      f"新增 {again.get('dispatched_trips')}、跳过 {again.get('skipped_duplicated')}（首次 {first_dispatched}）")

# ---------- 10. 异常上报 ----------
r = c.post(
    "/api/scheduling/exceptions",
    json={"task_id": task["id"], "event_type": "vehicle_breakdown", "source": "自检",
          "payload": {"vehicle": "沪A1001", "reason": "发动机故障"}},
    headers=auth,
)
event = r.json() if r.status_code == 200 else {}
check("异常上报成功", r.status_code == 200, f"{r.status_code} {r.text[:60]}")
event_id = event.get("id")

r = c.get("/api/scheduling/exceptions", params={"task_id": task["id"]}, headers=auth)
check("异常列表可查", r.status_code == 200 and len(r.json()) >= 1)

# ---------- 11. 重排与次数上限 ----------
r = c.post(f"/api/scheduling/tasks/{task['id']}/replan",
           params={"event_id": event_id, "scope": "local"}, headers=auth)
replan = r.json() if r.status_code == 200 else {}
check("异常重排成功", r.status_code == 200, str(replan)[:100])

# 连跑到上限（默认上限 3）
max_replan = 3
for i in range(max_replan):
    r = c.post(f"/api/scheduling/tasks/{task['id']}/replan",
               params={"scope": "local"}, headers=auth)
    if r.status_code == 409:
        break
check("重排次数达上限后被拒（409）", r.status_code == 409,
      f"{r.status_code} {r.text[:80]}")

# ---------- 12. 调度报告 ----------
r = c.get(f"/api/scheduling/tasks/{task['id']}/report", headers=auth)
report = r.json() if r.status_code == 200 else {}
check("调度报告可获取", r.status_code == 200 and bool(report.get("content")), f"{r.status_code}")
if report.get("content"):
    lines = report["content"].splitlines()
    check("报告含方案对比表", any("方案对比" in ln for ln in lines))
    check("报告含推荐方案说明", any("推荐方案" in ln for ln in lines))
    print(f"     报告 {len(report['content'])} 字符，{len(lines)} 行")

# ---------- 13. 任务列表 ----------
r = c.get("/api/scheduling/tasks", headers=auth)
check("任务列表可查", r.status_code == 200 and len(r.json()) >= 1, f"{len(r.json()) if r.status_code==200 else 0} 条")

# ---------- 14. 权限：只读账号不能调度 ----------
r = c.post("/api/auth/login", json={"username": "viewer", "password": "123456"})
vauth = {"Authorization": f"Bearer {r.json()['token']}"}
r = c.get("/api/scheduling/tasks", headers=vauth)
check("viewer 可读任务", r.status_code == 200, f"{r.status_code}")
r = c.post("/api/scheduling/tasks", json={"schedule_date": D}, headers=vauth)
check("viewer 创建任务被拒 403", r.status_code == 403, f"{r.status_code}")

# ---------- 15. 审计（用管理员查：调度员没有 logs:read 权限） ----------
r = c.get("/api/audit-logs", params={"limit": 100}, headers=auth)
check("调度员读审计日志被拒 403（无 logs:read）", r.status_code == 403, f"{r.status_code}")

r = c.get("/api/audit-logs", params={"limit": 100}, headers=admin_auth)
actions = {x["action"] for x in r.json()} if r.status_code == 200 else set()
check("管理员可读审计日志", r.status_code == 200, f"{r.status_code}")
for act in ("scheduling.create", "scheduling.confirm", "scheduling.dispatch", "scheduling.exception"):
    check(f"审计含 {act}", act in actions, str(sorted(a for a in actions if a.startswith("scheduling"))))

print()
print("=" * 70)
print(f"结果：{len(PASS)} 通过 / {len(FAIL)} 失败")
for n in FAIL:
    print("  -", n)
print("=" * 70)
sys.exit(1 if FAIL else 0)
