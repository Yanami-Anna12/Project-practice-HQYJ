"""应用配置中心。

配置优先级：环境变量 > .env 文件 > 默认值。
生产环境按 PDF 9.3「配置管理」要求，敏感信息走环境变量 / Secret，
业务规则（工单规则、巡检频率、报告周期、AI 开关）走数据库并支持热更新。
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
EXPORT_DIR = DATA_DIR / "exports"
EXPORT_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR = DATA_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
REPORT_DIR = DATA_DIR / "reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------------- 应用 ----------------
    APP_NAME: str = "充电桩运维管理 AI Agent 平台"
    APP_VERSION: str = "1.0.0"
    API_PREFIX: str = "/api/v1"
    ENV: str = "dev"  # dev / test / staging / prod（PDF 9.2 环境划分）
    DEBUG: bool = True
    HOST: str = "127.0.0.1"
    PORT: int = 8000

    # ---------------- 数据库 ----------------
    # 默认 SQLite 开箱即跑；生产改为
    # postgresql+psycopg://user:pass@host:5432/dbname
    DATABASE_URL: str = f"sqlite+aiosqlite:///{(DATA_DIR / 'maintenance.db').as_posix()}"
    DB_ECHO: bool = False
    # SQLite 写锁等待时间（秒）；并发写入时排队等待而非直接失败
    SQLITE_BUSY_TIMEOUT: float = 30.0

    # ---------------- 认证 ----------------
    SECRET_KEY: str = "change-me-in-production-charging-pile-ops-agent"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 12

    # ---------------- LLM（PDF 2.2：DeepSeek-V4 API / Qwen2.5-72B-Instruct）----------------
    LLM_PROVIDER: str = "deepseek"
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://api.deepseek.com/v1"
    LLM_MODEL: str = "deepseek-chat"
    LLM_TEMPERATURE: float = 0.2
    LLM_TIMEOUT: int = 120
    LLM_MAX_RETRIES: int = 2
    # 无 Key 或调用失败时降级为确定性规则引擎模板（PDF 4.1：硬约束代码化，LLM 只做解释）
    LLM_FALLBACK_ENABLED: bool = True
    AI_ENABLED: bool = True

    # ---------------- 求解器（PDF 4.1 原则 6 混合求解）----------------
    # 启发式快速出解始终可用；CP-SAT 在此基础上做精确优化（工作量均衡 + 日期紧凑）。
    # 若本机 OR-Tools 不可用或需要极致启动速度，设为 false 即退化为纯启发式。
    CPSAT_ENABLED: bool = True
    CPSAT_MAX_SECONDS: float = 5.0

    # ---------------- 可观测性（PDF 8.1 LangSmith / Langfuse）----------------
    LANGCHAIN_TRACING_V2: bool = False
    LANGCHAIN_API_KEY: str = ""
    LANGCHAIN_PROJECT: str = "maintenance-agent"

    # ---------------- 缓存 / 队列（PDF 2.2 Redis / Celery / RabbitMQ）----------------
    REDIS_URL: str = "redis://127.0.0.1:6379/0"
    RABBITMQ_URL: str = "amqp://guest:guest@127.0.0.1:5672/"
    CELERY_BROKER_URL: str = "redis://127.0.0.1:6379/1"

    # ---------------- 向量库（PDF 2.2 Milvus / Infinity）----------------
    VECTOR_STORE: str = "local"  # local(内置TF-IDF) / milvus / infinity
    MILVUS_URI: str = "http://127.0.0.1:19530"
    EMBEDDING_MODEL: str = "text-embedding-v4"
    KB_TOP_K: int = 5

    # ---------------- 对象存储（PDF 2.2 MinIO / OSS）----------------
    STORAGE_BACKEND: str = "local"  # local / minio / oss
    MINIO_ENDPOINT: str = "127.0.0.1:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET: str = "maintenance"

    # ---------------- 微信 / 消息推送（PDF 7.3）----------------
    WECHAT_APPID: str = ""
    WECHAT_SECRET: str = ""
    FEISHU_WEBHOOK: str = ""
    SMTP_HOST: str = ""
    SMTP_PORT: int = 465
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""

    # ---------------- 外部平台（PDF 7.1 / 7.2）----------------
    STORAGE_PLATFORM_API: str = ""  # 储能运营平台 REST API
    CHARGING_PLATFORM_API: str = ""  # 充电桩平台接口
    POWER_MARKET_API: str = ""  # 电力市场电价接口
    WEATHER_API: str = ""  # 天气 API
    MAP_API_KEY: str = ""  # 高德 / 百度地图
    OUTBOUND_TIMEOUT: int = 10

    # ---------------- 业务规则默认值（PDF 3.4 / 3.12）----------------
    REPORT_DAILY_CRON_HOUR: int = 2  # 日报告 T+1 凌晨 2 点
    REPORT_WEEKLY_CRON_HOUR: int = 3  # 周报告每周一凌晨 3 点
    REPORT_MONTHLY_CRON_HOUR: int = 4  # 月报告每月 1 日凌晨 4 点
    WORK_ORDER_DUE_SOON_HOURS: int = 24  # 快到期判定
    MAX_REPLAN_COUNT: int = 3  # PDF 4.9 replan_count 限制，避免无限循环
    DEFAULT_PAGE_SIZE: int = 20
    MAX_PAGE_SIZE: int = 200

    # ---------------- CORS ----------------
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")

    @property
    def llm_ready(self) -> bool:
        return bool(self.LLM_API_KEY) and self.AI_ENABLED


def _machine_scope_env(name: str) -> str:
    """读取 Windows 机器级环境变量。

    DSH 桌面端注入的 API Key 位于机器级环境变量，当前进程不一定可见，
    这里做一次兜底读取，避免用户手工复制密钥。
    """
    if os.name != "nt":
        return ""
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
        )
        try:
            value, _ = winreg.QueryValueEx(key, name)
            return str(value or "")
        finally:
            winreg.CloseKey(key)
    except Exception:
        return ""


def _resolve_llm_key(settings: Settings) -> None:
    if settings.LLM_API_KEY:
        return
    for candidate in ("DEEPSEEK_API_KEY", "LLM_API_KEY", "OPENAI_API_KEY"):
        value = os.environ.get(candidate) or _machine_scope_env(candidate)
        if value:
            settings.LLM_API_KEY = value
            if candidate == "OPENAI_API_KEY":
                settings.LLM_BASE_URL = os.environ.get(
                    "OPENAI_BASE_URL", "https://api.openai.com/v1"
                )
                settings.LLM_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
            return


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    _resolve_llm_key(settings)
    return settings


settings = get_settings()
