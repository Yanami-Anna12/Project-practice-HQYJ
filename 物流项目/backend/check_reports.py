# -*- coding: utf-8 -*-
"""报表接口自检。"""

from __future__ import annotations

import sys

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
PASS, FAIL = [], []


def check(name: str, ok: bool, note: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"{'OK  ' if ok else 'FAIL'} {name}{(' — ' + note) if note else ''}")


c = httpx.Client(base_url=BASE, timeout=60.0)
r = c.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
if r.status_code != 200:
    print("登录失败", r.text)
    sys.exit(1)
auth = {"Authorization": f"Bearer {r.json()['token']}"}

# 1. 日期列表
r = c.get("/api/reports/dates", headers=auth)
dates = r.json() if r.status_code == 200 else []
check("有调度数据的日期列表", r.status_code == 200 and len(dates) > 0, f"{len(dates)} 个日期")
if not dates:
    print("没有调度数据，请先跑 check_scheduling.py")
    sys.exit(1)
D = dates[0]
print(f"使用日期：{D}\n")

# 2. 车辆出勤
r = c.get("/api/reports/attendance", params={"schedule_date": D}, headers=auth)
att = r.json() if r.status_code == 200 else {}
check("车辆出勤报表", r.status_code == 200, f"{r.status_code}")
check("出勤含车型分项", len(att.get("by_type", [])) >= 3, str([t["name"] for t in att.get("by_type", [])]))
check(
    "出勤率口径合理（0~100）",
    all(0 <= t["attendance_rate"] <= 100 or t["attendance_rate"] == 0 for t in att.get("by_type", [])),
    str([t["attendance_rate"] for t in att.get("by_type", [])]),
)
print(f"     可出勤 {att.get('vehicle_available')} / 已使用 {att.get('vehicle_used')} / 已下发趟次 {att.get('dispatched_trips')}")

# 3. 趟次达成
r = c.get("/api/reports/trip-achievement", params={"schedule_date": D}, headers=auth)
trip = r.json() if r.status_code == 200 else {}
check("趟次达成报表", r.status_code == 200)
check("实际趟次 > 0", trip.get("total_trips", 0) > 0, f"实际 {trip.get('total_trips')}")
check("含大包小包保障达成", "small_package" in trip, str(trip.get("small_package")))
print(f"     总趟次 {trip.get('total_trips')} / 计划 {trip.get('planned_trips')} / 达成 {trip.get('achievement_rate')}%")

# 4. 装载率
r = c.get("/api/reports/load-rate", params={"schedule_date": D}, headers=auth)
lr = r.json() if r.status_code == 200 else {}
check("装载率报表", r.status_code == 200)
check("装载率在合理区间", 0 < lr.get("avg_load_rate", 0) <= 100.5, f"{lr.get('avg_load_rate')}%")
check("装载率分布 4 个区间", len(lr.get("buckets", [])) == 4, str([b["count"] for b in lr.get("buckets", [])]))
check("分布总数等于趟次数", sum(b["count"] for b in lr.get("buckets", [])) == lr.get("trip_count"),
      f"分箱 {sum(b['count'] for b in lr.get('buckets', []))} vs 趟次 {lr.get('trip_count')}")
print(f"     平均装载率 {lr.get('avg_load_rate')}%、四米二使用率 {lr.get('four_two_usage')}%、"
      f"区间 {lr.get('min_load_rate')}%~{lr.get('max_load_rate')}%")

# 5. 门店配送达成 + 线路覆盖
r = c.get("/api/reports/store", params={"schedule_date": D}, headers=auth)
st = r.json() if r.status_code == 200 else {}
check("门店配送达成报表", r.status_code == 200)
check("门店数 > 0", st.get("store_count", 0) > 0, f"{st.get('store_count')} 个店")
check("线路覆盖数据存在", len(st.get("routes", [])) >= 5, f"{len(st.get('routes', []))} 条线路")
check("识别交界门店", st.get("intersection_count", 0) >= 1, f"{st.get('intersection_count')} 个")
# 达成率不应超过 100%（配送量不该超过货量）
over = [s for s in st.get("stores", []) if s["achievement_rate"] > 100.01]
check("无超量配送（达成率 <= 100%）", not over, str([(s["store_code"], s["achievement_rate"]) for s in over[:3]]))
print(f"     门店 {st.get('store_count')} 个、完全满足 {st.get('fully_served')} 个"
      f"（{st.get('achievement_rate')}%）、交界门店 {st.get('intersection_count')} 个")
