<div align="center">

# Multi-Agent Platform

**One conversation. A reviewed team. Your final say.**

Chat with a Root agent about your local repository. Questions get answered directly; coding work goes to a
Planner → Coder → Gate → three independent reviewers → human signoff loop, visualized as a pixel office.

[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](https://www.python.org/) [![Node](https://img.shields.io/badge/node-22-339933)](https://nodejs.org/) [![Status](https://img.shields.io/badge/status-alpha-orange)](docs/DISCOVERY.md) [![Stars](https://img.shields.io/github/stars/Elyon0517/multi-agent-platform?style=flat)](https://github.com/Elyon0517/multi-agent-platform/stargazers)

Find this useful? Give it a star ⭐

[Architecture](#architecture) · [Setup](#setup) · [Usage](#usage) · [Testing](#testing) · [Design doc](docs/DISCOVERY.md) · [Acceptance checklist](docs/ACCEPTANCE.md)

</div>

```mermaid
flowchart LR
  You((You)) <--> Root[Root conversation]
  Root -- answer / clarify --> You
  Root -- task --> Planner --> Coder --> Gate{Gate<br/>optional}
  Gate -- fail --> Coder
  Gate --> R1[Correctness reviewer]
  Gate --> R2[Architecture reviewer]
  Gate --> R3[Test/style reviewer]
  R1 & R2 & R3 --> Arbiter
  Arbiter -- changes requested --> Coder
  Arbiter -- signoff --> Human{{Human signoff}}
  Human --> Summarizer[Summarizer → memory]
```

## What it does

- **One entry point.** Every message goes to Root, which decides whether to answer (read-only file, git, memory
  and web search tools), ask a clarifying question, or hand a task to the team.
- **Convergence, not a single shot.** Planner and Coder iterate until three reviewers on different models report
  no blocking or major findings, or the loop escalates to you.
- **Deterministic control.** Budgets, retries, convergence, oscillation detection, routing and approvals are
  plain Python, never delegated to a model.
- **Human signoff.** Nothing completes without you. The signoff card shows the goal and acceptance criteria,
  automated check results (or "no automated tests were run") and any remaining findings.
- **Memory that learns.** Global, project and per-agent memory; a summarizer turns your feedback and review
  findings into versioned lessons. Upload documents (PDF / Markdown / text) for retrieval-augmented answers.
- **Local first.** Your repository stays on your machine. Embeddings and reranking run on local CPU models by
  default; only LLM calls leave the machine.
- **Observable.** A live pixel office, run timelines, Gate diagnostics and a per-agent token Monitor.

## Architecture

| Layer | Responsibility | Where |
|---|---|---|
| UI | Conversation, office floor, run timeline, approvals, memory, Monitor | `ui/` (React, Vite, Pixi.js) |
| API | REST + SSE event stream, single source for every view | `src/agentlab/api/` (FastAPI) |
| Root session | Intent routing (answer / clarify / task), read-only tools, streamed replies | `src/agentlab/core/session/` |
| Loop driver | State machine, convergence, oscillation, arbiter, budget guard, checkpoints | `src/agentlab/core/loop/` |
| Model access | Role → alias → model routing, retry and fallback, structured output repair | `src/agentlab/core/llm/`, `config/model_policy.yaml` |
| Runtimes | OpenAI-compatible gateway, Anthropic Messages API, offline fake runtime | `src/agentlab/adapters/runtime/` |
| Gate and sandbox | Optional objective checks (built-in Python gate), Docker or local sandbox | `src/agentlab/adapters/gates/`, `docker/` |
| Storage | PostgreSQL with one schema per project, content-addressed blobs, Git snapshots | `src/agentlab/adapters/store/`, `.agentlab/` |
| Memory | Hybrid retrieval (BM25 + vectors + rerank), summarizer, versioned items | `src/agentlab/core/memory/` |

**Run states.** `PLANNING → CODING → GATING → REVIEWING → ARBITRATING → WAITING_HUMAN → DONE`. Projects without a
matching Gate skip `GATING`. Failures, budget limits, conflicts and oscillation all pause in `WAITING_HUMAN`; only
signoff can complete a run.

**Design principles.**

1. Anything deterministic stays out of the model: budgets, convergence, retries and routing are code.
2. Configuration is code: agents, prompts, routing, budgets and gates live in strictly validated YAML under `config/`.
3. Cheap checks first: when a Gate exists, build, type, lint and tests run before any reviewer token is spent.
4. Everything is replayable: steps, prompts, responses, artifacts and events are persisted and content-addressed.

**Repository layout.**

| Path | Contents |
|---|---|
| `config/` | Models, role routing, retry, budget, agent definitions, prompts, gates, policies |
| `src/agentlab/core/` | Framework-free logic: loop, routing, budget, memory, Root session, Monitor |
| `src/agentlab/adapters/` | Swappable implementations of `core/ports.py`: runtimes, sandboxes, gates, stores |
| `src/agentlab/api/`, `src/agentlab/cli/` | FastAPI daemon and the `agentlab` CLI |
| `src/agentlab/db/` | Alembic migrations and per-project schema isolation |
| `ui/` | Web console |
| `evals/`, `tests/`, `scripts/` | Regression tasks and scorecards, unit and integration tests, showcase and smoke scripts |
| `docs/` | [`DISCOVERY.md`](docs/DISCOVERY.md) (design and roadmap), [`ACCEPTANCE.md`](docs/ACCEPTANCE.md) |

## Setup

### Prerequisites

- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- Node.js 22 and npm
- Docker for PostgreSQL (on macOS without Docker Desktop: `colima start --cpu 4 --memory 8`)
- An OpenAI-compatible LLM gateway; optionally an Anthropic-compatible endpoint for Claude

### 1. Try it offline (no keys, no database)

```bash
uv sync
uv run agentlab config-check
uv run agentlab demo
```

`demo` runs the full loop with scripted model replies and an in-memory store.

### 2. Configure models

```bash
cp .env.example .env
```

| Variable | Purpose |
|---|---|
| `AGENTLAB_LLM_BASE_URL`, `AGENTLAB_LLM_API_KEY` | OpenAI-compatible gateway used by GPT aliases |
| `AGENTLAB_ANTHROPIC_BASE_URL`, `AGENTLAB_ANTHROPIC_API_KEY` | Anthropic Messages API used by Claude aliases (`/v1` suffix optional) |
| `AGENTLAB_DATABASE_URL` | PostgreSQL connection; leave empty for a disposable in-memory store |
| `AGENTLAB_EMBEDDING_BASE_URL` | Optional remote `/embeddings` service; empty uses local CPU models |

Aliases are defined in `config/models.yaml` and assigned to roles in `config/model_policy.yaml`; code only refers
to aliases, so switching models is a YAML change. Keys can also be entered in the console's **settings** tab
(masked, stored in `.env`). Check every alias:

```bash
uv run agentlab ping
```

If you use an API relay, Claude aliases need the relay's base URL and a key from a group that allows direct API
calls; keys restricted to a specific client are rejected.

### 3. Start the database and the server

```bash
docker compose up -d postgres
uv run agentlab db-upgrade
uv run agentlab serve            # http://127.0.0.1:8765
```

### 4. Start the console

```bash
cd ui
npm ci
npm run dev                      # http://localhost:5173
```

The dev server proxies `/api` to `127.0.0.1:8765`; set `AGENTLAB_API_TARGET` to use another port.

### 5. Optional: Python Gate image

```bash
docker build -t agentlab/gate-python:latest docker/gate-python
```

Python projects then run FAST checks each round and FULL checks before signoff, in an offline, read-only
container. Other languages run without a Gate and are marked as untested at signoff.

## Usage

1. **New project** (left sidebar): name, goal and a local Git repository root. **Choose folder…** opens the macOS
   folder picker. The project planner drafts phases and steps; model and budget settings live in the same dialog.
2. **Talk to Root** in the project conversation. Ask questions ("what is uncommitted on this branch?") or request
   work ("fix calc.add so the tests pass"). Say "answer only" or "go ahead and change it" to steer.
3. **Watch** the office, the run timeline and Gate diagnostics; progress and approvals also appear in the chat.
4. **Decide** on the signoff card: approve, reject with feedback (the team iterates), or abort.
5. **Memory** tab: upload documents globally or per project, test retrieval and rebuild vectors.
   **Monitor** shows cumulative tokens and estimated cost per agent across projects.
6. **⚙ Agent configuration** (console header) edits the current project's dispatch mode, models, budget and
   retrieval, with YAML export and import for version control.

Useful CLI commands:

```bash
uv run agentlab status                 # durable run state
uv run agentlab show RUN_ID            # timeline, artifacts, pending approval
uv run agentlab resume RUN_ID          # continue after a restart or kill -9
uv run agentlab decide RUN_ID approve  # resolve an approval from the terminal
```

## Testing

```bash
# Backend: unit tests, lint and types
uv run pytest -q
uv run ruff check src tests
uv run mypy src

# PostgreSQL integration tests (use a disposable schema, never application tables)
AGENTLAB_TEST_DATABASE_URL=postgresql://agentlab:agentlab@localhost:5432/agentlab uv run pytest -q tests/integration

# Frontend: tests, generated API types, typecheck and production build
npm --prefix ui test
npm --prefix ui run check:api
npm --prefix ui run build
```

After changing the API, regenerate the frontend types with `npm --prefix ui run gen:api`. CI runs the backend and
frontend jobs above on pull requests and pushes to `main`.

**Visual acceptance, offline.** `scripts/showcase.py` drives seven scripted scenarios through the real API,
driver and event stream with fixed model replies: happy path, Gate and review rework, provider outage fallback,
budget pause, conflicting reviews, workspace escape and oscillation.

```bash
uv run python scripts/showcase.py          # owns port 8765; stop agentlab serve first
npm --prefix ui run dev                    # then open http://localhost:5173/?follow=1
```

Options: `--only S2,S5`, `--speed 2`, `--manual` (decide approvals yourself), `--port 8766` together with
`AGENTLAB_API_TARGET=http://127.0.0.1:8766`.

**With real models** (small cost):

```bash
uv run agentlab smoke --trials 3                  # fixed Python repair task in Docker, stops at signoff
uv run agentlab eval                              # regression tasks + Root conversations, CI scorecard
AGENTLAB_LIVE=1 uv run pytest -q -s tests/live    # cross-provider handoff
uv run python scripts/check_local_memory.py       # local embedding upload and search
```

See [`docs/ACCEPTANCE.md`](docs/ACCEPTANCE.md) for the full checklist and expected results.

## Limitations

- Alpha software for personal, local use; the API binds to `127.0.0.1` and has no authentication.
- The built-in Gate covers Python only; custom check commands are planned.
- Vector ranking runs in Python; pgvector SQL indexes are planned.
- Project schemas separate data for export and deletion; access control is application-level filtering.
- The ADK runtime, LiteLLM virtual keys and external MCP tools are not implemented yet.

See the roadmap in [`docs/DISCOVERY.md`](docs/DISCOVERY.md) §16.

## Credits

The office visualization is adapted from [munder-difflin](https://github.com/chaitanyagiri/munder-difflin) (MIT).
Pixel art tilesets by [LimeZu](https://limezu.itch.io/), used under a purchased licence that does not permit
redistribution; they are planned to be replaced before any public release. Fonts are under the SIL OFL. Full
notices: [`ui/THIRD_PARTY_NOTICES.md`](ui/THIRD_PARTY_NOTICES.md).

---

<div align="center">

If this project helps you, please consider giving it a star ⭐

</div>
