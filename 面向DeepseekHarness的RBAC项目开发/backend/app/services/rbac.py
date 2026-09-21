"""RBAC 授权核心：有效权限的实时计算（R1 / R2 / R3 / R4 都落在这个文件）。

全部权限语义集中在此处，路由层只调用不实现。这样做的好处是：
「权限是怎么算出来的」只有一个地方需要读、需要改、需要测试。

四条业务规则与代码的对应关系：

  R1 多角色并集   —— effective_permissions() 用 SELECT DISTINCT，
                     天然求并集；全程没有 min/交集/优先级逻辑。
  R2 默认拒绝     —— 权限点不存在 / 未配置 / 用户无角色，结果都是空集，
                     has_permission() 判断「不在集合中」→ 调用方一律 403。
  R3 删除角色保护 —— delete_role() 先数引用再删；数据库层还有 RESTRICT 兜底。
  R4 实时生效     —— 每次调用都重新查库，SQL 里用 is_active 过滤，
                     本模块「没有任何缓存」，包括 lru_cache / 全局字典 / 会话对象。
"""

from __future__ import annotations

import logging

from sqlalchemy import Select, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.errors import LastAdminError, NotFoundError, RoleInUseError, ValidationError
from app.models import Permission, Role, RolePermission, User, UserRole

logger = logging.getLogger(__name__)

# MySQL 外键「父行仍被子行引用」的错误码
MYSQL_ERR_ROW_IS_REFERENCED = 1451


# ---------------------------------------------------------------------------
# ★ R1 + R2 + R4 的核心查询
# ---------------------------------------------------------------------------
def _permissions_stmt(user_id: int) -> Select:
    """构造「求某用户有效权限码」的查询。

    这条 SQL 同时承载了三条规则，拆开看每一处 JOIN 条件都对应一条需求：

        SELECT DISTINCT p.code
        FROM user_roles ur
          JOIN roles             r  ON r.id  = ur.role_id       AND r.is_active = 1   -- R4
          JOIN role_permissions  rp ON rp.role_id = r.id
          JOIN permissions       p  ON p.id  = rp.permission_id AND p.is_active = 1   -- R4
        WHERE ur.user_id = :uid                                                       -- 谁

    · DISTINCT           → R1：多角色权限合并，并集而非取最严
    · r.is_active = 1    → R4：角色被停用，其权限整体退出并集
    · p.is_active = 1    → R4：权限点被停用，持有者立即失去该权限
    · 没有任何 ORM 关系懒加载 → 一条 SQL 出结果，避免 N+1
    """
    return (
        select(Permission.code)
        .distinct()
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(Role, Role.id == RolePermission.role_id)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(
            UserRole.user_id == user_id,
            Role.is_active.is_(True),
            Permission.is_active.is_(True),
        )
    )


def effective_permissions(db: Session, user_id: int) -> set[str]:
    """返回该用户的「有效权限码集合」。

    ★ 这是全系统唯一的权限真相来源。
      登录响应用它、/api/me/permissions 用它、authorize() 也用它。

    用户不存在、无角色、角色全停用、权限点全停用 —— 都返回空集合，
    调用方对空集合一律按 403 处理，这就是 R2 fail-closed 的落点。
    """
    codes = db.execute(_permissions_stmt(user_id)).scalars().all()
    return set(codes)


def has_permission(db: Session, user_id: int, permission_code: str) -> bool:
    """判断用户是否拥有指定权限。

    ★ R2 的关键设计：这里「不」去 permissions 表检查权限码是否存在。
      因为「权限点不存在」⇒「它必然不在有效权限集合里」⇒ 返回 False ⇒ 403。
      三种 fail-closed 情形（不存在 / 未配置 / 无角色）因此收敛成同一个判断，
      实现最简且不可能漏判。
    """
    return permission_code in effective_permissions(db, user_id)


# ---------------------------------------------------------------------------
# 角色与绑定关系读取
# ---------------------------------------------------------------------------
def get_user(db: Session, user_id: int) -> User | None:
    return db.get(User, user_id)


def get_user_by_username(db: Session, username: str) -> User | None:
    return db.execute(select(User).where(User.username == username)).scalar_one_or_none()


