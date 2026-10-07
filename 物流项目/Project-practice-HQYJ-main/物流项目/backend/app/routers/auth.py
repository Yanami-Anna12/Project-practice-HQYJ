"""认证接口：登录、登出、当前用户、菜单。"""

from __future__ import annotations

from fastapi import APIRouter

from app.deps import CurrentUser, DbSession
from app.errors import AuthError
from app.menus import build_menus
from app.models import SysUser
from app.schemas import LoginRequest, LoginResponse, MenuNode, UserProfile
from app.security import create_access_token, verify_password
from app.services.audit import append_audit
from app.services.rbac import (
    get_active_role_names,
    get_effective_permissions,
    get_role_codes,
)

router = APIRouter(tags=["认证"])


def build_profile(db, user: SysUser) -> UserProfile:
    """组装返回给前端的用户信息（不含任何密码字段）。"""
    return UserProfile(
        id=user.id,
        username=user.username,
        nickname=user.nickname,
        dept=user.dept,
        phone=user.phone,
        is_active=user.is_active,
        roles=get_role_codes(user),
        role_names=get_active_role_names(user),
        permissions=get_effective_permissions(db, user),
    )


@router.post("/auth/login", response_model=LoginResponse, summary="登录")
def login(payload: LoginRequest, db: DbSession) -> LoginResponse:
    user = db.query(SysUser).filter(SysUser.username == payload.username).one_or_none()

    # 账号不存在 / 密码错误 / 账号停用 —— 三种情况都写审计，但对外提示保持克制
    if user is None or not verify_password(payload.password, user.password_hash):
        append_audit(
            db,
            actor=user,
            actor_name=payload.username,
            action="auth.login_failed",
            target_type="user",
            target_name=payload.username,
            detail={"原因": "账号不存在" if user is None else "密码错误"},
        )
        raise AuthError("账号不存在" if user is None else "密码错误")

    if not user.is_active:
        append_audit(
            db,
            actor=user,
            action="auth.login_failed",
            target_type="user",
            target_name=user.username,
            detail={"原因": "账号已停用"},
        )
        raise AuthError("账号已被停用，请联系管理员")

    token = create_access_token(user.id)
    append_audit(
        db,
        actor=user,
        action="auth.login",
        target_type="user",
        target_name=user.username,
        detail={"结果": "登录成功"},
    )
    return LoginResponse(token=token, user=build_profile(db, user))


@router.post("/auth/logout", summary="登出")
def logout(user: CurrentUser, db: DbSession) -> dict:
    """JWT 是无状态的，服务端不维护会话，登出由前端清除 Token。

    这里只记一条审计，便于追溯。
    """
    append_audit(
        db,
        actor=user,
        action="auth.logout",
        target_type="user",
        target_name=user.username,
        detail={},
    )
    return {"ok": True}


@router.get("/me", response_model=UserProfile, summary="当前用户信息")
def read_me(user: CurrentUser, db: DbSession) -> UserProfile:
    return build_profile(db, user)


@router.get("/me/menus", response_model=list[MenuNode], summary="当前用户可见菜单")
def read_menus(user: CurrentUser, db: DbSession) -> list[MenuNode]:
    """按权限裁剪后的菜单树。前端侧边栏直接渲染本接口的结果。"""
    perms = set(get_effective_permissions(db, user))
    return [MenuNode(**node) for node in build_menus(perms)]
