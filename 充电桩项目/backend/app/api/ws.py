"""WebSocket 进度推送 —— 对照 PDF 5.4。

推送格式：
{
  "task_id": "T001",
  "node": "report_generation",
  "status": "running",
  "message": "正在生成月度深度报告",
  "progress": 45
}
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import decode_access_token
from app.models import AIAgentTask, User

logger = logging.getLogger("app.ws")

router = APIRouter(tags=["WebSocket"])

NODE_MESSAGES = {
    "load_task": "正在加载任务与上下文",
    "data_perception": "正在并行拉取工单、故障、巡检与资产数据",
    "constraint_parse": "正在解析规则中心配置",
    "rule_validation": "正在校验数据完整性、规则与权限冲突",
    "work_order_generation": "正在生成工单与子任务多方案（CP-SAT + 启发式）",
    "task_scheduling": "正在分配人员、排班与路线",
    "inspection_processing": "正在处理巡检记录并识别异常",
    "fault_diagnosis": "正在进行根因分析（RAG + LLM）",
    "report_generation": "正在生成运维分析报告",
    "human_confirmation": "等待人工确认方案",
    "dispatch_execution": "正在下发工单到员工端",
    "monitor_exception": "正在接收异常事件",
    "impact_analysis": "正在做影响分析",
    "replan": "正在执行异常重排",
    "plan_scoring": "正在对方案评分",
    "relax_constraints": "正在放宽约束并重新求解",
    "exception_handler": "流程异常终止",
}


class TaskProgressHub:
    """任务进度订阅中心（进程内）。"""

    def __init__(self) -> None:
        self._subscribers: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, task_id: str, ws: WebSocket) -> None:
        async with self._lock:
            self._subscribers.setdefault(task_id, set()).add(ws)

    async def unsubscribe(self, task_id: str, ws: WebSocket) -> None:
        async with self._lock:
            subs = self._subscribers.get(task_id)
            if subs:
                subs.discard(ws)
                if not subs:
                    self._subscribers.pop(task_id, None)

    async def publish(self, task_id: str, payload: dict) -> int:
        async with self._lock:
            subs = list(self._subscribers.get(task_id, set()))
        sent = 0
        for ws in subs:
            try:
                await ws.send_json(payload)
                sent += 1
            except Exception:
                await self.unsubscribe(task_id, ws)
        return sent


hub = TaskProgressHub()


async def _authenticate(websocket: WebSocket) -> User | None:
    """通过 query 参数 token 或 Authorization 头鉴权。"""
    token = websocket.query_params.get("token")
    if not token:
        header = websocket.headers.get("authorization")
        if header and header.lower().startswith("bearer "):
            token = header.split(None, 1)[1]
    if not token:
        return None
    payload = decode_access_token(token)
    if not payload or not payload.get("sub"):
        return None
    async with AsyncSessionLocal() as db:
        user = await db.get(User, payload["sub"])
        return user if (user and user.status) else None


@router.websocket("/ws/agent/tasks/{task_id}")
async def agent_task_progress(websocket: WebSocket, task_id: str):
    """订阅单个 Agent 任务的执行进度（PDF 5.4）。"""
    user = await _authenticate(websocket)
    if user is None:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    await hub.subscribe(task_id, websocket)

    last_node: str | None = None
    last_progress = -1
    try:
        while True:
            async with AsyncSessionLocal() as db:
                task = await db.get(AIAgentTask, task_id)
                if task is None:
                    await websocket.send_json(
                        {
                            "task_id": task_id,
                            "node": None,
                            "status": "not_found",
                            "message": "任务不存在",
                            "progress": 0,
                        }
                    )
                    break
                snapshot = {
                    "task_id": task.id,
                    "task_no": task.task_no,
                    "agent_type": task.agent_type,
                    "node": task.current_node,
                    "status": task.status,
                    "message": NODE_MESSAGES.get(
                        task.current_node or "", task.task_name or "执行中"
                    ),
                    "progress": task.progress,
                    "llm_used": task.llm_used,
                    "degraded": task.degraded,
                    "error": task.error,
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                }

            if snapshot["node"] != last_node or snapshot["progress"] != last_progress:
                await websocket.send_json(snapshot)
                last_node = snapshot["node"]
                last_progress = snapshot["progress"]

            if snapshot["status"] in ("completed", "failed", "dispatched", "cancelled"):
                await websocket.send_json({**snapshot, "final": True})
                break

            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # pragma: no cover
        logger.warning("WS 推送异常：%s", exc)
    finally:
        await hub.unsubscribe(task_id, websocket)
        try:
            await websocket.close()
        except Exception:
            pass


@router.websocket("/ws/notifications")
async def notifications(websocket: WebSocket):
    """实时消息推送（PDF 3.8 消息中心未读小红点）。"""
    user = await _authenticate(websocket)
    if user is None:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    last_count = -1
    try:
        from sqlalchemy import func

        from app.models import Message

        while True:
            async with AsyncSessionLocal() as db:
                unread = int(
                    (
                        await db.execute(
                            select(func.count(Message.id)).where(
                                Message.receiver_id == user.id, Message.is_read.is_(False)
                            )
                        )
                    ).scalar()
                    or 0
                )
                latest = (
                    await db.execute(
                        select(Message)
                        .where(Message.receiver_id == user.id)
                        .order_by(Message.created_at.desc())
                        .limit(1)
                    )
                ).scalars().first()

            if unread != last_count:
                await websocket.send_json(
                    {
                        "type": "unread",
                        "unread_count": unread,
                        "latest": {
                            "id": latest.id,
                            "title": latest.title,
                            "msg_type": latest.msg_type,
                            "created_at": latest.created_at.isoformat()
                            if latest and latest.created_at
                            else None,
                        }
                        if latest
                        else None,
                        "timestamp": datetime.now().isoformat(timespec="seconds"),
                    }
                )
                last_count = unread
            await asyncio.sleep(3.0)
    except WebSocketDisconnect:
        pass
    except Exception as exc:  # pragma: no cover
        logger.warning("通知 WS 异常：%s", exc)
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


@router.get("/ws/info", summary="WebSocket 端点说明")
async def ws_info():
    return {
        "agent_progress": "/api/v1/ws/agent/tasks/{task_id}?token=<JWT>",
        "notifications": "/api/v1/ws/notifications?token=<JWT>",
        "progress_payload_example": {
            "task_id": "T001",
            "node": "report_generation",
            "status": "running",
            "message": "正在生成月度深度报告",
            "progress": 45,
        },
    }


def publish_progress(task_id: str, payload: dict) -> None:
    """供后台任务调用（同步上下文安全）。"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(hub.publish(task_id, payload))


def dumps(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)
