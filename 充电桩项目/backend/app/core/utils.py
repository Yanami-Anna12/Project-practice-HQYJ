"""通用工具：编号生成、JSON 安全转换、日期计算、模糊查询构造。"""

from __future__ import annotations

import json
import random
from datetime import date, datetime, timedelta
from typing import Any, Iterable

from sqlalchemy import ColumnElement, or_


def gen_no(prefix: str, seq: int | None = None) -> str:
    """生成业务编号，例如 WO20260115000001。"""
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    if seq is None:
        seq = random.randint(0, 9999)
    return f"{prefix}{stamp}{seq:04d}"


def gen_daily_no(prefix: str, seq: int) -> str:
    return f"{prefix}{datetime.now().strftime('%Y%m%d')}{seq:05d}"


def to_json_safe(value: Any) -> Any:
    """把任意对象转换为可 JSON 序列化的结构。"""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): to_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_json_safe(v) for v in value]
    if hasattr(value, "value"):  # Enum
        return to_json_safe(value.value)
    if hasattr(value, "model_dump"):
        return to_json_safe(value.model_dump())
    return str(value)


def dumps(value: Any) -> str:
    return json.dumps(to_json_safe(value), ensure_ascii=False)


def like_filter(columns: Iterable, keyword: str | None) -> ColumnElement | None:
    """构造多字段模糊查询条件（PDF 3.4 / 3.6 复杂模糊查询）。"""
    if not keyword:
        return None
    kw = keyword.strip()
    if not kw:
        return None
    pattern = f"%{kw}%"
    conditions = [col.ilike(pattern) for col in columns if col is not None]
    if not conditions:
        return None
    return or_(*conditions)


def daterange(start: date, end: date) -> list[date]:
    if end < start:
        return []
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def month_range(anchor: date) -> tuple[date, date]:
    first = anchor.replace(day=1)
    next_month = (first + timedelta(days=32)).replace(day=1)
    return first, next_month - timedelta(days=1)


def week_range(anchor: date) -> tuple[date, date]:
    monday = anchor - timedelta(days=anchor.weekday())
    return monday, monday + timedelta(days=6)


def safe_rate(numerator: float, denominator: float) -> float:
    if not denominator:
        return 0.0
    return round(numerator / denominator * 100, 2)


def chunked(items: list, size: int) -> Iterable[list]:
    for i in range(0, len(items), size):
        yield items[i: i + size]
