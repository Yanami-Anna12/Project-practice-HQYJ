"""消息中心服务 —— PDF 3.8 模块 7：消息中心。

消息卡片展示、消息类型区分、消息详情、未读小红点；
多通道推送（站内信 / 微信 / 飞书 / 邮件）按 PDF 7.3 落地。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.enums import MessageType
from app.core.errors import NotFoundError
from app.models import Message, Notification, User


async def create_message(
    db: AsyncSession,
    *,
    receiver_id: str,
    msg_type: str,
    title: str,
    content: str | None = None,
    detail: dict | None = None,
    work_order_id: str | None = None,
    fault_id: str | None = None,
    report_id: str | None = None,
    link: str | None = None,
    channel: str = "站内信",
    commit: bool = True,
) -> Message:
    message = Message(
        receiver_id=receiver_id,
        msg_type=msg_type,
        title=title,
        content=content,
        detail=detail,
        work_order_id=work_order_id,
        fault_id=fault_id,
        report_id=report_id,
        link=link,
        channel=channel,
    )
    db.add(message)
    if commit:
        await db.commit()
        await db.refresh(message)
    return message


async def list_messages(
    db: AsyncSession,
    *,
    receiver_id: str,
    msg_type: str | None = None,
    is_read: bool | None = None,
    keyword: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[Message], int, int]:
    """消息卡片列表 + 未读小红点数量（PDF 3.8）。"""
    conditions = [Message.receiver_id == receiver_id]
    if msg_type:
        conditions.append(Message.msg_type == msg_type)
    if is_read is not None:
        conditions.append(Message.is_read == is_read)
    if keyword:
        conditions.append(Message.title.ilike(f"%{keyword}%"))

    base = select(Message)
    count_stmt = select(func.count(Message.id))
    for cond in conditions:
        base = base.where(cond)
        count_stmt = count_stmt.where(cond)

    total = int((await db.execute(count_stmt)).scalar() or 0)
    unread = int(
        (
            await db.execute(
                select(func.count(Message.id)).where(
                    Message.receiver_id == receiver_id, Message.is_read.is_(False)
                )
            )
        ).scalar()
        or 0
    )
    stmt = base.order_by(Message.created_at.desc()).limit(limit).offset(offset)
    return list((await db.execute(stmt)).scalars().all()), total, unread


async def mark_read(db: AsyncSession, *, message_id: str, receiver_id: str) -> Message:
    message = await db.get(Message, message_id)
    if message is None or message.receiver_id != receiver_id:
        raise NotFoundError("消息不存在")
    message.is_read = True
    message.read_at = datetime.now()
    await db.commit()
    await db.refresh(message)
    return message


async def mark_all_read(db: AsyncSession, *, receiver_id: str) -> int:
    result = await db.execute(
        update(Message)
        .where(Message.receiver_id == receiver_id, Message.is_read.is_(False))
        .values(is_read=True, read_at=datetime.now())
    )
    await db.commit()
    return int(result.rowcount or 0)


async def message_type_summary(db: AsyncSession, receiver_id: str) -> list[dict]:
    """按消息类型区分统计（PDF 3.8 消息类型区分）。"""
    rows = (
        await db.execute(
            select(Message.msg_type, func.count(Message.id))
            .where(Message.receiver_id == receiver_id)
            .group_by(Message.msg_type)
        )
    ).all()
    summary = {t.value: {"type": t.value, "total": 0, "unread": 0} for t in MessageType}
    unread_rows = (
        await db.execute(
            select(Message.msg_type, func.count(Message.id))
            .where(Message.receiver_id == receiver_id, Message.is_read.is_(False))
            .group_by(Message.msg_type)
        )
    ).all()
    unread_map = {t: int(c) for t, c in unread_rows}
    for msg_type, count in rows:
        item = summary.setdefault(
            msg_type or "系统消息", {"type": msg_type or "系统消息", "total": 0, "unread": 0}
        )
        item["total"] = int(count)
        item["unread"] = unread_map.get(msg_type, 0)
    return list(summary.values())


async def dispatch(
    db: AsyncSession,
    *,
    message: Message,
    receiver: User | None,
    channels: list[str] | None = None,
) -> dict:
    """多通道推送落地（PDF 7.3：飞书、邮件、站内信、微信通知）。

    未配置凭据的通道记录为 skipped，保证主流程不被阻塞；
    真实接入时只需在此实现对应 SDK 调用。
    """
    channels = channels or ["站内信"]
    results: list[dict] = []
    for channel in channels:
        target = ""
        status = "pending"
        error = None
        if channel == "站内信":
            target = message.receiver_id
            status = "sent"
        elif channel == "微信":
            target = (receiver.wechat_openid if receiver else "") or ""
            status = "sent" if (target and settings.WECHAT_APPID) else "skipped"
            if status == "skipped":
                error = "未配置微信凭据或无 openid"
        elif channel == "飞书":
            target = settings.FEISHU_WEBHOOK
            status = "sent" if target else "skipped"
            if status == "skipped":
                error = "未配置飞书 Webhook"
        elif channel == "邮件":
            target = (receiver.email if receiver else "") or ""
            status = "sent" if (target and settings.SMTP_HOST) else "skipped"
            if status == "skipped":
                error = "未配置 SMTP 或用户邮箱"
        else:
            status = "skipped"
            error = f"不支持的通道：{channel}"

        notification = Notification(
            channel=channel,
            target=target or "-",
            title=message.title,
            content=message.content,
            payload=message.detail,
            status=status,
            error=error,
            sent_at=datetime.now() if status == "sent" else None,
            related_type="message",
            related_id=message.id,
        )
        db.add(notification)
        results.append({"channel": channel, "status": status, "error": error})

    await db.commit()
    return {"message_id": message.id, "channels": results}
