"""领域异常：把「业务上的错误」与「HTTP 状态码」对应起来。

设计意图：
  路由和 service 层只抛业务异常（不认识 HTTP），
  由 main.py 的统一异常处理器翻译成符合需求文档第 6 节的响应体：

        场景               状态码    响应体
        未登录              401     {"error": "未登录"}
        已登录但无权限      403     {"error": "没有权限"}
        删除被引用的角色    409     {"error": "该角色仍绑定 N 个用户，请先改绑"}

  这样「响应格式」只有一处定义，不会出现某个接口忘了套格式的情况。
"""

from __future__ import annotations


class AppError(Exception):
    """所有业务异常的基类。"""

    status_code: int = 400
    default_message: str = "请求有误"

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.default_message
        super().__init__(self.message)

    def to_response(self) -> dict[str, str]:
        return {"error": self.message}


class UnauthorizedError(AppError):
    """未登录 / Token 缺失、过期、非法 / 用户已被停用。

    注意：这三种情况都用 401 且文案统一为「未登录」，
    目的是不向未认证的调用方泄露「账号是否存在」「账号是否被停用」。
    """

    status_code = 401
    default_message = "未登录"


class ForbiddenError(AppError):
    """已登录但缺少所需权限（R2 默认拒绝的三种情形都收敛到这里）。"""

    status_code = 403
    default_message = "没有权限"


class NotFoundError(AppError):
    status_code = 404
    default_message = "资源不存在"


class ConflictError(AppError):
    status_code = 409
    default_message = "资源冲突"


class RoleInUseError(ConflictError):
    """★ R3：删除仍被用户引用的角色。

    文案必须包含绑定用户数，这是验收标准明确要求的。
    """

    def __init__(self, user_count: int) -> None:
        self.user_count = user_count
        super().__init__(f"该角色仍绑定 {user_count} 个用户，请先改绑")


class DuplicateError(ConflictError):
    """唯一键冲突，例如角色 code、权限 code、用户名重复。"""

    def __init__(self, field: str, value: str) -> None:
        super().__init__(f"{field} “{value}” 已存在")


class LastAdminError(ConflictError):
    """★ 防止把系统里最后一个管理员改绑掉，导致无人能进管理端。

    这是我在需求之外加的保护：R3 警告我们「不要让人被角色绑死」，
    但反过来「让系统失去最后一个管理员」是更严重的自锁——
    一旦发生，只能改数据库才能恢复，属于必须防住的不可逆故障。
    """

    def __init__(self) -> None:
        super().__init__("不能移除最后一个管理员的管理角色，否则将无人能进入管理端")


class ValidationError(AppError):
    status_code = 400
    default_message = "参数不合法"
