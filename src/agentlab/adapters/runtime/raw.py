from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any, TypeVar

import openai
from pydantic import BaseModel

from agentlab.core.config import AppConfig
from agentlab.core.llm.retry import NonRetryable, ParallelFailure, Retryable
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
        self,
        *,
        model: str,
        system: str,
        messages: list[dict[str, Any]],
        temperature: float,
        schema: dict[str, object],
        max_output_tokens: int = 16384,
        output_token_parameter: str = "max_tokens",
        tools: list[dict[str, Any]] | None = None,
        on_delta: Callable[[str], None] | None = None,
    ) -> Completion:
        system_msg = {
            "role": "system",
            "content": f"{system}\n\nRespond with JSON matching:\n{json.dumps(schema, ensure_ascii=False)}",
        }
        payload: list[Any] = [system_msg, *messages]
        token_options: dict[str, Any] = {output_token_parameter: max_output_tokens}
        if on_delta:
            return await self._stream(model, temperature, payload, token_options, tools, on_delta)
        try:
            resp = await self._client.chat.completions.create(  # type: ignore[call-overload]
                model=model,
                temperature=temperature,
                messages=payload,
                response_format={"type": "json_object"},
                **token_options,
                **({"tools": tools} if tools else {}),
            )
        except openai.OpenAIError as e:
            raise classify(e) from e
        message = resp.choices[0].message if resp.choices else None
        text = message.content if message else None
        usage = resp.usage
        refusal = (message and message.refusal) or (resp.choices and resp.choices[0].finish_reason == "content_filter")
        truncated = bool(resp.choices and resp.choices[0].finish_reason == "length")
        if refusal or truncated or (not text and not (message and message.tool_calls)):
            error = (
                NonRetryable("content_policy_refusal")
                if refusal
                else NonRetryable("output_truncated")
                if truncated
                else Retryable("empty_response")
            )
            error.usage_present = usage is not None
            error.tokens_in = usage.prompt_tokens if usage else 0
            error.tokens_out = usage.completion_tokens if usage else 0
            raise error
        return Completion(
            text or "",
            usage.prompt_tokens if usage else 0,
            usage.completion_tokens if usage else 0,
            [t.model_dump(exclude_none=True) for t in message.tool_calls] if message and message.tool_calls else None,
            usage_present=usage is not None,
        )

    async def _stream(
        self,
        model: str,
        temperature: float,
        payload: list[Any],
        options: dict[str, Any],
        tools: list[dict[str, Any]] | None,
        on_delta: Callable[[str], None],
    ) -> Completion:
        text = ""
        calls: dict[int, dict[str, Any]] = {}
        tokens_in = tokens_out = 0
        usage_present = False
        reason = None
        refusal = False
        try:
            stream = await self._client.chat.completions.create(  # type: ignore[call-overload]
                model=model,
                temperature=temperature,
                messages=payload,
                response_format={"type": "json_object"},
                stream=True,
                stream_options={"include_usage": True},
                **options,
                **({"tools": tools} if tools else {}),
            )
            async with stream:
                async for chunk in stream:
                    if chunk.usage:
                        usage_present = True
                        tokens_in, tokens_out = chunk.usage.prompt_tokens, chunk.usage.completion_tokens
                    if not chunk.choices:
                        continue
                    choice = chunk.choices[0]
                    reason = choice.finish_reason or reason
                    refusal |= bool(choice.delta.refusal)
                    for tc in choice.delta.tool_calls or []:
                        call = calls.setdefault(
                            tc.index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
                        )
                        call["id"] += tc.id or ""
                        if tc.function:
                            call["function"]["name"] += tc.function.name or ""
                            call["function"]["arguments"] += tc.function.arguments or ""
                    if choice.delta.content:
                        text += choice.delta.content
                        if not calls:
                            on_delta(text)
        except openai.OpenAIError as exc:
            error = classify(exc)
            error.usage_present = usage_present  # type: ignore[attr-defined]
            error.tokens_in, error.tokens_out = tokens_in, tokens_out  # type: ignore[attr-defined]
            raise error from exc
        if refusal or reason == "content_filter" or reason == "length" or (not text and not calls):
            error = (
                NonRetryable("output_truncated")
                if reason == "length"
                else NonRetryable("content_policy_refusal")
                if refusal or reason == "content_filter"
                else Retryable("empty_response")
            )
            error.usage_present = usage_present
            error.tokens_in, error.tokens_out = tokens_in, tokens_out
            raise error
        return Completion(text, tokens_in, tokens_out, list(calls.values()) or None, usage_present=usage_present)


class OpenAICompatEmbedder:
    BATCH = 64

    def __init__(
        self,
        creds: Callable[[], tuple[str | None, str | None]],
        model: str,
        dimensions: int | None = None,
        version: int = 1,
    ) -> None:
        self._creds = creds
        self.model = model
        self.dimensions = dimensions
        self.version = version

    def available(self) -> bool:
        url, key = self._creds()
        return bool(url and key)

    async def __call__(self, texts: list[str]) -> list[list[float]]:
        url, key = self._creds()
        client = openai.AsyncOpenAI(base_url=url, api_key=key, max_retries=0, timeout=30)
        out: list[list[float]] = []
        try:
            for i in range(0, len(texts), self.BATCH):
                resp = await client.embeddings.create(model=self.model, input=texts[i : i + self.BATCH])
                out += [d.embedding for d in resp.data]
        except openai.OpenAIError as e:
            raise classify(e) from e
        finally:
            await client.close()
        return out


class RawRuntime:
    def __init__(
        self, cfg: AppConfig, base_url: str, api_key: str, anthropic_creds: tuple[str | None, str | None] = (None, None)
    ) -> None:
        chats: dict[str, Any] = {"openai": OpenAICompatChat(base_url, api_key, cfg.retry.llm_call.timeout_s)}
        if all(anthropic_creds):
            from agentlab.adapters.runtime.anthropic import AnthropicChat

            url, key = anthropic_creds
            assert url and key
            chats["anthropic"] = AnthropicChat(url, key, cfg.retry.llm_call.timeout_s)

        async def chat(*, provider: str = "openai", **kwargs: Any) -> Completion:
            if provider not in chats:
                raise NonRetryable("provider_credentials_missing")
            return await chats[provider](**kwargs)  # type: ignore[no-any-return]

        self.chat = chat
        self._caller = StructuredCaller(cfg, chat)

    async def run_agent(self, role: str, inp: AgentInput, output_type: type[T], ctx: RunContext) -> AgentResult[T]:
        return await self._caller.call(role, inp, output_type, ctx)

    async def run_parallel(
        self, inputs: dict[str, AgentInput], output_type: type[T], ctx: RunContext
    ) -> list[AgentResult[T]]:
        outcomes = await asyncio.gather(
            *(self.run_agent(r, i, output_type, ctx) for r, i in inputs.items()), return_exceptions=True
        )
        results = [result for result in outcomes if not isinstance(result, BaseException)]
        for outcome in outcomes:
            if isinstance(outcome, asyncio.CancelledError):
                raise ParallelFailure(NonRetryable("agent_cancelled"), results)
            if isinstance(outcome, BaseException) and not isinstance(outcome, Exception):
                raise outcome
        errors = [result for result in outcomes if isinstance(result, Exception)]
        if errors:
            raise ParallelFailure(errors[0], results)
        return results
