# Multi-Agent Platform

Local multi-agent convergence loop with objective gates, independent model reviews, and human signoff.

Repository: `multi-agent-platform`. The Python package, CLI, and `AGENTLAB_*` settings retain their existing names for compatibility.

Workflow:

```
Task -> [Root dispatch in auto mode] -> Planner -> Coder -> [objective Gate] -> [LLM review panel x3] -> Arbiter -> Human -> Done
```

Design doc (source of truth): [`docs/DISCOVERY.md`](docs/DISCOVERY.md). Phases and progress: section 16.

## Current status

P0 prototype is implemented: deterministic loop, independent reviewer panel, human approval, SSE office visualization, and knowledge/project services. P2 PostgreSQL persistence and CLI resume are implemented. The real gateway and Docker Python gate are connected; project-specific auto/manual scheduling and persistent conversations are now connected to the UI.

Verified on 2026-10-10: 185 backend tests (including 19 persistence integration cases), 19 UI tests, UI typecheck/production build, and configuration validation. ADK remains a placeholder; runs, projects, memory versions, model attempts and recovery checkpoints persist when PostgreSQL is configured. The Python repair smoke test verifies real-model convergence inside Docker. Other language gates remain unverified.

Execution failures pause for human intervention. Only reviewed signoff plus the full gate can be approved as complete; budget pauses require an explicit increase. The console approval panel accepts budget and iteration limits. SSE resumes from Last-Event-ID and deduplicates replayed usage. Diffs are based on the run-start snapshot without changing the Git index. Alembic adopts the existing bootstrap SQL and applies subsequent migrations automatically.

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

## Persistence and recovery

Set `AGENTLAB_DATABASE_URL=postgresql+psycopg://agentlab:agentlab@localhost:5432/agentlab` in `.env`, then start PostgreSQL. `AGENTLAB_STORE_BACKEND=auto` selects PostgreSQL when the URL is present; `memory` is available for disposable runs. PostgreSQL dependencies are included in the normal install.

```bash
docker compose up -d postgres
uv run agentlab db-upgrade
uv run agentlab status
uv run agentlab show RUN_ID
uv run agentlab resume RUN_ID
uv run agentlab decide RUN_ID approve --budget-cents 1000
```

All projects, including existing projects and default runs, use their own `proj_<id>` PostgreSQL schema. Global knowledge and routing metadata stay in `public`. `db-upgrade` performs a transactional, content/count-verified migration and preserves the previous data in read-only `legacy_projects`; it does not automatically delete that backup. Stop older application processes before upgrading and back up both PostgreSQL and `.agentlab/`. The one-time script can also be run with `uv run python -m agentlab.db.isolation`. New projects use the same storage path. Each schema tracks its Alembic version; upgrades advance the base and all registered project schemas in one transaction, rolling all of them back on failure. Export a schema with `pg_dump -n proj_<id>`; restoring a complete project additionally requires the vector extension, routing registration, and its blob/snapshot files.

Physical schemas support project export and deletion boundaries. Access control remains application-level filtering by project ID and role: the shared database account can read all schemas, and memory is loaded into one process before scoped retrieval.

Pending approvals survive restart and are not automatically approved. Only signoff completes a run. If a process dies before a request returns usage, resume pauses with `interrupted_call`; approving explicitly authorizes retry, which may be billed again by the gateway. Returned usage and valid paid outputs are restored without reissuing their calls. Keep both PostgreSQL data and `.agentlab/` (blobs and isolated Git objects); a database backup alone cannot recover the baseline. Abort/terminal runs release their snapshot objects; paused runs retain them until explicitly aborted or completed.

Workspaces must point to a Git repository root. A monorepo package directory is rejected without initializing an embedded repository. Coder writes inside nested repositories/submodules remain forbidden; run an independent project at their root.

Integration tests use a disposable schema, never the application's tables:

```bash
AGENTLAB_TEST_DATABASE_URL=postgresql://agentlab:agentlab@localhost:5432/agentlab uv run pytest
```

Without this variable, PostgreSQL integration cases are skipped; the in-memory contract and workspace boundary tests still run. Real recovery validation on 2026-10-10 killed the worker after a paid planner result, resumed through the CLI and Docker FULL Gate, and reached signoff with one planner step (`6b2e0c696274`, estimated 5.4875 cents).

## Real gateway and Docker validation

```bash
colima start --cpu 4 --memory 8
docker build -t agentlab/gate-python:latest docker/gate-python
docker compose up -d postgres
uv run agentlab ping
uv run agentlab smoke --trials 3
```

`smoke` uses fresh copies of `evals/tasks/py-fix-add`, verifies failing baseline tests, and stops at human signoff. Reports stay in `.agentlab/smoke/`. Docker is the default sandbox; the offline demo continues to use a local sandbox. Python gate dependencies must be baked into the image; dependency installation and network-backed vulnerability auditing are not yet supported by the offline gate. Configure `AGENTLAB_DATABASE_URL` to use PostgreSQL. Smoke workspaces live under `~/.agentlab-workspaces/` so Colima can mount them.

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

## Projects, conversations and memory

Create a project with an existing, independent repository root. Choose **Root assigns models and tasks** or **Manually assign every agent** in the project form. The console edits future-run settings and exports/imports a YAML profile for Git version control. Automatic dispatch is validated and persisted; manual bindings have no fallback. All current aliases resolve to the same model ID, so model diversity awaits additional provider configuration.

The left sidebar selects a project and its conversations. Submitting a goal starts a run in the selected conversation. Finish or abort an unfinished run before starting another in the same workspace; use separate worktrees for parallel projects. Switching projects resets approval, tasks, telemetry, agent activity and private retrieval context. Inspect the actual diff in the run artifacts before human signoff.

Memory has explicit global sharing, project-private documents and project × role notes. Keyword retrieval works without embedding credentials and is the default. To use hybrid retrieval, provide `AGENTLAB_EMBEDDING_BASE_URL` and `AGENTLAB_EMBEDDING_API_KEY` in Settings or `.env`, and configure the embedding model/dimensions/version in `config/models.yaml`. Test the endpoint, select hybrid in project settings, then reindex existing project/agent chunks and shared knowledge separately. Readiness requires an actual successful embedding call; failure degrades to keyword retrieval. Vector ranking currently runs in Python over persisted payloads; pgvector HNSW and physical per-project schemas are pending.

The DISCOVERY §16.4 table records implemented UX paths, verification and remaining decisions. New dispatch has fake and PostgreSQL recovery coverage; real-provider dispatch and vector retrieval still require separate smoke acceptance.