def get_user_roles(db: Session, user_id: int) -> list[Role]:
    """该用户绑定的角色（含已停用的，用于界面展示真实绑定情况）。"""
    stmt = (
        select(Role)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id)
        .order_by(Role.id)
    )
    return list(db.execute(stmt).scalars().all())


def get_user_role_codes(db: Session, user_id: int) -> list[str]:
    return [r.code for r in get_user_roles(db, user_id)]


def permissions_for_user_ids(db: Session, user_ids: list[int]) -> dict[int, set[str]]:
    """批量求多个用户的有效权限（用户列表页用，避免 N+1 查询）。"""
    if not user_ids:
        return {}
    stmt = (
        select(UserRole.user_id, Permission.code)
        .distinct()
        .join(Role, Role.id == UserRole.role_id)
        .join(RolePermission, RolePermission.role_id == Role.id)
        .join(Permission, Permission.id == RolePermission.permission_id)
        .where(
            UserRole.user_id.in_(user_ids),
            Role.is_active.is_(True),
            Permission.is_active.is_(True),
        )
    )
    result: dict[int, set[str]] = {uid: set() for uid in user_ids}
    for uid, code in db.execute(stmt).all():
        result[uid].add(code)
    return result


def count_role_users(db: Session, role_id: int) -> int:
    """统计某角色被多少个用户引用（R3 的判定依据）。"""
    return db.execute(
        select(func.count()).select_from(UserRole).where(UserRole.role_id == role_id)
    ).scalar_one()


def role_usage_counts(db: Session) -> dict[int, int]:
    """统计所有角色的绑定用户数，一次查询搞定（角色列表页用）。"""
    rows = db.execute(
        select(UserRole.role_id, func.count()).group_by(UserRole.role_id)
    ).all()
    return {role_id: count for role_id, count in rows}


def get_role_by_code(db: Session, code: str) -> Role | None:
    return db.execute(select(Role).where(Role.code == code)).scalar_one_or_none()


def get_role(db: Session, role_id: int) -> Role:
    role = db.get(Role, role_id)
    if role is None:
        raise NotFoundError("角色不存在")
    return role


def list_roles(db: Session) -> list[Role]:
    stmt = (
        select(Role)
        .options(
            joinedload(Role.role_permissions).joinedload(RolePermission.permission),
        )
        .order_by(Role.id)
    )
    return list(db.execute(stmt).unique().scalars().all())


def list_permissions(db: Session) -> list[Permission]:
    return list(db.execute(select(Permission).order_by(Permission.module, Permission.id)).scalars())


def get_permission_by_code(db: Session, code: str) -> Permission | None:
    return db.execute(select(Permission).where(Permission.code == code)).scalar_one_or_none()


def resolve_permission_codes(db: Session, codes: list[str]) -> list[Permission]:
    """把权限码列表解析成 Permission 对象列表。

    遇到不存在的权限码直接报 400 —— 这是「配置期」的校验，
    与 R2 的「运行期默认拒绝」是两件不同的事：
      · 配置角色时写错了权限码，应当立即报错让人发现（本函数）
      · 运行时某个权限码恰好不存在，应当静默拒绝访问（has_permission）
    """
    if not codes:
        return []
    unique_codes = list(dict.fromkeys(codes))  # 去重但保持顺序
    found = list(
        db.execute(select(Permission).where(Permission.code.in_(unique_codes))).scalars()
    )
    missing = sorted(set(unique_codes) - {p.code for p in found})
    if missing:
        raise NotFoundError(f"权限点不存在：{', '.join(missing)}")
    return found


# ---------------------------------------------------------------------------
# 角色-权限绑定
# ---------------------------------------------------------------------------
def set_role_permissions(db: Session, role: Role, permission_codes: list[str]) -> None:
    """全量重置角色的权限绑定（不是增量追加）。

    选择全量覆盖而非增量，是为了让接口语义无歧义：
    客户端提交什么，角色最终就是什么。前端不需要先查差集再逐个增删。
    """
    permissions = resolve_permission_codes(db, permission_codes)

    # 先清空再插入。同一事务内完成，外部看不到中间态。
    db.execute(delete(RolePermission).where(RolePermission.role_id == role.id))
    for perm in permissions:
        db.add(RolePermission(role_id=role.id, permission_id=perm.id))
    db.flush()
    # 让 role.role_permissions 的内存状态与数据库一致，避免后续读到旧数据
    db.refresh(role)


