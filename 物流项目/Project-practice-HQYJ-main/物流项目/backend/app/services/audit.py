"""审计日志写入。

★ 全项目**只有这里**会写 sys_audit_log，且只做 INSERT（永不 UPDATE / DELETE）。
  这条约束是「日志只追加」的根本保证 —— 接口层没有写入口，代码层没有写方法。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models import SysAuditLog, SysUser

logger = logging.getLogger(__name__)


def append_audit(
    db: Session,
    *,
    actor: SysUser | None,
    action: str,
    target_type: str = "",
    target_name: str = "",
    detail: dict[str, Any] | None = None,
    actor_name: str | None = None,
    commit: bool = True,
) -> SysAuditLog:
    """追加一条审计日志。

    actor 为 None 时（例如「账号不存在」的登录失败）可用 actor_name 传入用户名。
    commit=False 时由调用方在同一事务里提交，保证「业务变更 + 审计」原子性。
    """
    log = SysAuditLog(
        actor_id=actor.id if actor else None,
        # 冗余存快照：即使操作者后续被删除，日志依然可读
        actor_name=(actor.username if actor else None) or actor_name or "unknown",
        action=action,
        target_type=target_type,
        target_name=target_name[:128],
        detail_json=json.dumps(detail or {}, ensure_ascii=False),
    )
    db.add(log)
    if commit:
        db.commit()
    logger.debug("audit: %s %s %s", log.actor_name, action, target_name)
    return log


def parse_detail(raw: str) -> dict[str, Any]:
    """把 detail_json 解析回 dict；坏数据不让它把整个列表接口带崩。"""
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}
