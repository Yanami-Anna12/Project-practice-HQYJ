"""集成与监控接口。

    GET /api/monitor/system        系统监控指标
    GET /api/monitor/alerts        预警清单
    GET /api/monitor/dashboard     总览（趋势 + 预警）
    GET /api/monitor/integrations  接口集成配置与落地情况
    GET /api/monitor/data-platform 数据与算法平台现状
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.deps import DbSession, require_permission
from app.models import SysUser
from app.services import monitor as monitor_service

router = APIRouter(prefix="/monitor", tags=["集成与监控"])

# 监控页面对应的权限点 monitor:read / integrations:manage 在 seed 里已定义
Monitor = Annotated[SysUser, Depends(require_permission("monitor:read"))]
Integrator = Annotated[SysUser, Depends(require_permission("integrations:manage"))]


@router.get("/system", summary="系统监控指标")
def system_metrics(db: DbSession, actor: Monitor) -> dict[str, Any]:
    return monitor_service.system_metrics(db)


@router.get("/alerts", summary="预警清单")
def alerts(db: DbSession, actor: Monitor) -> list[dict[str, Any]]:
    return monitor_service.alerts(db)


@router.get("/dashboard", summary="监控总览（趋势 + 预警）")
def dashboard(
    db: DbSession, actor: Monitor, days: int = Query(default=7, ge=1, le=90)
) -> dict[str, Any]:
    return monitor_service.dashboard_summary(db, days)


@router.get("/integrations", summary="接口集成配置")
def integrations(db: DbSession, actor: Integrator) -> list[dict[str, Any]]:
    return monitor_service.integrations_status(db)


@router.get("/data-platform", summary="数据与算法平台现状")
def data_platform(db: DbSession, actor: Monitor) -> dict[str, Any]:
    return monitor_service.data_platform(db)
