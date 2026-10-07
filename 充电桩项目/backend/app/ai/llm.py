"""LLM 客户端 —— 统一封装 DeepSeek / OpenAI 兼容接口。

PDF 4.1 原则 2「LLM 只做解释和辅助」：
- 所有硬约束（工单类型、巡检频率、子任务计算、故障等级、权限、报告周期）
  由 app/services 中的确定性代码保证；
- LLM 仅用于报告生成、根因分析、运维建议、自然语言摘要、知识库问答；
- 无 API Key 或调用失败时自动降级为模板化输出（degraded=True），
  保证主流程不被阻塞（PDF 11 关键技术风险：LLM 成本高、延迟大 → 降级）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.core.config import settings

logger = logging.getLogger("app.ai.llm")

try:  # openai 为可选依赖，缺失时仍可使用降级模式
    from openai import AsyncOpenAI
except Exception:  # pragma: no cover
    AsyncOpenAI = None  # type: ignore[assignment]


@dataclass
class LLMResult:
    """一次 LLM 调用的结果。"""

    text: str = ""
    used_llm: bool = False
    degraded: bool = True
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    error: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)


class LLMClient:
    """异步 LLM 客户端。"""

    def __init__(self) -> None:
        self._client: Any = None
        self._init_error: str | None = None

    @property
    def available(self) -> bool:
        return bool(settings.LLM_API_KEY) and AsyncOpenAI is not None and settings.AI_ENABLED

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        if not self.available:
            return None
        try:
            self._client = AsyncOpenAI(
                api_key=settings.LLM_API_KEY,
                base_url=settings.LLM_BASE_URL,
                timeout=settings.LLM_TIMEOUT,
                max_retries=settings.LLM_MAX_RETRIES,
            )
        except Exception as exc:  # pragma: no cover
            self._init_error = str(exc)
            logger.warning("LLM 客户端初始化失败：%s", exc)
            return None
        return self._client

    async def health(self) -> dict:
        """探活：用于 /api/v1/ai/health 与前端 AI 状态展示。"""
        info = {
            "enabled": settings.AI_ENABLED,
            "api_key_configured": bool(settings.LLM_API_KEY),
            "provider": settings.LLM_PROVIDER,
            "base_url": settings.LLM_BASE_URL,
            "model": settings.LLM_MODEL,
            "sdk_ready": AsyncOpenAI is not None,
            "fallback_enabled": settings.LLM_FALLBACK_ENABLED,
            "init_error": self._init_error,
        }
        if not self.available:
            info["status"] = "fallback"
            info["detail"] = "未配置 LLM_API_KEY，将使用确定性规则引擎降级输出"
            return info
        result = await self.chat("你是连通性探针，请只回复 pong。", "ping", max_tokens=8, temperature=0)
        info["status"] = "ok" if result.used_llm else "error"
        info["detail"] = result.error or (result.text or "")[:40]
        return info

    async def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float | None = None,
        max_tokens: int = 2048,
        json_mode: bool = False,
    ) -> LLMResult:
        """执行一次对话补全；失败时返回 degraded 结果而不是抛异常。"""
        if not self.available:
            return LLMResult(
                used_llm=False,
                degraded=True,
                model=settings.LLM_MODEL,
                error="未配置 LLM_API_KEY 或 AI 开关已关闭",
            )

        client = self._get_client()
        if client is None:
            return LLMResult(
                used_llm=False,
                degraded=True,
                model=settings.LLM_MODEL,
                error=self._init_error or "LLM 客户端不可用",
            )

        kwargs: dict[str, Any] = {
            "model": settings.LLM_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": settings.LLM_TEMPERATURE if temperature is None else temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            resp = await client.chat.completions.create(**kwargs)
            choice = resp.choices[0]
            text = (choice.message.content or "").strip()
            usage = getattr(resp, "usage", None)
            return LLMResult(
                text=text,
                used_llm=bool(text),
                degraded=not bool(text),
                model=settings.LLM_MODEL,
                prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
                error=None if text else "LLM 返回空内容",
            )
        except Exception as exc:
            logger.warning("LLM 调用失败，降级到规则引擎：%s", exc)
            return LLMResult(
                used_llm=False,
                degraded=True,
                model=settings.LLM_MODEL,
                error=f"{type(exc).__name__}: {exc}",
            )


llm_client = LLMClient()
