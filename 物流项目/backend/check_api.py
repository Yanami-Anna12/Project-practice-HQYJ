# -*- coding: utf-8 -*-
"""接口自检脚本。

覆盖：健康检查、登录、菜单裁剪、系统管理 CRUD、基础数据、权限拦截、审计日志。

用法：
    python check_api.py                 # 默认 http://127.0.0.1:8000
    python check_api.py --base http://127.0.0.1:8001
"""

from __future__ import annotations

import argparse
import sys

import httpx

PASS, FAIL = [], []


def check(name: str, ok: bool, note: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"{'OK  ' if ok else 'FAIL'} {name}{(' — ' + note) if note else ''}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    args = ap.parse_args()
    base = args.base.rstrip("/")

    c = httpx.Client(base_url=base, timeout=20.0)

    # ---------- 1. 健康检查 ----------
    r = c.get("/api/health")
    check("健康检查", r.status_code == 200, r.json().get("status") if r.status_code == 200 else r.text)

    # ---------- 2. 未登录访问受保护接口应 401 ----------
    r = c.get("/api/users")
    check("未登录访问 /api/users 返回 401", r.status_code == 401, f"实际 {r.status_code}")

    # ---------- 3. 错误密码 ----------
    r = c.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    check("错误密码返回 401", r.status_code == 401, r.json().get("error", ""))

    # ---------- 4. 停用账号登录被拒 ----------
    r = c.post("/api/auth/login", json={"username": "disabled", "password": "123456"})
    check("停用账号登录被拒", r.status_code == 401, r.json().get("error", ""))

    # ---------- 5. 管理员登录 ----------
    r = c.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    check("管理员登录", r.status_code == 200, f"HTTP {r.status_code}")
    if r.status_code != 200:
        return 1
    token = r.json()["token"]
    admin_perms = r.json()["user"]["permissions"]
    check("管理员权限数 = 29", len(admin_perms) == 29, f"实际 {len(admin_perms)}")

    auth = {"Authorization": f"Bearer {token}"}

    # ---------- 6. 菜单裁剪 ----------
    r = c.get("/api/me/menus", headers=auth)
    keys = [m["key"] for m in r.json()] if r.status_code == 200 else []
    check("管理员菜单含「系统管理」", "system" in keys, str(keys))
    check("管理员菜单含「智能调度 Agent」", "scheduling" in keys)

    # ---------- 7. 系统管理：用户 ----------
    r = c.get("/api/users", headers=auth)
    users = r.json() if r.status_code == 200 else []
    check("用户列表 6 条", len(users) == 6, f"实际 {len(users)}")
    multi = next((u for u in users if u["username"] == "multi"), None)
    # multi 绑定 dispatcher(9 个权限) + viewer(5 个)，而 viewer 的权限是 dispatcher 的子集，
    # 所以并集仍是 9 —— 这正是「并集」的含义：不会因为多绑一个角色就凭空多出权限。
    check(
        "multi 用户权限并集 = 9（viewer 是 dispatcher 子集）",
        bool(multi) and len(multi["permissions"]) == 9,
        f"实际 {len(multi['permissions']) if multi else 'N/A'}",
    )
    dispatcher_user = next((u for u in users if u["username"] == "dispatcher"), None)
    check(
        "multi 与 dispatcher 权限相同（并集验证）",
        bool(multi and dispatcher_user)
        and multi["permissions"] == dispatcher_user["permissions"],
    )

    # ---------- 8. 角色删除保护 ----------
    r = c.get("/api/roles", headers=auth)
    roles = r.json() if r.status_code == 200 else []
    admin_role = next((x for x in roles if x["code"] == "admin"), None)
    check("admin 角色绑定用户数 = 1", bool(admin_role) and admin_role["user_count"] == 1)
    if admin_role:
        r = c.delete(f"/api/roles/{admin_role['id']}", headers=auth)
        check("删除被引用的角色返回 409", r.status_code == 409, r.json().get("error", "")[:60])

    # ---------- 9. 权限点停用影响 ----------
    r = c.get("/api/permissions", headers=auth)
    perms = r.json() if r.status_code == 200 else []
    check("权限点 29 个", len(perms) == 29, f"实际 {len(perms)}")

    # ---------- 10. 字典 ----------
    r = c.get("/api/dicts/types", headers=auth)
    types = r.json() if r.status_code == 200 else []
    check("字典类型 7 个", len(types) == 7, f"实际 {len(types)}")
    r = c.get("/api/dicts/types/vehicle_type/items", headers=auth)
    items = r.json() if r.status_code == 200 else []
    check("车辆类型字典项 3 条", len(items) == 3, f"实际 {len(items)}")

    # ---------- 11. 参数修改 + 类型校验 ----------
    r = c.get("/api/params", headers=auth)
    params = r.json() if r.status_code == 200 else []
    check("参数 8 个", len(params) == 8, f"实际 {len(params)}")
    timeout_param = next((p for p in params if p["key"] == "scheduling.solver.timeout_seconds"), None)
    if timeout_param:
        r = c.put(f"/api/params/{timeout_param['id']}", json={"value": "abc"}, headers=auth)
        check("整数参数写入非数字被拒", r.status_code == 400, r.json().get("error", "")[:50])
        r = c.put(f"/api/params/{timeout_param['id']}", json={"value": "60"}, headers=auth)
        check("参数正常修改", r.status_code == 200 and r.json()["value"] == "60")
        c.put(f"/api/params/{timeout_param['id']}", json={"value": "30"}, headers=auth)

    # ---------- 12. 基础数据 ----------
    r = c.get("/api/stores", headers=auth)
    stores = r.json() if r.status_code == 200 else []
    check("门店 16 个", len(stores) == 16, f"实际 {len(stores)}")
    intersections = [s for s in stores if s["is_intersection"]]
    check("识别出交界门店（挂 >=2 线路）", len(intersections) == 3, f"实际 {len(intersections)}：{[s['code'] for s in intersections]}")

    r = c.get("/api/vehicles", headers=auth)
    vehicles = r.json() if r.status_code == 200 else []
    check("车辆 40 台", len(vehicles) == 40, f"实际 {len(vehicles)}")
    by_type: dict[str, int] = {}
    for v in vehicles:
        by_type[v["vehicle_type_code"]] = by_type.get(v["vehicle_type_code"], 0) + 1
    check(
        "车辆分布 28/3/9",
        by_type.get("4.2m") == 28 and by_type.get("big") == 3 and by_type.get("small") == 9,
        str(by_type),
    )

    r = c.get("/api/vehicle-types", headers=auth)
    vts = r.json() if r.status_code == 200 else []
    vt42 = next((t for t in vts if t["code"] == "4.2m"), None)
    check(
        "四米二规则 630-800 日 2 趟",
        bool(vt42) and vt42["min_load"] == 630 and vt42["max_load"] == 800 and vt42["trips_per_day"] == 2,
        f"{vt42['min_load']}-{vt42['max_load']}/{vt42['trips_per_day']}趟" if vt42 else "",
    )
    if vt42:
        r = c.put(
            f"/api/vehicle-types/{vt42['id']}",
            json={"am_trips": 2, "pm_trips": 2, "trips_per_day": 2},
            headers=auth,
        )
        check("趟次不一致被拒（上午+下午 != 每日）", r.status_code == 400, r.json().get("error", "")[:60])

    r = c.get("/api/terrain-matrix", headers=auth)
    matrix = r.json() if r.status_code == 200 else []
    check("地形通行矩阵 9 格", len(matrix) == 9, f"实际 {len(matrix)}")
    strict_small = next(
        (m for m in matrix if m["terrain_type"] == "strict" and m["capability"] == "small_only"), None
    )
    check("严控地形禁止小包能去", bool(strict_small) and strict_small["allowed"] is False)

    r = c.get("/api/mappings", headers=auth)
    mappings = r.json() if r.status_code == 200 else []
    check("门店线路映射 19 条", len(mappings) == 19, f"实际 {len(mappings)}")

    # ---------- 13. 审计日志只追加 ----------
    r = c.get("/api/audit-logs", headers=auth)
    logs = r.json() if r.status_code == 200 else []
    check("审计日志有记录", len(logs) > 0, f"{len(logs)} 条")
    actions = {entry["action"] for entry in logs}
    check("包含 param.update", "param.update" in actions)
    check("包含 auth.login", "auth.login" in actions)
    r = c.post("/api/audit-logs", json={}, headers=auth)
    check("日志接口不接受 POST（405）", r.status_code == 405, f"实际 {r.status_code}")

    # ---------- 14. 只读账号权限拦截 ----------
    r = c.post("/api/auth/login", json={"username": "viewer", "password": "123456"})
    vtoken = r.json()["token"]
    vauth = {"Authorization": f"Bearer {vtoken}"}
    vperms = r.json()["user"]["permissions"]
    check("viewer 权限 5 个", len(vperms) == 5, str(vperms))

    r = c.get("/api/me/menus", headers=vauth)
    vkeys = [m["key"] for m in r.json()] if r.status_code == 200 else []
    check("viewer 菜单不含「系统管理」", "system" not in vkeys, str(vkeys))
    check("viewer 菜单含「报表与看板」", "reports" in vkeys)

    r = c.get("/api/users", headers=vauth)
    check("viewer 读用户列表被拒 403", r.status_code == 403, f"实际 {r.status_code}")
    r = c.get("/api/params", headers=vauth)
    check("viewer 读参数被拒 403", r.status_code == 403, f"实际 {r.status_code}")
    r = c.get("/api/stores", headers=vauth)
    check("viewer 读门店允许 200", r.status_code == 200, f"实际 {r.status_code}")

    # ---------- 15. 调度员 ----------
    r = c.post("/api/auth/login", json={"username": "dispatcher", "password": "123456"})
    dtoken = r.json()["token"]
    dauth = {"Authorization": f"Bearer {dtoken}"}
    r = c.get("/api/me/menus", headers=dauth)
    dkeys = [m["key"] for m in r.json()] if r.status_code == 200 else []
    check("dispatcher 菜单含「智能调度 Agent」", "scheduling" in dkeys, str(dkeys))
    check("dispatcher 菜单不含「系统管理」", "system" not in dkeys)
    r = c.get("/api/vehicles", headers=dauth)
    check("dispatcher 读车辆允许 200", r.status_code == 200)
    r = c.post(
        "/api/vehicles",
        json={"plate_no": "沪Z9999", "vehicle_type_code": "4.2m"},
        headers=dauth,
    )
    check("dispatcher 建车辆被拒 403", r.status_code == 403, f"实际 {r.status_code}")

    # ---------- 汇总 ----------
    print()
    print("=" * 60)
    print(f"结果：{len(PASS)} 通过 / {len(FAIL)} 失败")
    if FAIL:
        print("失败项：")
        for name in FAIL:
            print("  -", name)
    print("=" * 60)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
