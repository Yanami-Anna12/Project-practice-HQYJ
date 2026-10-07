"""FastAPI 依赖：当前用户解析与权限校验。

★ 这里是权限系统的**最终防线**。前端的菜单裁剪、按钮隐藏都只是体验优化 ——
  真正决定一个请求能否通过的是 require_permission()。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AuthError, PermissionDeniedError
from app.models import SysUser
from app.security import decode_access_token
from app.services.rbac import get_effective_permissions


def _extract_token(request: Request) -> str | None:
    """从 Authorization: Bearer <token> 取 token。"""
    header = request.headers.get("Authorization") or ""
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return None


def get_current_user(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> SysUser:
    """解析当前登录用户。任何环节不通过都抛 401。

    刻意**不**区分「token 缺失」「token 无效」「用户被停用」的具体原因给前端 ——
    统一提示「登录已失效」，避免向未登录者泄露账号是否存在。
    真实原因只写日志。
    """
    token = _extract_token(request)
    if not token:
        raise AuthError("未登录")

    user_id = decode_access_token(token)
    if user_id is None:
        raise AuthError("登录已失效，请重新登录")

    user = db.get(SysUser, user_id)
    if user is None or not user.is_active:
        raise AuthError("登录已失效，请重新登录")

    return user


CurrentUser = Annotated[SysUser, Depends(get_current_user)]
DbSession = Annotated[Session, Depends(get_db)]


def require_permission(code: str) -> Callable[..., SysUser]:
    """生成一个「要求指定权限点」的依赖。

    用法：
        @router.get("/stores", dependencies=[Depends(require_permission("stores:read"))])

    或者在需要拿到用户对象时：
        def handler(user: Annotated[SysUser, Depends(require_permission("stores:read"))]):
    """

    def _dependency(
        user: Annotated[SysUser, Depends(get_current_user)],
        db: Annotated[Session, Depends(get_db)],
    ) -> SysUser:
        if code not in get_effective_permissions(db, user):
            raise PermissionDeniedError(f"没有权限 {code}")
        return user

    return _dependency


def require_any_permission(*codes: str) -> Callable[..., SysUser]:
    """要求拥有其中任意一个权限点。"""

    def _dependency(
        user: Annotated[SysUser, Depends(get_current_user)],
        db: Annotated[Session, Depends(get_db)],
    ) -> SysUser:
        perms = set(get_effective_permissions(db, user))
        if not perms.intersection(codes):
            raise PermissionDeniedError(f"需要以下权限之一：{'、'.join(codes)}")
        return user

    return _dependency
