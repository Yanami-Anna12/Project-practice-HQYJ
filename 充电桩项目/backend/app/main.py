"""充电桩运维管理 AI Agent 平台 —— FastAPI 应用入口。

对应 PDF 2.1 分层架构中的「FastAPI 应用层」：
REST API / WebSocket / 认证鉴权 / 请求校验。
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import api_router
from app.core.config import DATA_DIR, REPORT_DIR, settings
from app.core.database import init_db
from app.core.errors import register_exception_handlers
from app.core.response import ApiResponse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("app.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """启动时建表 + 初始化内置数据。"""
    logger.info("=" * 78)
    logger.info("  %s v%s", settings.APP_NAME, settings.APP_VERSION)
    logger.info("  环境：%s | 数据库：%s", settings.ENV, _mask_dsn(settings.DATABASE_URL))
    logger.info(
        "  LLM：%s（%s）| AI 开关：%s",
        settings.LLM_MODEL if settings.llm_ready else "未配置，使用规则引擎降级",
        settings.LLM_BASE_URL,
        "开启" if settings.AI_ENABLED else "关闭",
    )
    logger.info("=" * 78)

    await init_db()
    logger.info("数据库表结构就绪")

    from app.bootstrap import ensure_baseline_data

    result = await ensure_baseline_data()
    logger.info(
        "基线数据就绪：角色 %s，权限 %s，用户 %s，系统参数 %s，规则版本 %s",
        result.get("roles"),
        result.get("permissions"),
        result.get("users"),
        result.get("configs"),
        result.get("rule_version"),
    )
    if result.get("seeded"):
        logger.info("已注入演示数据（项目/站点/充电桩/工单/故障/巡检/知识库/报告）")

    yield
    logger.info("应用已停止")


def _mask_dsn(dsn: str) -> str:
    if "@" in dsn:
        head, tail = dsn.split("@", 1)
        prefix = head.split("://", 1)[0]
        return f"{prefix}://***@{tail}"
    return dsn


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "充电桩运维管理 AI Agent 平台后端 API。\n\n"
        "技术栈：FastAPI + SQLAlchemy(async) + LangGraph + OR-Tools + RAG。\n"
        "核心原则：硬约束代码化，LLM 只做解释和辅助。"
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)


@app.middleware("http")
async def access_log(request: Request, call_next):
    """访问日志 + 慢请求告警（PDF 8.2 系统监控）。"""
    started = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - started) * 1000
    response.headers["X-Process-Time-Ms"] = f"{duration_ms:.1f}"
    if request.url.path.startswith(settings.API_PREFIX) and not request.url.path.endswith(
        ("/docs", "/openapi.json")
    ):
        level = logging.WARNING if duration_ms > 1000 else logging.INFO
        logger.log(
            level,
            "%s %s -> %s (%.1f ms)",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
    return response


app.include_router(api_router, prefix=settings.API_PREFIX)

# 报告与图片静态访问
app.mount("/static/reports", StaticFiles(directory=str(REPORT_DIR)), name="reports")
app.mount("/static/data", StaticFiles(directory=str(DATA_DIR)), name="data")


@app.get("/", tags=["系统"], summary="服务信息")
async def root():
    return ApiResponse.ok(
        {
            "name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "env": settings.ENV,
            "docs": "/docs",
            "api_prefix": settings.API_PREFIX,
            "modules": [
                "系统管理",
                "角色与用户管理",
                "工单管理",
                "故障管理",
                "作业管理",
                "台账管理",
                "消息中心",
                "统计分析与看板",
                "二期扩展功能",
                "AI Agent 中心",
                "运维分析建议报告 Agent",
                "接口集成与数据交换",
                "监控预警与异常处理",
            ],
            "ai": {
                "enabled": settings.AI_ENABLED,
                "llm_ready": settings.llm_ready,
                "model": settings.LLM_MODEL,
                "fallback": settings.LLM_FALLBACK_ENABLED,
            },
        }
    )


@app.get("/health", tags=["系统"], summary="健康检查")
async def health():
    """供 K8s 探针与 Prometheus 采集（PDF 8.2 / 9.1）。"""
    from sqlalchemy import text

    from app.core.database import engine

    db_ok = True
    db_error = None
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        db_ok = False
        db_error = str(exc)

    return ApiResponse.ok(
        {
            "status": "healthy" if db_ok else "degraded",
            "database": {"ok": db_ok, "error": db_error},
            "env": settings.ENV,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
    )


@app.get("/metrics", tags=["系统"], summary="基础指标（Prometheus 文本格式）")
async def metrics():
    """轻量指标输出，可被 Prometheus 抓取（PDF 8.2）。"""
    from sqlalchemy import func, select

    from app.core.database import AsyncSessionLocal
    from app.models import AIAgentTask, FaultReport, WorkOrder

    async with AsyncSessionLocal() as db:
        order_total = int((await db.execute(select(func.count(WorkOrder.id)))).scalar() or 0)
        fault_total = int((await db.execute(select(func.count(FaultReport.id)))).scalar() or 0)
        agent_total = int((await db.execute(select(func.count(AIAgentTask.id)))).scalar() or 0)
        agent_failed = int(
            (
                await db.execute(
                    select(func.count(AIAgentTask.id)).where(AIAgentTask.status == "failed")
                )
            ).scalar()
            or 0
        )

    lines = [
        "# HELP maintenance_work_order_total 工单总数",
        "# TYPE maintenance_work_order_total gauge",
        f"maintenance_work_order_total {order_total}",
        "# HELP maintenance_fault_total 故障总数",
        "# TYPE maintenance_fault_total gauge",
        f"maintenance_fault_total {fault_total}",
        "# HELP maintenance_agent_task_total AI Agent 任务总数",
        "# TYPE maintenance_agent_task_total gauge",
        f"maintenance_agent_task_total {agent_total}",
        "# HELP maintenance_agent_task_failed AI Agent 失败任务数",
        "# TYPE maintenance_agent_task_failed gauge",
        f"maintenance_agent_task_failed {agent_failed}",
    ]
    from fastapi.responses import PlainTextResponse

    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """统一处理框架层 HTTP 异常（404 / 405 等）。

    要点：StaticFiles 等 Mount 子应用找不到文件时会抛 HTTPException(404)，
    必须在这里转换成「状态码原样」的普通响应。若直接返回 JSONResponse，
    或在处理器里再次 raise（会逃逸到兜底的 500 处理器），
    访问不存在的静态文件就会变成 500 而不是 404。
    """
    path = request.url.path
    if path.startswith("/api") or not path.startswith("/static"):
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.status_code,
                "message": exc.detail or f"HTTP {exc.status_code}",
                "data": None,
            },
            headers=getattr(exc, "headers", None),
        )
    # 静态资源：按标准语义返回纯文本状态码，避免被前端当成 JSON 解析
    return PlainTextResponse(
        str(exc.detail or "Not Found"),
        status_code=exc.status_code,
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(404)
async def not_found(request: Request, exc):  # pragma: no cover
    """路由未命中（未匹配任何路由时的兜底）。"""
    path = request.url.path
    if path.startswith("/static"):
        return PlainTextResponse("Not Found", status_code=404)
    return JSONResponse(
        status_code=404,
        content={"code": 404, "message": f"接口不存在：{path}", "data": None},
    )
