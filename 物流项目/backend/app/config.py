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
    APP_NAME: str = "车辆智能调度 Agent"
    DEBUG: bool = True

    # ---- 数据库 ----
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 3306
    DB_USER: str = "root"
    DB_PASSWORD: str = ""
    DB_NAME: str = "logistics_db"

    # ---- JWT ----
    JWT_SECRET: str = "dev-secret"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 720

    # ---- CORS ----
    CORS_ORIGINS: str = "http://localhost:5175,http://127.0.0.1:5175"

    # ---- 调度求解器 ----
    SOLVER_TIMEOUT_SECONDS: int = 30
    REPLAN_MAX_COUNT: int = 3

    # ---- LLM ----
    DEEPSEEK_API_KEY: str = ""
    LLM_MODEL: str = "deepseek-chat"

    # ---- 初始账号密码（仅 seed 首次建号时使用）----
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

        ★ 两个必须注意的坑：

        1. URL.__str__() 出于「防止密码写进日志」的考虑会把密码渲染成 `***`，
           所以绝不能用 str(URL.create(...))。必须用
           render_as_string(hide_password=False)，否则传给 create_engine 的
           密码会变成字面量 "***"，表现为 MySQL 报 1045 Access denied。

        2. 密码里含 @ : / ? # 等字符时，手写 f-string 拼接会出错，
           统一交给 URL.create 做百分号编码才安全。

        ★ 切换到 PostgreSQL 只需改这里的 drivername（并安装对应驱动）：
           本项目的模型与查询刻意不使用任何 MySQL 方言。
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

    @computed_field  # type: ignore[prop-decorator]
    @property
    def llm_enabled(self) -> bool:
        """是否启用 LLM（方案解释 / 报告）。未配置 API Key 时自动降级。"""
        return bool(self.DEEPSEEK_API_KEY.strip())

    def url_safe(self) -> str:
        """脱敏后的连接串，只用于打印日志/自检输出。"""
        return make_url(self.database_url).render_as_string(hide_password=True)


@lru_cache
def get_settings() -> Settings:
    """带缓存的配置单例。"""
    return Settings()


settings = get_settings()
