"""开发服务器启动脚本。

用法：
    python run.py            # 默认 127.0.0.1:8000
    python run.py --port 8001
"""

from __future__ import annotations

import argparse

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="启动车辆智能调度 Agent 后端")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    # 默认关闭 reload：Windows 下 uvicorn 的 reloader 会派生 multiprocessing worker 子进程，
    # 该子进程不继承控制台标题、netstat 又把端口记在已退出的父进程 PID 上，
    # 导致 stop.bat 停不干净（表现为“已停止”但端口仍被占用）。
    # 需要热重载时显式加 --reload。
    parser.add_argument("--reload", action="store_true", default=False)
    args = parser.parse_args()

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
