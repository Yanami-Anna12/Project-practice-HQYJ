"""导出与附件接口 —— PDF 3.4 工单导出 / 3.7 台账导出 / 3.9 数据导出。

前端流程（PDF 3.7：导出 Excel 需加载动画与充分提示）：
  1) POST /api/v1/exports/...            创建导出任务 → 返回 task_id
  2) GET  /api/v1/exports/tasks/{id}     轮询进度（progress + message）
  3) GET  /api/v1/exports/tasks/{id}/download  下载文件
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Query
from fastapi.responses import FileResponse

from app.core.database import AsyncSessionLocal
from app.core.deps import CurrentUser, DbSession
from app.core.errors import BizError, NotFoundError
from app.core.response import ApiResponse
from app.services import audit as audit_service
from app.services import export as export_service

router = APIRouter(prefix="/exports", tags=["导出管理"])


def _spawn(task_id: str, operator: str | None, kind: str, params: dict) -> None:
    """在后台执行导出（避免阻塞请求，同时让前端能轮询进度）。"""

    async def _run() -> None:
        async with AsyncSessionLocal() as db:
            try:
                if kind == "work_order":
                    await export_service.export_work_orders(
                        db,
                        task_id=task_id,
                        operator=operator,
                        order_ids=params.get("order_ids"),
                    )
                elif kind == "ledger":
                    await export_service.export_ledger(
                        db, task_id=task_id, operator=operator, **params
                    )
                elif kind == "statistics":
                    await export_service.export_statistics(
                        db, task_id=task_id, operator=operator, **params
                    )
                else:
                    export_service.update_task(
                        task_id, status="failed", message=f"未知导出类型：{kind}"
                    )
            except Exception as exc:  # pragma: no cover
                export_service.update_task(
                    task_id,
                    status="failed",
                    message=f"导出失败：{exc}",
                    error=f"{type(exc).__name__}: {exc}",
                )

    import asyncio

    asyncio.create_task(_run())


@router.get("/tasks", response_model=ApiResponse[list[dict]], summary="导出任务列表")
async def list_tasks(db: DbSession, user: CurrentUser, limit: int = Query(default=20, ge=1, le=100)):
    return ApiResponse.ok(export_service.list_tasks(limit))


@router.get("/tasks/{task_id}", response_model=ApiResponse[dict], summary="查询导出进度")
async def get_task(task_id: str, db: DbSession, user: CurrentUser):
    """前端据此展示加载动画与充分提示（PDF 3.7）。"""
    task = export_service.get_task(task_id)
    return ApiResponse.ok(
        {
            **task,
            "download_url": (
                f"/api/v1/exports/tasks/{task_id}/download"
                if task.get("status") == "success"
                else None
            ),
        }
    )


@router.get("/tasks/{task_id}/download", summary="下载导出文件")
async def download(task_id: str, db: DbSession, user: CurrentUser):
    task = export_service.get_task(task_id)
    if task.get("status") != "success" or not task.get("file_path"):
        raise BizError("导出尚未完成，暂时无法下载")

    path = Path(task["file_path"])
    if not path.exists():
        raise NotFoundError("导出文件已被清理，请重新导出")

    await audit_service.log_operation(
        db,
        module="导出管理",
        action="下载导出文件",
        user=user,
        target_type="export",
        target_id=task_id,
        description=f"下载导出文件 {task.get('file_name')}",
    )
    return FileResponse(
        path,
        filename=task.get("file_name") or path.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.post("/work-orders", response_model=ApiResponse[dict], summary="创建工单导出任务")
async def export_work_orders(
    db: DbSession,
    user: CurrentUser,
    background: BackgroundTasks,
    payload: dict | None = None,
):
    payload = payload or {}
    task = export_service.create_task("work_order", "工单导出报表", operator=user.real_name)
    _spawn(task["task_id"], user.real_name, "work_order", payload)
    await audit_service.log_operation(
        db,
        module="导出管理",
        action="创建工单导出任务",
        user=user,
        target_type="export",
        target_id=task["task_id"],
        description="工单导出",
    )
    return ApiResponse.ok(task, message="导出任务已创建")


@router.post("/ledger", response_model=ApiResponse[dict], summary="创建台账导出任务")
async def export_ledger(
    db: DbSession,
    user: CurrentUser,
    background: BackgroundTasks,
    payload: dict | None = None,
):
    """台账导出（PDF 3.7：站台台账 / 充电桩台账，信息导出）。"""
    payload = payload or {}
    ledger_type = payload.get("ledger_type")
    title = {
        "station": "站台台账导出",
        "pile": "充电桩台账导出",
    }.get(ledger_type or "", "资产台账导出")

    task = export_service.create_task("ledger", title, operator=user.real_name)
    params = {
        k: v
        for k, v in payload.items()
        if k in ("ledger_type", "keyword", "project_id", "station_id", "status")
    }
    _spawn(task["task_id"], user.real_name, "ledger", params)
    await audit_service.log_operation(
        db,
        module="导出管理",
        action="创建台账导出任务",
        user=user,
        target_type="export",
        target_id=task["task_id"],
        description=title,
    )
    return ApiResponse.ok(task, message="导出任务已创建")


@router.post("/statistics", response_model=ApiResponse[dict], summary="创建统计数据导出任务")
async def export_statistics(
    db: DbSession,
    user: CurrentUser,
    background: BackgroundTasks,
    payload: dict | None = None,
):
    payload = payload or {}
    task = export_service.create_task("statistics", "统计分析导出", operator=user.real_name)
    params = {
        k: v
        for k, v in payload.items()
        if k in ("period", "year", "month", "project_id", "station_id")
    }
    _spawn(task["task_id"], user.real_name, "statistics", params)
    await audit_service.log_operation(
        db,
        module="导出管理",
        action="创建统计导出任务",
        user=user,
        target_type="export",
        target_id=task["task_id"],
        description="统计数据分析导出（PDF 3.9 数据导出功能）",
    )
    return ApiResponse.ok(task, message="导出任务已创建")
