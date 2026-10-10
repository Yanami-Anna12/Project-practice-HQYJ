"""站内消息实时推送 —— 进程内 WebSocket 连接中心。

对应需求：司机端「管理员一按下发，司机当场有反应」，
即 `mobile_notification` 一落库就推给对应司机，而不是等司机切回页面才刷新。

★ 四条设计约束（与项目其余部分保持一致）：

1. **不引入外部依赖**：连接表就是进程内的 `dict[user_id, set[WebSocket]]`，
   没有 Redis / 消息队列。本项目是单进程 uvicorn（见 run.py 的说明），够用；
   将来要多副本部署，把这个模块换成 Redis Pub/Sub 即可 ——
   调用方只依赖 `publish_notification()` 这一个函数。

2. **推送绝不能影响主流程**：写消息的是「下发执行」这条业务链路
   （services/mobile.py 的 notify_dispatch），通知只是锦上添花。
   所以本模块对外的函数**一律不抛异常**：没有连接、没有事件循环、socket 已断开
   都只记日志。司机离线是常态，不能因为推不到就把一次成功的下发变成 500。

3. **同步线程安全**：本项目所有路由都是 `def`（同步），FastAPI 把它们放在
   anyio 的工作线程池里执行，而 WebSocket 只存在于事件循环线程。
   跨线程投递用 `asyncio.run_coroutine_threadsafe`：调用方立即返回，不阻塞业务线程。

4. **和 HTTP 接口同一套鉴权**：token 由 routers/ws.py 校验（query 参数），
   本模块只认「已经确认过的 user_id」，不碰 JWT。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Iterable

from fastapi import WebSocket

logger = logging.getLogger(__name__)


def _now() -> str:
    """报文里的时间戳（秒级 ISO 字符串，前端直接显示）。"""
    return datetime.now().isoformat(timespec="seconds")


class NotificationHub:
    """按 user_id 订阅的连接中心（进程内，单事件循环）。

    ★ 一个 user_id 可以挂多条连接：同一个司机账号可能同时开着手机小程序与
      开发者工具，两条都要收到（set 而不是单个 WebSocket）。
    ★ 所有对 `_connections` 的读写都在事件循环线程里，加锁是为了和
      充电桩项目的写法保持一致，也避免将来引入并发投递时踩坑。
    """

    def __init__(self) -> None:
        self._connections: dict[int, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def register(self, user_id: int, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.setdefault(int(user_id), set()).add(websocket)

    async def unregister(self, user_id: int, websocket: WebSocket) -> None:
        async with self._lock:
            peers = self._connections.get(int(user_id))
            if not peers:
                return
            peers.discard(websocket)
            if not peers:
                self._connections.pop(int(user_id), None)

    async def send_to_user(self, user_id: int, payload: dict[str, Any]) -> int:
        """投递给某个用户的全部连接，返回成功条数。

        发送失败的连接说明已经死了（真机切网、进程被杀等），顺手摘掉，
        否则后面每次推送都要在它身上再失败一次。
        """
        async with self._lock:
            peers = list(self._connections.get(int(user_id), ()))
        sent = 0
        for websocket in peers:
            try:
                await websocket.send_json(payload)
                sent += 1
            except Exception as exc:  # noqa: BLE001 —— 单条连接失败不影响其它连接
                logger.info("推送失败，摘除失效连接：user_id=%s（%s）", user_id, exc)
                await self.unregister(user_id, websocket)
        return sent

    async def send_to_users(self, user_ids: Iterable[int], payload: dict[str, Any]) -> int:
        sent = 0
        for user_id in {int(uid) for uid in user_ids}:
            sent += await self.send_to_user(user_id, payload)
        return sent

    @property
    def online_user_count(self) -> int:
        """当前有连接的用户数（诊断用）。"""
        return len(self._connections)

    @property
    def connection_count(self) -> int:
        """当前连接总数（诊断用）。"""
        return sum(len(peers) for peers in self._connections.values())

    def online_user_ids(self) -> list[int]:
        return sorted(self._connections)


# 全局单例：整个进程一个（与 app/services 里其它模块的用法一致）
hub = NotificationHub()

# 推送用的目标事件循环。由 app/main.py 的 startup 绑定；
# 万一 startup 没跑到（例如被别的 ASGI 服务器直接加载），
# 第一条 WebSocket 连接建立时会在 realtime.bind_loop() 里补上。
_loop: asyncio.AbstractEventLoop | None = None


def bind_loop(loop: asyncio.AbstractEventLoop | None = None) -> asyncio.AbstractEventLoop | None:
    """记录「往哪个事件循环里投递」。

    ★ 为什么需要显式绑定：写消息的业务代码跑在线程池里，
      线程池线程没有 running loop，但推送必须回到事件循环线程执行。
      传 None 表示「取当前正在运行的那个循环」（只能在循环线程里调用）。
    """
    global _loop
    if loop is not None:
        _loop = loop
        return _loop
    try:
        _loop = asyncio.get_running_loop()
    except RuntimeError:
        # 在读线程里误调时不要报错：只是暂时绑不上，等第一条 WS 连接再绑
        logger.debug("当前线程没有运行中的事件循环，实时推送暂不可用")
    return _loop


def current_loop() -> asyncio.AbstractEventLoop | None:
    return _loop


def build_notification_payload(
    notification: dict[str, Any], unread: int | None = None
) -> dict[str, Any]:
    """一条站内消息的推送报文（前端按 type 分发）。

    `unread` 是**推送这一刻**服务端算出的未读数：小程序直接用它更新 tabBar
    红点，不必再发一次 `GET /notifications/unread-count`（少一次弱网往返）。
    """
    return {
        "type": "notification",
        "notification": notification,
        "unread": unread,
        "timestamp": _now(),
    }


def publish_to_users(user_ids: Iterable[int], payload: dict[str, Any]) -> None:
    """把报文投递给若干用户（同步上下文安全，永不抛异常）。

    ★ 刻意不等待投递结果：调用方是「下发执行」的 HTTP 请求线程，
      它不该为了推送多等一个网络往返。真要有连接是坏的，
      `NotificationHub.send_to_user` 自己会摘掉。
    """
    targets = {int(uid) for uid in user_ids if uid is not None}
    if not targets:
        return

    loop = _loop
    if loop is None or loop.is_closed():
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # 正常现象：司机全部离线时没人连过 WS，也就没有可用的循环
            logger.info("实时推送跳过：事件循环未就绪（当前无在线连接）")
            return

    try:
        asyncio.run_coroutine_threadsafe(hub.send_to_users(targets, payload), loop)
    except Exception as exc:  # noqa: BLE001 —— 推送失败绝不影响业务主流程
        logger.warning("实时推送投递失败（不影响主流程）：%s", exc)


def publish_notification(
    notification: dict[str, Any], user_id: int, unread: int | None = None
) -> None:
    """单条站内消息推送（services/mobile.py 的唯一入口）。"""
    publish_to_users([user_id], build_notification_payload(notification, unread))
