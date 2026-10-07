"""审计与日志服务 —— PDF 8.4 日志与审计。

操作日志：谁创建、启动、确认、重排；
规则变更日志：谁改了规则、改了什么、何时生效；
方案审计：每个方案的规则版本、数据快照、评分明细；
下发审计：下发时间、接收方、结果；
AI 审计：Prompt、模型、输出、人工修正。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.utils import to_json_safe
from app.models import LoginLog, OperationLog, RuleVersion, User


async def log_operation(
    db: AsyncSession,
    *,
    module: str,
    action: str,
    user: User | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    description: str | None = None,
    method: str | None = None,
    path: str | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    status_code: int | None = None,
    duration_ms: float | None = None,
    before: dict | None = None,
    after: dict | None = None,
    commit: bool = True,
) -> OperationLog:
    log = OperationLog(
        user_id=user.id if user else None,
        user_name=user.real_name if user else None,
        module=module,
        action=action,
        target_type=target_type,
        target_id=target_id,
        description=description,
        method=method,
        path=path,
        ip=ip,
        user_agent=user_agent,
        status_code=status_code,
        duration_ms=duration_ms,
        before=to_json_safe(before) if before else None,
        after=to_json_safe(after) if after else None,
    )
    db.add(log)
    if commit:
        await db.commit()
    return log


async def log_login(
    db: AsyncSession,
    *,
    user: User | None,
    success: bool,
    message: str | None = None,
    login_type: str = "password",
    ip: str | None = None,
    user_agent: str | None = None,
) -> LoginLog:
    log = LoginLog(
        user_id=user.id if user else None,
        user_name=user.username if user else None,
        login_type=login_type,
        success=success,
        message=message,
        ip=ip,
        user_agent=user_agent,
    )
    db.add(log)
    if user and success:
        user.last_login_at = datetime.now()
    await db.commit()
    return log


async def list_operation_logs(
    db: AsyncSession,
    *,
    module: str | None = None,
    user_name: str | None = None,
    action: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[OperationLog], int]:
    conditions = []
    if module:
        conditions.append(OperationLog.module == module)
    if user_name:
        conditions.append(OperationLog.user_name.ilike(f"%{user_name}%"))
    if action:
        conditions.append(OperationLog.action == action)

    base = select(OperationLog)
    count_stmt = select(func.count(OperationLog.id))
    for cond in conditions:
        base = base.where(cond)
        count_stmt = count_stmt.where(cond)

    total = int((await db.execute(count_stmt)).scalar() or 0)
    stmt = base.order_by(OperationLog.created_at.desc()).limit(limit).offset(offset)
    return list((await db.execute(stmt)).scalars().all()), total


async def list_login_logs(
    db: AsyncSession, *, limit: int = 20, offset: int = 0
) -> tuple[list[LoginLog], int]:
    total = int((await db.execute(select(func.count(LoginLog.id)))).scalar() or 0)
    stmt = select(LoginLog).order_by(LoginLog.created_at.desc()).limit(limit).offset(offset)
    return list((await db.execute(stmt)).scalars().all()), total


async def record_rule_version(
    db: AsyncSession,
    *,
    version: str,
    hard_constraints: dict,
    soft_constraints: dict,
    change_log: str,
    user: User | None = None,
    activate: bool = True,
) -> RuleVersion:
    """规则版本化（PDF 4.1 原则 5）：每次调度记录规则版本，保证可追溯。"""
    if activate:
        rows = (await db.execute(select(RuleVersion).where(RuleVersion.is_active.is_(True)))).scalars().all()
        for row in rows:
            row.is_active = False

    record = RuleVersion(
        version=version,
        rule_snapshot={"hard": hard_constraints, "soft": soft_constraints},
        hard_constraints=hard_constraints,
        soft_constraints=soft_constraints,
        is_active=activate,
        change_log=change_log,
        created_by=user.id if user else None,
        effective_at=datetime.now() if activate else None,
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)
    return record


async def active_rule_version(db: AsyncSession) -> RuleVersion | None:
    return (
        await db.execute(
            select(RuleVersion)
            .where(RuleVersion.is_active.is_(True))
            .order_by(RuleVersion.created_at.desc())
        )
    ).scalars().first()