# ---------------------------------------------------------------------------
# 用户-角色绑定
# ---------------------------------------------------------------------------
def assert_admin_not_locked_out(db: Session, user: User, new_role_codes: list[str]) -> None:
    """防止把系统里最后一个管理员改绑成非管理员。

    这不是需求文档里的规则，是我加的保护。理由：
    R3 提醒我们「角色不能被删得让用户悬空」，而更严重的不可逆故障是
    「系统失去最后一个管理员」—— 一旦发生，任何管理接口都会 403，
    只能手工改数据库才能恢复。这类自锁必须提前拦。
    """
    admin_role = get_role_by_code(db, "admin")
    if admin_role is None or admin_role.id is None:
        return

    currently_admin = admin_role.id in {r.id for r in get_user_roles(db, user.id)}
    will_still_be_admin = "admin" in set(new_role_codes)
    if not currently_admin or will_still_be_admin:
        return

    admin_user_count = count_role_users(db, admin_role.id)
    if admin_user_count <= 1:
        raise LastAdminError()


def set_user_roles(db: Session, user: User, role_codes: list[str]) -> list[Role]:
    """全量重置用户的角色绑定，返回绑定后的角色列表。

    ★ R1 的写入侧：这里允许同一用户绑定任意多个角色，
      读取侧 effective_permissions() 会把它们并起来。
      整个链路没有任何「多角色取最严」的逻辑——那是对 RBAC 的常见误解。
    """
    if not role_codes:
        # 允许清空角色（用户随即失去全部权限）。这是 R2 的合法输入：
        # 无角色用户不是错误状态，而是「一个权限都没有」的正常状态。
        roles: list[Role] = []
    else:
        unique_codes = list(dict.fromkeys(role_codes))
        roles = list(db.execute(select(Role).where(Role.code.in_(unique_codes))).scalars())
        missing = sorted(set(unique_codes) - {r.code for r in roles})
        if missing:
            raise NotFoundError(f"角色不存在：{', '.join(missing)}")

        inactive = [r.code for r in roles if not r.is_active]
        if inactive:
            raise ValidationError(f"角色已停用，无法分配：{', '.join(inactive)}")

    assert_admin_not_locked_out(db, user, [r.code for r in roles])

    db.execute(delete(UserRole).where(UserRole.user_id == user.id))
    for role in roles:
        db.add(UserRole(user_id=user.id, role_id=role.id))
    db.flush()
    return roles


# ---------------------------------------------------------------------------
# R3 删除角色保护
# ---------------------------------------------------------------------------
def delete_role(db: Session, role_id: int) -> str:
    """删除角色，返回被删除角色的 code。

    ★ R3：仍被用户引用时抛 RoleInUseError（→ 409，文案含绑定用户数），
      绝不级联清除 user_roles。

    双保险设计：
      第一道 —— 应用层先 COUNT 引用数，>0 就带着具体数字报 409（能给出友好文案）；
      第二道 —— 数据库外键 ON DELETE RESTRICT，万一应用层逻辑被改坏，
                或并发场景下计数后有人插入了新引用，MySQL 会用 1451 拒绝，
                这里捕获后同样转成 409。
    """
    role = get_role(db, role_id)

    user_count = count_role_users(db, role_id)
    if user_count > 0:
        raise RoleInUseError(user_count)

    code = role.code
    db.delete(role)
    try:
        db.flush()
    except IntegrityError as exc:
        # 走到这里说明应用层计数与实际不符（并发插入新引用，或逻辑被改坏）。
        # 数据库替我们守住了底线，翻译成同样的 409 语义。
        db.rollback()
        if getattr(exc.orig, "args", None) and exc.orig.args[0] == MYSQL_ERR_ROW_IS_REFERENCED:
            logger.warning("数据库外键拒绝了角色 %s 的删除（应用层计数未拦住）", code)
            raise RoleInUseError(count_role_users(db, role_id)) from exc
        raise
    return code
