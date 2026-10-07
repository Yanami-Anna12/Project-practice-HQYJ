"""报表接口。

    GET /api/reports/summary   挂 reports:view

★ 验收对应：只读角色持有 reports:view，访问本接口应为 200；
             供应商没有该权限，访问应为 403。

这里刻意用聚合查询（SUM / GROUP BY）而不是把全表读出来在 Python 里统计，
顺便演示「权限通过后，业务层就是普通业务代码」——鉴权与业务是正交的。
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import CurrentUser, authorize_current
from app.models import Order, Product
from app.schemas import ReportSummaryResponse

router = APIRouter(prefix="/api/reports", tags=["报表"])


@router.get(
    "/summary",
    response_model=ReportSummaryResponse,
    summary="报表汇总",
    description=(
        "需要权限 `reports:view`。\n\n"
        "★ 管理员、运营、只读可访问；**供应商访问必须得到 403**。"
    ),
    responses={403: {"description": "没有权限（缺少 reports:view）"}},
)
def reports_summary(
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(authorize_current("reports:view")),
) -> ReportSummaryResponse:
    product_count = db.execute(select(func.count()).select_from(Product)).scalar_one()
    order_count = db.execute(select(func.count()).select_from(Order)).scalar_one()
    total_amount = db.execute(select(func.coalesce(func.sum(Order.amount), 0))).scalar_one()

    rows = db.execute(
        select(Order.status, func.count()).group_by(Order.status).order_by(Order.status)
    ).all()
    breakdown = {status: count for status, count in rows}

    return ReportSummaryResponse(
        product_count=int(product_count),
        order_count=int(order_count),
        total_amount=float(total_amount),
        order_status_breakdown=breakdown,
        generated_at=datetime.now(timezone.utc),
        # 演示鉴权身份透传到业务层
        generated_by=current.username,
    )
