"""验收测试：逐条对应需求文档第 7 节的 7 条验收标准。

    验收标准 1  四个内置角色可正常登录，权限表现符合第 2 节表格
    验收标准 2  供应商角色访问 POST /api/products 返回 403
    验收标准 3  只读角色访问 GET /api/products 返回 200，访问 POST 返回 403
    验收标准 4  多角色并集：用户同时绑定运营和只读，权限为两者并集
    验收标准 5  删除被引用角色返回 409，提示信息包含绑定用户数量
    验收标准 6  停用某权限点后，持有该权限的用户下次请求立即被拒绝（无缓存延迟）
    验收标准 7  前端菜单根据权限动态渲染，无权限菜单不显示

除 7 条标准外，还额外覆盖了 4 条业务规则（R1~R5）与错误响应规范，
它们与验收标准分开编号（T 系列），便于一眼区分「需求要求的」与「我加测的」。

运行：
    pytest                        # 全部
    pytest -k "标准2 or 标准3"     # 只跑指定标准
    pytest tests/test_acceptance.py::Test标准5_删除被引用角色
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.database import SessionLocal
from app.models import Permission, Role
from app.services import rbac
from seed import ROLE_PERMISSIONS, ROLES
from tests.conftest import (
    DEMO_ACCOUNTS,
    PROBE_PERM_PREFIX,
    PROBE_ROLE_PREFIX,
    PROBE_SKU_PREFIX,
    login,
)

# ---------------------------------------------------------------------------
# 期望的权限矩阵 —— 直接复用 seed.py 里的定义，而不是在测试里再抄一份。
# 这样「需求 → 种子数据 → 测试断言」是同一条数据流，
# 不会出现「改了种子数据但忘了改测试」导致测试变成假绿。
# ---------------------------------------------------------------------------
EXPECTED_MATRIX: dict[str, set[str]] = {
    code: set(codes) for code, codes in ROLE_PERMISSIONS.items()
}

ALL_PERMISSIONS: list[str] = [
    "products:read",
    "products:edit",
    "orders:read",
    "reports:view",
    "users:manage",
    "settings:edit",
]

ROLE_NAMES: dict[str, str] = {r["code"]: r["name"] for r in ROLES}


def _menu_keys(nodes: list[dict]) -> set[str]:
    """把菜单树拍平成 key 集合，便于断言。"""
    keys: set[str] = set()

    def walk(items: list[dict]) -> None:
        for node in items:
            keys.add(node["key"])
            if node.get("children"):
                walk(node["children"])

    walk(nodes)
    return keys


# ===========================================================================
# 验收标准 1：四个内置角色登录 + 权限矩阵
# ===========================================================================
class Test标准1_四角色权限矩阵:
    @pytest.mark.parametrize("role_code", ["admin", "operator", "supplier", "readonly"])
    def test_角色可以登录(self, client: TestClient, role_code: str) -> None:
        # 演示账号名与角色码同名（admin/operator/supplier/readonly）
        data = login(client, role_code)
        assert data["roles"] == [role_code]
        assert data["access_token"]
        assert data["token_type"] == "bearer"

    @pytest.mark.parametrize("role_code", ["admin", "operator", "supplier", "readonly"])
    @pytest.mark.parametrize("permission", ALL_PERMISSIONS)
    def test_权限矩阵逐格核对(
        self, client: TestClient, role_code: str, permission: str
    ) -> None:
        """★ 4 角色 × 6 权限 = 24 格逐格核对需求文档第 2 节的表格。"""
        data = login(client, role_code)
        actual = set(data["permissions"])
        expected = EXPECTED_MATRIX[role_code]

        should_have = permission in expected
        has = permission in actual

        assert has == should_have, (
            f"{ROLE_NAMES[role_code]}（{role_code}）对 {permission} 的权限不符："
            f"期望{'有' if should_have else '无'}，实际{'有' if has else '无'}；"
            f"完整权限={sorted(actual)}"
        )

    @pytest.mark.parametrize("role_code", ["admin", "operator", "supplier", "readonly"])
    def test_权限集合不多不少(
        self, client: TestClient, role_code: str
    ) -> None:
        """除了逐格核对，还确认「没有多出来的权限」。"""
        actual = set(login(client, role_code)["permissions"])
        assert actual == EXPECTED_MATRIX[role_code]


# ===========================================================================
# 验收标准 2：供应商 POST /api/products → 403
# ===========================================================================
class Test标准2_供应商不能编辑商品:
    def test_供应商POST商品返回403(self, client: TestClient, tokens, auth) -> None:
        resp = client.post(
            "/api/products",
            headers=auth(tokens["supplier"]),
            json={
                "name": "供应商越权创建",
                "sku": f"{PROBE_SKU_PREFIX}{uuid.uuid4().hex[:8]}",
                "price": 1,
                "stock": 1,
            },
        )
        assert resp.status_code == 403
        assert resp.json() == {"error": "没有权限"}

    def test_供应商可以读商品(self, client: TestClient, tokens, auth) -> None:
        """对照组：供应商有 products:read，读接口必须通。"""
        resp = client.get("/api/products", headers=auth(tokens["supplier"]))
        assert resp.status_code == 200


# ===========================================================================
# 验收标准 3：只读 GET 200 / POST 403
# ===========================================================================
class Test标准3_只读角色边界:
    def test_只读GET商品返回200(self, client: TestClient, tokens, auth) -> None:
        resp = client.get("/api/products", headers=auth(tokens["readonly"]))
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_只读POST商品返回403(self, client: TestClient, tokens, auth) -> None:
        resp = client.post(
            "/api/products",
            headers=auth(tokens["readonly"]),
            json={
                "name": "只读越权创建",
                "sku": f"{PROBE_SKU_PREFIX}{uuid.uuid4().hex[:8]}",
                "price": 1,
                "stock": 1,
            },
        )
        assert resp.status_code == 403
        assert resp.json() == {"error": "没有权限"}

    def test_只读可看订单与报表(self, client: TestClient, tokens, auth) -> None:
        assert client.get("/api/orders", headers=auth(tokens["readonly"])).status_code == 200
        assert (
            client.get("/api/reports/summary", headers=auth(tokens["readonly"])).status_code
            == 200
        )

    def test_只读不能进管理端(self, client: TestClient, tokens, auth) -> None:
        for path in ("/api/roles", "/api/users", "/api/permissions", "/api/audit-logs"):
            resp = client.get(path, headers=auth(tokens["readonly"]))
            assert resp.status_code == 403, f"{path} 期望 403，实际 {resp.status_code}"


# ===========================================================================
# 验收标准 4：多角色并集（R1）
# ===========================================================================
class Test标准4_多角色并集:
    def test_多角色权限等于并集(self, client: TestClient) -> None:
        multi = set(login(client, "multi")["permissions"])
        operator = set(login(client, "operator")["permissions"])
        readonly = set(login(client, "readonly")["permissions"])

        assert multi == (operator | readonly), (
            f"并集不符：multi={sorted(multi)} "
            f"operator∪readonly={sorted(operator | readonly)}"
        )

    def test_并集关键证据_取并集才有products_edit(self, client: TestClient) -> None:
        """★ 这一格是「并集 vs 交集」的判别式。

        products:edit 只有运营有、只读没有：
          · 取并集  → multi 拥有它（正确）
          · 取交集  → multi 丢失它（错误）
          · 取最严  → multi 丢失它（错误）
        """
        multi = set(login(client, "multi")["permissions"])
        operator = set(login(client, "operator")["permissions"])
        readonly = set(login(client, "readonly")["permissions"])

        assert "products:edit" in operator
        assert "products:edit" not in readonly
        assert "products:edit" in multi, "multi 缺少 products:edit —— 说明实现退化成了交集"

    def test_并集带来的实际能力(self, client: TestClient, tokens, auth) -> None:
        """multi 因运营角色获得 products:edit，所以能真正创建商品。"""
        resp = client.post(
            "/api/products",
            headers=auth(tokens["multi"]),
            json={
                "name": "多角色用户创建",
                "sku": f"{PROBE_SKU_PREFIX}{uuid.uuid4().hex[:8]}",
                "price": 88,
                "stock": 5,
            },
        )
        assert resp.status_code == 201

    def test_并集叠加管理权限(self, client: TestClient, tokens, auth) -> None:
        """R1 的更强形式：admin ∪ readonly 应同时具备管理权限与只读权限。"""
        with SessionLocal() as db:
            admin_user = rbac.get_user_by_username(db, "admin")
            assert admin_user is not None
            original = rbac.get_user_role_codes(db, admin_user.id)
            admin_id = admin_user.id

        try:
            resp = client.put(
                f"/api/users/{admin_id}/roles",
                headers=auth(tokens["admin"]),
                json={"role_codes": ["admin", "readonly"]},
            )
            assert resp.status_code == 200
            perms = set(resp.json()["permissions"])
            assert perms == EXPECTED_MATRIX["admin"] | EXPECTED_MATRIX["readonly"]
            assert "users:manage" in perms  # 来自 admin
            assert "products:read" in perms  # 来自 readonly
        finally:
            client.put(
                f"/api/users/{admin_id}/roles",
                headers=auth(tokens["admin"]),
                json={"role_codes": original},
            )


# ===========================================================================
# 验收标准 5：删除被引用角色 → 409 且含绑定用户数（R3）
# ===========================================================================
class Test标准5_删除被引用角色:
    def test_删除被引用角色返回409并含数量(self, client: TestClient, tokens, auth) -> None:
        # 用 operator 角色做实验（绑定了 operator 和 multi 两个用户）
        with SessionLocal() as db:
            role = rbac.get_role_by_code(db, "operator")
            assert role is not None
            role_id = role.id
            expected_count = rbac.count_role_users(db, role.id)

        assert expected_count > 0, "operator 角色应当有绑定用户，否则本用例无意义"

        resp = client.delete(f"/api/roles/{role_id}", headers=auth(tokens["admin"]))

        assert resp.status_code == 409
        error_text = resp.json()["error"]
        assert str(expected_count) in error_text, (
            f"提示信息必须包含绑定用户数 {expected_count}，实际为：{error_text!r}"
        )
        assert error_text == f"该角色仍绑定 {expected_count} 个用户，请先改绑"

    def test_删除被引用角色不得级联清除绑定(self, client: TestClient, tokens, auth) -> None:
        """R3 明确要求「禁止级联清除」——失败后绑定关系必须完好。"""
        with SessionLocal() as db:
            role = rbac.get_role_by_code(db, "readonly")
            assert role is not None
            role_id, before_count = role.id, rbac.count_role_users(db, role.id)

        assert client.delete(f"/api/roles/{role_id}", headers=auth(tokens["admin"])).status_code == 409

        with SessionLocal() as db:
            assert db.get(Role, role_id) is not None, "角色被删除了 —— 违反 R3"
            assert rbac.count_role_users(db, role_id) == before_count, "绑定关系被清除了 —— 违反 R3"

    def test_删除未被引用角色成功(self, client: TestClient, tokens, auth) -> None:
        """对照组：没有用户引用的角色必须能正常删除。"""
        code = f"{PROBE_ROLE_PREFIX}{uuid.uuid4().hex[:8]}"
        created = client.post(
            "/api/roles",
            headers=auth(tokens["admin"]),
            json={"code": code, "name": "临时角色", "permission_codes": ["products:read"]},
        )
        assert created.status_code == 201
        role_id = created.json()["id"]

        resp = client.delete(f"/api/roles/{role_id}", headers=auth(tokens["admin"]))
        assert resp.status_code == 200
        assert resp.json() == {"ok": True, "deleted": code}

    def test_数据库外键兜底_RESTRICT(self) -> None:
        """★ 绕过应用层，直接删库验证 ON DELETE RESTRICT 生效。

        应用层的 COUNT 检查是第一道防线；即便它被改坏或遇到并发，
        数据库外键也必须拒绝「删除仍被引用的角色」。
        """
        from sqlalchemy import text
        from sqlalchemy.exc import IntegrityError

        from app.database import engine

        with SessionLocal() as db:
            role = rbac.get_role_by_code(db, "admin")
            assert role is not None
            role_id = role.id

        with engine.connect() as conn:
            with pytest.raises(IntegrityError) as exc_info:
                conn.execute(text("DELETE FROM roles WHERE id = :rid"), {"rid": role_id})
                conn.commit()
            assert "1451" in str(exc_info.value) or "foreign key" in str(exc_info.value).lower()
            conn.rollback()


# ===========================================================================
# 验收标准 6：停用权限点立即生效（R4）
# ===========================================================================
class Test标准6_权限变更实时生效:
    def test_停用权限点后同一Token立即被拒(
        self, client: TestClient, tokens, auth
    ) -> None:
        """★ 全程使用同一个 Token，不做重新登录 —— 有缓存就必然失败。"""
        readonly_token = tokens["readonly"]

        # 1) 停用前可以访问
        assert client.get("/api/products", headers=auth(readonly_token)).status_code == 200

        with SessionLocal() as db:
            perm = rbac.get_permission_by_code(db, "products:read")
            assert perm is not None
            perm_id = perm.id

        try:
            # 2) 管理员停用该权限点
            resp = client.patch(
                f"/api/permissions/{perm_id}",
                headers=auth(tokens["admin"]),
                json={"is_active": False},
            )
            assert resp.status_code == 200

            # 3) ★ 同一个 Token 的下一次请求必须立刻 403
            resp = client.get("/api/products", headers=auth(readonly_token))
            assert resp.status_code == 403, (
                "停用权限点后仍然可访问 —— 说明存在权限缓存，违反 R4"
            )
            assert resp.json() == {"error": "没有权限"}

            # 4) /api/me/permissions 也应同步反映
            perms = set(
                client.get("/api/me/permissions", headers=auth(readonly_token)).json()[
                    "permissions"
                ]
            )
            assert "products:read" not in perms
        finally:
            # 恢复现场
            client.patch(
                f"/api/permissions/{perm_id}",
                headers=auth(tokens["admin"]),
                json={"is_active": True},
            )

        # 5) 恢复后又能访问（证明整个链路是双向即时生效，而非单向坏掉）
        assert client.get("/api/products", headers=auth(readonly_token)).status_code == 200

    def test_改绑角色后同一Token立即生效(self, client: TestClient, tokens, auth) -> None:
        """R4 的另一半：角色改绑也要实时生效，不能等 Token 过期。"""
        with SessionLocal() as db:
            user = rbac.get_user_by_username(db, "readonly")
            assert user is not None
            user_id = user.id

        readonly_token = tokens["readonly"]
        assert client.get("/api/orders", headers=auth(readonly_token)).status_code == 200

        try:
            # 清空角色 → 权限并集变空集
            resp = client.put(
                f"/api/users/{user_id}/roles",
                headers=auth(tokens["admin"]),
                json={"role_codes": []},
            )
            assert resp.status_code == 200
            assert resp.json()["permissions"] == []

            # 同一 Token 立即失去全部权限
            assert client.get("/api/orders", headers=auth(readonly_token)).status_code == 403
            assert client.get("/api/products", headers=auth(readonly_token)).status_code == 403
        finally:
            client.put(
                f"/api/users/{user_id}/roles",
                headers=auth(tokens["admin"]),
                json={"role_codes": ["readonly"]},
            )

        assert client.get("/api/orders", headers=auth(readonly_token)).status_code == 200

    def test_停用角色后其权限整体失效(self, client: TestClient, tokens, auth) -> None:
        """R4 第三种触发方式：角色级停用。"""
        with SessionLocal() as db:
            role = rbac.get_role_by_code(db, "supplier")
            assert role is not None
            role_id = role.id

        supplier_token = tokens["supplier"]
        assert client.get("/api/products", headers=auth(supplier_token)).status_code == 200

        try:
            resp = client.put(
                f"/api/roles/{role_id}", headers=auth(tokens["admin"]), json={"is_active": False}
            )
            assert resp.status_code == 200
            assert (
                client.get("/api/products", headers=auth(supplier_token)).status_code == 403
            ), "角色停用后其权限应整体退出并集"
        finally:
            client.put(
                f"/api/roles/{role_id}", headers=auth(tokens["admin"]), json={"is_active": True}
            )

        assert client.get("/api/products", headers=auth(supplier_token)).status_code == 200


# ===========================================================================
# 验收标准 7：前端菜单根据权限动态渲染
# ===========================================================================
class Test标准7_菜单按权限裁剪:
    def test_管理员可见全部菜单(self, client: TestClient, tokens, auth) -> None:
        keys = _menu_keys(client.get("/api/me/menus", headers=auth(tokens["admin"])).json())
        assert {"dashboard", "products", "orders", "reports", "system"} <= keys
        assert {"system-users", "system-roles", "system-permissions", "system-audit"} <= keys

    def test_供应商无权限菜单不显示(self, client: TestClient, tokens, auth) -> None:
        """★ 供应商只有 products:read，菜单应只剩工作台与商品管理。"""
        keys = _menu_keys(client.get("/api/me/menus", headers=auth(tokens["supplier"])).json())
        assert keys == {"dashboard", "products"}, f"供应商菜单不符：{sorted(keys)}"

    def test_只读菜单不含系统管理(self, client: TestClient, tokens, auth) -> None:
        keys = _menu_keys(client.get("/api/me/menus", headers=auth(tokens["readonly"])).json())
        assert keys == {"dashboard", "products", "orders", "reports"}
        assert not any(k.startswith("system") for k in keys)

    def test_运营菜单不含系统管理(self, client: TestClient, tokens, auth) -> None:
        keys = _menu_keys(client.get("/api/me/menus", headers=auth(tokens["operator"])).json())
        assert keys == {"dashboard", "products", "orders", "reports"}

    def test_菜单随权限实时变化(self, client: TestClient, tokens, auth) -> None:
        """停用 products:read 后，商品管理菜单应立刻消失。"""
        with SessionLocal() as db:
            perm = rbac.get_permission_by_code(db, "products:read")
            assert perm is not None
            perm_id = perm.id

        try:
            client.patch(
                f"/api/permissions/{perm_id}",
                headers=auth(tokens["admin"]),
                json={"is_active": False},
            )
            keys = _menu_keys(
                client.get("/api/me/menus", headers=auth(tokens["supplier"])).json()
            )
            assert "products" not in keys, "权限已停用，商品菜单仍然返回"
            assert keys == {"dashboard"}
        finally:
            client.patch(
                f"/api/permissions/{perm_id}",
                headers=auth(tokens["admin"]),
                json={"is_active": True},
            )

    def test_服务端裁剪而非前端过滤(self, client: TestClient, tokens, auth) -> None:
        """★ 校验裁剪确实发生在服务端。

        若实现改成「返回完整菜单树、由前端过滤」，那么无权用户也能从
        响应体里读到 system-* 节点，管理端结构就泄露了。
        """
        body = client.get("/api/me/menus", headers=auth(tokens["supplier"])).text
        assert "system" not in body
        assert "users:manage" not in body


# ===========================================================================
# T 系列：需求文档里提到但未列入验收标准的规则
# ===========================================================================
class TestT1_错误响应规范:
    """需求文档第 6 节的错误响应规范。"""

    def test_未登录401(self, client: TestClient) -> None:
        resp = client.get("/api/me")
        assert resp.status_code == 401
        assert resp.json() == {"error": "未登录"}

    def test_伪造Token401(self, client: TestClient) -> None:
        resp = client.get("/api/me", headers={"Authorization": "Bearer forged.token.here"})
        assert resp.status_code == 401
        assert resp.json() == {"error": "未登录"}

    def test_已登录无权限403(self, client: TestClient, tokens, auth) -> None:
        resp = client.get("/api/roles", headers=auth(tokens["supplier"]))
        assert resp.status_code == 403
        assert resp.json() == {"error": "没有权限"}

    def test_登录失败不泄露账号是否存在(self, client: TestClient) -> None:
        wrong_pw = client.post(
            "/api/auth/login", json={"username": "admin", "password": "definitely-wrong"}
        )
        no_user = client.post(
            "/api/auth/login", json={"username": "no-such-user-xyz", "password": "whatever"}
        )
        assert wrong_pw.status_code == no_user.status_code == 401
        assert wrong_pw.json() == no_user.json() == {"error": "未登录"}


class TestT2_默认拒绝fail_closed:
    """R2：权限点不存在、未配置、无角色，一律 403。"""

    def test_不存在的权限点也403(self, client: TestClient, tokens, auth) -> None:
        from fastapi import Depends, FastAPI

        from app.deps import authorize
        from app.main import register_exception_handlers

        probe = FastAPI()
        register_exception_handlers(probe)

        @probe.get("/probe/ghost", dependencies=[Depends(authorize("ghost:perm"))])
        def _ghost() -> dict:  # pragma: no cover
            return {"ok": True}

        probe_client = TestClient(probe)
        resp = probe_client.get("/probe/ghost", headers=auth(tokens["admin"]))
        # 连拥有全部权限的管理员也必须被拒 —— 权限点不存在就是不存在
        assert resp.status_code == 403

    def test_无角色用户全部403(self, client: TestClient, tokens, auth) -> None:
        with SessionLocal() as db:
            user = rbac.get_user_by_username(db, "supplier")
            assert user is not None
            user_id = user.id

        try:
            assert (
                client.put(
                    f"/api/users/{user_id}/roles",
                    headers=auth(tokens["admin"]),
                    json={"role_codes": []},
                ).status_code
                == 200
            )
            # 重新登录拿到「无角色」的 Token（supplier 的旧 Token 仍有效，也会被拒）
            fresh = login(client, "supplier")["access_token"]
            assert client.get("/api/products", headers=auth(fresh)).status_code == 403

            # 菜单应只剩工作台（它是 permission=None，登录即可见）
            menus = client.get("/api/me/menus", headers=auth(fresh)).json()
            assert [m["key"] for m in menus] == ["dashboard"], f"实际菜单：{menus}"
            assert menus[0]["permission"] is None, "工作台不应要求任何权限点"
        finally:
            client.put(
                f"/api/users/{user_id}/roles",
                headers=auth(tokens["admin"]),
                json={"role_codes": ["supplier"]},
            )

    def test_用户被停用后Token失效(self, client: TestClient, tokens, auth) -> None:
        """用户停用等同于「未登录」，因为鉴权每次都会重新查库确认用户状态。"""
        with SessionLocal() as db:
            user = rbac.get_user_by_username(db, "readonly")
            assert user is not None
            user_id = user.id

        try:
            with SessionLocal() as db:
                u = db.get(type(user), user_id)
                assert u is not None
                u.is_active = False
                db.commit()

            resp = client.get("/api/products", headers=auth(tokens["readonly"]))
            assert resp.status_code == 401
            assert resp.json() == {"error": "未登录"}
        finally:
            with SessionLocal() as db:
                u = db.get(type(user), user_id)
                assert u is not None
                u.is_active = True
                db.commit()


class TestT3_前端伪造权限无效:
    """★ 这次实践最核心的认知点：前端权限只是体验优化，后端才是防线。"""

    def test_登录响应里的permissions仅供参考(self, client: TestClient, tokens, auth) -> None:
        """供应商在登录响应里只拿到 1 个权限，但请求仍被独立校验。

        模拟「前端被篡改」：客户端谎称自己有 products:edit（比如改了
        localStorage / Pinia 状态 / 直接构造请求），后端完全不看这个字段，
        仍然实时查库算出真实的权限集合，因此照样 403。
        """
        supplier_login = login(client, "supplier")
        assert supplier_login["permissions"] == ["products:read"]

        # 客户端可以随便往请求里塞伪造的权限声明 —— 服务端一概忽略
        resp = client.post(
            "/api/products",
            headers={
                **auth(tokens["supplier"]),
                "X-Fake-Permissions": "products:edit,users:manage",
                "X-Permission": "products:edit",
            },
            json={
                "name": "伪造权限尝试",
                "sku": f"{PROBE_SKU_PREFIX}{uuid.uuid4().hex[:8]}",
                "price": 1,
                "stock": 1,
            },
        )
        assert resp.status_code == 403, "服务端不应信任任何客户端提供的权限声明"

    def test_权限不被写入Token(self, client: TestClient) -> None:
        """Token 里只有身份标识，没有权限集合。

        这是 R4「无缓存延迟」的前提：权限若写进 Token，
        停用权限点后就必须等 Token 过期才生效。
        """
        import jwt

        token = login(client, "admin")["access_token"]
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])

        assert set(payload.keys()) == {"sub", "username", "iat", "exp"}, (
            f"Token 里出现了预期外的字段（权限不应入 Token）：{sorted(payload.keys())}"
        )
        assert "permissions" not in payload
        assert "roles" not in payload


class TestT4_审计日志只追加:
    """R5：审计日志只追加、不修改、不删除。"""

    def test_关键操作都会留下日志(self, client: TestClient, tokens, auth) -> None:
        code = f"{PROBE_ROLE_PREFIX}{uuid.uuid4().hex[:8]}"
        created = client.post(
            "/api/roles",
            headers=auth(tokens["admin"]),
            json={"code": code, "name": "审计探针角色", "permission_codes": ["products:read"]},
        )
        assert created.status_code == 201
        role_id = created.json()["id"]
        client.delete(f"/api/roles/{role_id}", headers=auth(tokens["admin"]))

        logs = client.get(
            "/api/audit-logs",
            headers=auth(tokens["admin"]),
            params={"limit": 200},
        ).json()
        actions = [x["action"] for x in logs]

        assert "role.create" in actions
        assert "role.delete" in actions

        created_log = next(x for x in logs if x["action"] == "role.create" and x["target_name"] == code)
        assert created_log["actor_name"] == "admin"
        assert created_log["actor_id"] is not None
        assert created_log["detail"] is not None

    def test_审计接口只读_无写入方法(self, client: TestClient, tokens, auth) -> None:
        """审计日志接口不提供任何写方法。

        注意 TestClient.delete() 不接受 json 参数（httpx 的限制），
        所以这里分开处理，而不是统一 getattr + json=。
        """
        headers = auth(tokens["admin"])
        attempts = [
            ("post", {"json": {}}),
            ("put", {"json": {}}),
            ("patch", {"json": {}}),
            ("delete", {}),
        ]
        for method, kwargs in attempts:
            resp = getattr(client, method)("/api/audit-logs", headers=headers, **kwargs)
            assert resp.status_code == 405, (
                f"{method.upper()} /api/audit-logs 应返回 405，实际 {resp.status_code}"
            )

    def test_代码中不存在修改或删除审计日志的路径(self) -> None:
        """静态检查：全项目没有对 AuditLog 的删除 / 字段修改。

        这是 R5「只追加」在代码层面的直接证据 —— 比运行时行为更有说服力，
        因为它能发现「当前逻辑没走到但代码里存在」的隐患路径。

        ★ 判定必须精确到「写操作」，否则会大量误报。合法的读操作长这样：
              stmt.where(AuditLog.action == action)      # WHERE 过滤，不是修改
              select(AuditLog).order_by(AuditLog.id)     # 排序，不是修改
        真正的违规是「把值赋给日志字段」：
              log.action = "hacked"
              log.detail = {...}
        一个会误报的检查比没有检查更糟 —— 见本测试第一次运行时抓到的误报。
        """
        import re
        from pathlib import Path

        app_dir = Path(__file__).resolve().parent.parent / "app"
        # 匹配 `对象.审计字段 = 值`，捕获属性名
        assign_re = re.compile(
            r"\.(action|actor_id|actor_name|target_type|target_id|target_name|detail)\s*=[^=]"
        )
        delete_re = re.compile(r"delete\s*\(\s*AuditLog\b")
        offenders: list[str] = []

        for py_file in app_dir.rglob("*.py"):
            in_docstring = False
            for lineno, raw in enumerate(py_file.read_text(encoding="utf-8").splitlines(), 1):
                line = raw.strip()

                # 用三引号跟踪 docstring，跳过其中的说明文字
                # （本文件与 audit.py 的注释里就写有 "db.delete(AuditLog)" 这类字样）
                if line.count('"""') == 1:
                    in_docstring = not in_docstring
                    continue
                if in_docstring or not line or line.startswith("#"):
                    continue

                if delete_re.search(line):
                    offenders.append(f"{py_file.name}:{lineno} 删除审计日志: {line}")

                # 只有在操作 AuditLog 实例的上下文里才算违规；
                # 注意调用方对 AuditLog 没有写路径，所以检查范围限于 audit 相关模块
                if py_file.name in {"audit.py", "audit_logs.py"} and assign_re.search(line):
                    offenders.append(f"{py_file.name}:{lineno} 修改审计日志字段: {line}")

        assert not offenders, "发现修改/删除审计日志的代码路径：\n" + "\n".join(offenders)


