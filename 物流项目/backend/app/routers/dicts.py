"""字典管理接口。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.deps import DbSession, require_permission
from app.errors import ConflictError, NotFoundError
from app.models import SysDictItem, SysDictType, SysUser
from app.schemas import (
    DeletedResponse,
    DictItemCreate,
    DictItemOut,
    DictItemUpdate,
    DictTypeCreate,
    DictTypeOut,
    ToggleResponse,
)
from app.services.audit import append_audit

router = APIRouter(prefix="/dicts", tags=["字典管理"])

Reader = Annotated[SysUser, Depends(require_permission("dicts:read"))]
Manager = Annotated[SysUser, Depends(require_permission("dicts:manage"))]


def _type_out(db, dtype: SysDictType) -> DictTypeOut:
    count = db.query(SysDictItem).filter(SysDictItem.type_code == dtype.code).count()
    return DictTypeOut(
        id=dtype.id,
        code=dtype.code,
        name=dtype.name,
        description=dtype.description,
        is_active=dtype.is_active,
        item_count=count,
    )


@router.get("/types", response_model=list[DictTypeOut], summary="字典类型列表")
def list_types(db: DbSession, actor: Reader) -> list[DictTypeOut]:
    types = db.query(SysDictType).order_by(SysDictType.id).all()
    return [_type_out(db, t) for t in types]


@router.post("/types", response_model=DictTypeOut, summary="新建字典类型")
def create_type(payload: DictTypeCreate, db: DbSession, actor: Manager) -> DictTypeOut:
    exists = db.query(SysDictType).filter(SysDictType.code == payload.code).one_or_none()
    if exists is not None:
        raise ConflictError(f"字典类型 {payload.code} 已存在")

    dtype = SysDictType(
        code=payload.code, name=payload.name, description=payload.description, is_active=True
    )
    db.add(dtype)
    db.commit()
    db.refresh(dtype)

    append_audit(
        db,
        actor=actor,
        action="dict.create",
        target_type="dict",
        target_name=dtype.code,
        detail={"名称": dtype.name},
    )
    return _type_out(db, dtype)


@router.put("/types/{type_id}/active", response_model=ToggleResponse, summary="启用/停用字典类型")
def toggle_type(type_id: int, db: DbSession, actor: Manager) -> ToggleResponse:
    dtype = db.get(SysDictType, type_id)
    if dtype is None:
        raise NotFoundError("字典类型不存在")

    dtype.is_active = not dtype.is_active
    db.commit()
    append_audit(
        db,
        actor=actor,
        action="dict.toggle",
        target_type="dict",
        target_name=dtype.code,
        detail={"变更": "停用 → 启用" if dtype.is_active else "启用 → 停用"},
    )
    return ToggleResponse(id=dtype.id, is_active=dtype.is_active)


@router.delete("/types/{type_id}", response_model=DeletedResponse, summary="删除字典类型")
def delete_type(type_id: int, db: DbSession, actor: Manager) -> DeletedResponse:
    dtype = db.get(SysDictType, type_id)
    if dtype is None:
        raise NotFoundError("字典类型不存在")

    items = db.query(SysDictItem).filter(SysDictItem.type_code == dtype.code).count()
    if items:
        raise ConflictError(f"字典类型 {dtype.code} 下还有 {items} 个字典项，请先删除")

    code, name = dtype.code, dtype.name
    db.delete(dtype)
    db.commit()

    append_audit(
        db,
        actor=actor,
        action="dict.delete",
        target_type="dict",
        target_name=code,
        detail={"名称": name},
    )
    return DeletedResponse(deleted=code)


@router.get("/types/{type_code}/items", response_model=list[DictItemOut], summary="字典项列表")
def list_items(type_code: str, db: DbSession, actor: Reader) -> list[DictItemOut]:
    items = (
        db.query(SysDictItem)
        .filter(SysDictItem.type_code == type_code)
        .order_by(SysDictItem.sort, SysDictItem.id)
        .all()
    )
    return [DictItemOut.model_validate(i) for i in items]


@router.post("/types/{type_code}/items", response_model=DictItemOut, summary="新增字典项")
def create_item_under_type(
    type_code: str, payload: DictItemCreate, db: DbSession, actor: Manager
) -> DictItemOut:
    dtype = db.query(SysDictType).filter(SysDictType.code == type_code).one_or_none()
    if dtype is None:
        raise NotFoundError("字典类型不存在")

    exists = (
        db.query(SysDictItem)
        .filter(SysDictItem.type_code == type_code, SysDictItem.value == payload.value)
        .one_or_none()
    )
    if exists is not None:
        raise ConflictError(f"该字典类型下的值 {payload.value} 已存在")

    item = SysDictItem(
        type_code=type_code,
        label=payload.label,
        value=payload.value,
        sort=payload.sort,
        remark=payload.remark,
        is_active=True,
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    append_audit(
        db,
        actor=actor,
        action="dict_item.create",
        target_type="dict",
        target_name=f"{type_code}:{item.value}",
        detail={"标签": item.label},
    )
    return DictItemOut.model_validate(item)


@router.put("/items/{item_id}", response_model=DictItemOut, summary="更新字典项")
def update_item(
    item_id: int, payload: DictItemUpdate, db: DbSession, actor: Manager
) -> DictItemOut:
    item = db.get(SysDictItem, item_id)
    if item is None:
        raise NotFoundError("字典项不存在")

    before = f"{item.label}({item.value})"
    item.label = payload.label
    item.value = payload.value
    item.sort = payload.sort
    item.remark = payload.remark
    if payload.is_active is not None:
        item.is_active = payload.is_active
    db.commit()
    db.refresh(item)

    append_audit(
        db,
        actor=actor,
        action="dict_item.update",
        target_type="dict",
        target_name=f"{item.type_code}:{item.value}",
        detail={"变更前": before, "变更后": f"{item.label}({item.value})"},
    )
    return DictItemOut.model_validate(item)


@router.delete("/items/{item_id}", response_model=DeletedResponse, summary="删除字典项")
def delete_item(item_id: int, db: DbSession, actor: Manager) -> DeletedResponse:
    item = db.get(SysDictItem, item_id)
    if item is None:
        raise NotFoundError("字典项不存在")

    value, label, type_code = item.value, item.label, item.type_code
    db.delete(item)
    db.commit()

    append_audit(
        db,
        actor=actor,
        action="dict_item.delete",
        target_type="dict",
        target_name=f"{type_code}:{value}",
        detail={"标签": label},
    )
    return DeletedResponse(deleted=value)
