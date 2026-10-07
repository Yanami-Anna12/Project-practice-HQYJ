"""附件管理接口。

★ 首版只登记元信息（storage_path 留空），不做真实文件落盘。
  接真实上传时改为 UploadFile + 落盘/对象存储，并回填 storage_path。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.deps import DbSession, require_permission
from app.errors import ConflictError, NotFoundError
from app.models import SysAttachment, SysUser
from app.schemas import AttachmentCreate, AttachmentOut, DeletedResponse
from app.services.audit import append_audit

router = APIRouter(prefix="/attachments", tags=["附件管理"])

Reader = Annotated[SysUser, Depends(require_permission("attachments:read"))]
Manager = Annotated[SysUser, Depends(require_permission("attachments:manage"))]


@router.get("", response_model=list[AttachmentOut], summary="附件列表")
def list_attachments(
    db: DbSession,
    actor: Reader,
    keyword: str = Query(default="", max_length=128),
    biz_type: str = Query(default="", max_length=32),
) -> list[AttachmentOut]:
    q = db.query(SysAttachment)
    if keyword:
        q = q.filter(SysAttachment.name.contains(keyword))
    if biz_type:
        q = q.filter(SysAttachment.biz_type == biz_type)
    rows = q.order_by(SysAttachment.id.desc()).all()
    return [AttachmentOut.model_validate(a) for a in rows]


@router.post("", response_model=AttachmentOut, summary="登记附件")
def create_attachment(
    payload: AttachmentCreate, db: DbSession, actor: Manager
) -> AttachmentOut:
    exists = db.query(SysAttachment).filter(SysAttachment.name == payload.name).one_or_none()
    if exists is not None:
        raise ConflictError(f"附件「{payload.name}」已存在")

    item = SysAttachment(
        name=payload.name,
        biz_type=payload.biz_type or "未分类",
        size=payload.size,
        storage_path="",  # 演示模式：不落盘
        uploader=actor.username,
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    append_audit(
        db,
        actor=actor,
        action="attachment.upload",
        target_type="attachment",
        target_name=item.name,
        detail={"类型": item.biz_type, "大小": item.size},
    )
    return AttachmentOut.model_validate(item)


@router.delete("/{attachment_id}", response_model=DeletedResponse, summary="删除附件")
def delete_attachment(
    attachment_id: int, db: DbSession, actor: Manager
) -> DeletedResponse:
    item = db.get(SysAttachment, attachment_id)
    if item is None:
        raise NotFoundError("附件不存在")

    name, biz_type = item.name, item.biz_type
    db.delete(item)
    db.commit()

    append_audit(
        db,
        actor=actor,
        action="attachment.delete",
        target_type="attachment",
        target_name=name,
        detail={"类型": biz_type},
    )
    return DeletedResponse(deleted=name)
