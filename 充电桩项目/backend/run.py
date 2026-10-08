"""开发启动脚本：python run.py

等价于：uvicorn app.main:app --host 127.0.0.1 --port 8010
（需要开发热重载时加 --reload）

端口自适应：settings.PORT（默认 8010）被占用时自动顺延，
并把实际端口写入 backend/.runtime_port，start.bat 据此告诉前端代理到哪。
"""

from __future__ import annotations

import argparse
import socket
import sys
from pathlib import Path

import uvicorn

from app.core.config import settings

PORT_FILE = Path(__file__).resolve().parent / ".runtime_port"


def first_free_port(host: str, start: int, tries: int = 30) -> int:
    """返回 [start, start+tries) 内第一个可绑定的端口；全部占用则原样返回 start。"""
    for port in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
                return port
            except OSError:
                continue
    return start


def main() -> int:
    parser = argparse.ArgumentParser(description=f"{settings.APP_NAME} 后端服务")
    parser.add_argument("--host", default=settings.HOST)
    parser.add_argument("--port", type=int, default=0, help="0 表示从 settings.PORT 起自动找空闲端口")
    # 默认关闭 reload：Windows 下 uvicorn 的 reloader 会派生 multiprocessing worker 子进程，
    # 该子进程不继承控制台标题、netstat 又把端口记在已退出的父进程 PID 上，
    # 导致 stop.bat 停不干净（表现为“已停止”但端口仍被占用）。
    # 需要热重载时显式加 --reload。
    parser.add_argument("--reload", action="store_true", default=False)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()

    port = args.port or first_free_port(args.host, settings.PORT)
    if port != settings.PORT:
        print(f"[端口] {settings.PORT} 已被占用，自动改用 {port}")
    PORT_FILE.write_text(str(port), encoding="utf-8")

    print("=" * 78)
    print(f"  {settings.APP_NAME} v{settings.APP_VERSION}")
    print(f"  环境：{settings.ENV}")
    print(f"  接口文档：http://{args.host}:{port}/docs")
    print(f"  健康检查：http://{args.host}:{port}/health")
    print(f"  LLM：{'已配置 ' + settings.LLM_MODEL if settings.llm_ready else '未配置（规则引擎降级）'}")
    print("=" * 78)

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=port,
        reload=args.reload,
        workers=1 if args.reload else args.workers,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
