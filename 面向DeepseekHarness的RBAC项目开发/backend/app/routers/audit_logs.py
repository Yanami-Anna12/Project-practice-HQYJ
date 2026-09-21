"""审计日志查询（挂 users:manage）。

    GET /api/audit-logs

★ R5 要求「审计日志只追加、不修改、不删除」。本模块**只有 GET** ——
  不提供任何 POST/PUT/PATCH/DELETE，因为对审计日志的写操作只有系统内部
  通过 services/audit.append_audit() 进行，不应由外部接口触发。

  之所以加这个只读查询接口（需求文档未要求）：
    否则「日志确实被追加了」只能靠直接连数据库才能验证，验收与演示都不方便。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import authorize
from app.models import AuditLog
from app.schemas import AuditLogOut

router = APIRouter(prefix="/api/audit-logs", tags=["审计日志"])

REQUIRED = "users:manage"


@router.get(
    "",
    response_model=list[AuditLogOut],
    summary="审计日志列表（只读）",
    description=(
        "按时间倒序返回审计日志。可按 `action` 或 `target_type` 过滤。\n\n"
        "**本接口为只读**：审计日志不提供任何修改或删除接口（R5）。"
    ),
    dependencies=[Depends(authorize(REQUIRED))],
)
def list_audit_logs(
    db: Session = Depends(get_db),
    action: str | None = Query(default=None, description="按动作名过滤，如 role.delete"),
    target_type: str | None = Query(default=None, description="按目标类型过滤：role/user/permission"),
    limit: int = Query(default=100, ge=1, le=500, description="返回条数上限"),
) -> list[AuditLogOut]:
    stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if target_type:
        stmt = stmt.where(AuditLog.target_type == target_type)

    logs = db.execute(stmt).scalars()
    return [AuditLogOut.model_validate(x) for x in logs]
