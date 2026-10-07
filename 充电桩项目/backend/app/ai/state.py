"""LangGraph 状态定义 —— 严格对照 PDF 4.2 LangGraph 状态定义。"""

from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional, TypedDict


def merge_list(left: List[Any] | None, right: List[Any] | None) -> List[Any]:
    """列表字段的归并 reducer：新值追加到旧值之后。"""
    return list(left or []) + list(right or [])


def merge_messages(left: List[Any] | None, right: List[Any] | None) -> List[Any]:
    return list(left or []) + list(right or [])


class MaintenanceState(TypedDict, total=False):
    """运维 Agent 全局状态（PDF 4.2）。

    字段名与方案文档保持一致，便于对照验收。
    """

    # ---------------- 任务标识 ----------------
    task_id: str
    tenant_id: str
    project_id: str
    station_id: str
    schedule_date: str
    time_window: str
    status: str

    # ---------------- 数据快照 ----------------
    work_orders: List[Dict]
    work_order_subtasks: List[Dict]
    faults: List[Dict]
    inspections: List[Dict]
    assets: List[Dict]
    users: List[Dict]
    roles: List[Dict]
    messages: List[Dict]
    statistics: List[Dict]
    report_data: Dict

    # ---------------- 规则 ----------------
    hard_constraints: Dict
    soft_constraints: Dict
    rule_version: str

    # ---------------- 校验 ----------------
    validation_errors: Annotated[List[str], merge_list]
    validation_warnings: Annotated[List[str], merge_list]

    # ---------------- 方案 ----------------
    candidate_plans: List[Dict]
    scored_plans: List[Dict]
    selected_plan: Optional[Dict]
    plan_explanation: Optional[str]

    # ---------------- 人工确认 ----------------
    confirmation: Optional[Dict]
    # 阶段一产出的确认请求载荷（候选方案 + 推荐方案 + 解释）
    confirmation_request: Optional[Dict]

    # ---------------- 执行 ----------------
    dispatch_result: Optional[Dict]

    # ---------------- 异常与重排 ----------------
    exception_events: Annotated[List[Dict], merge_list]
    replan_count: int
    # 约束松弛重试次数（防止 work_order_generation <-> relax_constraints 死循环）
    relax_count: int

    # ---------------- 报告 ----------------
    report: Optional[str]
    report_payload: Dict
    messages_out: Annotated[List[Any], merge_messages]

    # ---------------- 请求参数与运行上下文 ----------------
    request: Dict
    order_type: str
    inspect_frequency: str
    inspect_cycle: int
    inspect_count: int
    station_ids: List[str]
    inspector_ids: List[str]

    # ---------------- 节点追踪 ----------------
    node_traces: Annotated[List[Dict], merge_list]
    progress: int
    current_node: str

    # ---------------- LLM 使用情况 ----------------
    llm_used: bool
    degraded: bool
    llm_notes: Annotated[List[Dict], merge_list]


def initial_state(**overrides: Any) -> MaintenanceState:
    """构造带默认值的初始状态。"""
    state: MaintenanceState = {
        "task_id": "",
        "tenant_id": "default",
        "project_id": "",
        "station_id": "",
        "schedule_date": "",
        "time_window": "09:00-18:00",
        "status": "created",
        "work_orders": [],
        "work_order_subtasks": [],
        "faults": [],
        "inspections": [],
        "assets": [],
        "users": [],
        "roles": [],
        "messages": [],
        "statistics": [],
        "report_data": {},
        "hard_constraints": {},
        "soft_constraints": {},
        "rule_version": "",
        "validation_errors": [],
        "validation_warnings": [],
        "candidate_plans": [],
        "scored_plans": [],
        "selected_plan": None,
        "plan_explanation": None,
        "confirmation": None,
        "confirmation_request": None,
        "dispatch_result": None,
        "exception_events": [],
        "replan_count": 0,
        "relax_count": 0,
        "report": None,
        "report_payload": {},
        "messages_out": [],
        "request": {},
        "order_type": "巡视",
        "inspect_frequency": "月",
        "inspect_cycle": 1,
        "inspect_count": 1,
        "station_ids": [],
        "inspector_ids": [],
        "node_traces": [],
        "progress": 0,
        "current_node": "",
        "llm_used": False,
        "degraded": False,
        "llm_notes": [],
    }
    state.update(overrides)  # type: ignore[arg-type]
    return state
