"""认证接口 —— PDF 5.1 /api/v1/auth/wechat-login、3.3 微信授权手机号登录。"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Request
from sqlalchemy import select

from app.core.config import settings
from app.core.deps import CurrentUser, DbSession
from app.core.errors import AuthError, BizError
from app.core.response import ApiResponse
from app.core.security import (
    create_access_token,
    hash_password,
    verify_password,
)
from app.models import Permission, User
from app.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    ProfileUpdate,
    TokenResponse,
    UserOut,
    WechatLoginRequest,
)
from app.services import audit as audit_service
from app.services import rbac as rbac_service

router = APIRouter(prefix="/auth", tags=["认证"])


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def _build_user_out(user: User) -> UserOut:
    out = UserOut.model_validate(user)
    out.project_name = user.project.name if user.project else None
    out.station_name = user.station.name if user.station else None
    out.data_scope = user.role.data_scope if user.role else None
    return out


async def _permission_codes(db: DbSession, user: User) -> list[str]:
    if not user.role_id:
        return []
    return await rbac_service.role_permission_codes(db, user.role_id)


@router.post("/login", response_model=ApiResponse[TokenResponse], summary="账号密码登录")
async def login(payload: LoginRequest, request: Request, db: DbSession):
    user = (
        await db.execute(select(User).where(User.username == payload.username))
    ).scalar_one_or_none()

    if user is None or not verify_password(payload.password, user.hashed_password):
        await audit_service.log_login(
            db,
            user=user,
            success=False,
            message="用户名或密码错误",
            ip=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
        raise AuthError("用户名或密码错误")
    if not user.status:
        await audit_service.log_login(
            db,
            user=user,
            success=False,
            message="账号已停用",
            ip=_client_ip(request),
        )
        raise AuthError("账号已被停用，请联系管理员")

    await audit_service.log_login(
        db,
        user=user,
        success=True,
        message="登录成功",
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )

    token = create_access_token(
        user.id,
        extra={"username": user.username, "role": user.role.code if user.role else None},
    )
    return ApiResponse.ok(
        TokenResponse(
            access_token=token,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            user=_build_user_out(user),
        )
    )


@router.post("/wechat-login", response_model=ApiResponse[TokenResponse], summary="微信授权登录")
async def wechat_login(payload: WechatLoginRequest, request: Request, db: DbSession):
    """微信授权手机号登录（PDF 3.3）。

    真实环境需用 code 换取 openid 与手机号；未配置微信凭据时，
    支持直接传 openid + phone 完成联调，便于本地演示。
    """
    openid = payload.openid
    if not openid:
        if not settings.WECHAT_APPID:
            raise BizError(
                "未配置微信凭据：请在 .env 设置 WECHAT_APPID / WECHAT_SECRET，"
                "或在请求中直接传入 openid 以便本地联调"
            )
        if not payload.code:
            raise BizError("缺少微信登录 code")
        import httpx

        async with httpx.AsyncClient(timeout=settings.OUTBOUND_TIMEOUT) as client:
            resp = await client.get(
                "https://api.weixin.qq.com/sns/jscode2session",
                params={
                    "appid": settings.WECHAT_APPID,
                    "secret": settings.WECHAT_SECRET,
                    "js_code": payload.code,
                    "grant_type": "authorization_code",
                },
            )
            data = resp.json()
        openid = data.get("openid")
        if not openid:
            raise AuthError(f"微信登录失败：{data.get('errmsg') or '未知错误'}")

    user, need_confirm = await rbac_service.wechat_login(
        db, openid=openid, phone=payload.phone, nickname=payload.nickname
    )
    if user is None:
        await audit_service.log_login(
            db,
            user=None,
            success=False,
            message=f"微信用户待管理员确认：{openid}",
            login_type="wechat",
            ip=_client_ip(request),
        )
        raise BizError(
            "该微信账号尚未绑定平台用户，已记录登录请求，请联系管理员确认身份并授予权限"
        )

    await audit_service.log_login(
        db,
        user=user,
        success=True,
        message="微信登录成功",
        login_type="wechat",
        ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    token = create_access_token(
        user.id, extra={"username": user.username, "login": "wechat"}
    )
    return ApiResponse.ok(
        TokenResponse(
            access_token=token,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            user=_build_user_out(user),
        )
    )


@router.get("/profile", response_model=ApiResponse[dict], summary="获取个人资料与权限")
async def get_profile(db: DbSession, user: CurrentUser):
    codes = await _permission_codes(db, user)
    permissions = (
        await db.execute(select(Permission).where(Permission.code.in_(codes)))
    ).scalars().all() if codes else []

    return ApiResponse.ok(
        {
            "user": _build_user_out(user).model_dump(),
            "permissions": [p.code for p in permissions],
            "menus": [
                {
                    "code": p.code,
                    "name": p.name,
                    "route_path": p.route_path,
                    "icon": p.icon,
                    "data_scope": p.data_scope,
                }
                for p in permissions
                if p.perm_type == "menu" and p.visible
            ],
            "role": {
                "code": user.role.code,
                "name": user.role.name,
                "data_scope": user.role.data_scope,
            }
            if user.role
            else None,
        }
    )


@router.put("/profile", response_model=ApiResponse[UserOut], summary="修改个人资料")
async def update_profile(payload: ProfileUpdate, db: DbSession, user: CurrentUser):
    if payload.real_name is not None:
        user.real_name = payload.real_name
    if payload.phone is not None:
        user.phone = payload.phone
    if payload.email is not None:
        user.email = payload.email
    if payload.avatar is not None:
        user.avatar = payload.avatar
    await db.commit()
    await db.refresh(user)
    await audit_service.log_operation(
        db,
        module="个人中心",
        action="修改资料",
        user=user,
        target_type="user",
        target_id=user.id,
        description="用户修改个人资料",
    )
    return ApiResponse.ok(_build_user_out(user))


@router.post("/change-password", response_model=ApiResponse[dict], summary="修改密码")
async def change_password(
    payload: ChangePasswordRequest, db: DbSession, user: CurrentUser
):
    if not verify_password(payload.old_password, user.hashed_password):
        raise BizError("原密码不正确")
    if payload.old_password == payload.new_password:
        raise BizError("新密码不能与原密码相同")
    user.hashed_password = hash_password(payload.new_password)
    await db.commit()
    await audit_service.log_operation(
        db,
        module="个人中心",
        action="修改密码",
        user=user,
        target_type="user",
        target_id=user.id,
        description=f"修改时间：{datetime.now():%Y-%m-%d %H:%M:%S}",
    )
    return ApiResponse.ok({"changed": True})


@router.post("/logout", response_model=ApiResponse[dict], summary="退出登录")
async def logout(db: DbSession, user: CurrentUser):
    await audit_service.log_operation(
        db, module="认证", action="退出登录", user=user, description="用户主动退出"
    )
    return ApiResponse.ok({"logout": True})
