"""Acceptance: work is handed between GPT (OpenAI-compatible) and Claude (Anthropic) agents.

Both provider clients are replaced by recording fakes, so these tests run offline while still
exercising the real routing (models.yaml provider → RawRuntime dispatch → StructuredCaller → Driver).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import agentlab.adapters.runtime.anthropic as anthropic_runtime
import agentlab.adapters.runtime.raw as raw_runtime
from agentlab.adapters.runtime.raw import RawRuntime
from agentlab.core.config import AppConfig
from agentlab.core.llm.retry import Retryable
from agentlab.core.llm.structured import Completion
from agentlab.core.schemas import RunStatus
from tests.unit.test_driver import make_driver

CLAUDE = "claude-test-opus"
GPT = "gpt-test-sol"
GPT_CHEAP = "gpt-test-mini"
PLAN_MARK = "PLAN-WRITTEN-BY-CLAUDE"
CODE_MARK = "# edited-by-claude-coder"


def mixed_config(cfg: AppConfig, retries: int = 0) -> AppConfig:
    """Pin a deterministic mixed catalog: Claude builds, GPT root and (most) reviewers."""
    data = cfg.model_dump(mode="json")
    aliases = data["models"]["aliases"]
    aliases["root"].update(model=GPT, provider="openai")
    aliases["strong"].update(model=CLAUDE, provider="anthropic")
    aliases["strong-alt"].update(model=GPT, provider="openai")
    aliases["cheap"].update(model=GPT_CHEAP, provider="openai")
    data["retry"]["llm_call"]["num_retries"] = retries
    return AppConfig.model_validate(data)


class Recorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.fail_titles: set[str] = set()

    def chat(self, provider: str) -> Any:
        async def call(**kwargs: Any) -> Completion:
            title = kwargs["schema"].get("title", "")
            user = next(m["content"] for m in kwargs["messages"] if m["role"] == "user")
            self.calls.append({"provider": provider, "model": kwargs["model"], "title": title, "user": user})
            if provider == "anthropic" and title in self.fail_titles:
                raise Retryable("server_error_5xx")
            return Completion(json.dumps(self.answer(title, user)), 100, 50)

        return call

    @staticmethod
    def answer(title: str, user: str) -> dict[str, Any]:
        if title == "Plan":
            return {"summary": PLAN_MARK, "steps": ["return a + b"], "acceptance_criteria": ["test_add passes"]}
        if title == "CoderOutput":
            return {"edits": [{"path": "calc.py", "content": f"def add(a, b):\n    return a + b  {CODE_MARK}\n"}]}
        if title == "Verdict":
            return {"reviewer_id": "x", "verdict": "APPROVE", "findings": [], "summary": "ok"}
        raise AssertionError(f"unexpected output schema {title}")


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    rec = Recorder()
    monkeypatch.setattr(raw_runtime, "OpenAICompatChat", lambda *a, **k: rec.chat("openai"))
    monkeypatch.setattr(anthropic_runtime, "AnthropicChat", lambda *a, **k: rec.chat("anthropic"))
    return rec


async def run_task(cfg: AppConfig, tmp_path: Path, anthropic_creds: tuple[str | None, str | None]) -> Any:
    driver = await make_driver(cfg, tmp_path)
    driver.runtime = RawRuntime(cfg, "http://gpt.test/v1", "k1", anthropic_creds)
    run = await driver.run(driver.create("make test_add pass").id)
    return driver, run


def models_by_role(driver: Any, run_id: str) -> dict[str, str]:
    return {s.role: s.model for s in driver.store.steps(run_id)}


async def test_claude_builds_and_gpt_reviews_the_claude_diff(
    cfg: AppConfig, tmp_path: Path, recorder: Recorder
) -> None:
    mixed = mixed_config(cfg)
    driver, run = await run_task(mixed, tmp_path, ("http://claude.test/v1/", "k2"))

    assert (run.status, run.paused_reason) == (RunStatus.WAITING_HUMAN, "signoff")
    assert models_by_role(driver, run.id) == {
        "planner": CLAUDE,
        "coder": CLAUDE,
        "correctness-reviewer": CLAUDE,
        "arch-reviewer": GPT,
        "test-style-reviewer": GPT_CHEAP,
    }
    # Handoff 1: Claude coder received the plan written by the Claude planner.
    coder_call = next(c for c in recorder.calls if c["title"] == "CoderOutput")
    assert coder_call["provider"] == "anthropic" and PLAN_MARK in coder_call["user"]
    # Handoff 2: every GPT reviewer judged the actual diff produced by the Claude coder.
    gpt_reviews = [c for c in recorder.calls if c["title"] == "Verdict" and c["provider"] == "openai"]
    assert len(gpt_reviews) == 2 and all(CODE_MARK in c["user"] for c in gpt_reviews)
    assert CODE_MARK in (driver.workspace.root / "calc.py").read_text()


async def test_claude_outage_falls_back_to_gpt_root(cfg: AppConfig, tmp_path: Path, recorder: Recorder) -> None:
    recorder.fail_titles = {"Plan"}
    driver, run = await run_task(mixed_config(cfg), tmp_path, ("http://claude.test/v1/", "k2"))

    planner = next(s for s in driver.store.steps(run.id) if s.role == "planner")
    assert planner.model == GPT and planner.routing_reason.startswith("fallback_from_")
    assert run.paused_reason == "signoff"


async def test_missing_claude_key_pauses_instead_of_hanging(cfg: AppConfig, tmp_path: Path, recorder: Recorder) -> None:
    data = mixed_config(cfg).model_dump(mode="json")
    data["model_policy"]["roles"]["planner"]["fallback"] = []  # no GPT rescue: surface the config error
    driver, run = await run_task(AppConfig.model_validate(data), tmp_path, (None, None))

    assert (run.status, run.paused_reason) == (RunStatus.WAITING_HUMAN, "execution_error")
    assert driver.store.pending_approval(run.id).payload["error_kind"] == "provider_credentials_missing"
    assert not [c for c in recorder.calls if c["provider"] == "anthropic"]


def test_current_catalog_mixes_providers_where_it_matters(cfg: AppConfig) -> None:
    """Guards the real config/models.yaml: building and reviewing must not collapse onto one vendor."""
    alias = cfg.models.aliases
    route = {role: alias[p.primary] for role, p in cfg.model_policy.roles.items()}
    providers = {route[r].provider for r in ("planner", "coder", *cfg.reviewer_roles)}
    assert providers == {"openai", "anthropic"}, providers
    assert route["correctness-reviewer"].model != route["arch-reviewer"].model
