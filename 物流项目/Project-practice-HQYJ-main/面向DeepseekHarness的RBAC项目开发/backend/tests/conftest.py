"""pytest 公共夹具（fixtures）。

★ 测试策略：直接打真实 MySQL 库，不做 mock。
  理由：本项目要验收的核心是 R3（数据库外键 RESTRICT）、R4（实时查库无缓存）
  这类**数据层行为**。一旦把数据库 mock 掉，恰恰把要验证的东西验证没了。
  所以测试跑在真实库上，靠 seed 保证数据确定，靠夹具保证用后恢复。

夹具分层：
    _seed_once        会话级   确保库与种子数据就绪（幂等）
    restored_roles    会话级   测试结束后把四个内置角色恢复原状
    _cleanup_probes   函数级   自动清理测试创建的角色/权限点/商品
    client            函数级   TestClient
    tokens            会话级   五类账号的 Token
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

# 让 tests/ 下的测试能 import 到 app 包
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import settings  # noqa: E402
from app.database import SessionLocal, create_all_tables, ensure_database_exists  # noqa: E402
from app.main import app as fastapi_app  # noqa: E402
from app.models import Permission, Product, Role, RolePermission, UserRole  # noqa: E402

# 测试期间可能被创建的临时对象，用统一前缀便于识别与清理
PROBE_ROLE_PREFIX = "probe_"
PROBE_PERM_PREFIX = "probe:"
PROBE_SKU_PREFIX = "PROBE-"


def pytest_configure(config: pytest.Config) -> None:
    """在测试会话开始前打印关键环境信息，便于排查失败原因。"""
    print(f"\n[conftest] 测试数据库：{settings.url_safe()}")


# ---------------------------------------------------------------------------
# 会话级：种子数据与现场恢复
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session", autouse=True)
def _seed_once() -> None:
    """确保库、表、种子数据都就绪（seed 是幂等的，反复执行安全）。"""
    ensure_database_exists()
    create_all_tables()

    # 直接调用 seed.main() 会打印一大张表格，这里只跑数据部分
    import seed as seed_module

    with SessionLocal() as db:
        perms = seed_module.seed_permissions(db)
        roles = seed_module.seed_roles(db)
        seed_module.seed_role_permissions(db, roles, perms)
        users = seed_module.seed_users(db, roles)
        seed_module.seed_business(db, users)
        db.commit()

    # 自检：四个内置角色必须都在，否则后续断言全部无意义
    with SessionLocal() as db:
        codes = {r.code for r in db.execute(select(Role)).scalars()}
    required = {"admin", "operator", "supplier", "readonly"}
    missing = required - codes
    assert not missing, f"种子数据缺少内置角色：{missing}"


@pytest.fixture(scope="session", autouse=True)
def restored_roles(_seed_once: None):
    """测试结束后把四个内置角色的权限绑定与启用状态恢复原状。

    为什么需要：验收标准 6 会停用权限点、R3 的测试会增删角色绑定，
    这些都会改动共享数据。若不恢复，第二次跑测试就会因为上一次的残留而失败。
    """
    yield

    import seed as seed_module

    with SessionLocal() as db:
        perms = seed_module.seed_permissions(db)
        roles = seed_module.seed_roles(db)
        for role in roles.values():
            role.is_active = True
        for perm in perms.values():
            perm.is_active = True
        db.flush()
        seed_module.seed_role_permissions(db, roles, perms)
        db.commit()


# ---------------------------------------------------------------------------
# 函数级：清理测试产生的临时对象
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _cleanup_probes():
    """每个测试前后都清理带探针前缀的临时数据。"""
    def _clean() -> None:
        with SessionLocal() as db:
            # 临时角色：先删绑定再删角色（角色侧被引用时要先解绑）
            probe_roles = list(
                db.execute(select(Role).where(Role.code.like(f"{PROBE_ROLE_PREFIX}%"))).scalars()
            )
            for role in probe_roles:
                db.execute(delete(UserRole).where(UserRole.role_id == role.id))
                db.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
                db.delete(role)
            # 临时权限点
            for perm in db.execute(
                select(Permission).where(Permission.code.like(f"{PROBE_PERM_PREFIX}%"))
            ).scalars():
                db.execute(delete(RolePermission).where(RolePermission.permission_id == perm.id))
                db.delete(perm)
            # 临时商品
            db.execute(delete(Product).where(Product.sku.like(f"{PROBE_SKU_PREFIX}%")))
            db.commit()

    _clean()
    yield
    _clean()


# ---------------------------------------------------------------------------
# 客户端
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def client() -> TestClient:
    """TestClient。

    刻意不传 raise_server_exceptions=False：
    那会把服务端未处理异常伪装成 500 响应，掩盖真实 bug。
    让异常直接抛出，测试失败时能看到完整堆栈。
    """
    return TestClient(fastapi_app)


# ---------------------------------------------------------------------------
# 账号与 Token
# ---------------------------------------------------------------------------
DEMO_ACCOUNTS: dict[str, str] = {
    "admin": settings.ADMIN_INIT_PASSWORD,
    "operator": settings.DEMO_PASSWORD,
    "supplier": settings.DEMO_PASSWORD,
    "readonly": settings.DEMO_PASSWORD,
    "multi": settings.DEMO_PASSWORD,
}


def login(client: TestClient, username: str, password: str | None = None) -> dict:
    """登录并返回响应 JSON。密码缺省时按账号类型取默认值。"""
    pwd = password if password is not None else DEMO_ACCOUNTS[username]
    resp = client.post("/api/auth/login", json={"username": username, "password": pwd})
    assert resp.status_code == 200, f"{username} 登录失败：{resp.status_code} {resp.text}"
    return resp.json()


@pytest.fixture(scope="session")
def tokens(client: TestClient) -> dict[str, str]:
    """五类演示账号的 Token，整个会话只登录一次。"""
    return {name: login(client, name)["access_token"] for name in DEMO_ACCOUNTS}


@pytest.fixture
def auth():
    """返回一个「生成认证头」的小工具：auth(tokens['admin']) → {"Authorization": ...}。"""
    def _make(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    return _make
