"""用户管理接口。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.config import settings
from app.deps import DbSession, require_permission
from app.errors import ConflictError, NotFoundError
from app.models import SysRole, SysUser
from app.schemas import (
    AssignRolesRequest,
    AssignRolesResponse,
    ResetPasswordResponse,
    ToggleResponse,
    UserOut,
)
from app.security import hash_password
from app.services.audit import append_audit
from app.services.rbac import get_effective_permissions, get_role_codes

router = APIRouter(prefix="/users", tags=["用户管理"])

Reader = Annotated[SysUser, Depends(require_permission("users:read"))]
Manager = Annotated[SysUser, Depends(require_permission("users:manage"))]


def _to_out(db, user: SysUser, *, current_id: int) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        nickname=user.nickname,
        dept=user.dept,
        phone=user.phone,
        is_active=user.is_active,
        roles=get_role_codes(user),
        permissions=get_effective_permissions(db, user),
        created_at=user.created_at,
        is_self=user.id == current_id,
    )


@router.get("", response_model=list[UserOut], summary="用户列表")
def list_users(db: DbSession, actor: Reader) -> list[UserOut]:
    users = db.query(SysUser).order_by(SysUser.id).all()
    return [_to_out(db, u, current_id=actor.id) for u in users]


@router.put("/{user_id}/roles", response_model=AssignRolesResponse, summary="分配角色")
def assign_roles(
    user_id: int, payload: AssignRolesRequest, db: DbSession, actor: Manager
) -> AssignRolesResponse:
    target = db.get(SysUser, user_id)
    if target is None:
        raise NotFoundError("用户不存在")

    roles = (
        db.query(SysRole).filter(SysRole.code.in_(payload.roles)).all() if payload.roles else []
    )
    missing = set(payload.roles) - {r.code for r in roles}
    if missing:
        raise NotFoundError(f"角色不存在：{'、'.join(sorted(missing))}")

    before = get_role_codes(target)
    target.roles = roles
    db.commit()

    perms = get_effective_permissions(db, target)
    append_audit(
        db,
        actor=actor,
        action="user.assign_roles",
        target_type="user",
        target_name=target.username,
        detail={
            "角色": before or ["（无）"],
            "变更为": payload.roles or ["（无）"],
            "有效权限数": len(perms),
        },
    )
    return AssignRolesResponse(id=target.id, roles=get_role_codes(target), permissions=perms)


@router.put("/{user_id}/active", response_model=ToggleResponse, summary="启用/停用用户")
def toggle_active(user_id: int, db: DbSession, actor: Manager) -> ToggleResponse:
    target = db.get(SysUser, user_id)
    if target is None:
        raise NotFoundError("用户不存在")
    if target.id == actor.id:
        # 防止把自己锁在系统外
        raise ConflictError("不能停用当前登录账号")

    target.is_active = not target.is_active
    db.commit()
    append_audit(
        db,
        actor=actor,
        action="user.toggle",
        target_type="user",
        target_name=target.username,
        detail={"变更": "停用 → 正常" if target.is_active else "正常 → 停用"},
    )
    return ToggleResponse(id=target.id, is_active=target.is_active)


@router.post(
    "/{user_id}/reset-password", response_model=ResetPasswordResponse, summary="重置密码"
)
def reset_password(user_id: int, db: DbSession, actor: Manager) -> ResetPasswordResponse:
    target = db.get(SysUser, user_id)
    if target is None:
        raise NotFoundError("用户不存在")

    initial = settings.DEMO_PASSWORD
    target.password_hash = hash_password(initial)
    db.commit()
    append_audit(
        db,
        actor=actor,
        action="user.reset_password",
        target_type="user",
        target_name=target.username,
        detail={"说明": "密码已重置为初始密码"},
    )
    return ResetPasswordResponse(id=target.id, password=initial)
