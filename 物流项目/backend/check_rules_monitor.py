# -*- coding: utf-8 -*-
"""规则配置与监控接口自检。"""

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
auth = {"Authorization": f"Bearer {r.json()['token']}"}

# ===================== 规则配置 =====================
r = c.get("/api/rules/overview", headers=auth)
ov = r.json() if r.status_code == 200 else {}
check("规则总览", r.status_code == 200, f"{r.status_code}")
check("含车辆类型规则", len(ov.get("vehicle_types", [])) >= 3, str([v["name"] for v in ov.get("vehicle_types", [])]))
check("含地形通行矩阵", len(ov.get("terrain_matrix", [])) == 9, f"{len(ov.get('terrain_matrix', []))} 格")
check("含参数列表", len(ov.get("params", [])) >= 8, f"{len(ov.get('params', []))} 个")
check("列出 7 条硬约束", len(ov.get("hard_constraints", [])) == 7, f"{len(ov.get('hard_constraints', []))} 条")
check("列出软约束", len(ov.get("soft_constraints", [])) >= 3, f"{len(ov.get('soft_constraints', []))} 条")
check("含评分公式说明", "formula" in ov.get("score_function", {}), ov.get("score_function", {}).get("formula", "")[:60])
check("含线路策略数据", len(ov.get("route_strategy", [])) >= 19, f"{len(ov.get('route_strategy', []))} 条")

# 冲突检测
r = c.get("/api/rules/conflicts", headers=auth)
conflicts = r.json() if r.status_code == 200 else []
check("规则冲突检测", r.status_code == 200, f"{len(conflicts)} 项")
errors = [x for x in conflicts if x["level"] == "error"]
check("当前无 error 级冲突", not errors, str([e["message"][:50] for e in errors]))
levels = {x["level"] for x in conflicts}
print(f"     冲突项级别分布：{levels or '无'}，共 {len(conflicts)} 项")

# ===================== 规则版本 =====================
r = c.get("/api/rules/versions", headers=auth)
initial = r.json() if r.status_code == 200 else []
check("版本列表可查", r.status_code == 200, f"初始 {len(initial)} 个版本")

# 发布第一版
r = c.post("/api/rules/versions", json={"description": "自检初始版本"}, headers=auth)
v1 = r.json() if r.status_code == 200 else {}
check("发布第一个版本", r.status_code == 200, str(v1)[:100])
first_version = v1.get("version")
print(f"     版本号 {first_version}，变更 {v1.get('change_count', 0)} 项")

# 改一个参数，再发布 → 应检出变更
r = c.get("/api/params", headers=auth)
params = r.json()
timeout_param = next((p for p in params if p["key"] == "scheduling.solver.timeout_seconds"), None)
old_value = timeout_param["value"]
new_value = "45" if old_value != "45" else "30"
c.put(f"/api/params/{timeout_param['id']}", json={"value": new_value}, headers=auth)

r = c.post("/api/rules/versions", json={"description": "自检：改求解超时"}, headers=auth)
v2 = r.json() if r.status_code == 200 else {}
check("发布第二个版本", r.status_code == 200)
check("检出参数变更", v2.get("change_count", 0) >= 1, f"变更 {v2.get('change_count')} 项")
changes = v2.get("changes", [])
param_change = [ch for ch in changes if "timeout_seconds" in ch["target"]]
check(
    "变更内容包含超时参数的新旧值",
    bool(param_change) and param_change[0]["before"] == old_value and param_change[0]["after"] == new_value,
    str(param_change[:1]),
)

# 版本详情含快照
r = c.get(f"/api/rules/versions/{v1['id']}", headers=auth)
detail = r.json() if r.status_code == 200 else {}
check("版本详情含快照", "vehicle_types" in detail.get("snapshot", {}), str(list(detail.get("snapshot", {}).keys())))

# 重复版本号应被拒
r = c.post("/api/rules/versions", json={"version": first_version}, headers=auth)
check("重复版本号被拒", r.status_code == 400, f"{r.status_code} {r.text[:60]}")

# 回滚到第一版
r = c.post(f"/api/rules/versions/{v1['id']}/rollback", headers=auth)
rb = r.json() if r.status_code == 200 else {}
check("回滚成功", r.status_code == 200, str(rb.get("message", ""))[:100])
check("回滚恢复了参数", rb.get("restored", {}).get("params", 0) >= 1, str(rb.get("restored")))
check("回滚产生新版本（保留痕迹）", bool(rb.get("new_version")), rb.get("new_version", ""))

