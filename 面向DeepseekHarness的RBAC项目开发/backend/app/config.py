"""应用配置。

所有可变参数集中在 .env，代码里不出现硬编码的连接串或密钥。
使用 pydantic-settings，读取 backend/.env。
"""

from functools import lru_cache
from pathlib import Path

from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url

# backend/ 目录（本文件位于 backend/app/config.py）
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- 应用 ----
    APP_NAME: str = "RBAC 权限管理系统"
    DEBUG: bool = True

    # ---- 数据库 ----
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 3306
    DB_USER: str = "root"
    DB_PASSWORD: str = ""
    DB_NAME: str = "rbac_db"

    # ---- JWT ----
    JWT_SECRET: str = "dev-secret"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 120

    # ---- CORS ----
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    # ---- 初始管理员密码（仅 seed.py 首次建号时使用）----
    ADMIN_INIT_PASSWORD: str = "admin123"
    DEMO_PASSWORD: str = "123456"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cors_origin_list(self) -> list[str]:
        """把逗号分隔的 CORS 配置切成列表。"""
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        """SQLAlchemy 连接串（带库名）。

        ★ 这里有一个 SQLAlchemy 2.0 的坑，务必注意：
        URL.__str__() 出于「防止密码写进日志」的考虑，会把密码渲染成 `***`。
        所以绝不能用 str(URL.create(...)) 来生成连接串 —— 那样传给 create_engine
        的密码会变成字面量 "***"，表现为 MySQL 返回
            (1045, "Access denied for user 'root'@'localhost' (using password: YES)")
        必须用 render_as_string(hide_password=False)。

        同理，密码里含 @ : / ? # 等字符时，手写 f-string 拼接也会出错，
        统一交给 URL.create 做百分号编码才是安全的。

        另：本文件用 URL.create 而不是 make_url(f"...")，是为了完全绕开字符串拼接。
        """
        return URL.create(
            drivername="mysql+pymysql",
            username=self.DB_USER,
            password=self.DB_PASSWORD,
            host=self.DB_HOST,
            port=self.DB_PORT,
            database=self.DB_NAME,
            query={"charset": "utf8mb4"},
        ).render_as_string(hide_password=False)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def server_url(self) -> str:
        """不带库名的连接串，用于 CREATE DATABASE。同样不能用 str()。"""
        return URL.create(
            drivername="mysql+pymysql",
            username=self.DB_USER,
            password=self.DB_PASSWORD,
            host=self.DB_HOST,
            port=self.DB_PORT,
            query={"charset": "utf8mb4"},
        ).render_as_string(hide_password=False)

    def url_safe(self) -> str:
        """脱敏后的连接串，只用于打印日志/自检输出。"""
        return make_url(self.database_url).render_as_string(hide_password=True)


@lru_cache
def get_settings() -> Settings:
    """带缓存的配置单例。"""
    return Settings()


settings = get_settings()
