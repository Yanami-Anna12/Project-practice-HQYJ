"""密码哈希与 JWT 签发/校验。

为什么不用 passlib：passlib 1.7.4 读取 bcrypt.__about__ 会报错，
直接使用 bcrypt 更干净（与 RBAC 项目一致）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.config import settings

# bcrypt 的算法限制：输入超过 72 字节会被静默截断，所以先截断再哈希，
# 避免「两个长密码哈希相同」这种意外。
_BCRYPT_MAX_BYTES = 72


def hash_password(plain: str) -> str:
    """生成密码哈希。"""
    raw = plain.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(raw, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """校验密码。哈希串损坏时返回 False 而不是抛异常。"""
    if not hashed:
        return False
    try:
        raw = plain.encode("utf-8")[:_BCRYPT_MAX_BYTES]
        return bcrypt.checkpw(raw, hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: int, *, expires_minutes: int | None = None) -> str:
    """签发 JWT。sub 存 userId，exp 由配置决定。"""
    minutes = expires_minutes or settings.JWT_EXPIRE_MINUTES
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> int | None:
    """解析 JWT 并返回 userId；无效或过期返回 None。"""
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
        sub = payload.get("sub")
        return int(sub) if sub is not None else None
    except (jwt.PyJWTError, ValueError, TypeError):
        return None
