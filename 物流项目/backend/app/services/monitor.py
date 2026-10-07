"""集成与监控服务。

对应需求文档 二.8「监控预警与异常处理」、二.9「数据与算法平台」
与技术方案文档 八「监控、可观测性与运维」。

★ 这里刻意**不伪造**监控数据：
  · 能真实测到的（数据库连通性、表规模、下发记录、异常事件、
    调度成功率、人工确认拒绝率、重排频率）就实测
  · 测不到的（API QPS、P95 延迟、Redis 命中率、MQ 堆积）
    明确标注 available=false 并说明原因，而不是编一个数字

  后者在真实部署里应由 Prometheus + Grafana 采集（见 routers/monitor.py 的说明），
  本项目没有引入那套中间件，所以只把「谁负责采集」写清楚。
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    DispatchRecord,
    ExceptionEvent,
    ReplanRecord,
    RuleVersion,
    SchedulingConfirmation,
    SchedulingPlan,
    SchedulingTask,
    StoreDemand,
    Vehicle,
)


# ---------------------------------------------------------------------------
# 系统监控
# ---------------------------------------------------------------------------
def system_metrics(db: Session) -> dict:
    """系统级监控指标。"""
    # --- 数据库连通性与版本（真测）---
    db_ok = True
    db_version = ""
    try:
        db_version = db.execute(text("SELECT VERSION()")).scalar() or ""
    except Exception as exc:  # noqa: BLE001
        db_ok = False
        db_version = f"连接失败：{exc}"

    # --- 表规模（真测）---
    table_counts = {
        "调度任务": db.query(func.count(SchedulingTask.id)).scalar() or 0,
        "调度方案": db.query(func.count(SchedulingPlan.id)).scalar() or 0,
        "下发记录": db.query(func.count(DispatchRecord.id)).scalar() or 0,
        "异常事件": db.query(func.count(ExceptionEvent.id)).scalar() or 0,
        "重排记录": db.query(func.count(ReplanRecord.id)).scalar() or 0,
        "人工确认": db.query(func.count(SchedulingConfirmation.id)).scalar() or 0,
        "规则版本": db.query(func.count(RuleVersion.id)).scalar() or 0,
        "货量记录": db.query(func.count(StoreDemand.id)).scalar() or 0,
    }

    # --- 调度健康度（从真实记录算）---
    tasks = db.query(SchedulingTask).all()
    total_tasks = len(tasks)
    failed = sum(1 for t in tasks if t.status == "failed")
    durations = [t.duration_ms for t in tasks if t.duration_ms > 0]

    confirmations = db.query(SchedulingConfirmation).all()
    approved = sum(1 for c in confirmations if c.approved)
    rejected = len(confirmations) - approved

    replans = db.query(ReplanRecord).count()

    # 异常的处置情况
    events = db.query(ExceptionEvent).all()
    pending_events = sum(1 for e in events if e.status == "pending")

    return {
        "checked_at": datetime.now().isoformat(timespec="seconds"),
        "database": {
            "available": db_ok,
            "version": db_version,
            "url": settings.url_safe(),
            "max_connections_note": "连接池配置见 app/database.py（pre_ping + recycle 3600）",
        },
        "tables": table_counts,
        "scheduling": {
            "total_tasks": total_tasks,
            "failed_tasks": failed,
            "success_rate": round((total_tasks - failed) / total_tasks * 100, 2) if total_tasks else 0.0,
            "avg_duration_ms": round(sum(durations) / len(durations)) if durations else 0,
            "max_duration_ms": max(durations) if durations else 0,
        },
        "confirmation": {
            "total": len(confirmations),
            "approved": approved,
            "rejected": rejected,
            "reject_rate": round(rejected / len(confirmations) * 100, 2) if confirmations else 0.0,
        },
        "exception": {
            "total": len(events),
            "pending": pending_events,
            "handled": len(events) - pending_events,
            "replan_count": replans,
        },
        "llm": {
            "enabled": settings.llm_enabled,
            "note": "未配置 DEEPSEEK_API_KEY 时方案解释降级为确定性文案，其余功能不受影响"
            if not settings.llm_enabled
            else "方案解释由 LLM 生成；硬约束始终不交给 LLM",
        },
        # ★ 明确列出「本项目未采集、需要外部监控栈」的指标，不编造数字
        "external_metrics": [
            {"name": "API QPS / 延迟 / 错误率", "collector": "Prometheus + Grafana", "available": False},
            {"name": "节点耗时分布（数据感知/求解/解释/下发）", "collector": "LangSmith / Langfuse", "available": False},
            {"name": "Redis 命中率、MQ 堆积", "collector": "Redis Exporter / RabbitMQ Exporter", "available": False},
        ],
    }


# ---------------------------------------------------------------------------
# 预警
# ---------------------------------------------------------------------------
def alerts(db: Session) -> list[dict]:
    """按真实数据推导预警项。

    每条预警都有明确的判断依据，不是随机生成的告警。
    """
    out: list[dict] = []

    # 1. 未处理的异常事件
    pending = (
        db.query(ExceptionEvent)
        .filter(ExceptionEvent.status == "pending")
        .order_by(ExceptionEvent.id.desc())
        .limit(20)
        .all()
    )
    for e in pending:
        out.append(
            {
                "level": "warning",
                "type": "异常事件未处理",
                "message": f"任务 #{e.task_id} 的异常「{e.event_type}」尚未处理",
                "target": f"exception:{e.id}",
                "occurred_at": e.occurred_at,
            }
        )

    # 2. 调度失败的任务
    failed = (
        db.query(SchedulingTask)
        .filter(SchedulingTask.status == "failed")
        .order_by(SchedulingTask.id.desc())
        .limit(10)
        .all()
    )
    for t in failed:
        out.append(
            {
                "level": "error",
                "type": "调度任务失败",
                "message": f"任务 {t.code} 未生成方案：{t.solver_note or '原因未记录'}",
                "target": f"task:{t.id}",
                "occurred_at": t.created_at,
            }
        )

    # 3. 重排次数接近上限
    max_replan = _int_param(db, "scheduling.replan.max_count", settings.REPLAN_MAX_COUNT)
    near = [
        t
        for t in db.query(SchedulingTask).all()
        if t.replan_count >= max(1, max_replan - 1)
    ]
    for t in near:
        out.append(
            {
                "level": "warning" if t.replan_count < max_replan else "error",
                "type": "重排次数接近上限",
                "message": f"任务 {t.code} 已重排 {t.replan_count}/{max_replan} 次，"
                f"{'已达上限，需人工介入' if t.replan_count >= max_replan else '接近上限'}",
                "target": f"task:{t.id}",
                "occurred_at": t.updated_at,
            }
        )

    # 4. 求解耗时偏长
    slow_threshold = 60000  # 60 秒
    slow = (
        db.query(SchedulingTask)
        .filter(SchedulingTask.duration_ms > slow_threshold)
        .order_by(SchedulingTask.id.desc())
        .limit(10)
        .all()
    )
    for t in slow:
        out.append(
            {
                "level": "info",
                "type": "求解耗时偏长",
                "message": f"任务 {t.code} 求解耗时 {t.duration_ms} ms，"
                f"可降低 CP-SAT 超时或关闭精确求解",
                "target": f"task:{t.id}",
                "occurred_at": t.created_at,
            }
        )

    # 5. 有方案但未确认且已过调度日期
    today = date.today()
    stale = (
        db.query(SchedulingTask)
        .filter(
            SchedulingTask.status == "pending_confirm",
            SchedulingTask.schedule_date < today,
        )
        .limit(10)
        .all()
    )
    for t in stale:
        out.append(
            {
                "level": "warning",
                "type": "方案待确认已过期",
                "message": f"任务 {t.code}（{t.schedule_date}）仍待确认，已过调度日期",
                "target": f"task:{t.id}",
                "occurred_at": t.created_at,
            }
        )

    # 6. 车辆可用性
    total_v = db.query(func.count(Vehicle.id)).filter(Vehicle.is_active.is_(True)).scalar() or 0
    maintenance = (
        db.query(func.count(Vehicle.id))
        .filter(Vehicle.is_active.is_(True), Vehicle.status == "maintenance")
        .scalar()
        or 0
    )
    if total_v and maintenance / total_v > 0.2:
        out.append(
            {
                "level": "warning",
                "type": "维保车辆占比偏高",
                "message": f"{maintenance}/{total_v} 台车辆处于维保中，可能影响运力",
                "target": "vehicle",
                "occurred_at": datetime.now(),
            }
        )

    order = {"error": 0, "warning": 1, "info": 2}
    out.sort(key=lambda x: order.get(x["level"], 9))
    return out


def _int_param(db: Session, key: str, default: int) -> int:
    from app.models import SysParam

    row = db.query(SysParam).filter(SysParam.key == key).one_or_none()
    if row is None:
        return default
    try:
        return int(row.value)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# 集成配置
# ---------------------------------------------------------------------------
# 需求文档与技术方案里的外部系统。★ 这些**尚未实际对接**，
# 所以每条都明确标注 status=not_connected，不假装已连通。
INTEGRATIONS = [
    {
        "name": "TMS",
        "full_name": "运输管理系统",
        "direction": "出向（下发）",
        "content": "调度方案下发、执行结果回传",
        "endpoint": "POST /tms/api/dispatch/plan",
        "enabled": True,
        "implemented": False,
        "note": "方案下发在本项目内已实现（写入 dispatch_record 并幂等去重），"
                "对外调用 TMS 真实接口尚未接入",
    },
    {
        "name": "OMS",
        "full_name": "订单管理系统",
        "direction": "入向（接收）",
        "content": "订单、货量、门店需求",
        "endpoint": "由 OMS 推送至 /api/demands",
        "enabled": True,
        "implemented": False,
        "note": "货量入口已就绪并可手工维护，OMS 推送接口尚未接入",
    },
    {
        "name": "WMS",
        "full_name": "仓储管理系统",
        "direction": "入向",
        "content": "出入库、拣货完成、装车确认",
        "endpoint": "—",
        "enabled": False,
        "implemented": False,
        "note": "未在本期范围内",
    },
    {
        "name": "ERP",
        "full_name": "企业资源计划",
        "direction": "双向",
        "content": "组织、财务、成本",
        "endpoint": "—",
        "enabled": False,
        "implemented": False,
        "note": "未在本期范围内；成本目前用相对系数而非财务口径",
    },
    {
        "name": "地图服务",
        "full_name": "高德 / 百度 / 自研",
        "direction": "出向（调用）",
        "content": "路径规划、距离矩阵",
        "endpoint": "—",
        "enabled": False,
        "implemented": False,
        "note": "当前求解器用「一趟最多 8 个门店」的简化顺序约束，未接入真实路径规划",
    },
    {
        "name": "GPS",
        "full_name": "车辆定位",
        "direction": "入向",
        "content": "GPS 轨迹",
        "endpoint": "—",
        "enabled": False,
        "implemented": False,
        "note": "移动端/司机端功能属后续范围",
    },
    {
        "name": "消息推送",
        "full_name": "企微 / 钉钉 / 短信",
        "direction": "出向",
        "content": "任务通知、异常提醒",
        "endpoint": "—",
        "enabled": False,
        "implemented": False,
        "note": "未在本期范围内",
    },
]


def integrations_status(db: Session) -> list[dict]:
    """集成配置清单 + 本项目内已落地的部分。"""
    dispatched = db.query(func.count(DispatchRecord.id)).scalar() or 0
    out = []
    for item in INTEGRATIONS:
        row = dict(item)
        if item["name"] == "TMS":
            row["local_evidence"] = f"本地下发记录 {dispatched} 条（dispatch_record，幂等去重）"
        elif item["name"] == "OMS":
            demands = db.query(func.count(StoreDemand.id)).scalar() or 0
            row["local_evidence"] = f"本地货量记录 {demands} 条（可手工维护或由生成器写入）"
        else:
            row["local_evidence"] = ""
        row["status"] = "partial" if item["implemented"] else "not_connected"
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# 数据与算法平台
# ---------------------------------------------------------------------------
def data_platform(db: Session) -> dict:
    """数据与算法平台的现状（需求 二.9）。

    ★ 明确区分「已实现」与「规划中」：
      求解器与规则中心已经可用，向量库/案例沉淀属于规划项。
    """
    from app.models import Route, Store, StoreRouteMapping, VehicleType

    return {
        "implemented": [
            {
                "name": "调度求解器",
                "detail": "启发式 + OR-Tools CP-SAT 三阶段混合求解（app/services/solver.py）",
            },
            {
                "name": "规则中心",
                "detail": "装载量/趟次/地形/线路规则 + 版本快照与回滚（app/services/rules.py）",
            },
            {
                "name": "方案与执行数据",
                "detail": "调度任务、方案、明细、确认、下发、异常、重排、报告共 9 张表",
            },
            {
                "name": "审计链路",
                "detail": "全部写操作落 sys_audit_log，只追加不可改",
            },
        ],
        "planned": [
            {
                "name": "规则知识库（向量库）",
                "detail": "把规则条文与历史调度案例向量化，供 LLM 检索增强解释",
                "collector": "pgvector / Milvus",
            },
            {
                "name": "历史调度案例沉淀",
                "detail": "把每次调度的输入、方案、执行结果作为训练/评估数据集",
                "collector": "LangSmith Datasets",
            },
            {
                "name": "求解参数自动调优",
                "detail": "根据历史达成率自动调整评分权重",
                "collector": "离线实验平台",
            },
        ],
        "data_scale": {
            "门店": db.query(func.count(Store.id)).scalar() or 0,
            "线路": db.query(func.count(Route.id)).scalar() or 0,
            "门店线路映射": db.query(func.count(StoreRouteMapping.id)).scalar() or 0,
            "车辆类型": db.query(func.count(VehicleType.id)).scalar() or 0,
            "车辆": db.query(func.count(Vehicle.id)).scalar() or 0,
            "货量记录": db.query(func.count(StoreDemand.id)).scalar() or 0,
            "调度任务": db.query(func.count(SchedulingTask.id)).scalar() or 0,
            "方案明细": db.query(func.count(SchedulingPlan.id)).scalar() or 0,
        },
    }


def dashboard_summary(db: Session, days: int = 7) -> dict:
    """总览：最近几天的调度活动趋势。"""
    since = date.today() - timedelta(days=days - 1)
    tasks = (
        db.query(SchedulingTask)
        .filter(SchedulingTask.schedule_date >= since)
        .order_by(SchedulingTask.schedule_date)
        .all()
    )
    by_date: dict[str, dict] = {}
    for t in tasks:
        key = str(t.schedule_date)
        row = by_date.setdefault(
            key, {"date": key, "tasks": 0, "dispatched": 0, "failed": 0, "avg_duration_ms": 0, "_d": []}
        )
        row["tasks"] += 1
        if t.status in ("dispatched", "completed"):
            row["dispatched"] += 1
        if t.status == "failed":
            row["failed"] += 1
        if t.duration_ms:
            row["_d"].append(t.duration_ms)

    trend = []
    for row in by_date.values():
        d = row.pop("_d")
        row["avg_duration_ms"] = round(sum(d) / len(d)) if d else 0
        trend.append(row)

    return {
        "days": days,
        "since": str(since),
        "trend": trend,
        "alerts": alerts(db)[:10],
    }
