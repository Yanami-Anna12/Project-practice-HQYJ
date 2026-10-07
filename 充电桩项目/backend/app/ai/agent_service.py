"""Agent 任务服务 —— 任务落库、图执行、人工确认、异常重排、追踪。

对应 PDF 5.3 / 5.4 / 6.1 / 8.4：
- ai_agent_task / ai_agent_trace 持久化
- WebSocket 进度推送的数据来源
- AI 审计（Prompt、模型、输出、人工修正）
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.graph import graph_snapshot, run_graph
from app.ai.state import MaintenanceState
from app.core.database import AsyncSessionLocal
from app.core.enums import AgentTaskStatus, AgentType
from app.core.errors import BizError, NotFoundError
from app.core.utils import gen_no, to_json_safe
from app.models import AIAgentTask, AIAgentTrace, AIReport, User

logger = logging.getLogger("app.ai.service")


async def create_agent_task(
    db: AsyncSession,
    *,
    agent_type: str,
    request_payload: dict,
    user: User | None = None,
    task_name: str | None = None,
    project_id: str | None = None,
    station_id: str | None = None,
    schedule_date: date | None = None,
    time_window: str | None = None,
) -> AIAgentTask:
    task = AIAgentTask(
        task_no=gen_no("AI"),
        agent_type=agent_type,
        task_name=task_name or f"{agent_type}任务",
        thread_id="",
        status=AgentTaskStatus.CREATED.value,
        tenant_id="default",
        project_id=project_id,
        station_id=station_id,
        schedule_date=schedule_date,
        time_window=time_window,
        request_payload=to_json_safe(request_payload),
        created_by=user.id if user else None,
    )
    db.add(task)
    await db.flush()
    task.thread_id = task.id  # thread_id 与 task_id 一致，便于 interrupt/resume
    await db.commit()
    await db.refresh(task)
    return task


async def _persist_traces(db: AsyncSession, task_id: str, state: dict, duration_ms: float) -> None:
    """把节点追踪写入 ai_agent_trace（PDF 6.1 / 8.4 AI 审计）。"""
    traces = state.get("node_traces") or []
    for index, trace in enumerate(traces):
        db.add(
            AIAgentTrace(
                task_id=task_id,
                node_name=trace.get("node_name") or "unknown",
                step_index=index,
                status=trace.get("status") or "success",
                output_summary=(trace.get("output_summary") or "")[:2000],
                detail=to_json_safe(trace.get("detail") or {}),
                duration_ms=round(duration_ms / max(1, len(traces)), 2),
            )
        )
    await db.commit()


def _run_payload(task: AIAgentTask, payload: dict) -> dict:
    run_payload = dict(payload)
    run_payload["project_id"] = task.project_id or ""
    if task.schedule_date:
        run_payload["schedule_date"] = task.schedule_date.isoformat()
    if task.time_window:
        run_payload["time_window"] = task.time_window
    return run_payload


async def _apply_state(db: AsyncSession, task_id: str, outcome: dict, state: MaintenanceState) -> AIAgentTask:
    """把图执行结果写入 ai_agent_task / ai_agent_trace。

    单独开一个短会话完成落库，绝不在图执行期间持有数据库连接
    （PDF 2.3 千人级并发；长事务会导致 SQLite/PG 写锁争用）。
    """
    task = await db.get(AIAgentTask, task_id)
    if task is None:
        raise NotFoundError("Agent 任务不存在")

    thread_id = task.thread_id or task.id
    await _persist_traces(db, thread_id, state, outcome.get("duration_ms") or 0)

    task.state_snapshot = to_json_safe(
        {
            k: v
            for k, v in state.items()
            if k
            in (
                "validation_errors",
                "validation_warnings",
                "hard_constraints",
                "soft_constraints",
                "report_data",
                "dispatch_result",
                "confirmation",
            )
        }
    )
    task.candidate_plans = to_json_safe(state.get("candidate_plans") or [])
    task.scored_plans = to_json_safe(
        [
            {k: v for k, v in p.items() if k != "subtasks"}
            for p in (state.get("scored_plans") or [])
        ]
    )
    task.selected_plan = to_json_safe(
        {k: v for k, v in (state.get("selected_plan") or {}).items() if k != "subtasks"}
    ) or None
    task.plan_explanation = state.get("plan_explanation")
    if not task.plan_explanation and state.get("report_payload"):
        # 解释由 report_generation 生成并随报告载荷返回
        task.plan_explanation = (state.get("report_payload") or {}).get("plan_explanation")
    task.rule_version = state.get("rule_version")
    task.replan_count = int(state.get("replan_count") or 0)
    task.llm_used = bool(state.get("llm_used"))
    task.degraded = bool(state.get("degraded"))
    if state.get("report"):
        task.result = to_json_safe(state.get("report_payload") or {})
    task.current_node = state.get("current_node")
    task.progress = int(state.get("progress") or 0)
    task.duration_ms = outcome.get("duration_ms")

    if state.get("confirmation_request"):
        # 阶段一：产出候选方案，等待人工确认（PDF 4.8）
        task.status = AgentTaskStatus.WAITING_CONFIRMATION.value
        task.progress = 92
        task.result = to_json_safe(
            {
                **(task.result or {}),
                "confirmation_request": state.get("confirmation_request"),
            }
        )
    elif state.get("dispatch_result"):
        task.status = AgentTaskStatus.DISPATCHED.value
        task.progress = 100
        task.finished_at = datetime.now()
        task.result = to_json_safe(
            {**(task.result or {}), "dispatch_result": state.get("dispatch_result")}
        )
    elif state.get("validation_errors"):
        task.status = AgentTaskStatus.FAILED.value
        task.error = "；".join(state.get("validation_errors") or [])[:2000]
    else:
        task.status = AgentTaskStatus.COMPLETED.value
        task.finished_at = datetime.now()

    await db.commit()
    await db.refresh(task)
    return task


async def execute_task(db: AsyncSession, task: AIAgentTask, payload: dict) -> dict:
    """执行 Agent 任务：调用 LangGraph，落库状态与追踪。

    关键约束：图执行期间不持有数据库会话。先提交运行状态并释放连接，
    跑完图之后再开短会话落库，避免与图内各节点的数据库访问争抢写锁。
    图会在 human_confirmation 节点 interrupt 挂起，任务状态置为 waiting_confirmation。
    """
    task_id = task.id
    thread_id = task.thread_id or task.id
    run_payload = _run_payload(task, payload)

    # 1) 标记运行中并立即提交，随后释放会话
    task.status = AgentTaskStatus.RUNNING.value
    task.progress = 5
    await db.commit()
    await db.close()

    # 2) 执行图（不持有任何数据库会话）
    outcome = await run_graph(thread_id, run_payload)
    state: MaintenanceState = outcome.get("state") or {}

    # 3) 开新会话落库结果
    async with AsyncSessionLocal() as write_db:
        if not outcome.get("ok"):
            row = await write_db.get(AIAgentTask, task_id)
            if row is None:
                return {"ok": False, "error": outcome.get("error")}
            row.status = AgentTaskStatus.FAILED.value
            row.error = outcome.get("error")
            row.progress = 100
            row.finished_at = datetime.now()
            await write_db.commit()
            return {"ok": False, "error": outcome.get("error")}

        row = await _apply_state(write_db, task_id, outcome, state)

    return {
        "ok": True,
        "status": row.status,
        "interrupted": outcome.get("interrupted"),
        "progress": row.progress,
    }


async def run_task_async(task_id: str, payload: dict) -> None:
    """后台执行（BackgroundTasks 调用）。

    会话只在读取任务与写入失败状态时短暂持有，图执行期间不占用连接。
    """
    async with AsyncSessionLocal() as db:
        task = await db.get(AIAgentTask, task_id)
        if task is None:
            logger.warning("后台任务不存在：%s", task_id)
            return
    try:
        async with AsyncSessionLocal() as db:
            task = await db.get(AIAgentTask, task_id)
            if task is None:
                return
            await execute_task(db, task, payload)
    except Exception as exc:  # pragma: no cover
        logger.exception("后台任务执行失败：%s", exc)
        async with AsyncSessionLocal() as db:
            row = await db.get(AIAgentTask, task_id)
            if row is not None:
                row.status = AgentTaskStatus.FAILED.value
                row.error = f"{type(exc).__name__}: {exc}"
                row.finished_at = datetime.now()
                await db.commit()


async def confirm_task(
    db: AsyncSession,
    *,
    task_id: str,
    approved: bool,
    plan_id: str | None,
    adjustments: list[dict] | None,
    comment: str | None,
    user: User | None = None,
) -> AIAgentTask:
    """人工确认（PDF 4.8）—— 阶段二：带着确认结果重新执行图并下发。

    阶段一（execute_task）已把候选方案与推荐方案写入 ai_agent_task；
    本接口读取留存的请求参数与规则版本，注入人工确认结果后再次执行图，
    由 dispatch_execution 完成建单与下发，全程幂等（ai_plan_id 去重）。
    """
    task = await db.get(AIAgentTask, task_id)
    if task is None:
        raise NotFoundError("Agent 任务不存在")
    if task.status not in (
        AgentTaskStatus.WAITING_CONFIRMATION.value,
        AgentTaskStatus.CREATED.value,
    ):
        raise BizError(f"任务当前状态为「{task.status}」，无法执行人工确认")

    # 规则/任务参数来自阶段一留存的请求
    base_request = dict(task.request_payload or {})
    if task.schedule_date:
        base_request["schedule_date"] = task.schedule_date.isoformat()
    if task.time_window:
        base_request["time_window"] = task.time_window

    chosen_plan_id = plan_id or (task.selected_plan or {}).get("plan_id")
    decision = {
        "approved": approved,
        "plan_id": chosen_plan_id,
        "adjustments": to_json_safe(adjustments or []),
        "comment": comment,
        "confirmed_by": user.real_name if user else None,
        "confirmed_at": datetime.now().isoformat(timespec="seconds"),
    }
    base_request["confirmation"] = decision
    base_request["preferred_plan_id"] = chosen_plan_id if approved else None
    thread_id = task.thread_id or task.id

    # 释放连接后再执行图
    await db.close()
    outcome = await run_graph(thread_id, base_request)

    async with AsyncSessionLocal() as write_db:
        task = await write_db.get(AIAgentTask, task_id)
        if task is None:
            raise NotFoundError("Agent 任务不存在")

        if not outcome.get("ok"):
            task.status = AgentTaskStatus.FAILED.value
            task.error = outcome.get("error")
            task.finished_at = datetime.now()
            await write_db.commit()
            raise BizError(f"确认后执行失败：{outcome.get('error')}")

        state: MaintenanceState = outcome.get("state") or {}
        await _persist_traces(
            write_db, thread_id, state, outcome.get("duration_ms") or 0
        )

        task.confirmation = to_json_safe(decision)
        task.current_node = state.get("current_node")
        task.progress = int(state.get("progress") or task.progress)
        if state.get("selected_plan"):
            task.selected_plan = to_json_safe(
                {k: v for k, v in state["selected_plan"].items() if k != "subtasks"}
            )
        task.plan_explanation = state.get("plan_explanation") or task.plan_explanation

        if state.get("dispatch_result"):
            task.status = AgentTaskStatus.DISPATCHED.value
            task.progress = 100
            task.result = to_json_safe(
                {**(task.result or {}), "dispatch_result": state.get("dispatch_result")}
            )
            task.finished_at = datetime.now()
        elif state.get("validation_errors"):
            task.status = AgentTaskStatus.FAILED.value
            task.error = "；".join(state.get("validation_errors") or [])[:2000]
        elif not approved:
            task.status = AgentTaskStatus.COMPLETED.value
            task.finished_at = datetime.now()
        else:
            task.status = AgentTaskStatus.COMPLETED.value
            task.finished_at = datetime.now()

        await write_db.commit()
        await write_db.refresh(task)
        return task


async def replan_task(
    db: AsyncSession,
    *,
    task_id: str,
    exception_type: str,
    description: str | None,
    target_id: str | None,
    lock_executed: bool,
    strategy: str,
    user: User | None = None,
) -> dict:
    """异常重排（PDF 4.9 / 5.3）。"""
    source_task = await db.get(AIAgentTask, task_id)
    if source_task is None:
        raise NotFoundError("Agent 任务不存在")

    max_replan = 3
    if int(source_task.replan_count or 0) >= max_replan:
        raise BizError(
            f"该任务已重排 {source_task.replan_count} 次，达到上限 {max_replan} 次，请人工介入"
        )

    payload = {
        "mode": "replan",
        "exception_type": exception_type,
        "description": description,
        "target_id": target_id,
        "lock_executed": lock_executed,
        "strategy": strategy,
        "project_id": source_task.project_id or "",
        "order_type": (source_task.request_payload or {}).get("order_type") or "巡视",
        "station_ids": (source_task.request_payload or {}).get("station_ids") or [],
        "inspect_cycle": (source_task.request_payload or {}).get("inspect_cycle") or 1,
        "inspect_frequency": (source_task.request_payload or {}).get("inspect_frequency") or "月",
        "inspect_count": (source_task.request_payload or {}).get("inspect_count") or 1,
        "use_llm": False,
        "created_by": user.id if user else None,
    }

    new_task = await create_agent_task(
        db,
        agent_type=AgentType.WORK_ORDER.value,
        request_payload=payload,
        user=user,
        task_name=f"异常重排 · {exception_type}",
        project_id=source_task.project_id,
        station_id=source_task.station_id,
        time_window=source_task.time_window,
    )
    new_task.replan_count = int(source_task.replan_count or 0)
    await db.commit()

    outcome = await execute_task(db, new_task, payload)
    return {
        "source_task_id": task_id,
        "new_task_id": new_task.id,
        "task_no": new_task.task_no,
        "replan_count": new_task.replan_count,
        "status": new_task.status,
        "outcome": outcome,
    }


async def get_task_state(db: AsyncSession, task_id: str) -> dict:
    """查询 Agent 任务状态（PDF 5.3 + WebSocket 推送数据源）。"""
    task = await db.get(AIAgentTask, task_id)
    if task is None:
        raise NotFoundError("Agent 任务不存在")

    traces = (
        await db.execute(
            select(AIAgentTrace)
            .where(AIAgentTrace.task_id == task_id)
            .order_by(AIAgentTrace.step_index.asc())
        )
    ).scalars().all()

    snapshot = await graph_snapshot(task.thread_id or task.id)

    return {
        "task": to_json_safe(
            {
                "id": task.id,
                "task_no": task.task_no,
                "agent_type": task.agent_type,
                "task_name": task.task_name,
                "status": task.status,
                "thread_id": task.thread_id,
                "progress": task.progress,
                "current_node": task.current_node,
                "rule_version": task.rule_version,
                "replan_count": task.replan_count,
                "llm_used": task.llm_used,
                "degraded": task.degraded,
                "error": task.error,
                "selected_plan": task.selected_plan,
                "plan_explanation": task.plan_explanation,
                "confirmation": task.confirmation,
                "result": task.result,
                "created_at": task.created_at,
                "finished_at": task.finished_at,
                "duration_ms": task.duration_ms,
            }
        ),
        "traces": [
            {
                "node_name": t.node_name,
                "step_index": t.step_index,
                "status": t.status,
                "output_summary": t.output_summary,
                "detail": t.detail,
                "duration_ms": t.duration_ms,
                "created_at": t.created_at,
            }
            for t in traces
        ],
        "graph_state": {
            "next": snapshot.get("next") if snapshot else [],
            "current_node": (snapshot.get("values") or {}).get("current_node") if snapshot else None,
            "progress": (snapshot.get("values") or {}).get("progress") if snapshot else None,
        },
        "pending_confirmation": task.status == AgentTaskStatus.WAITING_CONFIRMATION.value,
    }


async def list_tasks(
    db: AsyncSession,
    *,
    agent_type: str | None = None,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[AIAgentTask], int]:
    conditions = []
    if agent_type:
        conditions.append(AIAgentTask.agent_type == agent_type)
    if status:
        conditions.append(AIAgentTask.status == status)

    base = select(AIAgentTask)
    count_stmt = select(func.count(AIAgentTask.id))
    for cond in conditions:
        base = base.where(cond)
        count_stmt = count_stmt.where(cond)

    total = int((await db.execute(count_stmt)).scalar() or 0)
    stmt = base.order_by(AIAgentTask.created_at.desc()).limit(limit).offset(offset)
    return list((await db.execute(stmt)).scalars().all()), total


async def agent_center_overview(db: AsyncSession) -> dict:
    """AI Agent 中心概览（PDF 3.11 八类 Agent）。"""
    rows = (
        await db.execute(
            select(AIAgentTask.agent_type, AIAgentTask.status, func.count(AIAgentTask.id))
            .group_by(AIAgentTask.agent_type, AIAgentTask.status)
        )
    ).all()
    stats: dict[str, dict] = {}
    for agent_type, status, count in rows:
        entry = stats.setdefault(
            agent_type or "未分类", {"agent_type": agent_type, "total": 0, "by_status": {}}
        )
        entry["total"] += int(count)
        entry["by_status"][status] = int(count)

    pending = int(
        (
            await db.execute(
                select(func.count(AIAgentTask.id)).where(
                    AIAgentTask.status == AgentTaskStatus.WAITING_CONFIRMATION.value
                )
            )
        ).scalar()
        or 0
    )
    report_count = int((await db.execute(select(func.count(AIReport.id)))).scalar() or 0)
    llm_used = int(
        (
            await db.execute(
                select(func.count(AIAgentTask.id)).where(AIAgentTask.llm_used.is_(True))
            )
        ).scalar()
        or 0
    )
    total_tasks = int((await db.execute(select(func.count(AIAgentTask.id)))).scalar() or 0)

    return {
        "agents": [
            {"agent_type": t.value, "code": c}
            for t, c in [
                (AgentType.WORK_ORDER, "work_order"),
                (AgentType.FAULT_DIAGNOSIS, "fault_diagnosis"),
                (AgentType.INSPECTION_REPORT, "inspection_report"),
                (AgentType.MAINTENANCE_SUGGEST, "maintenance_suggest"),
                (AgentType.RISK_CONTROL, "risk_control"),
                (AgentType.REPORT, "report"),
                (AgentType.DATA_ANALYSIS, "data_analysis"),
                (AgentType.ORCHESTRATOR, "orchestrator"),
            ]
        ],
        "stats": list(stats.values()),
        "summary": {
            "total_tasks": total_tasks,
            "pending_confirmation": pending,
            "llm_enhanced_tasks": llm_used,
            "report_count": report_count,
        },
    }
