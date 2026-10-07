"""API 路由汇总。"""

from fastapi import APIRouter

from app.api import (
    admin,
    ai,
    auth,
    exports,
    faults,
    messages_stats,
    uploads,
    work_orders,
    ws,
)

api_router = APIRouter()

api_router.include_router(auth.router)
api_router.include_router(work_orders.router)
api_router.include_router(faults.router)
api_router.include_router(messages_stats.router)
api_router.include_router(messages_stats.stats_router)
api_router.include_router(exports.router)
api_router.include_router(uploads.router)
api_router.include_router(admin.router)
api_router.include_router(ai.router)
api_router.include_router(ws.router)

__all__ = ["api_router"]
