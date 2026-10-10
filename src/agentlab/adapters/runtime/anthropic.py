from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import anthropic

from agentlab.core.llm.retry import NonRetryable, Retryable
from agentlab.core.llm.structured import Completion


def convert_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep signed thinking intact and group parallel tool results into a user turn."""
    result: list[dict[str, Any]] = []
    for message in messages:
        role = message["role"]
        if role == "tool":
            role = "user"
            content = [{"type": "tool_result", "tool_use_id": message["tool_call_id"], "content": message["content"]}]
        elif message.get("_anthropic_content"):
            content = message["_anthropic_content"]
        else:
            content = [{"type": "text", "text": message["content"]}] if message.get("content") else []
            for call in message.get("tool_calls", []):
                content.append(
                    {
                        "type": "tool_use",
                        "id": call["id"],
                        "name": call["function"]["name"],
                        "input": json.loads(call["function"]["arguments"]),
                    }
                )
        if result and result[-1]["role"] == role:
            result[-1]["content"].extend(content)
        else:
            result.append({"role": role, "content": content})
    return result


class AnthropicChat:
    def __init__(self, base_url: str, api_key: str, timeout_s: float) -> None:
        # The SDK adds /v1/messages itself; .env may use the familiar /v1/ base.
        base_url = base_url.rstrip("/").removesuffix("/v1")
        self._client = anthropic.AsyncAnthropic(base_url=base_url, api_key=api_key, timeout=timeout_s, max_retries=0)

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
        # Opus 5.5 rejects non-default sampling parameters. Thinking is always on.
        request: dict[str, Any] = {
            "model": model,
            "max_tokens": max_output_tokens,
            "system": f"{system}\n\nRespond with JSON matching:\n{json.dumps(schema, ensure_ascii=False)}",
            "messages": convert_messages(messages),
        }
        if tools:
            request["tools"] = [
                {
                    "name": t["function"]["name"],
                    "description": t["function"].get("description", ""),
                    "input_schema": t["function"]["parameters"],
                }
                for t in tools
            ]
        try:
            if on_delta:
                text = ""
                async with self._client.messages.stream(**request) as stream:
                    async for part in stream.text_stream:
                        text += part
                        on_delta(text)
                    response = await stream.get_final_message()
            else:
                response = await self._client.messages.create(**request)
        except anthropic.APIError as exc:
            status = getattr(exc, "status_code", None)
            if isinstance(exc, anthropic.APITimeoutError):
                raise Retryable("read_timeout") from exc
            if isinstance(exc, anthropic.APIConnectionError):
                raise Retryable("connection_error") from exc
            if status == 429:
                raise Retryable("rate_limit_429") from exc
            if status and status >= 500:
                raise Retryable("server_error_5xx") from exc
            raise NonRetryable("auth_401_403" if status in {401, 403} else type(exc).__name__) from exc
        content = [block.model_dump(exclude_none=True) for block in response.content]
        text = "".join(block["text"] for block in content if block["type"] == "text")
        calls = [
            {
                "id": b["id"],
                "type": "function",
                "function": {"name": b["name"], "arguments": json.dumps(b["input"], ensure_ascii=False)},
            }
            for b in content
            if b["type"] == "tool_use"
        ]
        if response.stop_reason in {"max_tokens", "refusal"} or (not text and not calls):
            error = (
                Retryable("empty_response")
                if not text and not calls and response.stop_reason not in {"max_tokens", "refusal"}
                else NonRetryable(
                    "output_truncated" if response.stop_reason == "max_tokens" else "content_policy_refusal"
                )
            )
            error.usage_present = True
            error.tokens_in, error.tokens_out = response.usage.input_tokens, response.usage.output_tokens
            raise error
        return Completion(text, response.usage.input_tokens, response.usage.output_tokens, calls or None, content)
