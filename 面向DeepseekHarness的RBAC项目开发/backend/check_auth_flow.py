"""阶段 2+3 联调自检：鉴权链路是否真的通了。

用一个独立的可执行脚本（而不是 pytest）来跑，是因为在写正式验收测试之前，
需要一个能直接看到「每一步发生了什么」的探针。所有请求都打真实 HTTP 接口。

覆盖内容：
  · 路由是否注册成功（FastAPI 0.138 用了惰性 _IncludedRouter，不能只看 app.routes）
  · 认证链路：无 Token → 401、坏 Token → 401、好 Token → 200
  · 授权链路：供应商 POST 商品 → 403、只读 GET 订单 → 200
  · R1 并集：multi（运营+只读）的权限是否为两者并集
  · R4 实时生效：停用权限点后，同一 Token 的下一次请求立即被拒

运行：  python check_auth_flow.py
"""

from __future__ import annotations

import sys
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.models import Permission, Product

PASS = "通过 ✓"
FAIL = "失败 ✗"

_failures: list[str] = []


def check(label: str, ok: bool, extra: str = "") -> None:
    print(f"  {label:<52} {PASS if ok else FAIL}  {extra}")
    if not ok:
        _failures.append(label)


def login(client: TestClient, username: str, password: str) -> dict:
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    return {"status": resp.status_code, "json": resp.json() if resp.content else {}}


def auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def main() -> int:
    client = TestClient(app, raise_server_exceptions=False)

    print("=" * 86)
    print("阶段 2+3 联调自检：鉴权链路（requireAuth → authorize → handler）")
    print("=" * 86)

    # ------------------------------------------------------------------
    print("\n[1] 路由注册情况")
    from fastapi.routing import APIRoute

    included = [r for r in app.routes if type(r).__name__ == "_IncludedRouter"]
    inner: list[APIRoute] = []
    for wrapper in included:
        inner.extend(
            r for r in wrapper.original_router.routes if isinstance(r, APIRoute)
        )
    paths = sorted({r.path for r in inner})
    check("已注册业务路由数 >= 10", len(paths) >= 10, f"实际 {len(paths)} 个")
    for p in paths:
        print(f"        · {p}")

    # ------------------------------------------------------------------
    print("\n[2] 认证链路 requireAuth（401）")
    r = client.get("/api/me")
    check("无 Token 访问 /api/me 返回 401", r.status_code == 401, f"实际 {r.status_code}")
    check("响应体为 {'error': '未登录'}", r.json() == {"error": "未登录"}, str(r.json()))

    r = client.get("/api/me", headers=auth_header("not-a-real-token"))
    check("伪造 Token 返回 401", r.status_code == 401, f"实际 {r.status_code}")

    r = client.get("/api/me", headers={"Authorization": "Basic abc"})
    check("非 Bearer 方案返回 401", r.status_code == 401, f"实际 {r.status_code}")

    r = client.post("/api/auth/login", json={"username": "admin", "password": "wrong-password"})
    check("密码错误返回 401", r.status_code == 401, f"实际 {r.status_code}")
    check("密码错误响应体同样为 {'error': '未登录'}", r.json() == {"error": "未登录"})

    r = client.post("/api/auth/login", json={"username": "no-such-user", "password": "x"})
    check(
        "用户名不存在也返回 401 且响应体与密码错误一致（不泄露账号是否存在）",
        r.status_code == 401 and r.json() == {"error": "未登录"},
    )

    # ------------------------------------------------------------------
    print("\n[3] 五类账号登录与权限集合")
    tokens: dict[str, str] = {}
    logins = {
        "admin": settings.ADMIN_INIT_PASSWORD,
        "operator": settings.DEMO_PASSWORD,
        "supplier": settings.DEMO_PASSWORD,
        "readonly": settings.DEMO_PASSWORD,
        "multi": settings.DEMO_PASSWORD,
    }
    for username, password in logins.items():
        res = login(client, username, password)
        ok = res["status"] == 200
        check(f"{username} 登录成功", ok, f"状态 {res['status']}")
        if ok:
            tokens[username] = res["json"]["access_token"]
            perms = res["json"]["permissions"]
            print(f"        角色={res['json']['roles']}  权限={perms}")

    if len(tokens) != 5:
        print("\n登录未全部成功，后续检查跳过")
        return _summary()

    # ------------------------------------------------------------------
    print("\n[4] 授权链路 authorize（403）—— 验收标准 2 与 3")
    r = client.get("/api/products", headers=auth_header(tokens["supplier"]))
    check("供应商 GET /api/products → 200（有 products:read）", r.status_code == 200, f"实际 {r.status_code}")

    r = client.post(
        "/api/products",
        headers=auth_header(tokens["supplier"]),
        json={"name": "供应商偷建的商品", "sku": "HACK-001", "price": 1, "stock": 1},
    )
    check(
        "★ 供应商 POST /api/products → 403（验收标准 2）",
        r.status_code == 403,
        f"实际 {r.status_code}",
    )
    check("403 响应体为 {'error': '没有权限'}", r.json() == {"error": "没有权限"}, str(r.json()))

    r = client.get("/api/products", headers=auth_header(tokens["readonly"]))
    check("★ 只读 GET /api/products → 200（验收标准 3）", r.status_code == 200, f"实际 {r.status_code}")

    r = client.post(
        "/api/products",
        headers=auth_header(tokens["readonly"]),
        json={"name": "只读偷建的商品", "sku": "HACK-002", "price": 1, "stock": 1},
    )
    check(
        "★ 只读 POST /api/products → 403（验收标准 3）",
        r.status_code == 403,
        f"实际 {r.status_code}",
    )

    r = client.get("/api/orders", headers=auth_header(tokens["supplier"]))
    check("供应商 GET /api/orders → 403（无 orders:read）", r.status_code == 403, f"实际 {r.status_code}")

    r = client.get("/api/reports/summary", headers=auth_header(tokens["readonly"]))
    check("只读 GET /api/reports/summary → 200", r.status_code == 200, f"实际 {r.status_code}")

    r = client.get("/api/reports/summary", headers=auth_header(tokens["supplier"]))
    check("供应商 GET /api/reports/summary → 403", r.status_code == 403, f"实际 {r.status_code}")

    r = client.get("/api/roles", headers=auth_header(tokens["operator"]))
    check("运营 GET /api/roles → 403（无 users:manage）", r.status_code == 403, f"实际 {r.status_code}")

    r = client.get("/api/roles", headers=auth_header(tokens["admin"]))
    check("管理员 GET /api/roles → 200", r.status_code == 200, f"实际 {r.status_code}")

    # ------------------------------------------------------------------
    print("\n[5] R1 多角色并集 —— 验收标准 4")
    multi_perms = set(login(client, "multi", settings.DEMO_PASSWORD)["json"]["permissions"])
    operator_perms = set(login(client, "operator", settings.DEMO_PASSWORD)["json"]["permissions"])
    readonly_perms = set(login(client, "readonly", settings.DEMO_PASSWORD)["json"]["permissions"])
    expected = operator_perms | readonly_perms

    check(
        "multi 的权限 == 运营 ∪ 只读",
        multi_perms == expected,
        f"\n        实际   : {sorted(multi_perms)}\n        期望并集: {sorted(expected)}",
    )
    check(
        "★ 并集证据：multi 拥有 products:edit（运营有、只读没有，取并集才应出现）",
        "products:edit" in multi_perms,
    )
    check(
        "★ 非交集证据：若误取交集或最严，products:edit 会丢失",
        "products:edit" not in (operator_perms & readonly_perms),
    )

    # 用唯一 SKU，避免重复执行本脚本时命中唯一键冲突
    sku = f"MULTI-{uuid.uuid4().hex[:8].upper()}"
    r = client.post(
        "/api/products",
        headers=auth_header(tokens["multi"]),
        json={"name": "多角色用户建的商品", "sku": sku, "price": 88, "stock": 5},
    )
    check(
        "★ multi 可以 POST /api/products（201）—— 并集带来的实际能力",
        r.status_code == 201,
        f"实际 {r.status_code}",
    )

    # 自清理：删除本步骤创建的商品，避免污染演示数据
    if r.status_code == 201:
        with SessionLocal() as db:
            db.execute(delete(Product).where(Product.sku == sku))
            db.commit()

    # ------------------------------------------------------------------
    print("\n[6] R2 默认拒绝：不存在的权限点")
    from fastapi import Depends, FastAPI

    from app.deps import authorize
    from app.main import register_exception_handlers

    probe = FastAPI()
    # 探针实例必须挂上同一套异常处理器，否则 ForbiddenError 会被当成未捕获异常
    # 直接抛出，测出来的行为与线上不一致（这正是本步骤第一次运行时踩到的坑）。
    register_exception_handlers(probe)

    @probe.get("/probe/ghost", dependencies=[Depends(authorize("ghost:permission"))])
    def _ghost() -> dict:  # pragma: no cover - 仅用于探测
        return {"ok": True}

    @probe.get("/probe/known", dependencies=[Depends(authorize("products:read"))])
    def _known() -> dict:  # pragma: no cover - 仅用于探测
        return {"ok": True}

    probe_client = TestClient(probe, raise_server_exceptions=False)

    r = probe_client.get("/probe/known", headers=auth_header(tokens["admin"]))
    check("对照组：管理员访问真实权限点 → 200", r.status_code == 200, f"实际 {r.status_code}")

    r = probe_client.get("/probe/ghost", headers=auth_header(tokens["admin"]))
    check(
        "连管理员访问「不存在的权限点」也 403（R2 fail-closed）",
        r.status_code == 403,
        f"实际 {r.status_code}",
    )
    check("响应体为 {'error': '没有权限'}", r.json() == {"error": "没有权限"}, str(r.json()))

    # ------------------------------------------------------------------
    print("\n[7] R4 权限停用实时生效 —— 验收标准 6")
    # 取一个只读角色持有的权限点来做实验：products:read
    with SessionLocal() as db:
        perm = (
            db.query(Permission).filter(Permission.code == "products:read").one()
        )
        perm_id = perm.id

    r = client.get("/api/products", headers=auth_header(tokens["readonly"]))
    before_status = r.status_code
    check("停用前：只读 GET /api/products → 200", before_status == 200, f"实际 {before_status}")

    # 用 admin 停用该权限点（注意：admin 自己也有 products:read，也会一起失去）
    r = client.patch(
        f"/api/permissions/{perm_id}",
        headers=auth_header(tokens["admin"]),
        json={"is_active": False},
    )
    check("管理员停用 products:read → 200", r.status_code == 200, f"实际 {r.status_code}")

    # ★ 关键：完全相同的 Token，没有任何重新登录 / 刷新
    r = client.get("/api/products", headers=auth_header(tokens["readonly"]))
    check(
        "★ 停用后：同一 Token 的下一次请求立即 403（R4 无缓存延迟）",
        r.status_code == 403,
        f"实际 {r.status_code}",
    )

    r = client.get("/api/me/permissions", headers=auth_header(tokens["readonly"]))
    perms_now = set(r.json()["permissions"])
    check(
        "products:read 已从只读的有效权限中消失",
        "products:read" not in perms_now,
        f"当前权限 {sorted(perms_now)}",
    )

    # 恢复现场
    r = client.patch(
        f"/api/permissions/{perm_id}",
        headers=auth_header(tokens["admin"]),
        json={"is_active": True},
    )
    check("恢复启用 products:read → 200", r.status_code == 200, f"实际 {r.status_code}")

    r = client.get("/api/products", headers=auth_header(tokens["readonly"]))
    check("恢复后：只读 GET /api/products 又可访问（200）", r.status_code == 200, f"实际 {r.status_code}")

    # ------------------------------------------------------------------
    print("\n[8] 前端菜单裁剪（验收标准 7 的后端部分）")
    r = client.get("/api/me/menus", headers=auth_header(tokens["admin"]))
    admin_keys = _menu_keys(r.json())
    r = client.get("/api/me/menus", headers=auth_header(tokens["supplier"]))
    supplier_keys = _menu_keys(r.json())

    check(
        "管理员菜单包含系统管理相关节点",
        {"system", "system-users", "system-roles"} <= admin_keys,
        f"\n        管理员菜单: {sorted(admin_keys)}",
    )
    check(
        "★ 供应商菜单不含任何系统管理节点（服务端已裁剪）",
        not any(k.startswith("system") for k in supplier_keys),
        f"\n        供应商菜单: {sorted(supplier_keys)}",
    )
    check("供应商菜单含商品管理", "products" in supplier_keys)
    check("供应商菜单不含订单管理与数据报表", not ({"orders", "reports"} & supplier_keys))

    return _summary()


def _menu_keys(nodes: list[dict]) -> set[str]:
    keys: set[str] = set()

    def walk(items: list[dict]) -> None:
        for n in items:
            keys.add(n["key"])
            if n.get("children"):
                walk(n["children"])

    walk(nodes)
    return keys


def _summary() -> int:
    print("\n" + "=" * 86)
    if _failures:
        print(f"结果：{len(_failures)} 项未通过 ✗")
        for f in _failures:
            print(f"  · {f}")
    else:
        print("结果：全部通过 ✓")
    print("=" * 86)
    return 1 if _failures else 0


if __name__ == "__main__":
    sys.exit(main())
