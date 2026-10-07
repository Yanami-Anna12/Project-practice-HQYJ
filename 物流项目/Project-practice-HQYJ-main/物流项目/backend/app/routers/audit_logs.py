"""审计日志接口。

★ 只有 GET —— 日志「只追加、不修改、不删除」在接口层的体现。
  对 /audit-logs 发 POST/PUT/PATCH/DELETE 一律 405。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.deps import DbSession, require_permission
from app.models import SysAuditLog, SysUser
from app.schemas import AuditLogOut
from app.services.audit import parse_detail

router = APIRouter(prefix="/audit-logs", tags=["日志管理"])

Reader = Annotated[SysUser, Depends(require_permission("logs:read"))]


@router.get("", response_model=list[AuditLogOut], summary="审计日志列表")
def list_audit_logs(
    db: DbSession,
    actor: Reader,
    action: str = Query(default="", max_length=64),
    target_type: str = Query(default="", max_length=32),
    limit: int = Query(default=200, ge=1, le=1000),
) -> list[AuditLogOut]:
    q = db.query(SysAuditLog)
    if action:
        q = q.filter(SysAuditLog.action == action)
    if target_type:
        q = q.filter(SysAuditLog.target_type == target_type)
    rows = q.order_by(SysAuditLog.id.desc()).limit(limit).all()

    return [
        AuditLogOut(
            id=r.id,
            actor_id=r.actor_id,
            actor_name=r.actor_name,
            action=r.action,
            target_type=r.target_type,
            target_name=r.target_name,
            detail=parse_detail(r.detail_json),
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.get("/actions", response_model=list[str], summary="日志中出现过的动作码")
def list_actions(db: DbSession, actor: Reader) -> list[str]:
    rows = db.query(SysAuditLog.action).distinct().all()
    return sorted(r[0] for r in rows)
