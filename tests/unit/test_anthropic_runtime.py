from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import anthropic
import httpx
import pytest

from agentlab.adapters.runtime.anthropic import AnthropicChat, convert_messages
from agentlab.adapters.runtime.raw import RawRuntime
from agentlab.bootstrap import build_services
from agentlab.core.config import load_config
from agentlab.core.llm.retry import NonRetryable
from agentlab.settings import Settings
from tests.conftest import CONFIG_DIR


def test_signed_thinking_and_parallel_tool_results_are_preserved() -> None:
    blocks = [
        {"type": "thinking", "thinking": "", "signature": "signature"},
        {"type": "tool_use", "id": "a", "name": "read", "input": {}},
    ]
    result = convert_messages(
        [
            {"role": "user", "content": "Check files"},
            {"role": "assistant", "content": None, "_anthropic_content": blocks},
            {"role": "tool", "tool_call_id": "a", "content": "one"},
            {"role": "tool", "tool_call_id": "b", "content": "two"},
        ]
    )
    assert result[1]["content"] == blocks
    assert result[2]["role"] == "user"
    assert [b["tool_use_id"] for b in result[2]["content"]] == ["a", "b"]


async def test_opus_request_and_tool_response_normalization() -> None:
    blocks = [
        {"type": "thinking", "thinking": "", "signature": "s"},
        {"type": "tool_use", "id": "a", "name": "read", "input": {"path": "calc.py"}},
    ]
    chat = AnthropicChat("https://example.invalid", "test", 1)
    create = AsyncMock(
        return_value=SimpleNamespace(
            content=[SimpleNamespace(model_dump=lambda exclude_none, b=b: b) for b in blocks],
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
            stop_reason="tool_use",
        )
    )
    chat._client.messages.create = create
    result = await chat(
        model="claude-opus-5-5",
        system="Inspect",
        messages=[{"role": "user", "content": "Go"}],
        temperature=0.0,
        schema={},
        tools=[{"function": {"name": "read", "parameters": {"type": "object"}}}],
    )
    assert "temperature" not in create.call_args.kwargs
    assert result.provider_content == blocks
    assert result.tool_calls and json.loads(result.tool_calls[0]["function"]["arguments"]) == {"path": "calc.py"}
    assert (result.tokens_in, result.tokens_out) == (10, 5)
    await chat._client.close()


async def test_authentication_failure_does_not_retry_or_expose_key() -> None:
    chat = AnthropicChat("https://example.invalid", "test", 1)
    response = httpx.Response(401, request=httpx.Request("POST", "https://example.invalid/v1/messages"))
    chat._client.messages.create = AsyncMock(
        side_effect=anthropic.AuthenticationError("secret", response=response, body={})
    )
    with pytest.raises(NonRetryable, match="auth_401_403") as exc:
        await chat(model="claude-opus-5-5", system="S", messages=[], temperature=0, schema={})
    assert "secret" not in str(exc.value)
    await chat._client.close()


async def test_missing_claude_credentials_never_sends_claude_to_gpt_gateway() -> None:
    runtime = RawRuntime(load_config(CONFIG_DIR), "https://example.invalid", "gpt-key")
    with pytest.raises(NonRetryable, match="provider_credentials_missing"):
        await runtime.chat(provider="anthropic", model="claude-opus-5-5")


def test_anthropic_settings_mask_and_reread_credentials(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text("AGENTLAB_ANTHROPIC_BASE_URL=https://example.invalid\nAGENTLAB_ANTHROPIC_API_KEY=secret-first\n")
    svc = build_services(
        Settings(config_dir=CONFIG_DIR, env_file=env, store_backend="memory", data_dir=tmp_path / "data")
    )
    setting = next(v for v in svc.setting_views() if v.key == "AGENTLAB_ANTHROPIC_API_KEY")
    assert setting.secret and setting.is_set and "secret-first" not in setting.display
    assert "secret-first" in svc.workspace_secrets()
    env.write_text("AGENTLAB_ANTHROPIC_BASE_URL=https://example.invalid\nAGENTLAB_ANTHROPIC_API_KEY=secret-second\n")
    assert svc.anthropic_gateway()[1] == "secret-second"
