"""订单接口。

    GET /api/orders   挂 orders:read

需求文档 4.2 的接口表里没有列出订单接口，但第 2 节的权限矩阵中有 `orders:read`，
且「运营」与「只读」对该权限的取值不同（✓ / ✓）而「供应商」为 —。
为了让权限矩阵的每一行都有对应的接口出口、便于逐格验收，这里补上只读接口。

刻意不提供 POST/PUT：订单在权限矩阵里只有 read，没有对应的写权限点。
如果加了写接口，就不得不临时造一个 orders:edit 权限点，反而偏离需求。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import authorize
from app.models import Order
from app.schemas import OrderOut

router = APIRouter(prefix="/api/orders", tags=["订单"])


@router.get(
    "",
    response_model=list[OrderOut],
    summary="订单列表",
    description=(
        "需要权限 `orders:read`。\n\n"
        "★ 管理员、运营、只读持有该权限；**供应商没有，访问必须得到 403**。"
    ),
    responses={403: {"description": "没有权限（缺少 orders:read）"}},
    dependencies=[Depends(authorize("orders:read"))],
)
def list_orders(db: Session = Depends(get_db)) -> list[OrderOut]:
    orders = db.execute(select(Order).order_by(Order.id)).scalars()
    return [OrderOut.model_validate(o) for o in orders]
