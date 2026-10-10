# Agent Converge

Local multi-agent convergence loop with objective gates, independent model reviews, and human signoff.

Repository: `agent-converge`. The Python package, CLI, and `AGENTLAB_*` settings retain their existing names for compatibility.

Workflow:

```
Task -> Planner -> Coder -> [objective Gate] -> [LLM review panel x3] -> Arbiter -> Human -> Done
```

Design doc (source of truth): [`docs/DISCOVERY.md`](docs/DISCOVERY.md). Phases and progress: section 16.

## Current status

P0 prototype is implemented: deterministic loop, independent reviewer panel, human approval, SSE office visualization, and in-memory knowledge/project services. Next: P1 real gateway + Docker gate validation, then P2 persistence and resume.

Verified on 2026-10-09: 71 backend tests, 14 UI tests, UI typecheck/production build, and configuration validation. ADK remains a placeholder; runtime/project/memory state is not yet persisted. Real-model convergence and Docker gates remain unverified.

## Layout

| Path | What |
|---|---|
| `config/` | Everything tunable: models, role routing, retry, budget, agents, prompts, gates, policies. Strictly validated on load. |
| `src/agentlab/core/` | Framework-free deterministic logic: state machine, convergence, oscillation, arbiter, routing, budget, retry. |
| `src/agentlab/adapters/` | Swappable implementations of `core/ports.py`: runtimes (fake/raw/adk), sandbox (local/docker), gates, store. |
| `src/agentlab/api/` | FastAPI daemon + SSE event stream consumed by the UI. |
| `src/agentlab/cli/` | `agentlab` CLI. |
| `ui/` | React + Pixi Office Floor (ported from munder-difflin), run views. Optional. |

## Quickstart

```bash
uv sync
uv run agentlab config-check
uv run agentlab demo
uv run pytest
```

## Plugging in your LLM gateway

1. `cp .env.example .env` and set `AGENTLAB_LLM_BASE_URL` + `AGENTLAB_LLM_API_KEY` (any OpenAI-compatible endpoint).
2. Edit `config/models.yaml`: each alias (`root`, `strong`, `strong-alt`, `cheap`) maps to a model id on that gateway.
3. Edit `config/model_policy.yaml` to choose which alias each role uses.

Code only ever references aliases, so swapping `gpt-6.1` for something else is a YAML change.

## Infra

```bash
colima start --cpu 4 --memory 8
docker compose up -d postgres
docker compose --profile gateway up -d litellm
```

## Credits

See [`ui/THIRD_PARTY_NOTICES.md`](ui/THIRD_PARTY_NOTICES.md). The Office Floor visualization is adapted from
[munder-difflin](https://github.com/chaitanyagiri/munder-difflin) (MIT). Pixel art tilesets by
[LimeZu](https://limezu.itch.io/).
