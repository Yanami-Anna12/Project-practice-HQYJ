"""FastAPI 应用入口：路由注册 + 统一异常处理。

★ 本文件是「错误响应规范」的唯一出处（需求文档第 6 节）：
      未登录              401  {"error": "未登录"}
      已登录但无权限      403  {"error": "没有权限"}
      删除被引用的角色    409  {"error": "该角色仍绑定 N 个用户，请先改绑"}

  所有异常都在这里被翻译成标准响应体。业务代码只抛 AppError 子类，
  不需要知道 HTTP 状态码，也就不会出现某个接口漏套格式的情况。
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.config import settings
from app.errors import AppError
from app.routers import (
    audit_logs,
    auth,
    me,
    orders,
    permissions,
    products,
    reports,
    roles,
    users,
)

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)-7s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version="1.0.0",
        description=(
            "基于 Vue 3 + FastAPI 的 RBAC 权限管理系统。\n\n"
            "**鉴权链路**：`requireAuth(401)` → `authorize('权限码')(403)` → `handler`\n\n"
            "**注意**：登录响应中的 `permissions` 仅供前端渲染界面使用；"
            "后端每个接口都会实时查库重新计算权限，客户端伪造该字段不会获得任何实际权限。"
        ),
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # ---------------------------------------------------------------------
    # CORS：允许前端开发服务器（Vite，默认 5173）跨域访问
    # ---------------------------------------------------------------------
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)
    _register_routers(app)
    return app


def register_exception_handlers(app: FastAPI) -> None:
    """注册统一异常处理器。

    ★ 单独抽成公开函数（而不是写在 create_app 内部），有两个原因：
      1. 测试里创建的临时 FastAPI 实例也需要同一套错误契约，
         否则它会绕过处理器直接抛异常，测出来的行为与线上不一致；
      2. 「错误响应规范」只有一个实现，任何 App 实例挂上它即获得一致行为。
    """

    @app.exception_handler(AppError)
    async def handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
        """业务异常 → 对应状态码 + {"error": "..."}。

        这里是 401/403/409 三条规范的落地点。
        """
        return JSONResponse(status_code=exc.status_code, content=exc.to_response())

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """请求参数校验失败 → 422。

        需求文档未规定此场景，这里沿用 FastAPI 的 422 语义，
        但要包装成本项目的统一格式（error + detail），而不是默认的 {"detail": [...]}。
        """
        errors = [
            {
                "字段": ".".join(str(x) for x in err.get("loc", [])),
                "原因": err.get("msg", ""),
            }
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={"error": "参数校验失败", "detail": errors},
        )

    @app.exception_handler(IntegrityError)
    async def handle_integrity_error(_request: Request, exc: IntegrityError) -> JSONResponse:
        """未捕获的数据库完整性错误 → 409。

        正常情况下不该走到这里：R3 的场景应被 services/rbac.py 提前拦住并给出
        「仍绑定 N 个用户」的友好文案。此处理器是最后一道兜底，
        避免把 SQL 细节（表名、约束名）泄露给客户端。
        """
        logger.error("未处理的数据库完整性错误：%s", exc.orig)
        return JSONResponse(
            status_code=409,
            content={"error": "数据完整性冲突，操作被拒绝"},
        )

    @app.exception_handler(SQLAlchemyError)
    async def handle_db_error(_request: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.exception("数据库错误：%s", exc)
        return JSONResponse(status_code=500, content={"error": "数据库错误"})

    @app.exception_handler(Exception)
    async def handle_unexpected(_request: Request, exc: Exception) -> JSONResponse:
        """兜底：任何未预期异常都不泄露堆栈，只返回统一的 500。"""
        logger.exception("未预期异常：%s", exc)
        return JSONResponse(status_code=500, content={"error": "服务器内部错误"})


def _register_routers(app: FastAPI) -> None:
    """注册所有路由。

    统一在这里挂 security=[bearer_scheme] 作为 OpenAPI 元数据，
    让 /docs 中的受保护接口显示锁图标并出现 Authorize 按钮。
    """
    for router in (
        auth.router,
        me.router,
        permissions.router,
        roles.router,
        users.router,
        products.router,
        orders.router,
        reports.router,
        audit_logs.router,
    ):
        app.include_router(router)


app = create_app()
