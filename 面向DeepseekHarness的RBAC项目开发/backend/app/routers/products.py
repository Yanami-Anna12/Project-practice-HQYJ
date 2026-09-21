"""商品接口（需求文档 4.2 的验收重点）。

    GET   /api/products   挂 products:read
    POST  /api/products   挂 products:edit

★ 验收标准对应：
    供应商访问 POST /api/products 必须返回 403（供应商只有 products:read）
    只读角色访问 GET /api/products 返回 200，访问 POST 返回 403

注意挂载方式：权限用 Depends(authorize("...")) 挂在路由上，
handler 里没有任何 if 判断权限的代码 —— 权限是「横切关注点」，
放在装饰器上比散落在业务逻辑里更不容易漏。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import CurrentUser, authorize, authorize_current
from app.errors import DuplicateError
from app.models import Product
from app.schemas import ProductCreateRequest, ProductOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/products", tags=["商品"])


@router.get(
    "",
    response_model=list[ProductOut],
    summary="商品列表",
    description="需要权限 `products:read`（四种角色都有，所以四个角色都能访问）。",
    dependencies=[Depends(authorize("products:read"))],
)
def list_products(db: Session = Depends(get_db)) -> list[ProductOut]:
    products = db.execute(select(Product).order_by(Product.id)).scalars()
    return [ProductOut.model_validate(p) for p in products]


@router.post(
    "",
    response_model=ProductOut,
    status_code=201,
    summary="新建商品",
    description=(
        "需要权限 `products:edit`。\n\n"
        "★ 只有「管理员」和「运营」持有该权限；"
        "**供应商与只读角色访问本接口必须得到 403**。"
    ),
    responses={403: {"description": "没有权限（缺少 products:edit）"}},
)
def create_product(
    payload: ProductCreateRequest,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(authorize_current("products:edit")),
) -> ProductOut:
    exists = db.execute(
        select(Product).where(Product.sku == payload.sku)
    ).scalar_one_or_none()
    if exists is not None:
        raise DuplicateError("SKU", payload.sku)

    product = Product(
        name=payload.name,
        sku=payload.sku,
        price=payload.price,
        stock=payload.stock,
        # 鉴权通过后身份可透传到业务层：记录是谁创建的
        created_by=current.id,
    )
    db.add(product)
    db.commit()
    db.refresh(product)

    logger.info("用户 %s 新建商品 %s（sku=%s）", current.username, product.name, product.sku)
    return ProductOut.model_validate(product)
