"""角色管理接口（全部挂 users:manage）。

    GET     /api/roles                    角色列表
    POST    /api/roles                    新建角色 + 绑定权限
    PUT     /api/roles/{id}               更新角色 / 全量重置权限绑定
    DELETE  /api/roles/{id}               ★ R3：被引用时返回 409，绝不级联清除
    GET     /api/roles/{id}/permissions    某角色已绑定的权限码

★ R3 的实现分层（两道防线）：
    第一道  services/rbac.delete_role() 先 COUNT 引用数，
             >0 就带具体数字抛 RoleInUseError → 409「该角色仍绑定 N 个用户，请先改绑」
    第二道  数据库外键 user_roles.role_id ON DELETE RESTRICT，
             万一应用层被改坏或存在并发插入，MySQL 用 1451 拒绝，
             同样被翻译成 409
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import CurrentUser, authorize, authorize_current
from app.errors import DuplicateError
from app.models import Role, RolePermission
from app.schemas import (
    RoleCreateRequest,
    RoleDeleteResponse,
    RoleOut,
    RoleUpdateRequest,
)
from app.services import audit, rbac

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/roles", tags=["角色管理"])

REQUIRED = "users:manage"


def _to_out(role: Role, user_count: int) -> RoleOut:
    out = RoleOut.model_validate(role)
    out.permission_codes = role.permission_codes
    out.user_count = user_count
    return out


@router.get(
    "",
    response_model=list[RoleOut],
    summary="角色列表",
    dependencies=[Depends(authorize(REQUIRED))],
)
def list_roles(db: Session = Depends(get_db)) -> list[RoleOut]:
    counts = rbac.role_usage_counts(db)
    return [_to_out(r, counts.get(r.id, 0)) for r in rbac.list_roles(db)]


@router.get(
    "/{role_id}/permissions",
    response_model=list[str],
    summary="某角色绑定的权限码",
    dependencies=[Depends(authorize(REQUIRED))],
)
def read_role_permissions(role_id: int, db: Session = Depends(get_db)) -> list[str]:
    role = rbac.get_role(db, role_id)
    return role.permission_codes


@router.post(
    "",
    response_model=RoleOut,
    status_code=status.HTTP_201_CREATED,
    summary="新建角色并绑定权限",
)
def create_role(
    payload: RoleCreateRequest,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(authorize_current(REQUIRED)),
) -> RoleOut:
    if rbac.get_role_by_code(db, payload.code) is not None:
        raise DuplicateError("角色码", payload.code)

    # 先解析权限码：若提交了不存在的权限码，此处直接报错，
    # 避免创建出一个半成品角色（配置期校验，与 R2 的运行期拒绝是两回事）。
    permissions = rbac.resolve_permission_codes(db, payload.permission_codes)

    role = Role(
        code=payload.code,
        name=payload.name,
        description=payload.description,
        is_active=True,
    )
    db.add(role)
    db.flush()

    for perm in permissions:
        db.add(RolePermission(role_id=role.id, permission_id=perm.id))
    db.flush()
    db.refresh(role)

    audit.append_audit(
        db,
        action=audit.ACTION_ROLE_CREATE,
        actor_id=current.id,
        actor_name=current.username,
        target_type="role",
        target_id=role.id,
        target_name=role.code,
        detail={
            "角色码": role.code,
            "名称": role.name,
            "绑定权限": sorted(p.code for p in permissions),
        },
    )
    db.commit()
    logger.info("新建角色 %s，绑定权限 %s", role.code, role.permission_codes)
    return _to_out(role, 0)


@router.put(
    "/{role_id}",
    response_model=RoleOut,
    summary="更新角色 / 全量重置权限绑定",
    description=(
        "只更新请求中提交的字段。`permission_codes` 为**全量覆盖**语义："
        "提交什么，角色最终就是什么（不是增量追加）。"
        "`is_active=false` 会让该角色的全部权限整体退出所有持有者的权限并集（R4）。"
    ),
)
def update_role(
    role_id: int,
    payload: RoleUpdateRequest,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(authorize_current(REQUIRED)),
) -> RoleOut:
    role = rbac.get_role(db, role_id)
    before_permissions = role.permission_codes
    before_active = role.is_active

    if payload.name is not None:
        role.name = payload.name
    if payload.description is not None:
        role.description = payload.description
    if payload.is_active is not None:
        role.is_active = payload.is_active
    db.flush()

    if payload.permission_codes is not None:
        rbac.set_role_permissions(db, role, payload.permission_codes)
        after_permissions = sorted(role.permission_codes)
        audit.append_audit(
            db,
            action=audit.ACTION_ROLE_ASSIGN_PERMISSIONS,
            actor_id=current.id,
            actor_name=current.username,
            target_type="role",
            target_id=role.id,
            target_name=role.code,
            detail={
                "原权限": before_permissions,
                "新权限": after_permissions,
                "新增": sorted(set(after_permissions) - set(before_permissions)),
                "移除": sorted(set(before_permissions) - set(after_permissions)),
            },
        )
        logger.info("角色 %s 权限变更为 %s", role.code, after_permissions)

    if payload.is_active is not None and payload.is_active != before_active:
        audit.append_audit(
            db,
            action=audit.ACTION_ROLE_UPDATE,
            actor_id=current.id,
            actor_name=current.username,
            target_type="role",
            target_id=role.id,
            target_name=role.code,
            detail={
                "变更": f"is_active {'启用' if before_active else '停用'} -> "
                f"{'启用' if payload.is_active else '停用'}",
                "说明": "角色状态变更，其权限即时退出/进入持有者的权限并集（R4）",
            },
        )

    db.commit()
    counts = rbac.role_usage_counts(db)
    return _to_out(role, counts.get(role.id, 0))


@router.delete(
    "/{role_id}",
    response_model=RoleDeleteResponse,
    summary="删除角色",
    description=(
        "★ R3：若该角色仍被用户引用，返回 **409** 与"
        "「该角色仍绑定 N 个用户，请先改绑」，不做任何级联清除。"
    ),
    responses={
        409: {"description": "该角色仍绑定 N 个用户，请先改绑"},
        404: {"description": "角色不存在"},
    },
)
def delete_role(
    role_id: int,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(authorize_current(REQUIRED)),
) -> RoleDeleteResponse:
    # 先取出角色信息用于审计（delete_role 之后对象就没了）
    role = rbac.get_role(db, role_id)
    role_code, role_id_ = role.code, role.id

    # ★ R3 判定在这里：被引用则抛 RoleInUseError(409)，后面的代码不会执行
    deleted_code = rbac.delete_role(db, role_id)

    audit.append_audit(
        db,
        action=audit.ACTION_ROLE_DELETE,
        actor_id=current.id,
        actor_name=current.username,
        target_type="role",
        target_id=role_id_,
        target_name=role_code,
        detail={"角色码": deleted_code, "说明": "角色已删除，其权限绑定同时清除"},
    )
    db.commit()
    logger.warning("角色 %s（id=%s）已被删除", deleted_code, role_id_)
    return RoleDeleteResponse(ok=True, deleted=deleted_code)
