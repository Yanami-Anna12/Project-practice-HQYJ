"""认证基础设施：密码哈希（bcrypt）与令牌签发解析（JWT / HS256）。

这里刻意只用最基础的两个库，不引入 passlib / python-jose：
  - bcrypt 5.0 直接用即可（passlib 1.7.4 读 bcrypt.__about__ 会报警告）；
  - PyJWT 比 python-jose 更轻，且在 Python 3.12 上无兼容问题。

★ 本模块只负责「证明你是谁」（认证 authentication）。
  「你能做什么」（授权 authorization）在 deps.py + services/rbac.py。
  这一分工是理解权限系统的关键：认证 ≠ 授权。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.config import settings

logger = logging.getLogger(__name__)

# bcrypt 算法对输入有 72 字节硬上限（超过会被静默截断，造成「不同密码同哈希」的隐患）。
# bcrypt 5.0 对超长输入直接抛 ValueError，这里显式截断并统一成 bytes。
BCRYPT_MAX_BYTES = 72


def _to_bcrypt_bytes(password: str) -> bytes:
    """把明文密码转成 bcrypt 可接受的 bytes（按 72 字节安全截断）。"""
    raw = password.encode("utf-8")
    return raw[:BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    """生成 bcrypt 哈希（自带随机 salt，同一密码两次哈希结果不同）。"""
    return bcrypt.hashpw(_to_bcrypt_bytes(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """校验明文密码与哈希是否匹配。

    bcrypt.checkpw 内部是恒定时间比较，不用自己实现常数时间对比。
    任何异常（哈希格式损坏等）都视为校验失败，绝不向上抛——
    否则一个坏哈希会让登录接口 500，反而成了信息泄露点。
    """
    try:
        return bcrypt.checkpw(_to_bcrypt_bytes(password), password_hash.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        logger.warning("密码校验异常，按失败处理：%s", exc)
        return False


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------
def create_access_token(user_id: int, username: str, expires_minutes: int | None = None) -> str:
    """签发 JWT。

    payload 里只放「身份标识」，绝不放权限集合：
      ★ 权限每次请求实时查库（R4），放进 Token 就等于做了会话级缓存，
        会导致「停用权限点后要等 Token 过期才生效」，直接违反需求。
    """
    now = datetime.now(timezone.utc)
    minutes = expires_minutes if expires_minutes is not None else settings.JWT_EXPIRE_MINUTES
    payload = {
        "sub": str(user_id),  # PyJWT 要求 sub 为字符串
        "username": username,  # 仅用于日志排查，不作为鉴权依据
        "iat": now,
        "exp": now + timedelta(minutes=minutes),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """解析并校验 JWT。

    校验项：签名、过期时间（exp）、算法（显式指定，防止 alg=none 降级攻击）。
    任何失败都抛 jwt.InvalidTokenError 的子类，由 deps.py 统一转成 401。
    """
    return jwt.decode(
        token,
        settings.JWT_SECRET,
        algorithms=[settings.JWT_ALGORITHM],  # 必须显式指定，否则存在算法混淆风险
        options={"require": ["exp", "sub"]},
    )
