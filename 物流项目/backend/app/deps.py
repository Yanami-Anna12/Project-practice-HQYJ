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
from app.models import Driver, SysUser
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


# 司机端权限点。与 seed.py 的 PERMISSIONS 保持一致。
MOBILE_PERMISSION = "mobile:use"


def is_driver_account(db: Session, user: SysUser) -> bool:
    """当前账号是否已绑定司机档案（md_driver.user_id）。

    单独抽出来而不是内联：这段查询是「司机端准入兜底」的唯一判断依据，
    独立命名后便于阅读与将来复用（例如需要在别处判断身份时）。
    """
    return (
        db.query(Driver)
        .filter(Driver.user_id == user.id, Driver.is_active.is_(True))
        .one_or_none()
        is not None
    )


def require_mobile_access(
    user: Annotated[SysUser, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SysUser:
    """司机端（小程序）接口的准入依赖。

    放行条件满足其一即可：

      1. 持有 `mobile:use` 权限点（司机角色默认拥有；管理员角色是 `*`，自动包含）
      2. 账号已绑定司机档案（md_driver.user_id = 当前用户）

    ★ 第 2 条是刻意加的「兜底」：司机是**业务身份**，不一定有人记得给它的账号
      配上权限点。若只认权限点，一个建好司机档案、却没配角色的账号会 403 ——
      而它显然应该能看自己的趟次。反过来，调度员/管理员走第 1 条，调用不报错。
    """
    if MOBILE_PERMISSION in get_effective_permissions(db, user):
        return user
    if is_driver_account(db, user):
        return user
    raise PermissionDeniedError(f"没有权限 {MOBILE_PERMISSION}（该接口仅限司机端使用）")