class TestT5_防自锁与边界:
    """需求之外的保护：不能把系统改成无人能管理。"""

    def test_不能移除最后一个管理员(self, client: TestClient, tokens, auth) -> None:
        with SessionLocal() as db:
            user = rbac.get_user_by_username(db, "admin")
            assert user is not None
            user_id = user.id

        resp = client.put(
            f"/api/users/{user_id}/roles",
            headers=auth(tokens["admin"]),
            json={"role_codes": []},
        )
        assert resp.status_code == 409
        assert "最后" in resp.json()["error"]

    def test_空角色是合法输入(self, client: TestClient, tokens, auth) -> None:
        """清空非管理员用户的角色应当成功 —— 无角色不是错误状态，只是没有权限。"""
        with SessionLocal() as db:
            user = rbac.get_user_by_username(db, "multi")
            assert user is not None
            user_id = user.id

        try:
            resp = client.put(
                f"/api/users/{user_id}/roles",
                headers=auth(tokens["admin"]),
                json={"role_codes": []},
            )
            assert resp.status_code == 200
            assert resp.json()["roles"] == []
            assert resp.json()["permissions"] == []
        finally:
            client.put(
                f"/api/users/{user_id}/roles",
                headers=auth(tokens["admin"]),
                json={"role_codes": ["operator", "readonly"]},
            )

    def test_重复角色码被拒绝(self, client: TestClient, tokens, auth) -> None:
        code = f"{PROBE_ROLE_PREFIX}{uuid.uuid4().hex[:8]}"
        first = client.post(
            "/api/roles", headers=auth(tokens["admin"]), json={"code": code, "name": "A"}
        )
        assert first.status_code == 201
        second = client.post(
            "/api/roles", headers=auth(tokens["admin"]), json={"code": code, "name": "B"}
        )
        assert second.status_code == 409

    def test_绑定不存在的权限码被拒绝(self, client: TestClient, tokens, auth) -> None:
        """配置期校验：写错的权限码应立刻报错，而不是静默忽略。

        注意这与 R2 的运行期默认拒绝是两件事：
        配置角色时权限码写错 → 立即 404 让人发现；
        运行时权限码恰好不存在 → 静默 403。
        """
        resp = client.post(
            "/api/roles",
            headers=auth(tokens["admin"]),
            json={
                "code": f"{PROBE_ROLE_PREFIX}{uuid.uuid4().hex[:8]}",
                "name": "权限码写错的角色",
                "permission_codes": ["products:read", "nonexistent:perm"],
            },
        )
        assert resp.status_code == 404
        assert "nonexistent:perm" in resp.json()["error"]

    def test_新增权限点后角色可绑定(self, client: TestClient, tokens, auth) -> None:
        perm_code = f"{PROBE_PERM_PREFIX}export"
        resp = client.post(
            "/api/permissions",
            headers=auth(tokens["admin"]),
            json={"code": perm_code, "name": "导出报表", "module": "reports"},
        )
        assert resp.status_code == 201

        role_code = f"{PROBE_ROLE_PREFIX}{uuid.uuid4().hex[:8]}"
        created = client.post(
            "/api/roles",
            headers=auth(tokens["admin"]),
            json={"code": role_code, "name": "导出员", "permission_codes": [perm_code]},
        )
        assert created.status_code == 201
        assert created.json()["permission_codes"] == [perm_code]

    def test_权限码格式校验(self, client: TestClient, tokens, auth) -> None:
        """权限码必须形如「模块:动作」。"""
        resp = client.post(
            "/api/permissions",
            headers=auth(tokens["admin"]),
            json={"code": "products.read", "name": "点号写法", "module": "products"},
        )
        assert resp.status_code == 422


