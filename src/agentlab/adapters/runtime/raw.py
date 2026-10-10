from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any, TypeVar

import openai
from pydantic import BaseModel

from agentlab.core.config import AppConfig
from agentlab.core.llm.retry import NonRetryable, Retryable
from agentlab.core.llm.structured import Completion, StructuredCaller
from agentlab.core.ports import RunContext
from agentlab.core.schemas import AgentInput, AgentResult

T = TypeVar("T", bound=BaseModel)


def classify(e: openai.OpenAIError) -> Exception:
    match e:
        case openai.RateLimitError():
            return Retryable("rate_limit_429", str(e))
        case openai.APITimeoutError():
            return Retryable("read_timeout", str(e))
        case openai.APIConnectionError():
            return Retryable("connection_error", str(e))
        case openai.InternalServerError():
            return Retryable("server_error_5xx", str(e))
        case openai.AuthenticationError() | openai.PermissionDeniedError():
            return NonRetryable("auth_401_403", str(e))
        case openai.BadRequestError() if "context" in str(e).lower():
            return NonRetryable("context_length_exceeded", str(e))
        case _:
            return NonRetryable(type(e).__name__, str(e))


class OpenAICompatChat:
    def __init__(self, base_url: str, api_key: str, timeout_s: float) -> None:
        self._client = openai.AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=timeout_s, max_retries=0)

    async def __call__(
        self, *, model: str, system: str, messages: list[dict[str, str]], temperature: float,
        schema: dict[str, object],
    ) -> Completion:
        system_msg = {"role": "system", "content": f"{system}\n\nRespond with JSON matching:\n{schema}"}
        payload: list[Any] = [system_msg, *messages]
        try:
            resp = await self._client.chat.completions.create(
                model=model, temperature=temperature, messages=payload, response_format={"type": "json_object"},
            )
        except openai.OpenAIError as e:
            raise classify(e) from e
        text = resp.choices[0].message.content if resp.choices else None
        if not text:
            raise Retryable("empty_response")
        usage = resp.usage
        return Completion(text, usage.prompt_tokens if usage else 0, usage.completion_tokens if usage else 0)


class OpenAICompatEmbedder:
    BATCH = 64

    def __init__(self, creds: Callable[[], tuple[str | None, str | None]], model: str) -> None:
        self._creds = creds
        self.model = model

    def available(self) -> bool:
        url, key = self._creds()
        return bool(url and key)

    async def __call__(self, texts: list[str]) -> list[list[float]]:
        url, key = self._creds()
        client = openai.AsyncOpenAI(base_url=url, api_key=key, max_retries=2)
        out: list[list[float]] = []
        try:
            for i in range(0, len(texts), self.BATCH):
                resp = await client.embeddings.create(model=self.model, input=texts[i:i + self.BATCH])
                out += [d.embedding for d in resp.data]
        except openai.OpenAIError as e:
            raise classify(e) from e
        return out


class RawRuntime:
    def __init__(self, cfg: AppConfig, base_url: str, api_key: str) -> None:
        self._caller = StructuredCaller(cfg, OpenAICompatChat(base_url, api_key, cfg.retry.llm_call.timeout_s))

    async def run_agent(
        self, role: str, inp: AgentInput, output_type: type[T], ctx: RunContext
    ) -> AgentResult[T]:
        return await self._caller.call(role, inp, output_type, ctx)

    async def run_parallel(
        self, inputs: dict[str, AgentInput], output_type: type[T], ctx: RunContext
    ) -> list[AgentResult[T]]:
        return list(await asyncio.gather(*(self.run_agent(r, i, output_type, ctx) for r, i in inputs.items())))
