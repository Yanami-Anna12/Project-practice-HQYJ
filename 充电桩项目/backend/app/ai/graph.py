"""LangGraph 工作流编排 —— 对照 PDF 4.3 工作流图。

正常工单/巡检流程：
  START → load_task → data_perception → constraint_parse → rule_validation
        → work_order_generation → task_scheduling → inspection_processing
        → fault_diagnosis → report_generation → human_confirmation
        → dispatch_execution → END

异常重排入口：
  异常事件 → monitor_exception → impact_analysis → replan → plan_scoring
          → human_confirmation → dispatch_execution
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from app.ai import nodes as N
from app.ai.state import MaintenanceState, initial_state
from app.core.config import settings
from app.core.enums import AgentTaskStatus

logger = logging.getLogger("app.ai.graph")


# ---------------------------------------------------------------- 路由条件


def after_validation(state: MaintenanceState) -> str:
    """PDF 4.3：校验失败走 exception_handler。"""
    return "exception_handler" if state.get("validation_errors") else "work_order_generation"


# 约束松弛最大重试次数：超过则终止流程，避免
# work_order_generation <-> relax_constraints 无限循环导致内存爆炸
MAX_RELAX_RETRY = 2


def after_generation(state: MaintenanceState) -> str:
    """PDF 4.3：无候选方案则松弛约束重试；重试超限则终止，不再死循环。"""
    if state.get("candidate_plans"):
        return "task_scheduling"
    if int(state.get("relax_count") or 0) >= MAX_RELAX_RETRY:
        return "exception_handler"
    return "relax_constraints"


def after_confirmation(state: MaintenanceState) -> str:
    """人工确认路由（PDF 4.8）。

    - 已有人工确认结果且通过 → 下发执行
    - 已有人工确认结果但驳回 → 回到报告生成（重新出方案/重新确认）
    - 尚无确认结果       → 结束本次执行，任务置为等待确认（阶段一停止）
    """
    confirmation = state.get("confirmation")
    if not confirmation:
        return "await_confirmation"
    return "dispatch_execution" if confirmation.get("approved") else "report_generation"


async def await_confirmation(state: MaintenanceState) -> MaintenanceState:
    """阶段一终止节点：等待人工确认（不落任何业务数据）。

    真正的下发只会在 /confirm 触发阶段二后由 dispatch_execution 完成，
    因此「必须人工确认」的硬约束依然成立。
    """
    return {
        "status": AgentTaskStatus.WAITING_CONFIRMATION.value,
        "progress": 92,
        "current_node": "human_confirmation",
    }


def after_impact(state: MaintenanceState) -> str:
    return "replan"


def entry_router(state: MaintenanceState) -> str:
    """根据请求决定入口：正常流程 or 异常重排流程。"""
    request = state.get("request") or {}
    if request.get("mode") == "replan" or state.get("exception_events"):
        return "monitor_exception"
    return "load_task"


# ---------------------------------------------------------------- 建图


def build_graph() -> Any:
    builder = StateGraph(MaintenanceState)

    # 正常流程节点（PDF 4.4）
    builder.add_node("load_task", N.load_task)
    builder.add_node("data_perception", N.data_perception)
    builder.add_node("constraint_parse", N.constraint_parse)
    builder.add_node("rule_validation", N.rule_validation)
    builder.add_node("work_order_generation", N.work_order_generation)
    builder.add_node("task_scheduling", N.task_scheduling)
    builder.add_node("inspection_processing", N.inspection_processing)
    builder.add_node("fault_diagnosis", N.fault_diagnosis)
    builder.add_node("report_generation", N.report_generation)
    builder.add_node("human_confirmation", N.human_confirmation)
    builder.add_node("await_confirmation", await_confirmation)
    builder.add_node("dispatch_execution", N.dispatch_execution)

    # 异常与重排节点
    builder.add_node("monitor_exception", N.monitor_exception)
    builder.add_node("impact_analysis", N.impact_analysis)
    builder.add_node("replan", N.replan)
    builder.add_node("plan_scoring", N.plan_scoring)
    builder.add_node("relax_constraints", N.relax_constraints)
    builder.add_node("exception_handler", N.exception_handler)

    # 入口路由：正常流程 / 异常重排
    builder.add_conditional_edges(
        START,
        entry_router,
        {"load_task": "load_task", "monitor_exception": "monitor_exception"},
    )

    # 正常主链路
    builder.add_edge("load_task", "data_perception")
    builder.add_edge("data_perception", "constraint_parse")
    builder.add_edge("constraint_parse", "rule_validation")
    builder.add_conditional_edges(
        "rule_validation",
        after_validation,
        {
            "exception_handler": "exception_handler",
            "work_order_generation": "work_order_generation",
        },
    )
    builder.add_conditional_edges(
        "work_order_generation",
        after_generation,
        {
            "task_scheduling": "task_scheduling",
            "relax_constraints": "relax_constraints",
            "exception_handler": "exception_handler",
        },
    )
    builder.add_edge("relax_constraints", "work_order_generation")
    builder.add_edge("task_scheduling", "inspection_processing")
    builder.add_edge("inspection_processing", "fault_diagnosis")
    builder.add_edge("fault_diagnosis", "report_generation")
    builder.add_edge("report_generation", "human_confirmation")
    builder.add_conditional_edges(
        "human_confirmation",
        after_confirmation,
        {
            "dispatch_execution": "dispatch_execution",
            "report_generation": "report_generation",
            "await_confirmation": "await_confirmation",
        },
    )
    builder.add_edge("await_confirmation", END)
    builder.add_edge("dispatch_execution", END)
    builder.add_edge("exception_handler", END)

    # 异常重排链路
    builder.add_edge("monitor_exception", "impact_analysis")
    builder.add_conditional_edges(
        "impact_analysis", after_impact, {"replan": "replan"}
    )
    builder.add_edge("replan", "plan_scoring")
    builder.add_edge("plan_scoring", "human_confirmation")

    # 不使用 checkpointer：本图不依赖 interrupt，状态在两次调用之间
    # 通过数据库（ai_agent_task）持久化，可水平扩展且避免并发访问检查点。
    return builder.compile()


_GRAPH: Any = None


def get_graph() -> Any:
    """惰性构建并缓存编译后的图。"""
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
        logger.info("LangGraph 工作流已编译")
    return _GRAPH


# ---------------------------------------------------------------- 运行入口


def thread_config(task_id: str) -> dict:
    return {"configurable": {"thread_id": task_id}}


async def run_graph(task_id: str, payload: dict | None = None, **state_overrides) -> dict:
    """启动一次图执行，返回最终状态与耗时。

    图会在 human_confirmation 节点 interrupt 挂起，
    等待 POST /api/v1/ai/agent/tasks/{task_id}/confirm 恢复。
    """
    graph = get_graph()
    state = initial_state(task_id=task_id, **(payload or {}), **state_overrides)
    # 人工确认结果直接注入初始状态（两阶段执行，PDF 4.8）：
    # 阶段二带着 confirmation 重新跑一遍图，由 human_confirmation 的路由
    # 直接进入 dispatch_execution，无需依赖 checkpointer 恢复进程内状态。
    if isinstance(payload, dict) and payload.get("confirmation"):
        state["confirmation"] = payload["confirmation"]  # type: ignore[typeddict-item]
    started = time.perf_counter()
    try:
        result = await graph.ainvoke(state, config=thread_config(task_id))
    except Exception as exc:  # pragma: no cover - 图级异常兜底
        logger.exception("图执行失败：%s", exc)
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        }

    duration = round((time.perf_counter() - started) * 1000, 2)
    interrupts = result.get("__interrupt__") or []
    return {
        "ok": True,
        "interrupted": bool(interrupts),
        "interrupt_payload": [getattr(i, "value", None) for i in interrupts],
        "state": result,
        "duration_ms": duration,
    }


async def resume_graph(task_id: str, decision: dict) -> dict:
    """人工确认后恢复执行（PDF 4.8）。"""
    graph = get_graph()
    started = time.perf_counter()
    try:
        result = await graph.ainvoke(
            Command(resume=decision), config=thread_config(task_id)
        )
    except Exception as exc:
        logger.exception("图恢复失败：%s", exc)
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        }
    duration = round((time.perf_counter() - started) * 1000, 2)
    interrupts = result.get("__interrupt__") or []
    return {
        "ok": True,
        "interrupted": bool(interrupts),
        "interrupt_payload": [getattr(i, "value", None) for i in interrupts],
        "state": result,
        "duration_ms": duration,
    }


async def graph_snapshot(task_id: str, *, allow_running: bool = False) -> dict | None:
    """历史兼容接口。

    自 v1.1 起图不再使用 checkpointer（改为两阶段 + 数据库持久化状态），
    因此进程内不再保留图快照；任务状态统一从 ai_agent_task 读取。
    """
    return None


def graph_mermaid() -> str:
    """导出工作流图（用于文档与前端展示）。"""
    try:
        return get_graph().get_graph().draw_mermaid()
    except Exception:
        return "graph TD\n  START --> load_task"


def graph_info() -> dict:
    return {
        "framework": "LangGraph",
        "checkpointer": "InMemorySaver",
        "ai_enabled": settings.AI_ENABLED,
        "llm_model": settings.LLM_MODEL,
        "llm_ready": settings.llm_ready,
        "normal_flow": [
            "load_task",
            "data_perception",
            "constraint_parse",
            "rule_validation",
            "work_order_generation",
            "task_scheduling",
            "inspection_processing",
            "fault_diagnosis",
            "report_generation",
            "human_confirmation",
            "dispatch_execution",
        ],
        "replan_flow": [
            "monitor_exception",
            "impact_analysis",
            "replan",
            "plan_scoring",
            "human_confirmation",
            "dispatch_execution",
        ],
    }
