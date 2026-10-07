"""统一响应结构、分页与查询辅助。"""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """统一响应体：code=0 表示成功。"""

    code: int = 0
    message: str = "success"
    data: T | None = None

    @classmethod
    def ok(cls, data: Any = None, message: str = "success") -> "ApiResponse":
        return cls(code=0, message=message, data=data)

    @classmethod
    def fail(cls, message: str, code: int = 1, data: Any = None) -> "ApiResponse":
        return cls(code=code, message=message, data=data)


class PageMeta(BaseModel):
    page: int = 1
    page_size: int = 20
    total: int = 0
    total_pages: int = 0
    has_next: bool = False


class PageData(BaseModel, Generic[T]):
    items: list[T] = Field(default_factory=list)
    meta: PageMeta = Field(default_factory=PageMeta)

    @classmethod
    def build(
        cls, items: list[T], total: int, page: int, page_size: int
    ) -> "PageData[T]":
        total_pages = (total + page_size - 1) // page_size if page_size else 0
        return cls(
            items=items,
            meta=PageMeta(
                page=page,
                page_size=page_size,
                total=total,
                total_pages=total_pages,
                has_next=page < total_pages,
            ),
        )


class PageParams(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size
