from __future__ import annotations

from typing import Literal

from pydantic import Field

from agentlab.core.config import AppConfig
from agentlab.core.schemas import Strict


class Binding(Strict):
    alias: str = Field(min_length=1)
    task: str = Field(min_length=1, max_length=4000)


class ProjectSettings(Strict):
    mode: Literal["auto", "manual"] = "auto"
    root_alias: str = "root"
    allowed_aliases: list[str] = []
    bindings: dict[str, Binding] = {}
    budget_cents: float = Field(default=500, gt=0)
    max_iter: int = Field(default=5, ge=1, le=50)
    retrieval: Literal["off", "keyword", "hybrid"] = "keyword"
    retrieval_k: int = Field(default=6, ge=1, le=20)


def worker_roles(cfg: AppConfig) -> set[str]:
    return set(cfg.model_policy.roles) - {"supervisor", "project-planner"}


def validate_settings(settings: ProjectSettings, cfg: AppConfig) -> None:
    allowed = set(settings.allowed_aliases or cfg.models.aliases)
    if settings.root_alias not in cfg.models.aliases or allowed - cfg.models.aliases.keys():
        raise ValueError("unknown model alias")
    if settings.mode == "manual" and set(settings.bindings) != worker_roles(cfg):
        raise ValueError("manual mode requires a model and task for every worker role")
    if set(settings.bindings) - worker_roles(cfg):
        raise ValueError("unknown worker role")
    if any(b.alias not in allowed for b in settings.bindings.values()):
        raise ValueError("worker model is outside the project model catalog")


def project_config(cfg: AppConfig, settings: ProjectSettings) -> AppConfig:
    validate_settings(settings, cfg)
    data = cfg.model_dump(mode="json")
    for role in ("supervisor", "project-planner"):
        data["model_policy"]["roles"][role]["primary"] = settings.root_alias
        data["model_policy"]["roles"][role]["fallback"] = []
    if settings.mode == "manual":
        for role, binding in settings.bindings.items():
            data["model_policy"]["roles"][role]["primary"] = binding.alias
            data["model_policy"]["roles"][role]["fallback"] = []
    data["budget"]["default_run_budget_cents"] = settings.budget_cents
    data["budget"]["loop"]["max_iter"] = settings.max_iter
    return AppConfig.model_validate(data)


class Dispatch(Strict):
    assignments: dict[str, Binding]

    def validate_for(self, cfg: AppConfig, settings: ProjectSettings) -> None:
        if set(self.assignments) != worker_roles(cfg):
            raise ValueError("supervisor must assign every worker exactly once")
        allowed = set(settings.allowed_aliases or cfg.models.aliases)
        for role, binding in self.assignments.items():
            if binding.alias not in allowed:
                raise ValueError("supervisor selected an unavailable model")
            if role in cfg.reviewer_roles:
                limit = max(
                    cfg.models.tiers[cfg.model_policy.roles[role].primary], cfg.model_policy.override.reviewer_min_tier
                )
                if cfg.models.tiers[binding.alias] > limit:
                    raise ValueError("supervisor downgraded reviewer below its allowed tier")
