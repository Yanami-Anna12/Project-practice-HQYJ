# -*- coding: utf-8 -*-
"""货量接口自检：生成演示货量 → 查询 → 汇总 → 修改 → 校验。"""

from __future__ import annotations

import sys
from datetime import date, timedelta

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
PASS, FAIL = [], []


def check(name: str, ok: bool, note: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"{'OK  ' if ok else 'FAIL'} {name}{(' — ' + note) if note else ''}")


c = httpx.Client(base_url=BASE, timeout=30.0)

r = c.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
if r.status_code != 200:
    print("登录失败，后端是否已启动？", r.text)
    sys.exit(1)
auth = {"Authorization": f"Bearer {r.json()['token']}"}

D = str(date.today() + timedelta(days=1))  # 用明天的日期，避免污染当天数据

# ★ 这个脚本必须可重复执行。第一次跑时 D 是空的、第二次跑时已有数据，
#   所以「初始为空」这一项不能直接断言 —— 先清掉该日期的数据再验证。
r = c.get("/api/demands", params={"schedule_date": D}, headers=auth)
existing = r.json() if r.status_code == 200 else []
for row in existing:
    c.delete(f"/api/demands/{row['id']}", headers=auth)

# 1. 清理后应为空
r = c.get("/api/demands", params={"schedule_date": D}, headers=auth)
check(
    "清理后货量为空（保证脚本可重复执行）",
    r.status_code == 200 and r.json() == [],
    f"{r.status_code} len={len(r.json()) if r.status_code == 200 else '-'}",
)

# 2. 生成演示货量
r = c.post("/api/demands/generate", json={"schedule_date": D, "overwrite": False}, headers=auth)
check("生成演示货量", r.status_code == 200, r.text[:80] if r.status_code != 200 else "")
gen = r.json() if r.status_code == 200 else {}
check("生成覆盖 16 个门店", gen.get("stores") == 16, f"stores={gen.get('stores')}")
check("货量合计 > 0", (gen.get("total_quantity") or 0) > 0, f"合计={gen.get('total_quantity')}")

# 3. 重复生成应幂等（不覆盖）
r = c.post("/api/demands/generate", json={"schedule_date": D, "overwrite": False}, headers=auth)
again = r.json()
check("重复生成幂等（全部跳过）", again.get("skipped") == 16 and again.get("created") == 0, str(again))

# 4. 列表
r = c.get("/api/demands", params={"schedule_date": D}, headers=auth)
rows = r.json() if r.status_code == 200 else []
check("货量列表 16 条", len(rows) == 16, f"实际 {len(rows)}")
if rows:
    sample = rows[0]
    check("列表含门店信息", bool(sample["store_code"]) and bool(sample["store_name"]), str(sample.get("store_code")))
    check("列表含线路信息", isinstance(sample["route_codes"], list), str(sample.get("route_codes")))
    check("列表含最少趟次估算", sample["min_trips_4_2m"] >= 0, f"min_trips={sample['min_trips_4_2m']}")

    # 5. 手改一条
    r = c.put(
        "/api/demands",
        json={"schedule_date": D, "store_id": sample["store_id"], "quantity": 1500, "remark": "自检修改"},
        headers=auth,
    )
    check("手工修改货量", r.status_code == 200 and float(r.json()["quantity"]) == 1500, r.text[:80] if r.status_code != 200 else "")

    # 6. 超量应被拒
    r = c.put(
        "/api/demands",
        json={"schedule_date": D, "store_id": sample["store_id"], "quantity": -5},
        headers=auth,
    )
    check("负数货量被拒（422）", r.status_code == 422, f"实际 {r.status_code}")

# 7. 汇总
r = c.get("/api/demands/summary", params={"schedule_date": D}, headers=auth)
s = r.json() if r.status_code == 200 else {}
check("货量汇总", s.get("store_count") == 16, str(s))
check("汇总区分上午/下午门店", (s.get("am_stores", 0) + s.get("pm_stores", 0)) == 16, f"AM={s.get('am_stores')} PM={s.get('pm_stores')}")

# 8. 无权限账号
r = c.post("/api/auth/login", json={"username": "viewer", "password": "123456"})
vauth = {"Authorization": f"Bearer {r.json()['token']}"}
r = c.get("/api/demands", params={"schedule_date": D}, headers=vauth)
check("viewer 可读货量", r.status_code == 200, f"实际 {r.status_code}")
r = c.post("/api/demands/generate", json={"schedule_date": D}, headers=vauth)
check("viewer 生成货量被拒 403", r.status_code == 403, f"实际 {r.status_code}")

# 9. 审计日志
r = c.get("/api/audit-logs", params={"limit": 50}, headers=auth)
actions = {x["action"] for x in r.json()} if r.status_code == 200 else set()
check("审计含 demand.generate", "demand.generate" in actions, str(sorted(a for a in actions if "demand" in a)))

print()
print("=" * 56)
print(f"结果：{len(PASS)} 通过 / {len(FAIL)} 失败")
for n in FAIL:
    print("  -", n)
print("=" * 56)
sys.exit(1 if FAIL else 0)
