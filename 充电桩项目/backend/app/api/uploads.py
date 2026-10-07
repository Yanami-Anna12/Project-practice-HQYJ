"""附件上传接口 —— PDF 3.2 附件管理 / 3.4 巡检多图 / 3.5 故障多图。

POST /api/v1/uploads/images     批量上传图片（巡检、故障、核查现场照片）
POST /api/v1/uploads/files      批量上传文档（知识库导入：PDF/Word/Excel/PPT/txt）
GET  /api/v1/uploads/info       上传能力与限制说明（前端据此做提示与校验）
GET  /api/v1/uploads/attachments 按业务单据查询附件
"""

from __future__ import annotations

from fastapi import APIRouter, File, Query, UploadFile
from sqlalchemy import func, select

from app.core.deps import CurrentUser, DbSession
from app.core.response import ApiResponse, PageData
from app.models import Attachment
from app.services import audit as audit_service
from app.services import upload as upload_service

router = APIRouter(prefix="/uploads", tags=["附件上传"])


@router.get("/info", response_model=ApiResponse[dict], summary="上传能力与限制")
async def upload_info(db: DbSession, user: CurrentUser):
    return ApiResponse.ok(upload_service.storage_info())


@router.post("/images", response_model=ApiResponse[dict], summary="批量上传图片（多图上传）")
async def upload_images(
    db: DbSession,
    user: CurrentUser,
    files: list[UploadFile] = File(..., description="现场照片，单次最多 12 张"),
    biz_type: str = Query(default="inspection", description="inspection / fault / verify / station"),
    biz_id: str | None = Query(default=None, description="业务单据 ID，可稍后回填"),
):
    """巡检情况录入与故障上报的多图上传（PDF 3.4 / 3.5）。

    返回每个文件的 url（可直接写入 images 字段）与附件记录 ID。
    """
    stored = await upload_service.save_many(files, biz_type=biz_type)
    rows = await upload_service.persist_attachments(
        db, stored=stored, biz_type=biz_type, biz_id=biz_id, uploader_id=user.id
    )

    await audit_service.log_operation(
        db,
        module="附件管理",
        action="上传图片",
        user=user,
        target_type=biz_type,
        target_id=biz_id,
        description=f"上传 {len(stored)} 张图片，合计 {sum(s.size for s in stored) // 1024} KB",
    )

    return ApiResponse.ok(
        {
            "uploaded": len(stored),
            "urls": [s.file_url for s in stored],
            "files": [
                {
                    "id": row.id,
                    "file_name": s.file_name,
                    "url": s.file_url,
                    "size": s.size,
                    "content_type": s.content_type,
                }
                for row, s in zip(rows, stored)
            ],
        },
        message=f"成功上传 {len(stored)} 张图片",
    )


@router.post("/files", response_model=ApiResponse[dict], summary="批量上传文档")
async def upload_files(
    db: DbSession,
    user: CurrentUser,
    files: list[UploadFile] = File(..., description="PDF/Word/Excel/PPT/txt/md"),
    biz_type: str = Query(default="knowledge", description="knowledge / report / other"),
    biz_id: str | None = Query(default=None),
):
    """文档上传，供知识库导入使用（PDF 4.7 多格式解析）。"""
    stored = await upload_service.save_many(files, biz_type=biz_type, allow_doc=True)
    rows = await upload_service.persist_attachments(
        db, stored=stored, biz_type=biz_type, biz_id=biz_id, uploader_id=user.id
    )

    await audit_service.log_operation(
        db,
        module="附件管理",
        action="上传文档",
        user=user,
        target_type=biz_type,
        target_id=biz_id,
        description=f"上传 {len(stored)} 个文档",
    )

    return ApiResponse.ok(
        {
            "uploaded": len(stored),
            "files": [
                {
                    "id": row.id,
                    "file_name": s.file_name,
                    "path": s.file_path,
                    "url": s.file_url,
                    "size": s.size,
                    "content_type": s.content_type,
                }
                for row, s in zip(rows, stored)
            ],
        },
        message=f"成功上传 {len(stored)} 个文档",
    )


@router.get(
    "/attachments",
    response_model=ApiResponse[PageData[dict]],
    summary="按业务单据查询附件",
)
async def list_attachments(
    db: DbSession,
    user: CurrentUser,
    biz_type: str | None = None,
    biz_id: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    stmt = select(Attachment)
    count_stmt = select(func.count(Attachment.id))
    if biz_type:
        stmt = stmt.where(Attachment.biz_type == biz_type)
        count_stmt = count_stmt.where(Attachment.biz_type == biz_type)
    if biz_id:
        stmt = stmt.where(Attachment.biz_id == biz_id)
        count_stmt = count_stmt.where(Attachment.biz_id == biz_id)

    total = int((await db.execute(count_stmt)).scalar() or 0)
    rows = (
        await db.execute(
            stmt.order_by(Attachment.created_at.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
    ).scalars().all()

    items = [
        {
            "id": r.id,
            "biz_type": r.biz_type,
            "biz_id": r.biz_id,
            "file_name": r.file_name,
            "url": r.file_url,
            "content_type": r.content_type,
            "size": r.size,
            "storage": r.storage,
            "created_at": r.created_at,
        }
        for r in rows
    ]
    return ApiResponse.ok(PageData.build(items, total, page, page_size))
