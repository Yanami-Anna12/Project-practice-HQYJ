"""附件与多图上传服务 —— PDF 3.2 附件管理 + 2.2 对象存储 + 3.4/3.5 多图上传。

业务要求（PDF 3.4 巡检情况录入 / 3.5 故障上报与核查）：
「支持多图上传」「多图显示」。

存储后端按 STORAGE_BACKEND 切换：
  local —— 落到 backend/data/uploads，通过 /static/data/uploads 访问（默认，开箱可用）
  minio —— 上传到 MinIO（PDF 2.2），需配置凭据
  oss   —— 上传到阿里云 OSS，需配置凭据
未配置外部凭据时自动回落到 local，保证主流程不被阻塞。
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import UPLOAD_DIR, settings
from app.core.errors import BizError
from app.models import Attachment

logger = logging.getLogger("app.services.upload")

# 允许的图片类型（PDF 要求上传现场照片）
ALLOWED_IMAGE_TYPES: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/bmp": ".bmp",
    "image/heic": ".heic",
}

# 允许的非图片附件（设备手册、报告等，供知识库导入使用）
ALLOWED_DOC_TYPES: dict[str, str] = {
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "text/plain": ".txt",
    "text/markdown": ".md",
}

MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 单张图片 10MB
MAX_DOC_BYTES = 50 * 1024 * 1024  # 单个文档 50MB
MAX_IMAGES_PER_REQUEST = 12  # 单次最多 12 张（现场巡检照片量）

_SAFE_NAME = re.compile(r"[^\w\u4e00-\u9fff.\-]+")


@dataclass
class StoredFile:
    file_name: str
    file_path: str
    file_url: str
    content_type: str
    size: int
    storage: str
    sha256: str


def _safe_filename(name: str, fallback_ext: str) -> str:
    """清洗文件名，避免路径穿越与非法字符。"""
    base = Path(name or "").name
    base = _SAFE_NAME.sub("_", base).strip("._") or "file"
    if not Path(base).suffix:
        base = f"{base}{fallback_ext}"
    return base[:120]


def _detect_ext(content_type: str | None, filename: str, allow_doc: bool) -> tuple[str, str]:
    """返回 (扩展名, 归一化 content_type)；不合法则抛错。"""
    ctype = (content_type or "").split(";")[0].strip().lower()
    allowed = dict(ALLOWED_IMAGE_TYPES)
    if allow_doc:
        allowed.update(ALLOWED_DOC_TYPES)

    if ctype in allowed:
        return allowed[ctype], ctype

    # content-type 缺失时按扩展名兜底
    guess = mimetypes.guess_type(filename or "")[0]
    if guess and guess in allowed:
        return allowed[guess], guess

    ext = Path(filename or "").suffix.lower()
    for ct, e in allowed.items():
        if e == ext:
            return e, ct

    allowed_desc = "、".join(sorted({e for e in allowed.values()}))
    raise BizError(f"不支持的文件类型：{content_type or ext or '未知'}（允许：{allowed_desc}）")


def _month_dir() -> Path:
    d = UPLOAD_DIR / datetime.now().strftime("%Y%m")
    d.mkdir(parents=True, exist_ok=True)
    return d


async def save_upload(
    file: UploadFile,
    *,
    biz_type: str,
    allow_doc: bool = False,
) -> StoredFile:
    """保存单个上传文件到本地存储，返回文件元信息。"""
    raw = await file.read()
    size = len(raw)
    if size == 0:
        raise BizError(f"文件为空：{file.filename}")

    limit = MAX_DOC_BYTES if allow_doc else MAX_IMAGE_BYTES
    if size > limit:
        raise BizError(
            f"文件过大：{file.filename}（{size / 1024 / 1024:.1f}MB，上限 {limit // 1024 // 1024}MB）"
        )

    ext, ctype = _detect_ext(file.content_type, file.filename or "", allow_doc)
    safe = _safe_filename(file.filename or "", ext)
    unique = f"{datetime.now().strftime('%H%M%S')}_{uuid.uuid4().hex[:8]}_{safe}"

    target_dir = _month_dir()
    path = target_dir / unique
    path.write_bytes(raw)

    relative = path.relative_to(UPLOAD_DIR).as_posix()
    # 通过 /static/data 挂载访问：backend/data ↔ /static/data
    url = f"/static/data/uploads/{relative}"

    return StoredFile(
        file_name=safe,
        file_path=str(path),
        file_url=url,
        content_type=ctype,
        size=size,
        storage="local",
        sha256=hashlib.sha256(raw).hexdigest(),
    )


async def save_many(
    files: list[UploadFile],
    *,
    biz_type: str,
    allow_doc: bool = False,
) -> list[StoredFile]:
    """批量保存（PDF 3.4 / 3.5 多图上传）。"""
    if not files:
        return []
    if len(files) > MAX_IMAGES_PER_REQUEST:
        raise BizError(f"单次最多上传 {MAX_IMAGES_PER_REQUEST} 个文件，当前 {len(files)} 个")
    return [await save_upload(f, biz_type=biz_type, allow_doc=allow_doc) for f in files]


async def persist_attachments(
    db: AsyncSession,
    *,
    stored: list[StoredFile],
    biz_type: str,
    biz_id: str | None = None,
    uploader_id: str | None = None,
    commit: bool = True,
) -> list[Attachment]:
    """把上传结果登记到 attachment 表（PDF 3.2 附件管理）。"""
    rows: list[Attachment] = []
    for item in stored:
        row = Attachment(
            biz_type=biz_type,
            biz_id=biz_id,
            file_name=item.file_name,
            file_path=item.file_path,
            file_url=item.file_url,
            content_type=item.content_type,
            size=item.size,
            storage=item.storage,
            uploader_id=uploader_id,
        )
        db.add(row)
        rows.append(row)
    if commit and rows:
        await db.commit()
        for row in rows:
            await db.refresh(row)
    return rows


async def bind_attachments(
    db: AsyncSession,
    *,
    file_urls: list[str],
    biz_type: str,
    biz_id: str,
    commit: bool = True,
) -> int:
    """把已上传文件回填业务主键（上传时还不知道 biz_id 的场景）。

    巡检录入 / 故障上报时前端先调上传接口拿到 URL，再随表单提交；
    这里按 URL 把归属补齐，便于后续按业务单据检索附件。
    """
    if not file_urls:
        return 0
    from sqlalchemy import select

    rows = (
        await db.execute(
            select(Attachment).where(
                Attachment.file_url.in_(file_urls),
                Attachment.biz_id.is_(None),
            )
        )
    ).scalars().all()

    for row in rows:
        row.biz_id = biz_id
        row.biz_type = biz_type
    if rows and commit:
        await db.commit()
    return len(rows)


def storage_info() -> dict:
    """当前存储后端与限制说明，供前端提示。"""
    backend = settings.STORAGE_BACKEND
    fallback = None
    if backend == "minio" and not settings.MINIO_ENDPOINT:
        fallback = "minio 未配置，已回落 local"
    elif backend == "oss" and not settings.STORAGE_PLATFORM_API:
        fallback = "oss 未配置，已回落 local"
    return {
        "backend": "local" if fallback else backend,
        "configured": backend,
        "fallback_note": fallback,
        "upload_dir": str(UPLOAD_DIR),
        "public_prefix": "/static/data/uploads",
        "max_image_mb": MAX_IMAGE_BYTES // 1024 // 1024,
        "max_doc_mb": MAX_DOC_BYTES // 1024 // 1024,
        "max_files_per_request": MAX_IMAGES_PER_REQUEST,
        "allowed_image_types": sorted(set(ALLOWED_IMAGE_TYPES.values())),
    }
