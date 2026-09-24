"""权限计算。

★ 这是整个权限系统的核心，其他地方都不应重复实现这套逻辑。

有效权限的定义（与需求文档「多角色权限取并集」一致）：
    user.permissions = ⋃ { role.permissions | role ∈ user.roles, role.is_active }
                       过滤掉 is_active=False 的权限点

注意三个容易被忽略的点：
  1. 角色被停用 → 该角色贡献的权限全部失效（不是取最严，是整块不参与并集）
  2. 权限点被停用 → 即使角色仍引用它，也不生效
  3. 用户没有任何角色 → 权限为空集，所有受保护接口都会 403
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SysPermission, SysRole, SysUser


def get_role_codes(user: SysUser) -> list[str]:
    """用户绑定的角色码（含已停用角色，用于展示真实绑定关系）。"""
    return sorted(r.code for r in user.roles)


def get_active_role_names(user: SysUser) -> list[str]:
    """启用角色的名称，用于前端顶栏展示。"""
    return [r.name for r in user.roles if r.is_active]


def get_effective_permissions(db: Session, user: SysUser) -> list[str]:
    """计算用户的有效权限码集合（并集，且只含启用的权限点）。"""
    role_ids = [r.id for r in user.roles if r.is_active]
    if not role_ids:
        return []

    rows = db.execute(
        select(SysPermission.code)
        .join(SysPermission.roles)
        .where(SysRole.id.in_(role_ids), SysPermission.is_active.is_(True))
        .distinct()
    ).scalars()
    return sorted(set(rows))


def get_role_permission_codes(db: Session, role: SysRole) -> list[str]:
    """单个角色的权限码（不过滤权限点启用状态，便于后台看到真实配置）。"""
    return sorted(p.code for p in role.permissions)


def count_role_users(db: Session, role: SysRole) -> int:
    """角色绑定的用户数，用于删除保护。"""
    return len(role.users)


def user_has_permission(db: Session, user: SysUser, code: str) -> bool:
    """单点权限判断。注意每次都会查库 —— 权限变更即时生效，不做缓存。"""
    return code in get_effective_permissions(db, user)
