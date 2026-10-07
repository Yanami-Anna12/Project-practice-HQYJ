"""统一错误类型与异常处理器。

约定：所有错误响应体都是 {"error": "..."}，与 RBAC 项目保持一致，
前端只需读 data.error 即可展示。
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class AppError(Exception):
    """业务异常基类。"""

    status_code: int = status.HTTP_400_BAD_REQUEST

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND


class ConflictError(AppError):
    """用于「删除被引用对象」这类冲突，前端会拿到 409 与具体原因。"""

    status_code = status.HTTP_409_CONFLICT


class AuthError(AppError):
    """未登录 / Token 无效 / 账号被停用。"""

    status_code = status.HTTP_401_UNAUTHORIZED


class PermissionDeniedError(AppError):
    """已登录但缺少权限点。"""

    status_code = status.HTTP_403_FORBIDDEN


def register_exception_handlers(app: FastAPI) -> None:
    """把异常统一渲染成 {"error": "..."}。"""

    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"error": exc.message})

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # 把 Pydantic 的校验错误压成一句人话，前端不必解析嵌套结构
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(p) for p in first.get("loc", []) if p != "body")
        msg = first.get("msg", "参数校验失败")
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"error": f"参数错误：{loc} {msg}".strip()},
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("未处理的异常：%s", exc)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"error": "服务器内部错误"},
        )
