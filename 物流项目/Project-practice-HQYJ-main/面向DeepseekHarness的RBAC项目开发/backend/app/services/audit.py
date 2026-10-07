"""审计日志写入（R5：只追加、不修改、不删除）。

★ 全项目对 audit_logs 的「唯一写入口」就是本文件的 append_audit()。
  它只做 INSERT，没有任何 UPDATE / DELETE 路径。

「只追加」是怎么被保证的（四层）：
  1. 【代码层】本模块只提供 append_audit()，全项目没有第二处写 AuditLog；
     也没有任何 db.delete(AuditLog) / UPDATE audit_logs 的调用。
  2. 【接口层】/api/audit-logs 只暴露 GET，不提供任何写接口。
  3. 【模型层】AuditLog 的 actor_id 用 ON DELETE SET NULL 而非 CASCADE：
     操作者被删，日志依然保留（否则删个用户就把历史一起抹掉了）。
  4. 【数据层】actor_name 冗余存快照，即使 actor_id 变为 NULL，日志仍可读。

自证命令（应只命中本文件与模型注释）：
    grep -rn "AuditLog" app | grep -iE "delete|update|setattr"
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog, User

logger = logging.getLogger(__name__)

# 动作名常量：集中定义避免各处手写字符串拼错
ACTION_ROLE_CREATE = "role.create"
ACTION_ROLE_UPDATE = "role.update"
ACTION_ROLE_DELETE = "role.delete"
ACTION_ROLE_ASSIGN_PERMISSIONS = "role.assign_permissions"
ACTION_USER_ASSIGN_ROLES = "user.assign_roles"
ACTION_PERMISSION_CREATE = "permission.create"
ACTION_PERMISSION_TOGGLE = "permission.toggle"
ACTION_AUTH_LOGIN = "auth.login"
ACTION_AUTH_LOGIN_FAILED = "auth.login_failed"


def append_audit(
    db: Session,
    *,
    action: str,
    actor: User | None = None,
    actor_id: int | None = None,
    actor_name: str | None = None,
    target_type: str | None = None,
    target_id: int | None = None,
    target_name: str | None = None,
    detail: dict[str, Any] | None = None,
) -> AuditLog:
    """追加一条审计日志。

    参数说明：
      actor       操作者实体对象（可选）
      actor_id    操作者 ID；与 actor 二选一。
                  路由层通常只有鉴权用的 CurrentUser（不是 ORM 实体），
                  直接传 actor_id=current.id 可省掉一次 db.get(User, ...) 查询。
      actor_name  操作者名快照；不传 actor/actor_name 时记为 "system"
                  （例如登录失败、系统初始化）
      detail      变更详情（旧值/新值），用中文键名，便于直接在界面里读

    注意：本函数只 add 不 commit —— 事务边界由调用方掌握，
    这样「业务变更」与「审计记录」要么同时成功、要么同时回滚，不会出现
    「角色改了但日志没记」或「日志记了但角色没改」的不一致。
    """
    log = AuditLog(
        actor_id=actor.id if actor is not None else actor_id,
        # 冗余快照：即使将来 actor 被删除（actor_id 变 NULL），日志仍能读懂是谁做的
        actor_name=actor.username if actor is not None else (actor_name or "system"),
        action=action,
        target_type=target_type,
        target_id=target_id,
        target_name=target_name,
        detail=detail,
    )
    db.add(log)
    db.flush()
    logger.info(
        "审计：%s by=%s target=%s/%s",
        action,
        log.actor_name,
        target_type,
        target_name or target_id,
    )
    return log
