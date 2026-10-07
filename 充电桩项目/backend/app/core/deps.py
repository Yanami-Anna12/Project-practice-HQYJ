"""FastAPI 依赖：当前用户、权限校验、数据权限过滤。

PDF 4.1 原则 1「硬约束代码化」：数据权限（个人/站点/项目/平台）由确定性
代码保证，LLM 不参与鉴权决策。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Annotated

from fastapi import Depends, Header, Query
from sqlalchemy import Select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.enums import DATA_SCOPE_ORDER, DataScope
from app.core.errors import AuthError, PermissionDeniedError
from app.core.security import decode_access_token
from app.models import WorkOrder, User

DbSession = Annotated[AsyncSession, Depends(get_db)]


def _extract_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return authorization.strip() or None


async def get_current_user(
    db: DbSession,
    authorization: Annotated[str | None, Header()] = None,
    token: Annotated[str | None, Query(include_in_schema=False)] = None,
) -> User:
    """解析 JWT 并返回当前用户。

    支持 Header `Authorization: Bearer <token>`；为便于 WebSocket /
    导出下载等场景，也允许 `?token=` 传参。
    """
    raw = _extract_bearer(authorization) or token
    if not raw:
        raise AuthError("缺少认证信息，请先登录")
    payload = decode_access_token(raw)
    if not payload or not payload.get("sub"):
        raise AuthError("登录状态已失效，请重新登录")
    user = await db.get(User, payload["sub"])
    if user is None:
        raise AuthError("用户不存在")
    if not user.status:
        raise AuthError("账号已被停用，请联系管理员")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_optional_user(
    db: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> User | None:
    raw = _extract_bearer(authorization)
    if not raw:
        return None
    payload = decode_access_token(raw)
    if not payload or not payload.get("sub"):
        return None
    return await db.get(User, payload["sub"])


def scope_of(user: User) -> str:
    """取用户数据权限范围。"""
    if user.role and user.role.data_scope:
        return user.role.data_scope
    return DataScope.PERSONAL.value


def scope_rank(user: User) -> int:
    return DATA_SCOPE_ORDER.get(DataScope(scope_of(user)), 0)


def require_permission(*codes: str) -> Callable:
    """接口权限校验依赖工厂。

    用法：`dependencies=[Depends(require_permission("admin:user:create"))]`
    """

    async def _check(user: CurrentUser) -> User:
        if not codes:
            return user
        granted = {p.permission.code for p in (user.role.permissions if user.role else [])}
        # 平台数据权限默认拥有全部权限，避免内置超管被权限表锁死
        if scope_rank(user) >= DATA_SCOPE_ORDER[DataScope.PLATFORM]:
            return user
        if not granted.intersection(codes):
            raise PermissionDeniedError(f"缺少权限：{' / '.join(codes)}")
        return user

    return _check


def require_scope(*allowed: DataScope) -> Callable:
    """数据权限范围校验依赖工厂。"""

    async def _check(user: CurrentUser) -> User:
        current = DataScope(scope_of(user))
        if current not in allowed and scope_rank(user) < max(
            DATA_SCOPE_ORDER[s] for s in allowed
        ):
            raise PermissionDeniedError(
                f"当前数据权限为「{current.value}」，无权执行该操作"
            )
        return user

    return _check


# ---------------------------------------------------------------- 数据权限过滤


def apply_data_scope(
    stmt: Select,
    user: User,
    model: type = WorkOrder,
    *,
    owner_field: str = "inspector_id",
    station_field: str | None = "station_id",
    project_field: str | None = "project_id",
) -> Select:
    """按数据权限范围给查询语句追加过滤条件。

    - 平台数据：不过滤
    - 项目数据：限制 project_id
    - 站点数据：限制 station_id（以及所属项目）
    - 个人数据：限制 owner_field = 当前用户
    """
    scope = scope_of(user)
    if scope == DataScope.PLATFORM.value:
        return stmt

    if scope == DataScope.PROJECT.value:
        if project_field and hasattr(model, project_field):
            return stmt.where(getattr(model, project_field) == user.project_id)
        return stmt

    if scope == DataScope.STATION.value:
        conditions = []
        if station_field and hasattr(model, station_field):
            conditions.append(getattr(model, station_field) == user.station_id)
        if project_field and hasattr(model, project_field) and user.project_id:
            conditions.append(getattr(model, project_field) == user.project_id)
        if not conditions:
            return stmt
        return stmt.where(or_(*conditions) if len(conditions) > 1 else conditions[0])

    # 个人数据
    if hasattr(model, owner_field):
        return stmt.where(getattr(model, owner_field) == user.id)
    return stmt


def visible_station_ids(user: User) -> Sequence[str] | None:
    """返回用户可见站点 ID 列表；None 表示不限制。"""
    scope = scope_of(user)
    if scope == DataScope.PLATFORM.value:
        return None
    if scope == DataScope.STATION.value:
        return [user.station_id] if user.station_id else []
    return None


def paginate(page: int, page_size: int) -> tuple[int, int]:
    limit = max(1, min(page_size, 200))
    offset = max(0, (max(1, page) - 1) * limit)
    return limit, offset
