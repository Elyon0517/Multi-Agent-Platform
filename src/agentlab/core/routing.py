from __future__ import annotations

from dataclasses import dataclass

from agentlab.core.config import AppConfig


class RoutingError(ValueError):
    pass


@dataclass(frozen=True)
class Override:
    requested_by: str
    alias: str
    reason: str


@dataclass(frozen=True)
class Route:
    role: str
    alias: str
    model: str
    temperature: float
    fallbacks: tuple[str, ...]
    reason: str

    @property
    def chain(self) -> tuple[str, ...]:
        return (self.alias, *self.fallbacks)


class Router:
    def __init__(self, cfg: AppConfig) -> None:
        self._cfg = cfg

    def model_of(self, alias: str) -> str:
        return self._cfg.models.aliases[alias].model

    def resolve(self, role: str, override: Override | None = None) -> Route:
        try:
            pol = self._cfg.model_policy.roles[role]
        except KeyError as e:
            raise RoutingError(f"no model policy for role '{role}'") from e
        alias, reason = pol.primary, "static_policy"
        if override is not None:
            self._check_override(role, pol.primary, override)
            alias, reason = override.alias, f"override_by_{override.requested_by}: {override.reason}"
        fallbacks = tuple(a for a in pol.fallback if a != alias)
        max_fb = self._cfg.retry.fallback_chain.max_fallback_models
        return Route(role, alias, self.model_of(alias), pol.temperature, fallbacks[:max_fb], reason)

    def _check_override(self, role: str, primary: str, ov: Override) -> None:
        rules = self._cfg.model_policy.override
        if ov.requested_by != rules.allowed_by:
            raise RoutingError(f"'{ov.requested_by}' may not override routing")
        if not any(t.from_ == primary and t.to == ov.alias for t in rules.allowed_transitions):
            raise RoutingError(f"override {primary} -> {ov.alias} not whitelisted")
        is_reviewer = self._cfg.agents[role].kind == "reviewer"
        if is_reviewer and self._cfg.models.tiers[ov.alias] > rules.reviewer_min_tier:
            raise RoutingError(f"reviewer '{role}' may not drop below tier {rules.reviewer_min_tier}")
