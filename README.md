# Agent Converge

Local multi-agent convergence loop with objective gates, independent model reviews, and human signoff.

Repository: `agent-converge`. The Python package, CLI, and `AGENTLAB_*` settings retain their existing names for compatibility.

Workflow:

```
Task -> Planner -> Coder -> [objective Gate] -> [LLM review panel x3] -> Arbiter -> Human -> Done
```

Design doc (source of truth): [`docs/DISCOVERY.md`](docs/DISCOVERY.md). Phases and progress: section 16.

## Current status

P0 prototype is implemented: deterministic loop, independent reviewer panel, human approval, SSE office visualization, and in-memory knowledge/project services. The real gateway and Docker Python gate are connected. Next: P2 persistence and resume, followed by project-specific scheduling modes.

Verified on 2026-10-09: 132 backend tests, 17 UI tests, UI typecheck/production build, and configuration validation. ADK remains a placeholder; runtime/project/memory state is not yet persisted. The Python repair smoke test verifies real-model convergence inside Docker. Other language gates remain unverified.

Execution failures pause for human intervention. Only reviewed signoff plus the full gate can be approved as complete; budget pauses require an explicit increase. The console approval panel accepts budget and iteration limits. SSE resumes from Last-Event-ID and deduplicates replayed usage. Diffs are based on the run-start snapshot without changing the Git index. Apply `0002_model_alignment.sql` to an existing database before the future persistence adapter.

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

## Real gateway and Docker validation

```bash
colima start --cpu 4 --memory 8
docker build -t agentlab/gate-python:latest docker/gate-python
docker compose up -d postgres
uv run agentlab ping
uv run agentlab smoke --trials 3
```

`smoke` uses fresh copies of `evals/tasks/py-fix-add`, verifies failing baseline tests, and stops at human signoff. Reports stay in `.agentlab/smoke/`. Docker is the default sandbox; the offline demo continues to use a local sandbox. Python gate dependencies must be baked into the image; dependency installation and network-backed vulnerability auditing are not yet supported by the offline gate. PostgreSQL is deployed, but application persistence is still pending.

The interface supports English / 简体中文 through the top selector or Settings, with a saved browser preference.

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
