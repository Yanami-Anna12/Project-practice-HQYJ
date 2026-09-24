"""调度业务模型：门店货量需求、调度任务、方案、确认、下发、异常、重排、报告。

对应需求文档 四「智能调度 Agent 详细设计」与 六「表设计」。

★ 货量需求是调度的**输入**。需求文档里它由「订单/货量接口」从 OMS 推送，
  本项目按确认的方案做成系统内手工维护（md_store_demand），
  将来接 OMS 时只需把写入路径换成接口导入，调度侧读取逻辑不用改。
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, now_default


class StoreDemand(Base):
    """门店当日货量需求（调度的输入）。"""

    __tablename__ = "md_store_demand"
    __table_args__ = (
        UniqueConstraint("schedule_date", "store_id", name="uq_demand_date_store"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    schedule_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    store_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    # 货量。用 Numeric 而不是 Float：货量是要参与「是否达到最低装载量」判断的量，
    # 浮点误差会让 630 变成 629.9999 而误判为不达标。
    quantity: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    remark: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=now_default()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=now_default(), onupdate=datetime.now
    )


class SchedulingTask(Base):
    """调度任务。状态流转：created → running → pending_confirm → dispatched → completed。"""

    __tablename__ = "scheduling_task"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    schedule_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    # 时段：AM / PM / FULL（全天，上午+下午都排）
    time_window: Mapped[str] = mapped_column(String(8), nullable=False, default="FULL")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="created", index=True)
    # 规则版本快照：每次调度记录当时的规则版本，保证可追溯
    rule_version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1.0.0")
    # 求解统计
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    solver_note: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    replan_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=now_default()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=now_default(), onupdate=datetime.now
    )


class SchedulingPlan(Base):
    """方案主表。一次调度产出 A/B/C/D 多套方案。"""

    __tablename__ = "scheduling_plan"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    # 方案编号：A 四米二优先 / B 成本最低 / C 大包小包保障优先 / D 装载率均衡
    plan_code: Mapped[str] = mapped_column(String(8), nullable=False)
    strategy: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    # 评分明细（用于多方案比选）
    four_two_usage: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False, default=0)
    avg_load_rate: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False, default=0)
    trip_achievement: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False, default=0)
    total_load: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    vehicle_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trip_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_cost: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    soft_violation: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False, default=0)
    score: Mapped[float] = mapped_column(Numeric(8, 2), nullable=False, default=0)
    # 未覆盖的门店（货量无法安排），用逗号分隔的门店编码
    uncovered_stores: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    # LLM 生成的方案解释（未配置 API Key 时为固定文案）
    explanation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_recommended: Mapped[bool] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=now_default()
    )


class SchedulingPlanDetail(Base):
    """方案明细：一行 = 某车某趟服务某门店。

    对应需求文档 六.2 的关键字段示例。
    """

    __tablename__ = "scheduling_plan_detail"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    vehicle_id: Mapped[int] = mapped_column(Integer, nullable=False)
    vehicle_type: Mapped[str] = mapped_column(String(16), nullable=False)
    trip_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    time_window: Mapped[str] = mapped_column(String(8), nullable=False, default="AM")
    store_id: Mapped[int] = mapped_column(Integer, nullable=False)
    load_amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="planned")


class SchedulingConfirmation(Base):
    """人工确认记录。未确认前不允许下发。"""

    __tablename__ = "scheduling_confirmation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    plan_id: Mapped[int] = mapped_column(Integer, nullable=False)
    operator: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    approved: Mapped[bool] = mapped_column(Integer, nullable=False, default=0)
    adjustments: Mapped[str] = mapped_column(Text, nullable=False, default="")
    remark: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    confirmed_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=now_default()
    )


class DispatchRecord(Base):
    """下发执行记录。

    ★ 幂等设计：task_id + plan_id + trip_id 唯一（需求文档关键技术风险里的「下发重复」）。
    """

    __tablename__ = "dispatch_record"
    __table_args__ = (
        UniqueConstraint("task_id", "plan_id", "trip_id", name="uq_dispatch_idempotent"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    plan_id: Mapped[int] = mapped_column(Integer, nullable=False)
    vehicle_id: Mapped[int] = mapped_column(Integer, nullable=False)
    trip_id: Mapped[str] = mapped_column(String(64), nullable=False)
    target: Mapped[str] = mapped_column(String(32), nullable=False, default="TMS")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="accepted")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dispatched_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=now_default()
    )


class ExceptionEvent(Base):
    """异常事件。来源：车辆故障、司机缺勤、门店临时加减货、交通管制、地形临时管控。"""

    __tablename__ = "exception_event"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    payload: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=now_default()
    )


class ReplanRecord(Base):
    """重排记录。用 replan_count 限制，避免无限循环。"""

    __tablename__ = "replan_record"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    trigger_event_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scope: Mapped[str] = mapped_column(String(16), nullable=False, default="local")
    replan_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    result: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=now_default()
    )


class SchedulingReport(Base):
    """调度报告。"""

    __tablename__ = "scheduling_report"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    plan_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    generated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=now_default()
    )
