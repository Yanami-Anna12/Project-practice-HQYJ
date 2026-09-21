"""启动开发服务器。

    python run.py                 # 默认 127.0.0.1:8000，支持热重载
    python run.py --port 9000     # 指定端口

启动后：
    API 文档   http://127.0.0.1:8000/docs      ← 可直接点 Authorize 粘 Token 调接口
    ReDoc      http://127.0.0.1:8000/redoc
    健康检查   http://127.0.0.1:8000/api/health
"""

from __future__ import annotations

import argparse
import sys

import uvicorn

from app.config import settings


def main() -> int:
    parser = argparse.ArgumentParser(description="启动 RBAC 后端服务")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=8000, help="监听端口")
    parser.add_argument("--reload", action="store_true", default=True, help="热重载")
    parser.add_argument("--no-reload", dest="reload", action="store_false")
    args = parser.parse_args()

    print("=" * 70)
    print(f"  {settings.APP_NAME}")
    print("=" * 70)
    print(f"  数据库        : {settings.url_safe()}")
    print(f"  服务地址      : http://{args.host}:{args.port}")
    print(f"  接口文档      : http://{args.host}:{args.port}/docs")
    print(f"  热重载        : {'开启' if args.reload else '关闭'}")
    print("=" * 70)
    print("  提示：首次运行请先执行 `python seed.py` 灌入种子数据。")
    print("=" * 70)

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
