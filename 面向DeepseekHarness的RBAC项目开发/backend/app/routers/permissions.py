"""权限点管理接口（全部挂 users:manage）。

    GET    /api/permissions           权限点列表
    POST   /api/permissions           新建权限点
    PATCH  /api/permissions/{id}      启停权限点  ★ R4 的操作入口

为什么需要 PATCH（需求文档 4.2 只写了 GET/POST）：
    验收标准第 6 条是「停用某权限点后，持有该权限的用户下次请求立即被拒绝」。
    没有启停接口就无法触发这个场景，也就无法验证 R4。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import CurrentUser, authorize, authorize_current
from app.errors import DuplicateError, NotFoundError
from app.models import Permission, RolePermission
from app.schemas import PermissionCreateRequest, PermissionOut, PermissionToggleRequest
from app.services import audit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/permissions", tags=["权限点管理"])

REQUIRED = "users:manage"


def _role_counts(db: Session) -> dict[int, int]:
    """统计每个权限点被多少个角色引用（一次查询，避免 N+1）。"""
    rows = db.execute(
        select(RolePermission.permission_id, func.count()).group_by(RolePermission.permission_id)
    ).all()
    return {perm_id: count for perm_id, count in rows}


def _to_out(perm: Permission, role_count: int) -> PermissionOut:
    out = PermissionOut.model_validate(perm)
    out.role_count = role_count
    return out


@router.get(
    "",
    response_model=list[PermissionOut],
    summary="权限点列表",
    dependencies=[Depends(authorize(REQUIRED))],
)
def list_permissions(db: Session = Depends(get_db)) -> list[PermissionOut]:
    counts = _role_counts(db)
    perms = db.execute(
        select(Permission).order_by(Permission.module, Permission.id)
    ).scalars()
    return [_to_out(p, counts.get(p.id, 0)) for p in perms]


@router.post(
    "",
    response_model=PermissionOut,
    status_code=201,
    summary="新建权限点",
    dependencies=[Depends(authorize(REQUIRED))],
)
def create_permission(
    payload: PermissionCreateRequest,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(authorize_current(REQUIRED)),
) -> PermissionOut:
    existing = db.execute(
        select(Permission).where(Permission.code == payload.code)
    ).scalar_one_or_none()
    if existing is not None:
        raise DuplicateError("权限码", payload.code)

    perm = Permission(
        code=payload.code,
        name=payload.name,
        module=payload.module,
        is_active=True,
    )
    db.add(perm)
    db.flush()

    audit.append_audit(
        db,
        action=audit.ACTION_PERMISSION_CREATE,
        actor_id=current.id,
        actor_name=current.username,
        target_type="permission",
        target_id=perm.id,
        target_name=perm.code,
        detail={"权限码": perm.code, "名称": perm.name, "模块": perm.module},
    )
    db.commit()
    logger.info("新建权限点 %s", perm.code)
    return _to_out(perm, 0)


@router.patch(
    "/{permission_id}",
    response_model=PermissionOut,
    summary="启用 / 停用权限点",
    description=(
        "★ R4 验证入口：置 is_active=false 后，所有持有该权限的用户"
        "在**下一次请求**就会失去该权限，无需重启服务、无需等待 Token 过期，"
        "因为鉴权时每次都实时查库并按 is_active 过滤。"
    ),
)
def toggle_permission(
    permission_id: int,
    payload: PermissionToggleRequest,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(authorize_current(REQUIRED)),
) -> PermissionOut:
    perm = db.get(Permission, permission_id)
    if perm is None:
        raise NotFoundError("权限点不存在")

    before = perm.is_active
    perm.is_active = payload.is_active
    db.flush()

    if before != payload.is_active:
        affected = _role_counts(db).get(perm.id, 0)
        audit.append_audit(
            db,
            action=audit.ACTION_PERMISSION_TOGGLE,
            actor_name=current.username,
            target_type="permission",
            target_id=perm.id,
            target_name=perm.code,
            detail={
                "变更": f"{'启用' if before else '停用'} -> "
                f"{'启用' if payload.is_active else '停用'}",
                "影响角色数": affected,
                "说明": "权限点状态变更，持有者下次请求即时生效（R4）",
            },
        )
        db.commit()
        logger.warning(
            "权限点 %s 已%s（影响 %d 个角色，下一次请求即时生效）",
            perm.code,
            "启用" if payload.is_active else "停用",
            affected,
        )
    else:
        db.commit()

    return _to_out(perm, _role_counts(db).get(perm.id, 0))
