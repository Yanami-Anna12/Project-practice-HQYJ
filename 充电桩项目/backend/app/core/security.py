"""认证与密码安全。

密码哈希直接使用 bcrypt 库，不引入 passlib：
passlib 1.7.x 会读取 `bcrypt.__about__`，在 bcrypt 4.1+ 上会抛
AttributeError/告警；而 bcrypt 5.x 的 API 本身已经足够简洁，
直连可以少一层依赖，也便于与同环境下的其他项目共用。

JWT 使用 python-jose（HS256）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
from jose import JWTError, jwt

from app.core.config import settings

# bcrypt 只处理前 72 字节，超长密码先按字节截断，避免底层抛错
_BCRYPT_MAX_BYTES = 72


def _prepare(password: str) -> bytes:
    """把明文密码转成 bcrypt 可接受的字节串（≤72 字节）。"""
    raw = password.encode("utf-8")
    if len(raw) <= _BCRYPT_MAX_BYTES:
        return raw
    # 按字节截断后可能切坏多字节字符，用 ignore 丢弃残缺字节
    return raw[:_BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    """生成 bcrypt 哈希（返回 utf-8 字符串，便于入库）。"""
    return bcrypt.hashpw(_prepare(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """校验密码；哈希格式非法时返回 False 而不是抛异常。"""
    if not plain or not hashed:
        return False
    try:
        return bcrypt.checkpw(_prepare(plain), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(
    subject: str,
    extra: dict[str, Any] | None = None,
    expires_minutes: int | None = None,
) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload: dict[str, Any] = {"sub": subject, "exp": expire, "type": "access"}
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError:
        return None
