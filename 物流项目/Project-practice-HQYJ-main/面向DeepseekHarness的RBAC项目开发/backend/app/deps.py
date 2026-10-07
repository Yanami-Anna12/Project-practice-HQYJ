"""鉴权依赖：requireAuth(401) → authorize(权限码)(403) → handler。

这是需求文档 4.3 要求的请求链路，也是整个系统的「最终防线」。

★ 三条必须记住的设计约束：

  1. 权限每次请求实时查库计算，不做任何缓存。
     实现方式：有效权限集合挂在 CurrentUser 上，而 CurrentUser 由本模块
     在每次请求中重新构造。不要用 lru_cache 包住它 —— 那会直接违反 R4。

  2. Token 里不带权限，只带 user_id。
     所以「停用权限点」或「改绑角色」在下一次请求就生效（R4），
     不需要等 Token 过期，也不需要踢人下线。

  3. 前端登录响应里返回的 permissions 仅供渲染界面，后端一概不信。
     客户端可以随意伪造该字段让按钮显示出来，但请求到达这里时，
     权限是重新查库算的 —— 这也是「前端隐藏只是体验优化」的技术含义。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import ForbiddenError, UnauthorizedError
from app.models import User
from app.security import decode_access_token
from app.services import rbac

logger = logging.getLogger(__name__)

# 仅用于 OpenAPI：声明「本接口需要 Bearer 认证」，让 /docs 出现 Authorize 按钮。
# 注意它**不作为 Depends 使用**（那样会走 FastAPI 的 async 依赖解析），
# 而是作为 security 元数据挂到路由上，见 main.py 的 include_router(..., security=...)。
bearer_scheme = HTTPBearer(auto_error=False, description="Bearer <JWT>")


@dataclass
class CurrentUser:
    """当前登录用户 + 本次请求实时算出的权限集合。

    这个对象是「认证」与「授权」的交接点：
      · 身份部分（id/username）来自 JWT
      · 权限部分（permissions/role_codes）来自本次请求的实时查库
    """

    id: int
    username: str
    nickname: str | None
    permissions: set[str] = field(default_factory=set)
    role_codes: list[str] = field(default_factory=list)

    def has(self, permission_code: str) -> bool:
        """是否拥有指定权限。注意「权限码不存在」时这里自然是 False → 403（R2）。"""
        return permission_code in self.permissions


def _extract_bearer(request: Request) -> str:
    """从 Authorization 头取出 Bearer Token。

    直接解析 header，而不是依赖 HTTPBearer —— 因为 HTTPBearer.__call__ 是 async 的
    （FastAPI 正常在 async 依赖里 await 它），而本模块的依赖刻意写成同步 def，
    手工解析这两行反而更直白，也少一层事件循环。

    解析规则：Authorization: Bearer <token>
    任何缺失或格式不符都抛 401，由统一异常处理器输出 {"error": "未登录"}。
    """
    header = request.headers.get("Authorization")
    if header:
        scheme, _, credentials = header.partition(" ")
        if scheme.lower() == "bearer":
            token = credentials.strip()
            if token:
                return token
    raise UnauthorizedError()


def get_current_user(request: Request, db: Session = Depends(get_db)) -> CurrentUser:
    """★ requireAuth：认证 + 实时计算权限。任何失败都是 401。

    fail-closed 的处理：Token 缺失、格式错、签名错、已过期、
    用户不存在、用户被停用 —— 全部归为 401「未登录」。
    统一文案是有意的：不向未认证调用方泄露「该账号是否存在」或「是否被停用」。
    """
    token = _extract_bearer(request)

    try:
        payload = decode_access_token(token)
    except jwt.ExpiredSignatureError:
        logger.info("Token 已过期")
        raise UnauthorizedError() from None
    except jwt.InvalidTokenError as exc:
        logger.info("Token 非法：%s", exc)
        raise UnauthorizedError() from None

    subject = payload.get("sub")
    try:
        user_id = int(subject)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        logger.info("Token 的 sub 不是合法用户 ID：%r", subject)
        raise UnauthorizedError() from None

    user: User | None = db.get(User, user_id)
    if user is None or not user.is_active:
        # 用户被删除或被停用 → 立即失效，即使 Token 本身还在有效期内
        logger.info("Token 对应的用户不存在或已停用：user_id=%s", user_id)
        raise UnauthorizedError()

    # ★★ R4 的核心：每次请求都在这里重新查库计算权限，全程无缓存。
    permissions = rbac.effective_permissions(db, user.id)
    role_codes = rbac.get_user_role_codes(db, user.id)

    logger.debug(
        "鉴权：user=%s roles=%s permissions=%d 个",
        user.username,
        role_codes,
        len(permissions),
    )

    return CurrentUser(
        id=user.id,
        username=user.username,
        nickname=user.nickname,
        permissions=permissions,
        role_codes=role_codes,
    )


def authorize(permission_code: str):
    """★ authorize(permission_code)：权限点校验依赖工厂。

    用法：
        @router.post("/api/products", dependencies=[Depends(authorize("products:edit"))])
        def create_product(...): ...

    写成「工厂函数返回依赖」而不是直接写一个依赖函数，是为了能在装饰器里
    带上参数（需要校验哪个权限码）。

    R2 默认拒绝的三种情形在这里被统一处理，无需分别判断：
        · 权限码在 permissions 表里不存在 → 不在集合里 → 403
        · 用户没有任何角色               → 集合为空     → 403
        · 权限点/角色被停用              → SQL 已过滤掉 → 403
    """

    def _checker(current: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not current.has(permission_code):
            logger.info(
                "拒绝访问：user=%s 缺少权限 %s（实际持有 %d 个）",
                current.username,
                permission_code,
                len(current.permissions),
            )
            raise ForbiddenError()
        return current

    return _checker


def authorize_current(permission_code: str):
    """同 authorize，但同时把 CurrentUser 注入到 handler 参数里。

    对需要「知道是谁在操作」的接口更方便，例如创建商品时要记录 created_by。
    保留 authorize 是因为大多数接口只需要「能过就行」，参数越少越清晰。
    """

    def _checker(current: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not current.has(permission_code):
            raise ForbiddenError()
        return current

    return _checker
