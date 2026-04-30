"""LLM provider 추상화.

Anthropic / OpenAI / Google Gemini 어느 쪽이든 같은 시그니처로 호출한다.
- 입력: system 텍스트 + user 텍스트 + 출력 JSON Schema
- 출력: 모델이 생성한 JSON(또는 JSON-블록 포함) 텍스트

provider별 SDK는 lazy import 한다 — 실제 사용하는 provider 패키지만 있어도 동작.
시스템 프롬프트는 가능한 경우 캐시(Anthropic의 ephemeral cache_control 등)를 활성화한다.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod

from mimmy.config import get_settings


class LLMClient(ABC):
    """provider 중립 호출 인터페이스."""

    model: str

    @abstractmethod
    async def complete_json(self, *, system: str, user: str, schema: dict) -> str:
        """JSON 오브젝트 텍스트를 반환한다 (앞뒤 텍스트가 섞여있을 수 있음)."""


# ─── Anthropic ───


class AnthropicClient(LLMClient):
    def __init__(self, *, api_key: str, model: str) -> None:
        from anthropic import AsyncAnthropic  # lazy

        self._client = AsyncAnthropic(api_key=api_key)
        self.model = model

    async def complete_json(self, *, system: str, user: str, schema: dict) -> str:
        full_system = (
            system
            + "\n\n## 출력 규약\n"
            + "반드시 아래 JSON Schema를 충족하는 JSON 오브젝트 **하나만** 응답한다. "
            + "자연어 설명을 앞뒤에 붙이지 마라.\n\n"
            + json.dumps(schema, ensure_ascii=False)
        )
        resp = await self._client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=[
                {
                    "type": "text",
                    "text": full_system,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user}],
        )
        return "".join(
            block.text for block in resp.content if getattr(block, "type", None) == "text"
        )


# ─── OpenAI ───


class OpenAIClient(LLMClient):
    def __init__(self, *, api_key: str, model: str) -> None:
        from openai import AsyncOpenAI  # lazy

        self._client = AsyncOpenAI(api_key=api_key)
        self.model = model

    async def complete_json(self, *, system: str, user: str, schema: dict) -> str:
        full_system = (
            system
            + "\n\n## 출력 규약\n"
            + "반드시 아래 JSON Schema를 충족하는 JSON 오브젝트 **하나만** 응답한다. "
            + "자연어 설명을 앞뒤에 붙이지 마라.\n\n"
            + json.dumps(schema, ensure_ascii=False)
        )
        # response_format=json_object 강제: schema를 메시지에 그대로 넣고 형식만 JSON 강요.
        resp = await self._client.chat.completions.create(
            model=self.model,
            max_tokens=2048,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": full_system},
                {"role": "user", "content": user},
            ],
        )
        choice = resp.choices[0]
        return choice.message.content or ""


# ─── Google Gemini ───


class GeminiClient(LLMClient):
    def __init__(self, *, api_key: str, model: str) -> None:
        from google import genai  # lazy — google-genai 패키지

        self._genai = genai
        self._client = genai.Client(api_key=api_key)
        self.model = model

    async def complete_json(self, *, system: str, user: str, schema: dict) -> str:
        full_system = (
            system
            + "\n\n## 출력 규약\n"
            + "반드시 아래 JSON Schema를 충족하는 JSON 오브젝트 **하나만** 응답한다. "
            + "자연어 설명을 앞뒤에 붙이지 마라.\n\n"
            + json.dumps(schema, ensure_ascii=False)
        )
        # google-genai SDK는 동기 generate_content를 비동기 wrapper로 감싸 호출한다.
        # aio 인터페이스가 있으면 그걸 쓴다 (버전마다 노출 위치가 달라 안전 분기).
        config = {
            "response_mime_type": "application/json",
            "system_instruction": full_system,
        }
        aio = getattr(self._client, "aio", None)
        if aio is not None and hasattr(aio, "models"):
            resp = await aio.models.generate_content(
                model=self.model,
                contents=user,
                config=config,
            )
        else:
            import asyncio

            resp = await asyncio.to_thread(
                self._client.models.generate_content,
                model=self.model,
                contents=user,
                config=config,
            )
        return getattr(resp, "text", "") or ""


# ─── Factory ───


def make_llm_client() -> LLMClient:
    """현재 settings 기준으로 활성 provider의 client를 만든다."""
    s = get_settings()
    provider = s.resolved_ai_provider
    model = s.resolved_ai_model
    api_key = s.resolved_ai_api_key
    if provider == "openai":
        return OpenAIClient(api_key=api_key, model=model)
    if provider == "gemini":
        return GeminiClient(api_key=api_key, model=model)
    return AnthropicClient(api_key=api_key, model=model)