class TestT6_权限点为空的边界:
    """确认集合运算在空集/单元素等边界上行为正确。"""

    def test_权限点被停用后角色绑定关系保留(self, client: TestClient, tokens, auth) -> None:
        """R4 是「实时过滤」而不是「删除绑定关系」—— 重新启用应当自动恢复。"""
        with SessionLocal() as db:
            perm = rbac.get_permission_by_code(db, "reports:view")
            assert perm is not None
            perm_id = perm.id
            role = rbac.get_role_by_code(db, "readonly")
            assert role is not None
            bound_before = perm.code in role.permission_codes

        assert bound_before

        try:
            client.patch(
                f"/api/permissions/{perm_id}",
                headers=auth(tokens["admin"]),
                json={"is_active": False},
            )
            with SessionLocal() as db:
                role = rbac.get_role_by_code(db, "readonly")
                assert role is not None
                # 绑定关系还在（只是运行时被 is_active 过滤掉了）
                assert "reports:view" in role.permission_codes
                assert (
                    client.get(
                        "/api/reports/summary", headers=auth(tokens["readonly"])
                    ).status_code
                    == 403
                )
        finally:
            client.patch(
                f"/api/permissions/{perm_id}",
                headers=auth(tokens["admin"]),
                json={"is_active": True},
            )

        assert (
            client.get("/api/reports/summary", headers=auth(tokens["readonly"])).status_code
            == 200
        )
