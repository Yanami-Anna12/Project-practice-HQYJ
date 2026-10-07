"""AI Agent 接口 —— PDF 5.3 AI Agent 核心接口。

POST /api/v1/ai/work-order/generate      智能工单生成
POST /api/v1/ai/fault/diagnose           智能故障诊断
POST /api/v1/ai/inspection/report        智能巡检报告
POST /api/v1/ai/maintenance/suggest      智能运维建议
POST /api/v1/ai/report/generate          智能报告生成
POST /api/v1/ai/assistant/ask            学习助手追问
POST /api/v1/ai/risk/check               风控检查
GET  /api/v1/ai/agent/tasks/{id}         查询 Agent 任务状态
POST /api/v1/ai/agent/tasks/{id}/confirm 人工确认
POST /api/v1/ai/agent/tasks/{id}/replan  异常重排
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Query
from sqlalchemy import func, select

from app.ai import agent_service
from app.ai.graph import graph_info, graph_mermaid
from app.ai.knowledge import build_context, retrieve, upsert_document
from app.ai.llm import llm_client
from app.ai.nodes import rule_based_root_cause
from app.core.deps import CurrentUser, DbSession
from app.core.enums import AgentTaskStatus, AgentType, FaultStatus, TimeStatus
from app.core.errors import BizError, NotFoundError
from app.core.response import ApiResponse, PageData
from app.core.utils import safe_rate, to_json_safe
from app.models import (
    AIAgentTask,
    AIExceptionEvent,
    AIFeedback,
    AIKnowledgeBase,
    AIReport,
    ChargingPile,
    FaultReport,
    InspectionRecord,
    OperationLog,
    Station,
    User,
    WorkOrder,
    WorkOrderSubtask,
)
from app.schemas import (
    AgentConfirmRequest,
    AgentReplanRequest,
    AgentTaskOut,
    AssistantAskRequest,
    FaultDiagnoseRequest,
    FeedbackCreate,
    InspectionReportRequest,
    KnowledgeAskRequest,
    KnowledgeDocCreate,
    MaintenanceSuggestRequest,
    ReportGenerateRequest,
    RiskCheckRequest,
    WorkOrderGenerateRequest,
)
from app.services.audit import log_operation

router = APIRouter(prefix="/ai", tags=["AI Agent"])

# 注意：report_service 依赖 app.ai.nodes -> app.schemas，
# 若在模块顶部导入会与「app.schemas -> app.api.ai」形成循环引用，
# 因此在 schemas 完成加载后再导入。
from app.ai.report_service import (  # noqa: E402
    compare_reports,
    follow_up,
    generate_report,
    get_report,
    list_reports,
    push_report,
)


# ================================================================ 健康检查 / 工作流


@router.get("/health", response_model=ApiResponse[dict], summary="AI 能力与 LLM 状态")
async def ai_health(db: DbSession, user: CurrentUser):
    health = await llm_client.health()
    kb_count = int((await db.execute(select(func.count(AIKnowledgeBase.id)))).scalar() or 0)
    return ApiResponse.ok({**health, "knowledge_docs": kb_count})


@router.get("/graph", response_model=ApiResponse[dict], summary="LangGraph 工作流信息")
async def graph_meta(db: DbSession, user: CurrentUser):
    return ApiResponse.ok({**graph_info(), "mermaid": graph_mermaid()})


# ================================================================ 智能工单生成


@router.post("/work-order/generate", response_model=ApiResponse[dict], summary="智能工单生成")
async def work_order_generate(
    payload: WorkOrderGenerateRequest,
    db: DbSession,
    user: CurrentUser,
    background: BackgroundTasks,
):
    """智能工单调度 Agent：生成工单与子任务多方案（PDF 3.11 / 4.3）。

    硬约束由 CP-SAT + 启发式保证，LLM 只做方案解释；
    流程会在 human_confirmation 节点挂起，等待人工确认接口恢复。
    """
    request_payload = {
        "order_type": payload.order_type,
        "station_ids": payload.station_ids,
        "inspect_cycle": payload.inspect_cycle,
        "inspect_frequency": payload.inspect_frequency,
        "inspect_count": payload.inspect_count,
        "order_name": f"{payload.order_type}工单（AI 生成）",
        "inspector_ids": payload.inspector_ids,
        "time_window": payload.time_window or "09:00-18:00",
        "use_llm": payload.explain_with_llm,
        "created_by": user.id,
    }
    task = await agent_service.create_agent_task(
        db,
        agent_type=AgentType.WORK_ORDER.value,
        request_payload=request_payload,
        user=user,
        task_name=f"智能工单生成 · {payload.order_type}",
        project_id=payload.project_id,
        schedule_date=payload.schedule_date,
        time_window=payload.time_window,
    )

    if payload.auto_start:
        if payload.schedule_date:
            request_payload["schedule_date"] = payload.schedule_date.isoformat()
        background.add_task(agent_service.run_task_async, task.id, request_payload)
        return ApiResponse.ok(
            {
                "task_id": task.id,
                "task_no": task.task_no,
                "thread_id": task.thread_id,
                "status": task.status,
                "status_url": f"/api/v1/ai/agent/tasks/{task.id}",
                "confirm_url": f"/api/v1/ai/agent/tasks/{task.id}/confirm",
            },
            message="任务已创建并开始执行，可在人工确认节点前轮询任务状态",
        )

    return ApiResponse.ok(
        {"task_id": task.id, "task_no": task.task_no, "thread_id": task.thread_id},
        message="任务已创建（未自动启动）",
    )


# ================================================================ 智能故障诊断


@router.post("/fault/diagnose", response_model=ApiResponse[dict], summary="智能故障诊断")
async def fault_diagnose(payload: FaultDiagnoseRequest, db: DbSession, user: CurrentUser):
    """智能故障诊断 Agent：RAG 知识库 + 设备手册 + 历史工单做根因分析（PDF 3.11）。"""
    target: dict = {
        "fault_type": payload.fault_type,
        "description": payload.description,
        "fault_level": payload.fault_level,
        "pile_asset_code": payload.pile_asset_code,
        "station_id": payload.station_id,
    }

    if payload.fault_id:
        fault = await db.get(FaultReport, payload.fault_id)
        if fault is None:
            raise NotFoundError("故障记录不存在")
        target.update(
            {
                "fault_no": fault.fault_no,
                "fault_type": fault.fault_type,
                "description": fault.description,
                "fault_level": fault.fault_level,
                "pile_asset_code": fault.pile_asset_code,
                "station_name": fault.station_name,
            }
        )
    elif not payload.description and not payload.fault_type:
        raise BizError("请提供 fault_id，或至少填写 fault_type / description")

    query = f"{target.get('fault_type') or ''} {target.get('description') or ''} 根因 处置"
    context, refs = await build_context(db, query, top_k=4, user=user)

    base = rule_based_root_cause(
        target.get("fault_type"), target.get("description"), target.get("fault_level")
    )
    diagnosis = {**target, **base, "references": refs, "rag_hit": bool(refs)}

    llm_used = False
    llm_error = None
    if llm_client.available:
        prompt = (
            f"故障类型：{target.get('fault_type') or '未知'}\n"
            f"故障现象：{target.get('description') or '未描述'}\n"
            f"系统判定等级：{target.get('fault_level') or '未知'}\n"
            f"资产编码：{target.get('pile_asset_code') or '-'}\n"
            f"站点：{target.get('station_name') or '-'}\n\n"
            f"【知识库参考】\n{context or '（无匹配知识条目）'}\n\n"
            "请输出：1) 最可能根因（按可能性排序，最多 3 条，标注可信度）；"
            "2) 现场检查步骤；3) 处置措施与是否需要停机；4) 预防建议。"
            "使用简体中文分点作答。若知识库无相关信息，请说明依据通用经验推断。"
        )
        result = await llm_client.chat(
            "你是充电桩与储能电站运维专家。系统已按硬约束规则给出故障等级与 SLA，"
            "你的职责是做根因分析与处置建议，不得修改系统判定的等级。",
            prompt,
            max_tokens=1200,
        )
        llm_used = result.used_llm
        llm_error = result.error
        diagnosis["llm_analysis"] = result.text

    if payload.fault_id:
        fault = await db.get(FaultReport, payload.fault_id)
        if fault:
            fault.ai_diagnosis = to_json_safe(diagnosis)
            fault.ai_level_suggestion = base.get("matched_category")
            await db.commit()

    await log_operation(
        db,
        module="AI Agent 中心",
        action="智能故障诊断",
        user=user,
        target_type="fault",
        target_id=payload.fault_id,
        description=f"故障诊断（{'LLM 增强' if llm_used else '规则引擎降级'}）",
        after={"category": base.get("matched_category"), "confidence": base.get("confidence")},
    )

    return ApiResponse.ok(
        {
            "diagnosis": to_json_safe(diagnosis),
            "llm_used": llm_used,
            "llm_error": llm_error,
            "degraded": not llm_used,
        }
    )


# ================================================================ 智能巡检报告


@router.post("/inspection/report", response_model=ApiResponse[dict], summary="智能巡检报告")
async def inspection_report(payload: InspectionReportRequest, db: DbSession, user: CurrentUser):
    """智能巡检报告 Agent：根据巡检记录、图片、异常项生成报告（PDF 3.11）。"""
    stmt = select(InspectionRecord).order_by(InspectionRecord.created_at.desc())
    if payload.work_order_id:
        stmt = stmt.where(InspectionRecord.work_order_id == payload.work_order_id)
    if payload.inspection_ids:
        stmt = stmt.where(InspectionRecord.id.in_(payload.inspection_ids))
    if payload.subtask_ids:
        stmt = stmt.where(InspectionRecord.subtask_id.in_(payload.subtask_ids))
    if not (payload.work_order_id or payload.inspection_ids or payload.subtask_ids):
        stmt = stmt.limit(30)

    records = (await db.execute(stmt.limit(200))).scalars().all()
    if not records:
        raise BizError("未找到巡检记录，无法生成巡检报告")

    total = len(records)
    abnormal_records = [r for r in records if (r.abnormal_count or 0) > 0]
    total_items = sum((r.normal_count or 0) + (r.abnormal_count or 0) for r in records)
    total_abnormal = sum(r.abnormal_count or 0 for r in records)

    abnormal_items: list[dict] = []
    for record in abnormal_records:
        content = record.content or {}
        for item in content.get("items") or []:
            if isinstance(item, dict) and item.get("result") == "异常":
                abnormal_items.append(
                    {
                        "station_name": record.station_name,
                        "inspector_name": record.inspector_name,
                        "item_name": item.get("item_name"),
                        "item_group": item.get("item_group"),
                        "remark": item.get("remark"),
                        "inspection_id": record.id,
                    }
                )

    metrics = {
        "巡检记录数": total,
        "巡检项总数": total_items,
        "异常项总数": total_abnormal,
        "异常记录数": len(abnormal_records),
        "正常率(%)": safe_rate(total_items - total_abnormal, total_items),
        "拍照记录数": sum(1 for r in records if r.images),
        "缺图记录数": sum(1 for r in records if not r.images),
    }

    markdown = [
        "# 巡检报告",
        "",
        f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 关联工单：{payload.work_order_id or '（未指定）'}",
        f"- 巡检记录：{total} 条",
        "",
        "## 一、巡检概况",
        "",
        f"- 累计巡检项 {total_items} 项，其中异常 {total_abnormal} 项，正常率 {metrics['正常率(%)']}%",
        f"- 异常记录 {len(abnormal_records)} 条",
        f"- 现场照片：{metrics['拍照记录数']} 条记录已上传，{metrics['缺图记录数']} 条记录缺图",
        "",
        "## 二、异常项明细",
        "",
    ]
    if abnormal_items:
        markdown.append("| 站点 | 巡检项 | 分类 | 异常描述 | 巡检人 |")
        markdown.append("| --- | --- | --- | --- | --- |")
        for item in abnormal_items[:50]:
            markdown.append(
                f"| {item['station_name'] or '-'} | {item['item_name'] or '-'} | "
                f"{item['item_group'] or '-'} | {item['remark'] or '无备注'} | "
                f"{item['inspector_name'] or '-'} |"
            )
    else:
        markdown.append("本次巡检未发现异常项。")

    llm_used = False
    llm_error = None
    if payload.use_llm and llm_client.available:
        prompt = (
            f"【巡检统计】\n{to_json_safe(metrics)}\n\n"
            f"【异常明细】\n{to_json_safe(abnormal_items[:40])}\n\n"
            "请生成巡检报告的文字分析，包含：整体结论、异常项风险分级、"
            "需要转消缺工单的项、后续巡检关注重点。使用简体中文 Markdown。"
        )
        result = await llm_client.chat(
            "你是充电桩运维巡检分析专家，基于巡检记录输出结论与建议，不得编造未记录的巡检项。",
            prompt,
            max_tokens=1200,
        )
        llm_used = result.used_llm
        llm_error = result.error
        if result.used_llm:
            markdown += ["", "## 三、智能分析", "", result.text]

    report_md = "\n".join(markdown)
    await log_operation(
        db,
        module="AI Agent 中心",
        action="智能巡检报告",
        user=user,
        target_type="work_order",
        target_id=payload.work_order_id,
        description=f"生成巡检报告：{total} 条记录，{total_abnormal} 个异常项",
    )
    return ApiResponse.ok(
        {
            "metrics": metrics,
            "abnormal_items": abnormal_items[:100],
            "markdown": report_md,
            "llm_used": llm_used,
            "llm_error": llm_error,
            "degraded": not llm_used,
        }
    )


# ================================================================ 智能运维建议


@router.post("/maintenance/suggest", response_model=ApiResponse[dict], summary="智能运维建议")
async def maintenance_suggest(
    payload: MaintenanceSuggestRequest, db: DbSession, user: CurrentUser
):
    """智能运维建议 Agent：基于诊断结果和历史 SOP 生成可操作建议（PDF 3.11）。"""
    fault_type = payload.fault_type
    description = payload.diagnosis
    fault_level = None

    if payload.fault_id:
        fault = await db.get(FaultReport, payload.fault_id)
        if fault is None:
            raise NotFoundError("故障记录不存在")
        fault_type = fault_type or fault.fault_type
        description = description or fault.description
        fault_level = fault.fault_level

    if not (fault_type or description):
        raise BizError("请提供 fault_id 或 fault_type / diagnosis")

    base = rule_based_root_cause(fault_type, description, fault_level)
    query = f"{fault_type or ''} 处置 SOP 运维建议 {description or ''}"
    context, refs = await build_context(db, query, top_k=4, user=user)

    suggestions = [
        {
            "title": f"现场检查：{check}",
            "priority": "高" if i < 2 else "中",
            "owner": "运维工程师",
            "deadline_hours": base["sla_hours"] if i < 2 else base["sla_hours"] * 2,
        }
        for i, check in enumerate(base["checks"][:4])
    ]
    suggestions += [
        {
            "title": f"处置措施：{action}",
            "priority": "高" if i == 0 else "中",
            "owner": "运维工程师",
            "deadline_hours": base["sla_hours"],
        }
        for i, action in enumerate(base["actions"][:3])
    ]

    llm_text = None
    llm_used = False
    llm_error = None
    if payload.use_llm and llm_client.available:
        prompt = (
            f"故障类型：{fault_type or '未知'}\n故障现象：{description or '未描述'}\n"
            f"系统判定等级：{fault_level or '未判定'}\n"
            f"规则引擎初判类别：{base['matched_category']}（可能性 {base['confidence']}）\n\n"
            f"【知识库参考】\n{context or '（无匹配知识条目）'}\n\n"
            "请给出可执行的运维建议，每条包含：措施内容、责任角色、建议时限、"
            "所需备件或工具、风险提示。使用简体中文，按优先级排序。"
        )
        result = await llm_client.chat(
            "你是充电桩运维技术专家，输出可执行、可验收的运维建议，不夸大也不编造备件型号。",
            prompt,
            max_tokens=1200,
        )
        llm_used = result.used_llm
        llm_error = result.error
        llm_text = result.text

    return ApiResponse.ok(
        {
            "category": base["matched_category"],
            "confidence": base["confidence"],
            "sla_hours": base["sla_hours"],
            "suggestions": suggestions,
            "llm_suggestions": llm_text,
            "references": refs,
            "llm_used": llm_used,
            "llm_error": llm_error,
            "degraded": not llm_used,
        }
    )


# ================================================================ 智能风控


@router.post("/risk/check", response_model=ApiResponse[dict], summary="智能风控检查")
async def risk_check(payload: RiskCheckRequest, db: DbSession, user: CurrentUser):
    """智能风控 Agent：识别异常工单、异常故障、异常巡检、异常核销（PDF 3.11）。"""
    since = datetime.now() - timedelta(days=payload.days)
    findings: list[dict] = []

    if payload.scope in ("work_order", "whole"):
        stmt = select(WorkOrder).where(WorkOrder.created_at >= since)
        if payload.target_id:
            stmt = stmt.where(WorkOrder.id == payload.target_id)
        orders = (await db.execute(stmt.limit(2000))).scalars().all()

        for order in orders:
            # 逾期未处理
            if (
                order.time_status == TimeStatus.OVERDUE.value
                and order.status
                not in ("已完成", "已取消")
            ):
                findings.append(
                    {
                        "risk_type": "异常工单",
                        "level": "高",
                        "target_type": "work_order",
                        "target_id": order.id,
                        "title": f"工单逾期未处理：{order.order_no}",
                        "detail": f"计划结束 {order.inspect_end_date}，当前状态「{order.status}」",
                        "suggestion": "重新排期或调整执行人，必要时上报项目管理员",
                    }
                )
            # 无执行人
            if not order.inspector_id and order.status in ("待接单", "待完成"):
                findings.append(
                    {
                        "risk_type": "异常工单",
                        "level": "中",
                        "target_type": "work_order",
                        "target_id": order.id,
                        "title": f"工单未指派执行人：{order.order_no}",
                        "detail": "工单处于待接单/待完成但无巡检人员",
                        "suggestion": "补充指派执行人或重新下发",
                    }
                )
            # 子任务数量与公式不符（数据一致性风控）
            station_count = len(
                order.station_ids or ([order.station_id] if order.station_id else [])
            )
            from app.services.work_order import calc_subtask_count

            expected = calc_subtask_count(
                order.order_type,
                station_count,
                order.inspect_cycle,
                order.inspect_frequency,
                order.inspect_count,
            )
            if order.subtask_total != expected:
                findings.append(
                    {
                        "risk_type": "数据一致性",
                        "level": "中",
                        "target_type": "work_order",
                        "target_id": order.id,
                        "title": f"子任务数量与公式不符：{order.order_no}",
                        "detail": f"记录 {order.subtask_total}，按公式应为 {expected}",
                        "suggestion": "重算子任务或修正工单参数",
                    }
                )

    if payload.scope in ("fault", "whole"):
        stmt = select(FaultReport).where(FaultReport.created_at >= since)
        if payload.target_id:
            stmt = stmt.where(FaultReport.id == payload.target_id)
        faults = (await db.execute(stmt.limit(2000))).scalars().all()

        from app.services.fault import LEVEL_SLA_HOURS

        for fault in faults:
            if fault.status == FaultStatus.PENDING_VERIFY.value:
                sla = LEVEL_SLA_HOURS.get(fault.fault_level, 72)
                deadline = (fault.reported_at or fault.created_at) + timedelta(hours=sla)
                if deadline < datetime.now():
                    findings.append(
                        {
                            "risk_type": "异常故障",
                            "level": "高" if fault.fault_level == "危急" else "中",
                            "target_type": "fault",
                            "target_id": fault.id,
                            "title": f"故障核查超期：{fault.fault_no}",
                            "detail": f"等级 {fault.fault_level}，SLA {sla} 小时已超期",
                            "suggestion": "立即安排现场核查并升级处理",
                        }
                    )
            if fault.is_draft and (datetime.now() - fault.created_at).days >= 3:
                findings.append(
                    {
                        "risk_type": "异常故障",
                        "level": "低",
                        "target_type": "fault",
                        "target_id": fault.id,
                        "title": f"故障草稿长期未提交：{fault.fault_no}",
                        "detail": f"草稿创建于 {fault.created_at:%Y-%m-%d}，超过 3 天未上报",
                        "suggestion": "提醒上报人或清理无效草稿",
                    }
                )

    if payload.scope in ("inspection", "whole"):
        stmt = select(InspectionRecord).where(InspectionRecord.created_at >= since)
        if payload.target_id:
            stmt = stmt.where(InspectionRecord.id == payload.target_id)
        records = (await db.execute(stmt.limit(2000))).scalars().all()

        for record in records:
            if not record.images:
                findings.append(
                    {
                        "risk_type": "异常巡检",
                        "level": "中",
                        "target_type": "inspection",
                        "target_id": record.id,
                        "title": f"巡检记录缺现场照片：{record.station_name or '-'}",
                        "detail": f"巡检人 {record.inspector_name or '-'}，时间 {record.created_at:%Y-%m-%d %H:%M}",
                        "suggestion": "要求补传照片，否则巡检记录不予核销",
                    }
                )
            if not record.checkin_location or not record.checkout_location:
                findings.append(
                    {
                        "risk_type": "异常巡检",
                        "level": "中",
                        "target_type": "inspection",
                        "target_id": record.id,
                        "title": f"巡检定位缺失：{record.station_name or '-'}",
                        "detail": "缺少签到或签退定位信息",
                        "suggestion": "核查是否存在代巡检，必要时重新巡检",
                    }
                )
            if record.normal_count and record.normal_count >= 20 and not record.images:
                findings.append(
                    {
                        "risk_type": "异常巡检",
                        "level": "高",
                        "target_type": "inspection",
                        "target_id": record.id,
                        "title": f"疑似批量勾选正常但无影像：{record.station_name or '-'}",
                        "detail": f"一次性勾选正常 {record.normal_count} 项且无照片",
                        "suggestion": "人工复核该巡检记录",
                    }
                )

    level_rank = {"高": 3, "中": 2, "低": 1}
    findings.sort(key=lambda f: level_rank.get(f["level"], 0), reverse=True)
    summary = {
        "高": sum(1 for f in findings if f["level"] == "高"),
        "中": sum(1 for f in findings if f["level"] == "中"),
        "低": sum(1 for f in findings if f["level"] == "低"),
    }

    await log_operation(
        db,
        module="AI Agent 中心",
        action="智能风控检查",
        user=user,
        description=f"风控检查范围 {payload.scope}，命中 {len(findings)} 条风险",
        after=summary,
    )
    return ApiResponse.ok(
        {
            "scope": payload.scope,
            "days": payload.days,
            "total": len(findings),
            "summary": summary,
            "findings": findings[:200],
        }
    )


# ================================================================ 智能数据分析


@router.post("/data-analysis", response_model=ApiResponse[dict], summary="智能数据分析")
async def data_analysis(db: DbSession, user: CurrentUser, payload: dict | None = None):
    """智能数据分析 Agent：把分析引擎结果转化为自然语言摘要（PDF 3.11）。"""
    from app.ai.nodes import gather_report_metrics
    from app.ai.state import initial_state
    from app.services.statistics import dashboard_overview

    payload = payload or {}
    project_id = payload.get("project_id")
    period = payload.get("period") or "month"

    metrics = await gather_report_metrics(initial_state(project_id=project_id or ""))
    dashboard = await dashboard_overview(db, period=period, project_id=project_id)

    llm_text = None
    llm_used = False
    if payload.get("use_llm", True) and llm_client.available:
        result = await llm_client.chat(
            "你是运维数据分析师，把统计指标转述为管理者能快速理解的自然语言摘要。"
            "不得编造指标外数据。",
            f"【核心指标】\n{to_json_safe(metrics)}\n\n"
            f"【看板数据】\n{to_json_safe({k: v for k, v in dashboard.items() if k != 'trend'})}\n\n"
            "请输出 200 字以内的运营摘要，突出异常与改进方向。",
            max_tokens=600,
        )
        llm_used = result.used_llm
        llm_text = result.text

    if not llm_text:
        llm_text = (
            f"统计周期 {dashboard['period']['start']} ~ {dashboard['period']['end']}："
            f"工单 {dashboard['work_order']['total']} 个，完成率 "
            f"{dashboard['work_order']['completion_rate']}%，逾期率 "
            f"{dashboard['work_order']['overdue_rate']}%；故障 {dashboard['fault']['total']} 个，"
            f"核查率 {dashboard['fault']['verify_rate']}%；巡检异常率 "
            f"{dashboard['inspection']['abnormal_rate']}%。"
        )

    return ApiResponse.ok(
        {
            "metrics": to_json_safe(metrics),
            "dashboard": to_json_safe(dashboard),
            "summary": llm_text,
            "llm_used": llm_used,
        }
    )


# ================================================================ 智能报告


@router.post("/report/generate", response_model=ApiResponse[dict], summary="智能报告生成")
async def report_generate(
    payload: ReportGenerateRequest, db: DbSession, user: CurrentUser, background: BackgroundTasks
):
    """运维分析建议报告 Agent：日/周/月/即时报告自动生成（PDF 3.12 / 4.6）。"""
    if payload.async_run:
        task = await agent_service.create_agent_task(
            db,
            agent_type=AgentType.REPORT.value,
            request_payload=to_json_safe(payload.model_dump()),
            user=user,
            task_name=f"{payload.report_type} 报告生成",
            project_id=payload.project_id,
        )

        async def _run() -> None:
            from app.core.database import AsyncSessionLocal

            async with AsyncSessionLocal() as bg_db:
                task_row = await bg_db.get(AIAgentTask, task.id)
                if task_row is None:
                    return
                try:
                    report = await generate_report(
                        bg_db,
                        report_type=payload.report_type,
                        project_id=payload.project_id,
                        station_id=payload.station_id,
                        period_start=payload.period_start,
                        period_end=payload.period_end,
                        use_llm=payload.use_llm,
                        user=user,
                    )
                    task_row.status = AgentTaskStatus.COMPLETED.value
                    task_row.progress = 100
                    task_row.result = {
                        "report_id": report.id,
                        "report_no": report.report_no,
                        "title": report.title,
                        "llm_used": report.llm_used,
                        "degraded": report.degraded,
                    }
                    task_row.finished_at = datetime.now()
                except Exception as exc:  # pragma: no cover
                    task_row.status = AgentTaskStatus.FAILED.value
                    task_row.error = f"{type(exc).__name__}: {exc}"
                await bg_db.commit()

        background.add_task(_run)
        return ApiResponse.ok(
            {
                "task_id": task.id,
                "task_no": task.task_no,
                "status_url": f"/api/v1/ai/agent/tasks/{task.id}",
            },
            message="报告生成任务已提交，请轮询任务状态",
        )

    report = await generate_report(
        db,
        report_type=payload.report_type,
        project_id=payload.project_id,
        station_id=payload.station_id,
        period_start=payload.period_start,
        period_end=payload.period_end,
        use_llm=payload.use_llm,
        user=user,
    )

    if payload.push_channels:
        target_ids = [r[0] for r in (await db.execute(select(User.id))).all()]
        await push_report(
            db, report=report, user_ids=target_ids, channels=payload.push_channels
        )

    await log_operation(
        db,
        module="AI Agent 中心",
        action="智能报告生成",
        user=user,
        target_type="report",
        target_id=report.id,
        description=(
            f"生成{payload.report_type}报告 {report.report_no}"
            f"（{'LLM 增强' if report.llm_used else '规则引擎降级'}）"
        ),
    )
    return ApiResponse.ok(
        {
            "report_id": report.id,
            "report_no": report.report_no,
            "title": report.title,
            "report_type": report.report_type,
            "period": {
                "start": report.period_start.isoformat() if report.period_start else None,
                "end": report.period_end.isoformat() if report.period_end else None,
            },
            "llm_used": report.llm_used,
            "degraded": report.degraded,
            "markdown": report.markdown,
            "suggestions": report.suggestions,
            "metrics": (report.content or {}).get("metrics"),
            "file_url": report.file_url,
            "md_url": report.md_url,
            "html_url": report.html_url,
        }
    )


@router.get("/report/list", response_model=ApiResponse[PageData[dict]], summary="报告列表")
async def report_list(
    db: DbSession,
    user: CurrentUser,
    report_type: str | None = None,
    project_id: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
):
    rows, total = await list_reports(
        db,
        report_type=report_type,
        project_id=project_id,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    items = [
        {
            "id": r.id,
            "report_no": r.report_no,
            "report_type": r.report_type,
            "title": r.title,
            "period_start": r.period_start,
            "period_end": r.period_end,
            "summary": r.summary,
            "suggestions": r.suggestions,
            "llm_used": r.llm_used,
            "degraded": r.degraded,
            "status": r.status,
            "file_url": r.file_url,
            "md_url": r.md_url,
            "html_url": r.html_url,
            "created_at": r.created_at,
        }
        for r in rows
    ]
    return ApiResponse.ok(PageData.build(items, total, page, page_size))


@router.get("/report/{report_id}", response_model=ApiResponse[dict], summary="报告详情")
async def report_detail(report_id: str, db: DbSession, user: CurrentUser):
    report = await get_report(db, report_id)
    return ApiResponse.ok(
        {
            "id": report.id,
            "report_no": report.report_no,
            "report_type": report.report_type,
            "title": report.title,
            "period_start": report.period_start,
            "period_end": report.period_end,
            "content": report.content,
            "markdown": report.markdown,
            "summary": report.summary,
            "suggestions": report.suggestions,
            "llm_used": report.llm_used,
            "degraded": report.degraded,
            "pushed_channels": report.pushed_channels,
            "file_url": report.file_url,
            "md_url": report.md_url,
            "html_url": report.html_url,
            "created_at": report.created_at,
        }
    )


@router.post("/report/{report_id}/follow-up", response_model=ApiResponse[dict], summary="报告追问下钻")
async def report_follow_up(
    report_id: str, payload: AssistantAskRequest, db: DbSession, user: CurrentUser
):
    follow = await follow_up(
        db,
        report_id=report_id,
        question=payload.question,
        use_llm=payload.use_llm,
        user=user,
    )
    return ApiResponse.ok(
        {
            "id": follow.id,
            "report_id": follow.report_id,
            "question": follow.question,
            "answer": follow.answer,
            "refs": follow.refs,
            "llm_used": follow.llm_used,
            "created_at": follow.created_at,
        }
    )


@router.get("/report/compare/{report_type}", response_model=ApiResponse[dict], summary="报告历史对比")
async def report_compare(
    report_type: str,
    db: DbSession,
    user: CurrentUser,
    limit: int = Query(default=6, ge=2, le=24),
):
    return ApiResponse.ok(await compare_reports(db, report_type=report_type, limit=limit))


@router.post("/report/{report_id}/push", response_model=ApiResponse[dict], summary="报告推送")
async def report_push(
    report_id: str,
    db: DbSession,
    user: CurrentUser,
    payload: dict | None = None,
):
    """报告推送（PDF 3.12）：飞书 / 邮件 / 站内信（PDF 7.3）。"""
    payload = payload or {}
    report = await get_report(db, report_id)
    channels = payload.get("channels") or ["站内信"]
    user_ids = payload.get("user_ids")
    if not user_ids:
        user_ids = [
            r[0]
            for r in (
                await db.execute(select(User.id).where(User.status.is_(True)))
            ).all()
        ]
    result = await push_report(db, report=report, user_ids=user_ids, channels=channels)
    await log_operation(
        db,
        module="AI Agent 中心",
        action="报告推送",
        user=user,
        target_type="report",
        target_id=report_id,
        description=f"推送报告到 {result['pushed']} 人，通道 {'/'.join(channels)}",
    )
    return ApiResponse.ok(result)


# ================================================================ 学习助手追问


@router.post("/assistant/ask", response_model=ApiResponse[dict], summary="学习助手追问")
async def assistant_ask(payload: AssistantAskRequest, db: DbSession, user: CurrentUser):
    """学习助手追问（PDF 5.3）：RAG 知识库问答 + 业务数据下钻。"""
    context, refs = await build_context(db, payload.question, top_k=5, user=user)

    biz_context: dict = {}
    if payload.work_order_id:
        order = await db.get(WorkOrder, payload.work_order_id)
        if order:
            subtasks = (
                await db.execute(
                    select(WorkOrderSubtask).where(
                        WorkOrderSubtask.work_order_id == order.id
                    )
                )
            ).scalars().all()
            biz_context["work_order"] = {
                "order_no": order.order_no,
                "order_name": order.order_name,
                "order_type": order.order_type,
                "status": order.status,
                "time_status": order.time_status,
                "inspect_range": f"{order.inspect_start_date} ~ {order.inspect_end_date}",
                "subtask_total": order.subtask_total,
                "subtask_done": order.subtask_done,
                "subtask_status": {
                    s: sum(1 for x in subtasks if x.status == s)
                    for s in {x.status for x in subtasks}
                },
            }
    if payload.fault_id:
        fault = await db.get(FaultReport, payload.fault_id)
        if fault:
            biz_context["fault"] = {
                "fault_no": fault.fault_no,
                "fault_type": fault.fault_type,
                "fault_level": fault.fault_level,
                "status": fault.status,
                "description": fault.description,
                "ai_diagnosis": fault.ai_diagnosis,
            }

    if not llm_client.available:
        answer = (
            "当前未配置 LLM_API_KEY，无法进行自然语言问答。\n\n"
            + (
                "以下为知识库检索到的相关条目：\n"
                + "\n".join(f"- 《{r['title']}》（{r['category']}，相关度 {r['score']}）" for r in refs)
                if refs
                else "知识库中未检索到相关条目，可先在「知识库」中导入设备手册或 SOP 文档。"
            )
        )
    else:
        prompt = (
            f"【用户问题】{payload.question}\n\n"
            f"【业务数据】\n{to_json_safe(biz_context) if biz_context else '（未关联具体单据）'}\n\n"
            f"【知识库检索结果】\n{context or '（无匹配知识条目）'}\n\n"
            "请回答用户问题。优先使用知识库与业务数据中的事实；"
            "数据不足时明确说明，不编造。使用简体中文。"
        )
        result = await llm_client.chat(
            "你是充电桩运维平台的知识助手，基于平台知识库与实时业务数据回答问题。",
            prompt,
            max_tokens=1200,
        )
        answer = result.text or (
            "LLM 调用未成功，以下为知识库检索结果：\n"
            + "\n".join(f"- 《{r['title']}》" for r in refs)
        )

    return ApiResponse.ok(
        {
            "question": payload.question,
            "answer": answer,
            "references": refs,
            "business_context": to_json_safe(biz_context),
            "llm_used": llm_client.available and payload.use_llm,
        }
    )


# ================================================================ Agent 任务管理


@router.get("/agent/tasks", response_model=ApiResponse[PageData[AgentTaskOut]], summary="Agent 任务列表")
async def agent_tasks(
    db: DbSession,
    user: CurrentUser,
    agent_type: str | None = None,
    status: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
):
    rows, total = await agent_service.list_tasks(
        db,
        agent_type=agent_type,
        status=status,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    return ApiResponse.ok(
        PageData.build([AgentTaskOut.model_validate(r) for r in rows], total, page, page_size)
    )


@router.get("/agent/tasks/{task_id}", response_model=ApiResponse[dict], summary="查询 Agent 任务状态")
async def agent_task_state(task_id: str, db: DbSession, user: CurrentUser):
    return ApiResponse.ok(await agent_service.get_task_state(db, task_id))


@router.post("/agent/tasks/{task_id}/confirm", response_model=ApiResponse[dict], summary="人工确认")
async def agent_task_confirm(
    task_id: str, payload: AgentConfirmRequest, db: DbSession, user: CurrentUser
):
    """人工确认（PDF 4.8）：POST /api/v1/ai/agent/tasks/{task_id}/confirm。"""
    task = await agent_service.confirm_task(
        db,
        task_id=task_id,
        approved=payload.approved,
        plan_id=payload.plan_id,
        adjustments=payload.adjustments,
        comment=payload.comment,
        user=user,
    )
    await log_operation(
        db,
        module="AI Agent 中心",
        action="人工确认",
        user=user,
        target_type="agent_task",
        target_id=task_id,
        description=(
            f"{'通过' if payload.approved else '驳回'}方案 "
            f"{payload.plan_id or (task.selected_plan or {}).get('plan_id') or '-'}"
        ),
        after={"status": task.status, "approved": payload.approved},
    )
    return ApiResponse.ok(
        {
            "task_id": task.id,
            "status": task.status,
            "progress": task.progress,
            "selected_plan": task.selected_plan,
            "confirmation": task.confirmation,
            "dispatch_result": (task.result or {}).get("dispatch_result"),
            "message": (
                "已确认并完成下发" if task.status == AgentTaskStatus.DISPATCHED.value else "已恢复执行"
            ),
        }
    )


@router.post("/agent/tasks/{task_id}/replan", response_model=ApiResponse[dict], summary="异常重排")
async def agent_task_replan(
    task_id: str, payload: AgentReplanRequest, db: DbSession, user: CurrentUser
):
    """异常重排（PDF 4.9 / 5.3）：锁定已执行任务，局部优先修复。"""
    result = await agent_service.replan_task(
        db,
        task_id=task_id,
        exception_type=payload.exception_type,
        description=payload.description,
        target_id=payload.target_id,
        lock_executed=payload.lock_executed,
        strategy=payload.strategy,
        user=user,
    )
    await log_operation(
        db,
        module="AI Agent 中心",
        action="异常重排",
        user=user,
        target_type="agent_task",
        target_id=result["new_task_id"],
        description=f"基于任务 {task_id} 发起异常重排：{payload.exception_type}",
    )
    return ApiResponse.ok(result)


@router.get("/agent/center", response_model=ApiResponse[dict], summary="AI Agent 中心概览")
async def agent_center(db: DbSession, user: CurrentUser):
    """AI Agent 中心八类 Agent 概览（PDF 3.11）。"""
    return ApiResponse.ok(await agent_service.agent_center_overview(db))


# ================================================================ 异常事件


@router.get("/exceptions", response_model=ApiResponse[PageData[dict]], summary="异常事件列表")
async def exceptions(
    db: DbSession,
    user: CurrentUser,
    handled: bool | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
):
    stmt = select(AIExceptionEvent)
    count_stmt = select(func.count(AIExceptionEvent.id))
    if handled is not None:
        stmt = stmt.where(AIExceptionEvent.handled.is_(handled))
        count_stmt = count_stmt.where(AIExceptionEvent.handled.is_(handled))
    total = int((await db.execute(count_stmt)).scalar() or 0)
    rows = (
        await db.execute(
            stmt.order_by(AIExceptionEvent.created_at.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
    ).scalars().all()
    items = [
        {
            "id": r.id,
            "event_no": r.event_no,
            "event_type": r.event_type,
            "source": r.source,
            "severity": r.severity,
            "work_order_id": r.work_order_id,
            "subtask_id": r.subtask_id,
            "fault_id": r.fault_id,
            "description": r.description,
            "impact_analysis": r.impact_analysis,
            "handled": r.handled,
            "handled_at": r.handled_at,
            "handle_note": r.handle_note,
            "created_at": r.created_at,
        }
        for r in rows
    ]
    return ApiResponse.ok(PageData.build(items, total, page, page_size))


@router.post("/exceptions/scan", response_model=ApiResponse[dict], summary="扫描并登记异常事件")
async def scan_exceptions(db: DbSession, user: CurrentUser):
    """执行异常扫描（PDF 4.9 异常来源），把结果登记到 ai_exception_event。"""
    from app.ai.nodes import monitor_exception
    from app.ai.state import initial_state
    from app.core.utils import gen_no

    state = await monitor_exception(initial_state())
    events = state.get("exception_events") or []

    created = 0
    for event in events:
        exists = (
            await db.execute(
                select(func.count(AIExceptionEvent.id)).where(
                    AIExceptionEvent.event_type == event.get("event_type"),
                    AIExceptionEvent.handled.is_(False),
                    AIExceptionEvent.work_order_id == event.get("work_order_id"),
                    AIExceptionEvent.subtask_id == event.get("subtask_id"),
                )
            )
        ).scalar()
        if exists:
            continue
        db.add(
            AIExceptionEvent(
                event_no=gen_no("EX"),
                event_type=event.get("event_type") or "未知异常",
                source=event.get("source") or "system",
                severity=event.get("severity") or "中",
                work_order_id=event.get("work_order_id"),
                subtask_id=event.get("subtask_id"),
                fault_id=event.get("fault_id"),
                description=event.get("description"),
                payload=to_json_safe(event),
            )
        )
        created += 1
    await db.commit()

    # 同步刷新工单时间状态
    from app.services.work_order import push_due_soon_messages

    reminder = await push_due_soon_messages(db)

    return ApiResponse.ok(
        {
            "scanned": len(events),
            "created": created,
            "reminders": reminder,
            "events": events[:50],
        }
    )


# ================================================================ 知识库


@router.get("/knowledge", response_model=ApiResponse[PageData[dict]], summary="知识库列表")
async def knowledge_list(
    db: DbSession,
    user: CurrentUser,
    category: str | None = None,
    keyword: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
):
    stmt = select(AIKnowledgeBase)
    count_stmt = select(func.count(AIKnowledgeBase.id))
    conditions = []
    if category:
        conditions.append(AIKnowledgeBase.category == category)
    if keyword:
        conditions.append(AIKnowledgeBase.title.ilike(f"%{keyword}%"))
    for cond in conditions:
        stmt = stmt.where(cond)
        count_stmt = count_stmt.where(cond)

    total = int((await db.execute(count_stmt)).scalar() or 0)
    rows = (
        await db.execute(
            stmt.order_by(AIKnowledgeBase.created_at.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
    ).scalars().all()
    items = [
        {
            "id": r.id,
            "title": r.title,
            "category": r.category,
            "source_type": r.source_type,
            "summary": r.summary,
            "tags": r.tags,
            "chunk_index": r.chunk_index,
            "embedding_status": r.embedding_status,
            "enabled": r.enabled,
            "created_at": r.created_at,
        }
        for r in rows
    ]
    return ApiResponse.ok(PageData.build(items, total, page, page_size))


@router.post("/knowledge", response_model=ApiResponse[dict], summary="新增知识库文档")
async def knowledge_create(payload: KnowledgeDocCreate, db: DbSession, user: CurrentUser):
    docs = await upsert_document(
        db,
        title=payload.title,
        category=payload.category,
        content=payload.content,
        tags=payload.tags,
        project_id=payload.project_id,
        role_codes=payload.role_codes,
        source_type=payload.source_type,
        created_by=user.id,
    )
    await log_operation(
        db,
        module="AI Agent 中心",
        action="新增知识库文档",
        user=user,
        target_type="knowledge",
        target_id=docs[0].id if docs else None,
        description=f"新增知识文档《{payload.title}》，切分为 {len(docs)} 个片段",
    )
    return ApiResponse.ok(
        {"doc_count": len(docs), "root_id": docs[0].id if docs else None},
        message=f"已入库并切分为 {len(docs)} 个片段",
    )


@router.get("/knowledge/categories", response_model=ApiResponse[list[dict]], summary="知识库分类")
async def knowledge_categories(db: DbSession, user: CurrentUser):
    rows = (
        await db.execute(
            select(AIKnowledgeBase.category, func.count(AIKnowledgeBase.id)).group_by(
                AIKnowledgeBase.category
            )
        )
    ).all()
    return ApiResponse.ok(
        [{"category": c or "未分类", "count": int(n)} for c, n in rows]
    )


@router.post("/knowledge/ask", response_model=ApiResponse[dict], summary="知识库问答")
async def knowledge_ask(payload: KnowledgeAskRequest, db: DbSession, user: CurrentUser):
    chunks = await retrieve(
        db, payload.question, top_k=payload.top_k, category=payload.category, user=user
    )
    if not chunks:
        return ApiResponse.ok(
            {
                "answer": "知识库中未检索到相关内容，请先在「知识库」中导入设备手册、SOP 或故障案例。",
                "references": [],
                "llm_used": False,
            }
        )

    context = "\n\n".join(
        f"[{i}] 《{c.title}》（{c.category}）\n{c.content}" for i, c in enumerate(chunks, 1)
    )
    refs = [
        {"doc_id": c.doc_id, "title": c.title, "category": c.category, "score": c.score}
        for c in chunks
    ]

    if not llm_client.available:
        answer = "（未配置 LLM_API_KEY，以下为知识库原文摘录）\n\n" + "\n\n".join(
            f"《{c.title}》\n{c.content[:500]}" for c in chunks
        )
        return ApiResponse.ok(
            {"answer": answer, "references": refs, "llm_used": False}
        )

    result = await llm_client.chat(
        "你是充电桩运维知识库问答助手，只依据给定资料回答，资料不足时明确说明。",
        f"【资料】\n{context}\n\n【问题】{payload.question}\n\n请用简体中文作答，并标注引用的资料编号。",
        max_tokens=1000,
    )
    return ApiResponse.ok(
        {
            "answer": result.text or "LLM 未返回内容",
            "references": refs,
            "llm_used": result.used_llm,
            "llm_error": result.error,
        }
    )


# ================================================================ 反馈


@router.post("/feedback", response_model=ApiResponse[dict], summary="AI 结果反馈")
async def create_feedback(payload: FeedbackCreate, db: DbSession, user: CurrentUser):
    """AI 反馈（PDF 6.1 / 11 知识库更新反馈闭环）。"""
    feedback = AIFeedback(
        task_id=payload.task_id,
        report_id=payload.report_id,
        agent_type=payload.agent_type,
        rating=payload.rating,
        accurate=payload.accurate,
        comment=payload.comment,
        corrected_output=payload.corrected_output,
        user_id=user.id,
    )
    db.add(feedback)
    await db.commit()
    await db.refresh(feedback)
    return ApiResponse.ok({"id": feedback.id, "rating": feedback.rating})


@router.get("/feedback/stats", response_model=ApiResponse[dict], summary="AI 反馈统计")
async def feedback_stats(db: DbSession, user: CurrentUser):
    """AI Agent 评估（PDF 12 交付物：AI Agent 评估报告）。"""
    total = int((await db.execute(select(func.count(AIFeedback.id)))).scalar() or 0)
    avg = (await db.execute(select(func.avg(AIFeedback.rating)))).scalar()
    accurate = int(
        (
            await db.execute(
                select(func.count(AIFeedback.id)).where(AIFeedback.accurate.is_(True))
            )
        ).scalar()
        or 0
    )
    rows = (
        await db.execute(
            select(AIFeedback.agent_type, func.avg(AIFeedback.rating), func.count(AIFeedback.id))
            .group_by(AIFeedback.agent_type)
        )
    ).all()
    return ApiResponse.ok(
        {
            "total": total,
            "average_rating": round(float(avg), 2) if avg else None,
            "accuracy_rate": safe_rate(accurate, total),
            "by_agent": [
                {
                    "agent_type": t or "未分类",
                    "avg_rating": round(float(a), 2) if a else None,
                    "count": int(c),
                }
                for t, a, c in rows
            ],
        }
    )


# ================================================================ 定时任务


@router.get("/jobs", response_model=ApiResponse[list[dict]], summary="定时任务列表")
async def list_jobs(db: DbSession, user: CurrentUser):
    from app.models import AIScheduledJob

    rows = (
        await db.execute(select(AIScheduledJob).order_by(AIScheduledJob.run_hour))
    ).scalars().all()
    return ApiResponse.ok(
        [
            {
                "id": r.id,
                "job_code": r.job_code,
                "job_name": r.job_name,
                "job_type": r.job_type,
                "cron_expr": r.cron_expr,
                "run_hour": r.run_hour,
                "run_minute": r.run_minute,
                "weekday": r.weekday,
                "day_of_month": r.day_of_month,
                "enabled": r.enabled,
                "last_run_at": r.last_run_at,
                "last_status": r.last_status,
                "last_message": r.last_message,
            }
            for r in rows
        ]
    )


@router.post("/jobs/{job_code}/run", response_model=ApiResponse[dict], summary="手动触发定时任务")
async def run_job(job_code: str, db: DbSession, user: CurrentUser):
    """手动触发定时任务（PDF 3.2 定时任务 / 3.12 数据更新策略）。"""
    from app.models import AIScheduledJob

    job = (
        await db.execute(select(AIScheduledJob).where(AIScheduledJob.job_code == job_code))
    ).scalar_one_or_none()
    if job is None:
        raise NotFoundError("定时任务不存在")

    result: dict = {}
    try:
        if job_code == "daily_report":
            report = await generate_report(
                db, report_type="daily", use_llm=True, user=user
            )
            result = {"report_id": report.id, "report_no": report.report_no}
        elif job_code == "weekly_report":
            report = await generate_report(
                db, report_type="weekly", use_llm=True, user=user
            )
            result = {"report_id": report.id, "report_no": report.report_no}
        elif job_code == "monthly_report":
            report = await generate_report(
                db, report_type="monthly", use_llm=True, user=user
            )
            result = {"report_id": report.id, "report_no": report.report_no}
        elif job_code == "daily_statistics":
            from app.services.statistics import build_daily_statistics

            rows = await build_daily_statistics(db)
            result = {"generated": len(rows)}
        elif job_code == "due_soon_reminder":
            from app.services.work_order import push_due_soon_messages

            result = await push_due_soon_messages(db)
        elif job_code == "exception_scan":
            from app.ai.nodes import monitor_exception
            from app.ai.state import initial_state
            from app.core.utils import gen_no

            state = await monitor_exception(initial_state())
            for event in state.get("exception_events") or []:
                db.add(
                    AIExceptionEvent(
                        event_no=gen_no("EX"),
                        event_type=event.get("event_type") or "未知异常",
                        source=event.get("source") or "system",
                        severity=event.get("severity") or "中",
                        work_order_id=event.get("work_order_id"),
                        subtask_id=event.get("subtask_id"),
                        fault_id=event.get("fault_id"),
                        description=event.get("description"),
                        payload=to_json_safe(event),
                    )
                )
            await db.commit()
            result = {"events": len(state.get("exception_events") or [])}
        else:
            raise BizError(f"未实现的任务类型：{job_code}")

        job.last_run_at = datetime.now()
        job.last_status = "success"
        job.last_message = to_json_safe(result)
        await db.commit()
    except Exception as exc:
        job.last_run_at = datetime.now()
        job.last_status = "failed"
        job.last_message = f"{type(exc).__name__}: {exc}"
        await db.commit()
        raise

    await log_operation(
        db,
        module="AI Agent 中心",
        action="手动触发定时任务",
        user=user,
        target_type="job",
        target_id=job_code,
        description=f"触发定时任务 {job.job_name}",
        after=result,
    )
    return ApiResponse.ok({"job_code": job_code, "result": result})
