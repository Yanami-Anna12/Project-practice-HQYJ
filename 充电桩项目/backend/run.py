"""开发启动脚本：python run.py

等价于：uvicorn app.main:app --host 127.0.0.1 --port 8000
（需要开发热重载时加 --reload）
"""

from __future__ import annotations

import argparse
import sys

import uvicorn

from app.core.config import settings


def main() -> int:
    parser = argparse.ArgumentParser(description=f"{settings.APP_NAME} 后端服务")
    parser.add_argument("--host", default=settings.HOST)
    parser.add_argument("--port", type=int, default=settings.PORT)
    # 默认关闭 reload：Windows 下 uvicorn 的 reloader 会派生 multiprocessing worker 子进程，
    # 该子进程不继承控制台标题、netstat 又把端口记在已退出的父进程 PID 上，
    # 导致 stop.bat 停不干净（表现为“已停止”但端口仍被占用）。
    # 需要热重载时显式加 --reload。
    parser.add_argument("--reload", action="store_true", default=False)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()

    print("=" * 78)
    print(f"  {settings.APP_NAME} v{settings.APP_VERSION}")
    print(f"  环境：{settings.ENV}")
    print(f"  接口文档：http://{args.host}:{args.port}/docs")
    print(f"  健康检查：http://{args.host}:{args.port}/health")
    print(f"  LLM：{'已配置 ' + settings.LLM_MODEL if settings.llm_ready else '未配置（规则引擎降级）'}")
    print("=" * 78)

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        workers=1 if args.reload else args.workers,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
