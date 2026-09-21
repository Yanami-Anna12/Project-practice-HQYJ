"""初始化种子数据（幂等，可反复执行）。

灌入内容严格对齐需求文档第 2 节的权限矩阵：
    · 6 个权限点
    · 4 个内置角色（管理员 / 运营 / 供应商 / 只读）
    · 角色-权限绑定关系
    · 5 个演示账号（含一个多角色账号，用于验证 R1 并集）
    · 少量商品与订单演示数据

幂等策略：全部按业务唯一键（code / username / sku / order_no）做 upsert，
          已存在则更新，不存在则插入。所以可以随时重跑，不用先清库。

运行：  python seed.py
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from app import models  # noqa: F401  （注册所有表）
from app.config import settings
from app.database import Base, SessionLocal, create_all_tables, engine, ensure_database_exists
from app.models import Order, Permission, Product, Role, RolePermission, User, UserRole
from app.security import hash_password
from app.services import audit

logging.basicConfig(level=logging.INFO, format="%(levelname)-7s %(message)s")
logger = logging.getLogger("seed")


# ---------------------------------------------------------------------------
# 1) 权限点定义（需求文档第 2 节的六行）
# ---------------------------------------------------------------------------
PERMISSIONS: list[dict[str, str]] = [
    {"code": "products:read", "name": "查看商品", "module": "products"},
    {"code": "products:edit", "name": "编辑商品", "module": "products"},
    {"code": "orders:read", "name": "查看订单", "module": "orders"},
    {"code": "reports:view", "name": "查看报表", "module": "reports"},
    {"code": "users:manage", "name": "用户与权限管理", "module": "users"},
    {"code": "settings:edit", "name": "系统设置", "module": "settings"},
]

# ---------------------------------------------------------------------------
# 2) 角色定义
# ---------------------------------------------------------------------------
ROLES: list[dict[str, str]] = [
    {"code": "admin", "name": "管理员", "description": "拥有全部权限，可管理用户、角色与权限点"},
    {"code": "operator", "name": "运营", "description": "可查看与编辑商品，可查看订单与报表"},
    {"code": "supplier", "name": "供应商", "description": "仅可查看商品"},
    {"code": "readonly", "name": "只读", "description": "只读访问订单与报表"},
]

# ---------------------------------------------------------------------------
# 3) ★ 角色-权限绑定矩阵 —— 严格抄自需求文档第 2 节的表格
# ---------------------------------------------------------------------------
#              products:read  products:edit  orders:read  reports:view  users:manage  settings:edit
# 管理员            ✓              ✓             ✓            ✓             ✓             ✓
# 运营              ✓              ✓             ✓            ✓             —             —
# 供应商            ✓              —             —            —             —             —
# 只读              ✓              —             ✓            ✓             —             —
ROLE_PERMISSIONS: dict[str, list[str]] = {
    "admin": [
        "products:read",
        "products:edit",
        "orders:read",
        "reports:view",
        "users:manage",
        "settings:edit",
    ],
    "operator": [
        "products:read",
        "products:edit",
        "orders:read",
        "reports:view",
    ],
    "supplier": [
        "products:read",
    ],
    "readonly": [
        "products:read",
        "orders:read",
        "reports:view",
    ],
}

# ---------------------------------------------------------------------------
# 4) 演示账号
# ---------------------------------------------------------------------------
# 密码策略：admin 用独立密码（避免全站同一个默认口令），其余演示号统一 123456。
# 注意 multi 账号绑定了两个角色 —— 这是验证 R1「多角色并集」的关键样本。
USERS: list[dict[str, object]] = [
    {
        "username": "admin",
        "nickname": "系统管理员",
        "password": settings.ADMIN_INIT_PASSWORD,
        "roles": ["admin"],
        "note": "全权限，管理端演示",
    },
    {
        "username": "operator",
        "nickname": "运营小王",
        "password": settings.DEMO_PASSWORD,
        "roles": ["operator"],
        "note": "运营",
    },
    {
        "username": "supplier",
        "nickname": "供应商小李",
        "password": settings.DEMO_PASSWORD,
        "roles": ["supplier"],
        "note": "验收：POST /api/products 应 403",
    },
    {
        "username": "readonly",
        "nickname": "只读观察员",
        "password": settings.DEMO_PASSWORD,
        "roles": ["readonly"],
        "note": "验收：GET 200 / POST 403",
    },
    {
        "username": "multi",
        "nickname": "多角色用户",
        "password": settings.DEMO_PASSWORD,
        "roles": ["operator", "readonly"],
        "note": "★ 验收 R1：运营 + 只读，权限应为两者并集（4 个权限点）",
    },
]

# ---------------------------------------------------------------------------
# 5) 业务演示数据
# ---------------------------------------------------------------------------
PRODUCTS: list[dict[str, object]] = [
    {"name": "机械键盘 K8", "sku": "KB-K8-001", "price": 399.00, "stock": 120},
    {"name": "人体工学椅 E3", "sku": "CH-E3-001", "price": 1299.00, "stock": 35},
    {"name": "4K 显示器 27 寸", "sku": "MN-27-4K", "price": 1899.00, "stock": 18},
]

ORDERS: list[dict[str, object]] = [
    {"order_no": "SO2024001", "customer": "北京华远科技", "amount": 3198.00, "status": "paid"},
    {"order_no": "SO2024002", "customer": "上海启明贸易", "amount": 799.00, "status": "pending"},
    {"order_no": "SO2024003", "customer": "深圳维新电子", "amount": 5697.00, "status": "shipped"},
]


# ---------------------------------------------------------------------------
# 灌数据（全部 upsert，幂等）
# ---------------------------------------------------------------------------
def seed_permissions(db) -> dict[str, Permission]:
    result: dict[str, Permission] = {}
    for item in PERMISSIONS:
        perm = db.execute(
            select(Permission).where(Permission.code == item["code"])
        ).scalar_one_or_none()
        if perm is None:
            perm = Permission(**item, is_active=True)
            db.add(perm)
            logger.info("新增权限点 %s（%s）", item["code"], item["name"])
        else:
            perm.name = item["name"]
            perm.module = item["module"]
        result[item["code"]] = perm
    db.flush()
    return result


def seed_roles(db) -> dict[str, Role]:
    result: dict[str, Role] = {}
    for item in ROLES:
        role = db.execute(select(Role).where(Role.code == item["code"])).scalar_one_or_none()
        if role is None:
            role = Role(**item, is_active=True)
            db.add(role)
            logger.info("新增角色 %s（%s）", item["code"], item["name"])
        else:
            role.name = item["name"]
            role.description = item["description"]
        result[item["code"]] = role
    db.flush()
    return result


def seed_role_permissions(db, roles: dict[str, Role], perms: dict[str, Permission]) -> None:
    for role_code, perm_codes in ROLE_PERMISSIONS.items():
        role = roles[role_code]
        wanted = {perms[c].id for c in perm_codes}

        existing = {
            rp.permission_id
            for rp in db.execute(
                select(RolePermission).where(RolePermission.role_id == role.id)
            ).scalars()
        }

        for pid in sorted(wanted - existing):
            db.add(RolePermission(role_id=role.id, permission_id=pid))
            logger.info("  绑定 %s -> %s", role_code, perms_by_id(perms, pid))
        for pid in sorted(existing - wanted):
            rp = db.execute(
                select(RolePermission).where(
                    RolePermission.role_id == role.id,
                    RolePermission.permission_id == pid,
                )
            ).scalar_one()
            db.delete(rp)
            logger.info("  解绑 %s -> %s", role_code, perms_by_id(perms, pid))
    db.flush()


def perms_by_id(perms: dict[str, Permission], pid: int) -> str:
    for code, p in perms.items():
        if p.id == pid:
            return code
    return str(pid)


def seed_users(db, roles: dict[str, Role]) -> dict[str, User]:
    result: dict[str, User] = {}
    for item in USERS:
        username = str(item["username"])
        user = db.execute(
            select(User).where(User.username == username)
        ).scalar_one_or_none()
        if user is None:
            user = User(
                username=username,
                nickname=str(item["nickname"]),
                password_hash=hash_password(str(item["password"])),
                is_active=True,
            )
            db.add(user)
            logger.info("新增用户 %s（%s）", username, item["note"])
        else:
            user.nickname = str(item["nickname"])
        result[username] = user
    db.flush()

    # 角色绑定
    for item in USERS:
        username = str(item["username"])
        user = result[username]
        wanted = {roles[c].id for c in item["roles"]}  # type: ignore[union-attr]
        existing = {
            ur.role_id
            for ur in db.execute(select(UserRole).where(UserRole.user_id == user.id)).scalars()
        }

        if wanted != existing:
            for rid in sorted(existing - wanted):
                ur = db.execute(
                    select(UserRole).where(
                        UserRole.user_id == user.id, UserRole.role_id == rid
                    )
                ).scalar_one()
                db.delete(ur)
            for rid in sorted(wanted - existing):
                db.add(UserRole(user_id=user.id, role_id=rid))
            logger.info(
                "  用户 %s 角色绑定调整为 %s", username, " + ".join(item["roles"])  # type: ignore[arg-type]
            )
    db.flush()
    return result


def seed_business(db, users: dict[str, User]) -> None:
    admin = users["admin"]
    for item in PRODUCTS:
        exists = db.execute(
            select(Product).where(Product.sku == item["sku"])
        ).scalar_one_or_none()
        if exists is None:
            db.add(Product(**item, created_by=admin.id))  # type: ignore[arg-type]
    for item in ORDERS:
        exists = db.execute(
            select(Order).where(Order.order_no == item["order_no"])
        ).scalar_one_or_none()
        if exists is None:
            db.add(Order(**item))  # type: ignore[arg-type]
    db.flush()
    logger.info("业务演示数据已就绪（商品 %d 条、订单 %d 条）", len(PRODUCTS), len(ORDERS))


def print_matrix(db) -> None:
    """打印权限矩阵，便于直接对照需求文档第 2 节的表格逐格核验。"""
    from app.services import rbac

    print()
    print("=" * 88)
    print("权限矩阵（由数据库实际绑定关系实时计算得出）")
    print("=" * 88)

    perm_codes = [p["code"] for p in PERMISSIONS]
    roles = rbac.list_roles(db)
    header = f"{'权限点':<16}" + "".join(f"{r.name:<10}" for r in roles)
    print(header)
    print("-" * 88)
    for code in perm_codes:
        row = f"{code:<16}"
        for role in roles:
            row += f"{'✓' if code in role.permission_codes else '—':<10}"
        print(row)

    print("-" * 88)
    print("\n演示账号（密码见下方说明）")
    print("-" * 88)
    print(f"{'用户名':<12}{'昵称':<14}{'角色':<26}{'有效权限'}")
    for item in USERS:
        username = str(item["username"])
        user = db.execute(select(User).where(User.username == username)).scalar_one()
        codes = sorted(rbac.effective_permissions(db, user.id))
        role_codes = rbac.get_user_role_codes(db, user.id)
        print(
            f"{username:<12}{str(item['nickname']):<14}"
            f"{' + '.join(role_codes):<26}{', '.join(codes) if codes else '(无)'}"
        )

    admin_pw = settings.ADMIN_INIT_PASSWORD
    demo_pw = settings.DEMO_PASSWORD
    print("-" * 88)
    print(f"admin 的密码：{admin_pw}")
    print(f"其余演示账号（operator/supplier/readonly/multi）的密码：{demo_pw}")
    print("=" * 88)


def main() -> int:
    logger.info("目标数据库：%s", settings.url_safe())

    ensure_database_exists()
    create_all_tables()

    with SessionLocal() as db:
        perms = seed_permissions(db)
        roles = seed_roles(db)
        seed_role_permissions(db, roles, perms)
        users = seed_users(db, roles)
        seed_business(db, users)

        # R5：初始化动作也留审计痕迹（actor 为 system）
        audit.append_audit(
            db,
            action="system.seed",
            target_type="system",
            target_name="seed",
            detail={
                "权限点": len(PERMISSIONS),
                "角色": len(ROLES),
                "演示用户": len(USERS),
                "说明": "初始化种子数据（幂等执行）",
            },
        )

        db.commit()
        print_matrix(db)

    logger.info("种子数据初始化完成 ✓")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - 便于定位初始化失败原因
        logger.error("初始化失败：%s", exc)
        raise
