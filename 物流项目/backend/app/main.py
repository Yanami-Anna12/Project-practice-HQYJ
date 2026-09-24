"""FastAPI 应用入口。

职责：装配 CORS、异常处理器、路由，并提供健康检查。
业务逻辑一律不写在这里。
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import ensure_database_exists
from app.errors import register_exception_handlers
from app.routers import (
    attachments,
    audit_logs,
    auth,
    demands,
    dicts,
    master,
    monitor,
    params,
    permissions,
    reports,
    roles,
    rules,
    scheduling,
    users,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        description=(
            "门店配送车辆与趟次智能分配系统。\n\n"
            "权限模型：用户 → 角色 → 权限点，有效权限为所有**启用角色**权限的**并集**。"
        ),
        version="0.1.0",
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    # 所有业务接口统一挂在 /api 下
    app.include_router(auth.router, prefix="/api")
    app.include_router(users.router, prefix="/api")
    app.include_router(roles.router, prefix="/api")
    app.include_router(permissions.router, prefix="/api")
    app.include_router(dicts.router, prefix="/api")
    app.include_router(params.router, prefix="/api")
    app.include_router(attachments.router, prefix="/api")
    app.include_router(audit_logs.router, prefix="/api")
    app.include_router(master.router, prefix="/api")
    app.include_router(demands.router, prefix="/api")
    app.include_router(scheduling.router, prefix="/api")
    app.include_router(reports.router, prefix="/api")
    app.include_router(rules.router, prefix="/api")
    app.include_router(monitor.router, prefix="/api")

    @app.get("/api/health", tags=["系统"], summary="健康检查")
    def health() -> dict:
        return {
            "status": "ok",
            "app": settings.APP_NAME,
            "database": settings.url_safe(),
            "llm_enabled": settings.llm_enabled,
        }

    @app.on_event("startup")
    def _startup() -> None:
        # 库不存在时自动创建，省去手工建库步骤
        try:
            created = ensure_database_exists()
            if created:
                logger.warning(
                    "数据库 %s 是本次新建的，请执行 python seed.py 载入初始数据",
                    settings.DB_NAME,
                )
        except Exception as exc:  # noqa: BLE001
            logger.error("数据库检查失败：%s", exc)
        logger.info("数据库：%s", settings.url_safe())
        logger.info("LLM 方案解释：%s", "已启用" if settings.llm_enabled else "未配置（降级）")

    return app


app = create_app()