# 确认参数真的回滚了
r = c.get("/api/params", headers=auth)
after = next((p for p in r.json() if p["key"] == "scheduling.solver.timeout_seconds"), None)
check("参数值已还原", after and after["value"] == old_value, f"{after['value']} (期望 {old_value})")

# ===================== 监控 =====================
r = c.get("/api/monitor/system", headers=auth)
sysd = r.json() if r.status_code == 200 else {}
check("系统监控指标", r.status_code == 200, f"{r.status_code}")
check("数据库连通性实测", sysd.get("database", {}).get("available") is True, sysd.get("database", {}).get("version", "")[:40])
check("表规模统计", len(sysd.get("tables", {})) >= 8, str(list(sysd.get("tables", {}).keys())))
check("调度健康度", "success_rate" in sysd.get("scheduling", {}), str(sysd.get("scheduling")))
check(
    "明确标注未采集的外部指标（不编造）",
    len(sysd.get("external_metrics", [])) >= 3
    and all(not m["available"] for m in sysd["external_metrics"]),
    str([m["name"] for m in sysd.get("external_metrics", [])]),
)
print(f"     任务 {sysd['scheduling']['total_tasks']} 个，成功率 {sysd['scheduling']['success_rate']}%，"
      f"平均耗时 {sysd['scheduling']['avg_duration_ms']}ms")
print(f"     确认 {sysd['confirmation']['total']} 次，拒绝率 {sysd['confirmation']['reject_rate']}%；"
      f"异常 {sysd['exception']['total']} 起（未处理 {sysd['exception']['pending']}）")

r = c.get("/api/monitor/alerts", headers=auth)
alerts = r.json() if r.status_code == 200 else []
check("预警清单", r.status_code == 200, f"{len(alerts)} 条")
for a in alerts[:5]:
    print(f"     [{a['level']}] {a['type']}：{a['message'][:60]}")

r = c.get("/api/monitor/dashboard", headers=auth)
dash = r.json() if r.status_code == 200 else {}
check("监控总览", r.status_code == 200 and "trend" in dash, f"趋势 {len(dash.get('trend', []))} 天")

r = c.get("/api/monitor/integrations", headers=auth)
integrations = r.json() if r.status_code == 200 else []
check("集成配置清单", r.status_code == 200 and len(integrations) >= 6, f"{len(integrations)} 项")
check(
    "集成项如实标注未连通",
    all(i["status"] in ("partial", "not_connected") for i in integrations),
    str({i["name"]: i["status"] for i in integrations}),
)
tms = next((i for i in integrations if i["name"] == "TMS"), None)
check("TMS 有本地落地证据", bool(tms and tms.get("local_evidence")), tms.get("local_evidence", "") if tms else "")

r = c.get("/api/monitor/data-platform", headers=auth)
dp = r.json() if r.status_code == 200 else {}
check("数据与算法平台", r.status_code == 200 and "implemented" in dp, f"已实现 {len(dp.get('implemented', []))} 项、规划 {len(dp.get('planned', []))} 项")
check("含数据规模统计", len(dp.get("data_scale", {})) >= 6, str(dp.get("data_scale")))

# ===================== 权限 =====================
r = c.post("/api/auth/login", json={"username": "dispatcher", "password": "123456"})
dauth = {"Authorization": f"Bearer {r.json()['token']}"}
r = c.get("/api/rules/overview", headers=dauth)
check("调度员可读规则（scheduling:read）", r.status_code == 200, f"{r.status_code}")
r = c.get("/api/monitor/system", headers=dauth)
check("调度员无 monitor:read 被拒 403", r.status_code == 403, f"{r.status_code}")

r = c.post("/api/auth/login", json={"username": "viewer", "password": "123456"})
vauth = {"Authorization": f"Bearer {r.json()['token']}"}
r = c.get("/api/monitor/system", headers=vauth)
check("viewer 无 monitor:read 被拒 403", r.status_code == 403, f"{r.status_code}")
r = c.post("/api/rules/versions", json={}, headers=vauth)
check("viewer 发布规则版本被拒 403", r.status_code == 403, f"{r.status_code}")

print()
print("=" * 68)
print(f"结果：{len(PASS)} 通过 / {len(FAIL)} 失败")
for n in FAIL:
    print("  -", n)
print("=" * 68)
sys.exit(1 if FAIL else 0)
