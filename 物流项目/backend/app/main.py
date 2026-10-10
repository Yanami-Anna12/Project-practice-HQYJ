"""FastAPI 应用入口。

职责：装配 CORS、异常处理器、路由、静态目录，并提供健康检查。
业务逻辑一律不写在这里。
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.database import Base, ensure_database_exists
from app.errors import register_exception_handlers
from app.routers import (
    attachments,
    audit_logs,
    auth,
    demands,
    dicts,
    master,
    mobile,
    monitor,
    params,
    permissions,
    reports,
    roles,
    rules,
    scheduling,
    users,
    ws,
)
from app.services import realtime

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
    app.include_router(mobile.router, prefix="/api")
    # 实时推送（WebSocket）。挂在 /api 下，地址是 /api/ws/notifications?token=<JWT>
    app.include_router(ws.router, prefix="/api")

    # 司机端上传的现场照片：以静态目录对外提供访问（/uploads/<文件名>）。
    # 目录不存在时 StaticFiles 会直接报错，所以这里先建出来。
    # ★ 这是「演示级」的静态托管：没有鉴权、没有防盗链。生产环境应当
    #   换成对象存储 + 带签名的临时 URL（见 backend/README.md「已知边界」）。
    upload_dir = settings.upload_dir
    upload_dir.mkdir(parents=True, exist_ok=True)
    app.mount(
        settings.UPLOAD_URL_PREFIX,
        StaticFiles(directory=str(upload_dir)),
        name="uploads",
    )

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
                logger.warning("数据库 %s 是本次新建的", settings.DB_NAME)
        except Exception as exc:  # noqa: BLE001
            logger.error("数据库检查失败：%s", exc)

        # ★ 空库自动灌演示数据：换一台电脑时不必再手动跑 `python seed.py`。
        #   只在「账号表一条都没有」时触发，已有数据绝不覆盖；
        #   想关掉就设 AUTO_SEED_ON_EMPTY=false。
        if settings.AUTO_SEED_ON_EMPTY:
            try:
                from app.database import SessionLocal, engine
                from app.models import SysUser

                Base.metadata.create_all(bind=engine)
                db = SessionLocal()
                try:
                    empty = db.query(SysUser).first() is None
                finally:
                    db.close()
                if empty:
                    import sys

                    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
                    import seed as seed_module

                    logger.warning("检测到空库，正在自动载入演示数据（等价于 python seed.py）…")
                    seed_module.main()
                    logger.warning("演示数据已就绪，可直接用 admin / driver1 等账号登录")
            except Exception as exc:  # noqa: BLE001
                logger.error("自动载入演示数据失败（不影响启动，可手动跑 python seed.py）：%s", exc)

        logger.info("数据库：%s", settings.url_safe())
        logger.info("LLM 方案解释：%s", "已启用" if settings.llm_enabled else "未配置（降级）")

    @app.on_event("startup")
    async def _bind_realtime_loop() -> None:
        """把实时推送绑到当前事件循环。

        ★ 必须是 async def：`_startup` 是同步函数，FastAPI 会把它放到工作线程池里
          跑，那里没有 running loop。而这个函数在事件循环线程里执行，
          `asyncio.get_running_loop()` 拿到的正是 WebSocket 所在的那个循环。

        ★ 绑定之后，线程池里的业务代码（下发执行）就能跨线程把消息投递回来，
          见 app/services/realtime.py 的 publish_to_users()。
        """
        loop = asyncio.get_running_loop()
        realtime.bind_loop(loop)
        logger.info("实时推送已就绪：WebSocket /api/ws/notifications")

    return app


app = create_app()
