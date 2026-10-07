"""当前用户接口：/api/me 系列。

这三个接口都只需要「登录」（requireAuth），不需要额外权限点：
    GET /api/me                 当前用户信息
    GET /api/me/permissions     当前用户的有效权限码（前端按钮控制用）
    GET /api/me/menus           当前用户可见的菜单树（★ 服务端已按权限裁剪）

为什么 /api/me/menus 在服务端裁剪而不是把完整菜单发给前端过滤：
    完整树发给前端等于把管理端的菜单结构暴露给了无权用户；
    而且前端过滤一旦写错，用户会看到点不动的死菜单。
    服务端裁剪后，无权用户连「系统管理」这一栏都收不到。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.deps import CurrentUser, get_current_user
from app.menus import filter_menus
from app.schemas import MeResponse, MenuNode, PermissionsResponse, UserBrief

router = APIRouter(prefix="/api/me", tags=["当前用户"])


@router.get("", response_model=MeResponse, summary="当前用户信息")
def read_me(current: CurrentUser = Depends(get_current_user)) -> MeResponse:
    return MeResponse(
        user=UserBrief(id=current.id, username=current.username, nickname=current.nickname),
        roles=current.role_codes,
        permissions=sorted(current.permissions),
    )


@router.get(
    "/permissions",
    response_model=PermissionsResponse,
    summary="当前用户的有效权限码",
    description=(
        "返回本次请求实时查库计算出的权限集合（多角色取并集）。"
        "前端用它做按钮级显隐；后端接口仍会独立校验，不依赖此结果。"
    ),
)
def read_my_permissions(
    current: CurrentUser = Depends(get_current_user),
) -> PermissionsResponse:
    return PermissionsResponse(
        permissions=sorted(current.permissions),
        roles=current.role_codes,
    )


@router.get(
    "/menus",
    response_model=list[MenuNode],
    summary="当前用户可见的菜单树",
    description=(
        "按当前用户权限裁剪后的菜单树。无权限的节点、以及子节点全被裁掉的分组节点"
        "都不会出现在结果中。"
    ),
)
def read_my_menus(current: CurrentUser = Depends(get_current_user)) -> list[MenuNode]:
    nodes = filter_menus(current.permissions)
    return [MenuNode.model_validate(n) for n in nodes]
