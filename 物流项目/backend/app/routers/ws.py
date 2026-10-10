"""WebSocket 实时推送接口（司机端消息中心 / 趟次列表）。

对应需求：管理员在网页端点「下发执行」后，司机端**当场**收到新任务通知，
而不是等司机切回页面才刷新。

地址（挂载在 /api 前缀下）：

    GET /api/ws/notifications?token=<JWT>

★ 为什么 token 走 query 而不是 Authorization 头：
  小程序端 `uni.connectSocket` 无法可靠地自定义请求头（微信小程序
  `wx.connectSocket` 有 header 字段但历史上限制多、且 H5 端 WebSocket
  构造函数根本不支持自定义头），所以统一用 query 传 token。
  服务端用与 HTTP 接口**同一套** JWT 校验（app/security.py），
  并且额外要求账号处于启用状态。

报文（服务端 → 客户端，均为 JSON 文本）：

    {"type": "connected",    "user_id": 7, "username": "driver1", "unread": 4, "timestamp": "..."}
    {"type": "notification", "notification": {...MobileNotificationOut 同字段...},
                             "unread": 5, "timestamp": "..."}
    {"type": "ping",         "timestamp": "..."}          # 每 25 秒一次保活

报文（客户端 → 服务端）：

    ping  或  {"type": "ping"}   →  服务端回 {"type": "pong", ...}

错误码：鉴权失败时直接 `close(4401)`，此时握手会被拒绝（客户端表现为
连接失败 / HTTP 403），客户端应停止重连并回到登录页。
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.database import SessionLocal
from app.models import SysUser
from app.security import decode_access_token
from app.services import mobile as mobile_service
from app.services import realtime
from app.services.realtime import hub

logger = logging.getLogger(__name__)

router = APIRouter(tags=["实时推送"])

# 心跳间隔（秒）。取 25 秒：低于常见反向代理 30s 的空闲断连阈值，
# 也远低于微信小程序的 60s 无数据超时。
HEARTBEAT_SECONDS = 25.0

# 自定义关闭码：4401 表示「未授权 / 登录已失效」（对齐 HTTP 401 的语义）
WS_CLOSE_UNAUTHORIZED = 4401


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _authenticate(websocket: WebSocket) -> tuple[int, str] | None:
    """校验 token，返回 (user_id, username)；不通过返回 None。

    ★ 只返回基本类型，不返回 ORM 对象：会话在这里就关掉了，
      把游离对象带出去迟早会踩到 DetachedInstanceError。
    """
    token = (websocket.query_params.get("token") or "").strip()
    if not token:
        # 兼容：部分客户端（如浏览器调试、脚本）能带 header，也一并认
        header = websocket.headers.get("authorization") or ""
        if header.lower().startswith("bearer "):
            token = header.split(None, 1)[1].strip()
    if not token:
        return None

    user_id = decode_access_token(token)
    if user_id is None:
        return None

    with SessionLocal() as db:
        user = db.get(SysUser, user_id)
        if user is None or not user.is_active:
            return None
        return int(user.id), user.username


def _unread_count(user_id: int) -> int:
    """未读数。★ 取不到时返回 0 而不是抛错：连上了就该能用，不能因为
    一次计数查询失败把连接打掉。"""
    try:
        with SessionLocal() as db:
            return mobile_service.unread_count_for_user(db, user_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("未读数查询失败：user_id=%s（%s）", user_id, exc)
        return 0


def _is_ping(text: str) -> bool:
    """客户端心跳：纯文本 ping，或 {"type":"ping"}。"""
    value = (text or "").strip()
    if not value:
        return False
    if value.lower() == "ping":
        return True
    try:
        return json.loads(value).get("type") == "ping"
    except (ValueError, AttributeError):
        return False


@router.websocket("/ws/notifications")
async def notifications_socket(websocket: WebSocket) -> None:
    """司机端实时消息推送。"""
    identity = _authenticate(websocket)
    if identity is None:
        # ★ accept 之前 close：握手被拒（客户端看到的是 HTTP 403），
        #   不会给未授权者建立一条「连上了但什么都不推」的连接。
        await websocket.close(code=WS_CLOSE_UNAUTHORIZED)
        return

    user_id, username = identity
    await websocket.accept()
    # 兜底绑定事件循环：正常由 app/main.py 的 startup 绑定，
    # 万一没跑到（换 ASGI 服务器直接加载 app 等），这里补上。
    realtime.bind_loop()
    await hub.register(user_id, websocket)
    logger.info(
        "WS 已连接：user_id=%s（%s），在线用户 %d / 连接 %d",
        user_id,
        username,
        hub.online_user_count,
        hub.connection_count,
    )

    try:
        # 首帧告诉客户端「我是谁 + 现在几条未读」，客户端不用再发一次 HTTP
        await websocket.send_json(
            {
                "type": "connected",
                "user_id": user_id,
                "username": username,
                "unread": _unread_count(user_id),
                "timestamp": _now(),
            }
        )

        while True:
            try:
                text = await asyncio.wait_for(
                    websocket.receive_text(), timeout=HEARTBEAT_SECONDS
                )
            except asyncio.TimeoutError:
                # 保活 + 探活：连接已经被对端悄悄掐掉时，send 会抛错并走下面的清理
                await websocket.send_json({"type": "ping", "timestamp": _now()})
                continue
            if _is_ping(text):
                await websocket.send_json({"type": "pong", "timestamp": _now()})
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # noqa: BLE001 —— 连接级异常只记日志
        logger.warning("WS 连接异常：user_id=%s（%s）", user_id, exc)
    finally:
        await hub.unregister(user_id, websocket)
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass
        logger.info("WS 已断开：user_id=%s（%s）", user_id, username)


@router.get("/ws/info", summary="WebSocket 端点说明")
def ws_info() -> dict:
    """给「怎么连」一个自解释的入口（也方便现场排查连不上的原因）。"""
    return {
        "notifications": "/api/ws/notifications?token=<JWT>",
        "online_users": hub.online_user_count,
        "online_connections": hub.connection_count,
        "heartbeat_seconds": HEARTBEAT_SECONDS,
        "frames_from_server": {
            "connected": {"type": "connected", "user_id": 7, "username": "driver1", "unread": 4},
            "notification": {
                "type": "notification",
                "notification": {
                    "id": 13,
                    "title": "新任务下发：T20261010-002（沪A1001）",
                    "content": "2026-10-10 AM 时段，车牌 沪A1001 共 1 个趟次，请在小程序「我的趟次」中查看并按时打卡。",
                    "biz_type": "dispatch",
                    "biz_id": 3,
                    "is_read": False,
                    "created_at": "2026-10-10T10:00:00",
                },
                "unread": 5,
            },
            "ping": {"type": "ping"},
        },
        "frames_from_client": {"ping": "ping 或 {\"type\":\"ping\"}（服务端回 pong）"},
    }
