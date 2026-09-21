"""认证接口：登录。

POST /api/auth/login
    公开接口（不需要 Token）。
    成功返回 JWT + 该用户的有效权限集合。

★ 关于响应里的 permissions 字段，务必理解它的定位：
    它**只是给前端渲染菜单和按钮用的**，是「服务端主动告诉前端该怎么画界面」。
    后端任何一个接口都不会读取这个字段，更不会信任它。
    前端可以随意篡改它把按钮显示出来，但请求到了 authorize() 依然会被拒绝。

  这就是需求文档「菜单和按钮的隐藏仅作为体验优化，后端接口始终是最终防线」
  这句话在代码上的确切含义。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.errors import UnauthorizedError
from app.models import User
from app.schemas import LoginRequest, LoginResponse, UserBrief
from app.security import create_access_token, verify_password
from app.services import audit, rbac

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["认证"])


@router.post(
    "/login",
    response_model=LoginResponse,
    summary="登录",
    description="校验用户名密码，返回 JWT Token 及该用户的有效权限集合（仅用于前端渲染）。",
)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    user: User | None = rbac.get_user_by_username(db, payload.username)

    # 统一失败路径：用户名不存在与密码错误返回完全相同的 401 响应，
    # 避免通过响应差异探测「哪些用户名存在」。
    if user is None or not verify_password(payload.password, user.password_hash):
        # 审计「登录失败」但不记录密码本身，只记用户名与来源
        audit.append_audit(
            db,
            action=audit.ACTION_AUTH_LOGIN_FAILED,
            actor_name=payload.username,
            target_type="user",
            target_name=payload.username,
            detail={"原因": "用户名或密码错误"},
        )
        db.commit()
        raise UnauthorizedError()

    if not user.is_active:
        audit.append_audit(
            db,
            action=audit.ACTION_AUTH_LOGIN_FAILED,
            actor=user,
            target_type="user",
            target_id=user.id,
            target_name=user.username,
            detail={"原因": "账号已停用"},
        )
        db.commit()
        raise UnauthorizedError()

    # ★ 登录时才第一次计算权限，用于前端首屏渲染。
    #   注意这里算出的结果**不做任何存储**，后续每个请求都会重新算（R4）。
    permissions = rbac.effective_permissions(db, user.id)
    role_codes = rbac.get_user_role_codes(db, user.id)

    audit.append_audit(
        db,
        action=audit.ACTION_AUTH_LOGIN,
        actor=user,
        target_type="user",
        target_id=user.id,
        target_name=user.username,
        detail={"角色": role_codes, "权限数": len(permissions)},
    )
    db.commit()

    token = create_access_token(user.id, user.username)
    logger.info("登录成功：%s（角色 %s，权限 %d 个）", user.username, role_codes, len(permissions))

    return LoginResponse(
        access_token=token,
        token_type="bearer",
        expires_in=settings.JWT_EXPIRE_MINUTES * 60,
        user=UserBrief.model_validate(user),
        roles=role_codes,
        permissions=sorted(permissions),
    )
