from __future__ import annotations

from functools import cached_property
from pathlib import Path
from typing import Literal

import yaml
from pydantic import ConfigDict, Field, model_validator

from agentlab.core.schemas import GateMode, Strict


class ConfigError(ValueError):
    pass


class GatewayCfg(Strict):
    base_url_env: str
    api_key_env: str


class AliasCfg(Strict):
    model: str
    max_output_tokens: int = Field(default=16384, ge=1)
    estimate_input_tokens_per_byte: float = Field(default=1.0, gt=0)
    estimate_output_token_ratio: float = Field(default=1.0, gt=0, le=1)
    output_token_parameter: Literal["max_tokens", "max_completion_tokens"] = "max_tokens"
    supports_tools: bool = True
    structured_output: Literal["native", "json_mode", "react"] = "native"
    ctx_window: int
    cost_in_per_1m_cents: float
    cost_out_per_1m_cents: float

    def cost_cents(self, tokens_in: int, tokens_out: int) -> float:
        return (tokens_in * self.cost_in_per_1m_cents + tokens_out * self.cost_out_per_1m_cents) / 1_000_000


class EmbeddingCfg(Strict):
    model: str
    dimensions: int
    version: int


class ModelsCfg(Strict):
    gateway: GatewayCfg
    aliases: dict[str, AliasCfg]
    tiers: dict[str, int]
    embedding: EmbeddingCfg

    @model_validator(mode="after")
    def _tiers_cover_aliases(self) -> ModelsCfg:
        if missing := set(self.aliases) ^ set(self.tiers):
            raise ConfigError(f"models.yaml: aliases and tiers differ on {sorted(missing)}")
        return self


class RolePolicy(Strict):
    primary: str
    temperature: float = Field(ge=0.0, le=2.0)
    fallback: list[str] = []


class AliasTransition(Strict):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    from_: str = Field(alias="from")
    to: str


class OverrideCfg(Strict):
    allowed_by: str
    allowed_transitions: list[AliasTransition]
    reviewer_min_tier: int
    must_log: bool = True


class ModelPolicyCfg(Strict):
    roles: dict[str, RolePolicy]
    override: OverrideCfg


class LlmCallCfg(Strict):
    num_retries: int = Field(ge=0, le=10)
    backoff_base_s: float
    timeout_s: float
    retry_on: list[str]
    do_not_retry_on: list[str]


class RepairCfg(Strict):
    max_repairs: int = Field(ge=0, le=5)


class FallbackCfg(Strict):
    max_fallback_models: int = Field(ge=0, le=3)


class RetryCfg(Strict):
    llm_call: LlmCallCfg
    structured_output_repair: RepairCfg
    fallback_chain: FallbackCfg


class LoopCfg(Strict):
    max_iter: int = Field(ge=1, le=50)
    blocking_confidence_threshold: float = Field(ge=0.0, le=1.0)


class AskBudgetCfg(Strict):
    max_turn_cents: float = Field(default=100, gt=0)
    web_search_cents: float = Field(default=1, ge=0)


class BudgetCfg(Strict):
    ask: AskBudgetCfg = Field(default_factory=AskBudgetCfg)
    default_run_budget_cents: float
    warn_ratio: float = Field(gt=0.0, lt=1.0)
    default_project_weekly_cents: float
    loop: LoopCfg


class AgentDef(Strict):
    role: str
    output: str
    prompt: str
    tool_grants: list[str]
    kind: Literal["worker", "reviewer", "deterministic"]


class GateStepCfg(Strict):
    name: str
    argv: list[str] = Field(min_length=1)
    timeout_s: int = Field(gt=0)
    modes: list[GateMode]


class GateCfg(Strict):
    language: str
    image: str
    markers: list[str]
    steps: list[GateStepCfg]


class PolicyCfg(Strict):
    name: str
    dispatch: Literal["supervisor", "human"]
    require_human_signoff: bool
    dangerous_ops_require_approval: list[str]


class AppConfig(Strict):
    frozen_prompts: dict[str, str] = {}
    root: Path
    models: ModelsCfg
    model_policy: ModelPolicyCfg
    retry: RetryCfg
    budget: BudgetCfg
    agents: dict[str, AgentDef]
    gates: dict[str, GateCfg]
    policies: dict[str, PolicyCfg]

    @model_validator(mode="after")
    def _cross_refs(self) -> AppConfig:
        aliases = set(self.models.aliases)
        for role, pol in self.model_policy.roles.items():
            if unknown := ({pol.primary, *pol.fallback} - aliases):
                raise ConfigError(f"model_policy.{role}: unknown aliases {sorted(unknown)}")
            if role not in self.agents:
                raise ConfigError(f"model_policy.{role}: no agents/*.yaml defines this role")
        for t in self.model_policy.override.allowed_transitions:
            if unknown := ({t.from_, t.to} - aliases):
                raise ConfigError(f"model_policy.override: unknown aliases {sorted(unknown)}")
        for role, agent in self.agents.items():
            if agent.kind != "deterministic" and role not in self.model_policy.roles:
                raise ConfigError(f"agents/{role}: missing model_policy entry")
            if role not in self.frozen_prompts and not (self.root / agent.prompt).is_file():
                raise ConfigError(f"agents/{role}: prompt file {agent.prompt} not found")
        return self

    @cached_property
    def reviewer_roles(self) -> list[str]:
        return sorted(r for r, a in self.agents.items() if a.kind == "reviewer")

    def prompt(self, role: str) -> str:
        return (
            self.frozen_prompts[role]
            if role in self.frozen_prompts
            else (self.root / self.agents[role].prompt).read_text()
        )


def _read(path: Path) -> object:
    try:
        return yaml.safe_load(path.read_text())
    except FileNotFoundError as e:
        raise ConfigError(f"missing config file {path}") from e


def _read_dir(directory: Path, key: str) -> dict[str, object]:
    out: dict[str, object] = {}
    for f in sorted(directory.glob("*.yaml")):
        data = _read(f)
        if not isinstance(data, dict):
            raise ConfigError(f"{f}: expected a mapping")
        name = str(data.get(key, f.stem))
        if name in out:
            raise ConfigError(f"{f}: duplicate {key} '{name}'")
        out[name] = data
    return out


def load_config(root: Path) -> AppConfig:
    root = root.resolve()
    try:
        return AppConfig.model_validate(
            {
                "root": root,
                "models": _read(root / "models.yaml"),
                "model_policy": _read(root / "model_policy.yaml"),
                "retry": _read(root / "retry.yaml"),
                "budget": _read(root / "budget.yaml"),
                "agents": _read_dir(root / "agents", "role"),
                "gates": _read_dir(root / "gates", "language"),
                "policies": _read_dir(root / "policies", "name"),
            }
        )
    except ConfigError:
        raise
    except ValueError as e:
        raise ConfigError(str(e)) from e
