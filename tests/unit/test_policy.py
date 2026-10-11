from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from agentlab.core.budget import BudgetExceeded, BudgetGuard
from agentlab.core.config import AppConfig, ConfigError, LlmCallCfg, load_config
from agentlab.core.llm.retry import AttemptLog, NonRetryable, RetriesExhausted, Retryable, call_with_retry
from agentlab.core.routing import Override, Router, RoutingError
from agentlab.core.schemas import Run, Usage
from tests.conftest import CONFIG_DIR


class TestConfig:
    def test_loads(self, cfg: AppConfig) -> None:
        assert cfg.reviewer_roles == ["arch-reviewer", "correctness-reviewer", "test-style-reviewer"]

    def test_unknown_field_rejected(self, tmp_path: Path) -> None:
        root = shutil.copytree(CONFIG_DIR, tmp_path / "config")
        (root / "budget.yaml").write_text((root / "budget.yaml").read_text() + "typo_field: 1\n")
        with pytest.raises(ConfigError, match="typo_field"):
            load_config(root)

    def test_unknown_alias_rejected(self, tmp_path: Path) -> None:
        root = shutil.copytree(CONFIG_DIR, tmp_path / "config")
        p = root / "model_policy.yaml"
        p.write_text(p.read_text().replace("primary: cheap, temperature: 0.3", "primary: nope, temperature: 0.3"))
        with pytest.raises(ConfigError, match="nope"):
            load_config(root)


class TestRouting:
    def test_static(self, cfg: AppConfig) -> None:
        r = Router(cfg).resolve("supervisor")
        assert (r.alias, r.model, r.reason) == ("root", cfg.models.aliases["root"].model, "static_policy")

    def test_sub_agents_use_different_model_same_gateway(self, cfg: AppConfig) -> None:
        custom = cfg.model_copy(deep=True)
        custom.models.aliases["root"].model = "test-root-model"
        custom.models.aliases["cheap"].model = "test-worker-model"
        router = Router(custom)
        assert router.resolve("supervisor").model != router.resolve("test-style-reviewer").model

    def test_whitelisted_override(self, cfg: AppConfig) -> None:
        r = Router(cfg).resolve("coder", Override("supervisor", "root", "hard task"))
        assert r.alias == "root" and r.reason.startswith("override_by_supervisor")

    def test_override_by_non_root_rejected(self, cfg: AppConfig) -> None:
        with pytest.raises(RoutingError):
            Router(cfg).resolve("coder", Override("coder", "root", "x"))

    def test_reviewer_downgrade_rejected(self, cfg: AppConfig) -> None:
        with pytest.raises(RoutingError):
            Router(cfg).resolve("correctness-reviewer", Override("supervisor", "cheap", "save money"))


class TestBudget:
    def test_legacy_budget_does_not_block(self) -> None:
        run = Run(goal="g", workspace=".", budget_cents=1.0, cost_cents=0.9)
        BudgetGuard(run, 0.8, lambda r: None).check(1_000_000)
        assert run.budget_unlimited

    def test_tracks_cost_without_budget_warnings(self) -> None:
        run = Run(goal="g", workspace=".", budget_cents=10.0)
        warned: list[float] = []
        guard = BudgetGuard(run, 0.8, lambda r: warned.append(r.cost_cents))
        guard.record(Usage(cost_cents=5))
        guard.record(Usage(cost_cents=4))
        guard.record(Usage(cost_cents=0.5))
        assert warned == []
        assert run.cost_cents == 9.5


RETRY = LlmCallCfg(num_retries=3, backoff_base_s=0, timeout_s=5, retry_on=["rate_limit_429", "server_error_5xx"], do_not_retry_on=["auth_401_403"])


async def _nosleep(_: float) -> None:
    return None


class TestRetry:
    async def test_four_attempts_then_exhausted(self) -> None:
        log = AttemptLog()

        async def boom() -> str:
            raise Retryable("rate_limit_429")

        with pytest.raises(RetriesExhausted):
            await call_with_retry(boom, RETRY, log, lambda: None, _nosleep)
        assert log.count == 4 and log.reasons == ["rate_limit_429"] * 4

    async def test_non_retryable_fails_fast(self) -> None:
        log = AttemptLog()

        async def auth() -> str:
            raise NonRetryable("auth_401_403")

        with pytest.raises(NonRetryable):
            await call_with_retry(auth, RETRY, log, lambda: None, _nosleep)
        assert log.count == 1

    async def test_budget_checked_before_each_attempt(self) -> None:
        calls = {"n": 0}

        def budget() -> None:
            calls["n"] += 1
            if calls["n"] == 2:
                raise BudgetExceeded("stop")

        async def flaky() -> str:
            raise Retryable("server_error_5xx")

        with pytest.raises(BudgetExceeded):
            await call_with_retry(flaky, RETRY, AttemptLog(), budget, _nosleep)

    async def test_recovers(self) -> None:
        state = {"n": 0}

        async def flaky() -> str:
            state["n"] += 1
            if state["n"] < 3:
                raise Retryable("server_error_5xx")
            return "ok"

        assert await call_with_retry(flaky, RETRY, AttemptLog(), lambda: None, _nosleep) == "ok"
