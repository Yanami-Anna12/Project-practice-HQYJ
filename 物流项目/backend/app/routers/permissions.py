"""权限点管理接口。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.deps import DbSession, require_permission
from app.errors import ConflictError, NotFoundError
from app.models import SysPermission, SysRole, SysUser
from app.schemas import DeletedResponse, PermissionCreate, PermissionOut, ToggleResponse
from app.services.audit import append_audit

router = APIRouter(prefix="/permissions", tags=["权限管理"])

Reader = Annotated[SysUser, Depends(require_permission("permissions:read"))]
Manager = Annotated[SysUser, Depends(require_permission("permissions:manage"))]


def _to_out(perm: SysPermission) -> PermissionOut:
    return PermissionOut(
        id=perm.id,
        code=perm.code,
        name=perm.name,
        module=perm.module,
        action=perm.action,
        is_active=perm.is_active,
        role_count=len(perm.roles),
    )


@router.get("", response_model=list[PermissionOut], summary="权限点列表")
def list_permissions(db: DbSession, actor: Reader) -> list[PermissionOut]:
    perms = db.query(SysPermission).order_by(SysPermission.module, SysPermission.id).all()
    return [_to_out(p) for p in perms]


@router.post("", response_model=PermissionOut, summary="新建权限点")
def create_permission(
    payload: PermissionCreate, db: DbSession, actor: Manager
) -> PermissionOut:
    exists = db.query(SysPermission).filter(SysPermission.code == payload.code).one_or_none()
    if exists is not None:
        raise ConflictError(f"权限码 {payload.code} 已存在")

    perm = SysPermission(
        code=payload.code,
        name=payload.name,
        module=payload.module,
        action=payload.action,
        is_active=True,
    )
    db.add(perm)
    db.commit()
    db.refresh(perm)

    append_audit(
        db,
        actor=actor,
        action="permission.create",
        target_type="permission",
        target_name=perm.code,
        detail={"名称": perm.name, "模块": perm.module},
    )
    return _to_out(perm)


@router.put("/{permission_id}/active", response_model=ToggleResponse, summary="启用/停用权限点")
def toggle_permission(
    permission_id: int, db: DbSession, actor: Manager
) -> ToggleResponse:
    perm = db.get(SysPermission, permission_id)
    if perm is None:
        raise NotFoundError("权限点不存在")

    perm.is_active = not perm.is_active
    db.commit()

    affected = len(perm.roles)
    append_audit(
        db,
        actor=actor,
        action="permission.toggle",
        target_type="permission",
        target_name=perm.code,
        detail={
            "变更": "停用 → 启用" if perm.is_active else "启用 → 停用",
            "影响角色数": affected,
            "说明": "已恢复生效" if perm.is_active else "停用后所有角色都不再拥有该权限",
        },
    )
    return ToggleResponse(id=perm.id, is_active=perm.is_active, affected_roles=affected)


@router.delete("/{permission_id}", response_model=DeletedResponse, summary="删除权限点")
def delete_permission(
    permission_id: int, db: DbSession, actor: Manager
) -> DeletedResponse:
    perm = db.get(SysPermission, permission_id)
    if perm is None:
        raise NotFoundError("权限点不存在")

    # 仍被角色引用时拒绝删除，避免角色指向不存在的权限（悬空引用）
    bound = list(perm.roles)
    if bound:
        names = "、".join(r.code for r in bound[:5])
        raise ConflictError(
            f"权限点 {perm.code} 仍被 {len(bound)} 个角色引用（{names}），请先解绑"
        )

    code = perm.code
    name = perm.name
    db.delete(perm)
    db.commit()

    append_audit(
        db,
        actor=actor,
        action="permission.delete",
        target_type="permission",
        target_name=code,
        detail={"名称": name},
    )
    return DeletedResponse(deleted=code)
