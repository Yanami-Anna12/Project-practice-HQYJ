"""角色管理接口。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.deps import DbSession, require_permission
from app.errors import ConflictError, NotFoundError
from app.models import SysPermission, SysRole, SysUser
from app.schemas import DeletedResponse, RoleCreate, RoleOut, RoleUpdate
from app.services.audit import append_audit
from app.services.rbac import get_role_permission_codes

router = APIRouter(prefix="/roles", tags=["角色管理"])

Reader = Annotated[SysUser, Depends(require_permission("roles:read"))]
Manager = Annotated[SysUser, Depends(require_permission("roles:manage"))]


def _to_out(db, role: SysRole) -> RoleOut:
    return RoleOut(
        id=role.id,
        code=role.code,
        name=role.name,
        description=role.description,
        is_active=role.is_active,
        permission_codes=get_role_permission_codes(db, role),
        user_count=len(role.users),
    )


def _resolve_permissions(db, codes: list[str]) -> list[SysPermission]:
    if not codes:
        return []
    perms = db.query(SysPermission).filter(SysPermission.code.in_(codes)).all()
    missing = set(codes) - {p.code for p in perms}
    if missing:
        raise NotFoundError(f"权限点不存在：{'、'.join(sorted(missing))}")
    return perms


@router.get("", response_model=list[RoleOut], summary="角色列表")
def list_roles(db: DbSession, actor: Reader) -> list[RoleOut]:
    roles = db.query(SysRole).order_by(SysRole.id).all()
    return [_to_out(db, r) for r in roles]


@router.post("", response_model=RoleOut, summary="新建角色")
def create_role(payload: RoleCreate, db: DbSession, actor: Manager) -> RoleOut:
    exists = db.query(SysRole).filter(SysRole.code == payload.code).one_or_none()
    if exists is not None:
        raise ConflictError(f"角色码 {payload.code} 已存在")

    role = SysRole(
        code=payload.code,
        name=payload.name,
        description=payload.description,
        is_active=True,
    )
    role.permissions = _resolve_permissions(db, payload.permission_codes)
    db.add(role)
    db.commit()
    db.refresh(role)

    append_audit(
        db,
        actor=actor,
        action="role.create",
        target_type="role",
        target_name=role.code,
        detail={"名称": role.name, "权限数": len(role.permissions)},
    )
    return _to_out(db, role)


@router.put("/{role_id}", response_model=RoleOut, summary="更新角色")
def update_role(role_id: int, payload: RoleUpdate, db: DbSession, actor: Manager) -> RoleOut:
    role = db.get(SysRole, role_id)
    if role is None:
        raise NotFoundError("角色不存在")

    before = get_role_permission_codes(db, role)
    role.name = payload.name
    role.description = payload.description
    role.permissions = _resolve_permissions(db, payload.permission_codes)
    if payload.is_active is not None:
        role.is_active = payload.is_active
    db.commit()
    db.refresh(role)

    after = get_role_permission_codes(db, role)
    append_audit(
        db,
        actor=actor,
        action="role.update",
        target_type="role",
        target_name=role.code,
        detail={
            "名称": role.name,
            "新增权限": sorted(set(after) - set(before)) or ["（无）"],
            "移除权限": sorted(set(before) - set(after)) or ["（无）"],
        },
    )
    return _to_out(db, role)


@router.delete("/{role_id}", response_model=DeletedResponse, summary="删除角色")
def delete_role(role_id: int, db: DbSession, actor: Manager) -> DeletedResponse:
    role = db.get(SysRole, role_id)
    if role is None:
        raise NotFoundError("角色不存在")

    # ★ 删除保护：仍被用户引用时拒绝，并说明还剩几个用户绑着
    bound = list(role.users)
    if bound:
        names = "、".join(u.username for u in bound[:5])
        more = f" 等 {len(bound)} 个" if len(bound) > 5 else ""
        raise ConflictError(
            f"角色「{role.name}」仍绑定 {len(bound)} 个用户（{names}{more}），请先改绑"
        )

    code = role.code
    role.permissions = []
    db.delete(role)
    db.commit()

    append_audit(
        db,
        actor=actor,
        action="role.delete",
        target_type="role",
        target_name=code,
        detail={"名称": role.name},
    )
    return DeletedResponse(deleted=code)
