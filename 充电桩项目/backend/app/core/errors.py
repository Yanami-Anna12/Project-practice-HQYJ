"""业务异常与全局异常处理。"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

logger = logging.getLogger("app.errors")


class BizError(Exception):
    """业务异常，统一由异常处理器转换为 ApiResponse。"""

    def __init__(self, message: str, code: int = 1, http_status: int = status.HTTP_400_BAD_REQUEST):
        super().__init__(message)
        self.message = message
        self.code = code
        self.http_status = http_status


class NotFoundError(BizError):
    def __init__(self, message: str = "资源不存在"):
        super().__init__(message, code=404, http_status=status.HTTP_404_NOT_FOUND)


class PermissionDeniedError(BizError):
    def __init__(self, message: str = "无权访问该数据"):
        super().__init__(message, code=403, http_status=status.HTTP_403_FORBIDDEN)


class AuthError(BizError):
    def __init__(self, message: str = "认证失败"):
        super().__init__(message, code=401, http_status=status.HTTP_401_UNAUTHORIZED)


class ConflictError(BizError):
    def __init__(self, message: str = "数据冲突"):
        super().__init__(message, code=409, http_status=status.HTTP_409_CONFLICT)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(BizError)
    async def _biz(_: Request, exc: BizError):
        return JSONResponse(
            status_code=exc.http_status,
            content={"code": exc.code, "message": exc.message, "data": None},
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError):
        first = exc.errors()[0] if exc.errors() else {}
        loc = ".".join(str(x) for x in first.get("loc", []) if x != "body")
        msg = f"参数校验失败：{loc} {first.get('msg', '')}".strip()
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"code": 422, "message": msg, "data": exc.errors()},
        )

    @app.exception_handler(IntegrityError)
    async def _integrity(_: Request, exc: IntegrityError):
        logger.warning("integrity error: %s", exc)
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"code": 409, "message": "数据唯一性冲突或外键约束失败", "data": None},
        )

    @app.exception_handler(SQLAlchemyError)
    async def _sqlalchemy(_: Request, exc: SQLAlchemyError):
        logger.exception("database error")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"code": 500, "message": f"数据库异常：{exc.__class__.__name__}", "data": None},
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        logger.exception("unhandled error")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"code": 500, "message": f"服务器内部错误：{exc}", "data": None},
        )