for rt in st.get("routes", [])[:3]:
    print(f"     {rt['route_code']} {rt['route_name']}：覆盖 {rt['covered_count']}/{rt['store_count']}"
          f"（{rt['coverage_rate']}%），配送量 {rt['total_delivered']}")

# 6. 成本与方案对比
r = c.get("/api/reports/cost", params={"schedule_date": D}, headers=auth)
cost = r.json() if r.status_code == 200 else {}
check("成本报表", r.status_code == 200)
check("含方案对比数据", len(cost.get("plans", [])) >= 4, f"{len(cost.get('plans', []))} 套方案")
check("成本按车型拆解", len(cost.get("cost_by_type", [])) >= 1, str([c["code"] for c in cost.get("cost_by_type", [])]))
check("成本占比合计约 100%",
      abs(sum(c["cost_share"] for c in cost.get("cost_by_type", [])) - 100) < 1,
      str([c["cost_share"] for c in cost.get("cost_by_type", [])]))
print(f"     方案 {cost.get('plan_count')} 套、总成本 {cost.get('total_cost')}")

# 7. 汇总
r = c.get("/api/reports/overview", params={"schedule_date": D}, headers=auth)
ov = r.json() if r.status_code == 200 else {}
check("汇总接口一次返回全部报表", r.status_code == 200 and all(
    k in ov for k in ("attendance", "trip", "load_rate", "store", "cost")
), str(list(ov.keys())))

# 8. 权限
r = c.post("/api/auth/login", json={"username": "dispatcher", "password": "123456"})
dauth = {"Authorization": f"Bearer {r.json()['token']}"}
r = c.get("/api/reports/overview", headers=dauth)
check("调度员可看报表（有 reports:view）", r.status_code == 200, f"{r.status_code}")

# 找一个真正没有 reports:view 的账号来验证拒绝路径。
# 实测：admin / dispatcher / dataadmin / viewer / multi 都有 reports:view，
# 所以这里临时把 viewer 的 reports:view 停用，验证完再恢复 ——
# 直接断言「某个账号没有权限」会随 seed 变化而失效，不如显式构造条件。
perm_resp = c.get("/api/permissions", headers=auth)
perms = perm_resp.json() if perm_resp.status_code == 200 else []
rp = next((x for x in perms if x["code"] == "reports:view"), None)
if rp is None:
    check("找到 reports:view 权限点", False, "未找到")
else:
    # 停用权限点
    c.put(f"/api/permissions/{rp['id']}/active", headers=auth)
    r = c.post("/api/auth/login", json={"username": "viewer", "password": "123456"})
    vauth = {"Authorization": f"Bearer {r.json()['token']}"}
    vperms = r.json()["user"]["permissions"]
    check("停用后 viewer 不再有 reports:view", "reports:view" not in vperms, str(vperms))
    r = c.get("/api/reports/overview", headers=vauth)
    check("无 reports:view 的账号被拒 403", r.status_code == 403, f"{r.status_code}")
    # 恢复权限点
    c.put(f"/api/permissions/{rp['id']}/active", headers=auth)
    r = c.post("/api/auth/login", json={"username": "viewer", "password": "123456"})
    vauth = {"Authorization": f"Bearer {r.json()['token']}"}
    r = c.get("/api/reports/overview", headers=vauth)
    check("恢复后 viewer 又可访问 200", r.status_code == 200, f"{r.status_code}")

# 9. 空日期不应崩
r = c.get("/api/reports/overview", params={"schedule_date": "2000-01-01"}, headers=auth)
check("无数据日期不崩溃", r.status_code == 200, f"{r.status_code}")

print()
print("=" * 66)
print(f"结果：{len(PASS)} 通过 / {len(FAIL)} 失败")
for n in FAIL:
    print("  -", n)
print("=" * 66)
sys.exit(1 if FAIL else 0)
