"""Pydantic 请求/响应模型（前后端契约）。

约定：
  · Request 后缀 = 请求体；其余为响应模型
  · 响应模型一律不包含 password_hash（用 Pydantic 的白名单机制天然排除：
    只要不在模型里声明该字段，它就不可能被序列化出去）
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# 认证
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=50, description="登录名")
    password: str = Field(min_length=1, max_length=72, description="密码（bcrypt 上限 72 字节）")


class UserBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    nickname: str | None = None


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Token 有效期（秒）")
    user: UserBrief
    roles: list[str] = Field(description="角色码列表")
    permissions: list[str] = Field(
        description="有效权限码列表（多角色取并集）。★ 仅供前端渲染，后端不信任此字段。"
    )


# ---------------------------------------------------------------------------
# 当前用户 / 菜单
# ---------------------------------------------------------------------------


class MeResponse(BaseModel):
    user: UserBrief
    roles: list[str]
    permissions: list[str]


class MenuNode(BaseModel):
    """菜单节点。children 为空时不输出该键，前端据此判断叶子节点。"""

    key: str
    title: str
    path: str | None = None
    icon: str | None = None
    permission: str | None = None
    children: list["MenuNode"] | None = None


# 自引用模型需要显式重建，否则 Pydantic v2 无法解析 MenuNode 的前向引用。
# 这一步必须写在 MenuNode 定义之后（用 `python -c "import app.schemas"` 可验证）。
MenuNode.model_rebuild()


class PermissionsResponse(BaseModel):
    permissions: list[str]
    roles: list[str]


# ---------------------------------------------------------------------------
# 权限点
# ---------------------------------------------------------------------------


class PermissionCreateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=80, description="权限码，如 products:export")
    name: str = Field(min_length=1, max_length=80, description="中文名")
    module: str = Field(min_length=1, max_length=50, description="所属模块")

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        """权限码统一「模块:动作」格式，避免出现 products.read 这类混用写法。"""
        code = v.strip()
        if ":" not in code:
            raise ValueError("权限码必须形如「模块:动作」，例如 products:export")
        module, _, action = code.partition(":")
        if not module or not action:
            raise ValueError("权限码的模块名与动作名都不能为空")
        return code


class PermissionToggleRequest(BaseModel):
    is_active: bool = Field(description="true 启用，false 停用（★ R4：停用后立即生效）")


class PermissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    module: str
    is_active: bool
    created_at: datetime
    # 被多少个角色引用 —— 让管理员知道停用某权限点会影响谁
    role_count: int = 0


# ---------------------------------------------------------------------------
# 角色
# ---------------------------------------------------------------------------


class RoleCreateRequest(BaseModel):
    code: str = Field(min_length=1, max_length=50, description="角色码，如 auditor")
    name: str = Field(min_length=1, max_length=50, description="中文名")
    description: str | None = Field(default=None, max_length=200)
    permission_codes: list[str] = Field(
        default_factory=list, description="绑定的权限码；全量覆盖语义"
    )


class RoleUpdateRequest(BaseModel):
    """全部字段可选，只更新提交的字段。permission_codes 为全量覆盖。"""

    name: str | None = Field(default=None, min_length=1, max_length=50)
    description: str | None = Field(default=None, max_length=200)
    is_active: bool | None = None
    permission_codes: list[str] | None = None


class RoleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    description: str | None = None
    is_active: bool
    created_at: datetime
    permission_codes: list[str] = Field(default_factory=list)
    user_count: int = Field(default=0, description="绑定该角色的用户数（R3 的判定依据）")


class RoleDeleteResponse(BaseModel):
    ok: bool = True
    deleted: str = Field(description="被删除的角色码")


# ---------------------------------------------------------------------------
# 用户
# ---------------------------------------------------------------------------


class UserOut(BaseModel):
    """用户响应模型。

    ★ roles 字段显式声明 validation_alias="role_codes"。
      原因：User 实体上同时有 roles（返回 Role 对象列表）和 role_codes（返回字符串列表）
      两个属性，而本模型的 roles 是 list[str]。
      若不加别名，Pydantic 的 from_attributes 会优先读 user.roles，
      把 Role 对象塞进 list[str] 导致
          ValidationError: roles.0 Input should be a valid string
      从而让 GET /api/users 直接 500。

      validation_alias 让「从 ORM 读哪个属性」由显式声明决定，
      同时对外输出的 JSON 键仍然是 roles（不影响前端契约）。
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    username: str
    nickname: str | None = None
    is_active: bool
    created_at: datetime
    roles: list[str] = Field(default_factory=list, validation_alias="role_codes")
    permissions: list[str] = Field(
        default_factory=list, description="该用户的有效权限（多角色并集）"
    )


class UserRolesRequest(BaseModel):
    role_codes: list[str] = Field(
        default_factory=list,
        description="目标角色码列表；全量覆盖。★ 传多个角色时权限取并集（R1）",
    )


class UserRolesResponse(BaseModel):
    user_id: int
    username: str
    roles: list[str]
    permissions: list[str] = Field(description="改绑后的有效权限并集，便于前端立即刷新界面")


# ---------------------------------------------------------------------------
# 业务
# ---------------------------------------------------------------------------


class ProductCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    sku: str = Field(min_length=1, max_length=50)
    price: float = Field(default=0, ge=0, description="单价，不能为负")
    stock: int = Field(default=0, ge=0, description="库存，不能为负")


class ProductOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    sku: str
    price: float
    stock: int
    created_by: int | None = None
    created_at: datetime


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_no: str
    customer: str
    amount: float
    status: str
    created_at: datetime


class ReportSummaryResponse(BaseModel):
    product_count: int
    order_count: int
    total_amount: float
    order_status_breakdown: dict[str, int]
    generated_at: datetime
    generated_by: str = Field(description="生成该报表的用户名（演示鉴权身份透传）")


# ---------------------------------------------------------------------------
# 审计日志
# ---------------------------------------------------------------------------


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    actor_id: int | None = None
    actor_name: str
    action: str
    target_type: str | None = None
    target_id: int | None = None
    target_name: str | None = None
    detail: dict | None = None
    created_at: datetime
