"""AI Agent 相关表（PDF 6.1 / 4.x / 3.11 / 3.12）。"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import AgentTaskStatus, ReportType
from app.models.mixins import BaseModel


class AIAgentTask(BaseModel):
    """AI Agent 任务表（PDF 6.1 / 5.3 查询 Agent 任务状态）。"""

    __tablename__ = "ai_agent_task"
    __table_args__ = (Index("ix_agent_task_type_status", "agent_type", "status"),)

    task_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    agent_type: Mapped[str] = mapped_column(String(32), index=True)
    task_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # LangGraph thread_id，用于 interrupt / resume（PDF 4.8）
    thread_id: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(
        String(32), default=AgentTaskStatus.CREATED.value, index=True
    )
    tenant_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    project_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    station_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    schedule_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    time_window: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # 输入 / 状态快照 / 输出
    request_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    state_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    candidate_plans: Mapped[list | None] = mapped_column(JSON, nullable=True)
    scored_plans: Mapped[list | None] = mapped_column(JSON, nullable=True)
    selected_plan: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    plan_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 人工确认（PDF 4.8）
    confirmation: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 规则版本（PDF 4.1 原则 5）
    rule_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    replan_count: Mapped[int] = mapped_column(Integer, default=0)
    # 执行进度（PDF 5.4 WebSocket 进度推送）
    current_node: Mapped[str | None] = mapped_column(String(64), nullable=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_used: Mapped[bool] = mapped_column(Boolean, default=False)
    degraded: Mapped[bool] = mapped_column(Boolean, default=False)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    traces: Mapped[list["AIAgentTrace"]] = relationship(
        back_populates="task", cascade="all, delete-orphan"
    )


class AIAgentTrace(BaseModel):
    """AI Agent 追踪表（PDF 6.1 / 8.4 AI 审计：Prompt、模型、输出、人工修正）。"""

    __tablename__ = "ai_agent_trace"

    task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ai_agent_task.id", ondelete="CASCADE"), index=True
    )
    node_name: Mapped[str] = mapped_column(String(64), index=True)
    step_index: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="success")
    input_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    task: Mapped[AIAgentTask] = relationship(back_populates="traces")


class AIPromptTemplate(BaseModel):
    """Prompt 模板表（PDF 6.1）。"""

    __tablename__ = "ai_prompt_template"

    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    agent_type: Mapped[str] = mapped_column(String(32), index=True)
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[str] = mapped_column(String(16), default="v1")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class AIKnowledgeBase(BaseModel):
    """知识库表（PDF 6.1 / 4.7 RAG：多格式解析、向量化、权限体系、分类建设）。"""

    __tablename__ = "ai_knowledge_base"

    title: Mapped[str] = mapped_column(String(255), index=True)
    category: Mapped[str] = mapped_column(String(64), index=True)  # 设备手册/SOP/故障案例/规程
    source_type: Mapped[str] = mapped_column(String(16), default="text")  # pdf/word/excel/txt
    source_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # 向量化状态与向量（local 模式存放 TF-IDF 词表 / 向量）
    embedding_status: Mapped[str] = mapped_column(String(16), default="pending")
    embedding: Mapped[list | None] = mapped_column(JSON, nullable=True)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    parent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # 权限体系（PDF 4.7 第 3 点）
    project_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    role_codes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    version: Mapped[str] = mapped_column(String(16), default="v1")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)


class AIReport(BaseModel):
    """AI 报告表（PDF 6.2 / 3.12）。"""

    __tablename__ = "ai_report"
    __table_args__ = (Index("ix_ai_report_type_period", "report_type", "period_start"),)

    report_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    report_type: Mapped[str] = mapped_column(
        String(32), default=ReportType.DAILY.value, index=True
    )
    title: Mapped[str] = mapped_column(String(255))
    project_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    station_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    period_start: Mapped[date | None] = mapped_column(Date, index=True, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, index=True, nullable=True)
    # PDF 3.12 报告内容模块
    content: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggestions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    file_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    md_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    html_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="generated")
    llm_used: Mapped[bool] = mapped_column(Boolean, default=False)
    degraded: Mapped[bool] = mapped_column(Boolean, default=False)
    generated_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    pushed_channels: Mapped[list | None] = mapped_column(JSON, nullable=True)
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class AIReportFollowUp(BaseModel):
    """报告追问下钻记录（PDF 3.12 交互能力：追问下钻、历史对比）。"""

    __tablename__ = "ai_report_follow_up"

    report_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("ai_report.id", ondelete="CASCADE"), index=True
    )
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    refs: Mapped[list | None] = mapped_column(JSON, nullable=True)
    llm_used: Mapped[bool] = mapped_column(Boolean, default=False)
    asker_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class AIExceptionEvent(BaseModel):
    """AI 异常事件表（PDF 6.1 / 4.9 异常重排机制）。"""

    __tablename__ = "ai_exception_event"

    event_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    # 工单逾期 / 人员缺勤 / 车辆故障 / 故障误报 / 故障等级变更 /
    # 巡检未完成 / 图片缺失 / 定位异常 / 报告生成失败 / LLM 调用异常 / 天气 / 交通
    source: Mapped[str] = mapped_column(String(32), default="system")
    severity: Mapped[str] = mapped_column(String(16), default="中")
    work_order_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    subtask_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    fault_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 影响分析结果（PDF 4.4 impact_analysis）
    impact_analysis: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    handled: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    handled_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    handled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    replan_task_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    handle_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class AIFeedback(BaseModel):
    """AI 反馈表（PDF 6.1 / 11 知识库更新反馈闭环）。"""

    __tablename__ = "ai_feedback"

    task_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    report_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    agent_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    rating: Mapped[int] = mapped_column(Integer, default=5)
    accurate: Mapped[bool] = mapped_column(Boolean, default=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    corrected_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class AIScheduledJob(BaseModel):
    """定时任务（PDF 3.2 定时任务 + 3.12 数据更新策略）。"""

    __tablename__ = "ai_scheduled_job"

    job_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    job_name: Mapped[str] = mapped_column(String(128))
    job_type: Mapped[str] = mapped_column(String(32), default="report")  # report/reminder/stat
    cron_expr: Mapped[str | None] = mapped_column(String(64), nullable=True)
    run_hour: Mapped[int] = mapped_column(Integer, default=2)
    run_minute: Mapped[int] = mapped_column(Integer, default=0)
    weekday: Mapped[int | None] = mapped_column(Integer, nullable=True)
    day_of_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)
