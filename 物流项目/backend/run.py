"""开发服务器启动脚本。

用法：
    python run.py            # 监听 127.0.0.1，端口从 8000 起自动挑第一个空闲的
    python run.py --port 8001

端口自适应：默认端口被占用时自动顺延，并把实际端口写入 backend/.runtime_port，
start.bat 读取该文件后用 VITE_PROXY_TARGET 告诉前端把 /api 代理到正确端口。
"""

from __future__ import annotations

import argparse
import socket
from pathlib import Path

import uvicorn

PORT_FILE = Path(__file__).resolve().parent / ".runtime_port"
BASE_PORT = 8000


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


def main() -> None:
    parser = argparse.ArgumentParser(description="启动车辆智能调度 Agent 后端")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0, help="0 表示从 8000 起自动找空闲端口")
    # 默认关闭 reload：Windows 下 uvicorn 的 reloader 会派生 multiprocessing worker 子进程，
    # 该子进程不继承控制台标题、netstat 又把端口记在已退出的父进程 PID 上，
    # 导致 stop.bat 停不干净（表现为“已停止”但端口仍被占用）。
    # 需要热重载时显式加 --reload。
    parser.add_argument("--reload", action="store_true", default=False)
    args = parser.parse_args()

    port = args.port or first_free_port(args.host, BASE_PORT)
    if port != BASE_PORT:
        print(f"[端口] {BASE_PORT} 已被占用，自动改用 {port}")

    PORT_FILE.write_text(str(port), encoding="utf-8")
    print(f"[地址] http://{args.host}:{port}/docs")

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
