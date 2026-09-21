"""用户管理接口（全部挂 users:manage）。

    GET  /api/users                用户列表（含角色与有效权限）
    GET  /api/users/{id}/roles     某用户的角色
    PUT  /api/users/{id}/roles     ★ 用户-角色分配（全量覆盖）→ 触发 R1 并集

★ R1 在这里的体现：
    PUT 传 ["operator", "readonly"] 时，返回的 permissions 是两者权限的**并集**
    （products:read, products:edit, orders:read, reports:view），
    而不是取两者共有（那会是 products:read/orders:read/reports:view，丢掉 products:edit）。
    整个链路没有任何「取最严」的逻辑 —— 那是对 RBAC 的常见误解。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import CurrentUser, authorize, authorize_current
from app.errors import NotFoundError
from app.models import User, UserRole
from app.schemas import UserOut, UserRolesRequest, UserRolesResponse
from app.services import audit, rbac

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/users", tags=["用户管理"])

REQUIRED = "users:manage"


def _to_out(db_user: User, perms_map: dict[int, set[str]]) -> UserOut:
    """把 User 实体转成 UserOut 响应模型。

    ★ 注意 UserOut.roles 声明了 validation_alias="role_codes"。
      User 实体上同时有 roles（Role 对象列表）和 role_codes（字符串列表）两个属性，
      若不指定别名，Pydantic 的 from_attributes 会优先读到 user.roles，
      把 Role 对象塞进 list[str] 字段直接报校验错误、接口 500。
      别名把「从 ORM 读哪个属性」变成显式声明，同时对外 JSON 键仍是 roles。

      permissions 不属于 ORM 属性（要实时查库算并集），所以单独赋值后
      再走一次校验，避免使用 model_construct（它会跳过所有校验，容易掩盖错误）。
    """
    data = UserOut.model_validate(db_user)
    data.permissions = sorted(perms_map.get(db_user.id, set()))
    return data


@router.get(
    "",
    response_model=list[UserOut],
    summary="用户列表",
    dependencies=[Depends(authorize(REQUIRED))],
)
def list_users(db: Session = Depends(get_db)) -> list[UserOut]:
    users = list(db.execute(select(User).order_by(User.id)).scalars())

    # 批量算权限，避免每个用户三次查询（N+1）
    perms_map = rbac.permissions_for_user_ids(db, [u.id for u in users])

    return [_to_out(u, perms_map) for u in users]


@router.get(
    "/{user_id}/roles",
    response_model=list[str],
    summary="某用户的角色码",
    dependencies=[Depends(authorize(REQUIRED))],
)
def read_user_roles(user_id: int, db: Session = Depends(get_db)) -> list[str]:
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("用户不存在")
    return rbac.get_user_role_codes(db, user_id)


@router.put(
    "/{user_id}/roles",
    response_model=UserRolesResponse,
    summary="用户-角色分配（全量覆盖）",
    description=(
        "★ **R1 多角色并集**：提交多个角色时，用户权限为各角色权限的并集，"
        "不是取最严。返回体直接给出改绑后的权限并集，前端可立即刷新界面。\n\n"
        "传入空数组 `[]` 表示清空该用户所有角色 —— 此时用户权限为空集合，"
        "后续任何受保护接口都会返回 403（R2 的合法输入，不是错误状态）。"
    ),
)
def set_user_roles(
    user_id: int,
    payload: UserRolesRequest,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(authorize_current(REQUIRED)),
) -> UserRolesResponse:
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("用户不存在")

    before = rbac.get_user_role_codes(db, user_id)

    # ★ R1 写入侧：允许多角色，读取侧 effective_permissions() 求并集。
    #   本函数内部还会拦住「移除最后一个管理员」的自锁操作（LastAdminError → 409）。
    roles = rbac.set_user_roles(db, user, payload.role_codes)
    after = sorted(r.code for r in roles)

    # 改绑后立刻重算权限并集，一并返回给前端
    permissions = sorted(rbac.effective_permissions(db, user_id))

    audit.append_audit(
        db,
        action=audit.ACTION_USER_ASSIGN_ROLES,
        actor_id=current.id,
        actor_name=current.username,
        target_type="user",
        target_id=user.id,
        target_name=user.username,
        detail={
            "原角色": before,
            "新角色": after,
            "新增": sorted(set(after) - set(before)),
            "移除": sorted(set(before) - set(after)),
            "权限并集": permissions,
        },
    )
    db.commit()
    logger.warning(
        "用户 %s 的角色由 %s 变更为 %s，权限并集 %d 个（下次请求即时生效）",
        user.username,
        before,
        after,
        len(permissions),
    )

    return UserRolesResponse(
        user_id=user.id,
        username=user.username,
        roles=after,
        permissions=permissions,
    )
