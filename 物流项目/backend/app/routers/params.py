"""参数管理接口。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.deps import DbSession, require_permission
from app.errors import AppError, NotFoundError
from app.models import SysParam, SysUser
from app.schemas import ParamOut, ParamUpdate, ToggleResponse
from app.services.audit import append_audit

router = APIRouter(prefix="/params", tags=["参数管理"])

Reader = Annotated[SysUser, Depends(require_permission("params:read"))]
Manager = Annotated[SysUser, Depends(require_permission("params:manage"))]

# 各参数类型的取值校验：服务端把关，避免写进不合法的值把调度器搞崩
_TYPE_HINT = {"int": "整数", "bool": "true 或 false"}


def _is_valid(param_type: str, value: str) -> bool:
    if param_type == "int":
        return value.lstrip("-").isdigit()
    if param_type == "bool":
        return value in ("true", "false")
    return True


@router.get("", response_model=list[ParamOut], summary="参数列表")
def list_params(db: DbSession, actor: Reader) -> list[ParamOut]:
    rows = db.query(SysParam).order_by(SysParam.group, SysParam.id).all()
    return [ParamOut.model_validate(p) for p in rows]


@router.put("/{param_id}", response_model=ParamOut, summary="修改参数值")
def update_param(
    param_id: int, payload: ParamUpdate, db: DbSession, actor: Manager
) -> ParamOut:
    param = db.get(SysParam, param_id)
    if param is None:
        raise NotFoundError("参数不存在")

    value = payload.value.strip()
    if not _is_valid(param.type, value):
        raise AppError(f"参数 {param.key} 要求{_TYPE_HINT.get(param.type, '合法值')}")

    before = param.value
    param.value = value
    db.commit()
    db.refresh(param)

    append_audit(
        db,
        actor=actor,
        action="param.update",
        target_type="param",
        target_name=param.key,
        detail={"变更": f"{before} → {param.value}"},
    )
    return ParamOut.model_validate(param)


@router.put("/{param_id}/active", response_model=ToggleResponse, summary="启用/停用参数")
def toggle_param(param_id: int, db: DbSession, actor: Manager) -> ToggleResponse:
    param = db.get(SysParam, param_id)
    if param is None:
        raise NotFoundError("参数不存在")

    param.is_active = not param.is_active
    db.commit()
    append_audit(
        db,
        actor=actor,
        action="param.toggle",
        target_type="param",
        target_name=param.key,
        detail={"变更": "停用 → 启用" if param.is_active else "启用 → 停用"},
    )
    return ToggleResponse(id=param.id, is_active=param.is_active)
