<div align="center">

# Multi-Agent Platform

**One conversation. A reviewed team. Your final say.**

Chat with a Root agent about your local repository. Questions get answered directly; coding work goes to a
Planner → Coder → Gate → Review → human signoff loop, visualized as a pixel office.
Use the raw runtime for a review panel, or opt into Codex SDK Coding → Claude Agent SDK Review.

Python 3.12+ · Node 22.12+ · Alpha

Find this useful? Give it a star ⭐

[Architecture](#architecture) · [Setup](#setup) · [Usage](#usage) · [SDK workflow](#native-sdk-workflow-route-b) · [Testing](#testing) · [Design doc](docs/DISCOVERY.md) · [Acceptance checklist](docs/ACCEPTANCE.md)

</div>

```mermaid
flowchart LR
  You((You)) <--> Root[Root conversation]
  Root -- answer / clarify --> You
  Root -- task --> Planner --> Coder --> Gate{Gate<br/>optional}
  Gate -- fail --> Coder
  Gate --> Review[Raw review panel<br/>or single Claude SDK reviewer]
  Review --> Arbiter
  Arbiter -- changes requested --> Coder
  Arbiter -- signoff --> Human{{Human signoff}}
  Human --> Summarizer[Summarizer → memory]
```

## See the team converge

![Live office and review evidence from a real offline run](docs/screenshots/office-review.png)

**Give the team a broken function. Watch it test, revise, review, and deliver.**
The walkthrough starts with an incorrect `add()` implementation. A real pytest Gate catches
it, the coder fixes it, an architecture reviewer requests a docstring, and the next review
round approves the final diff.

<details>
<summary>See the completed run and Gate history</summary>

![Completed run with the failed Gate, passing checks, and reviewer results](docs/screenshots/completed-run.png)

</details>

These are screenshots of the real API and console. Model replies are scripted; pytest,
file edits, revision checks and event streaming execute locally. Displayed usage and costs
come from scripted replies and configured rates; no paid model call is made. This demo
uses an explicit workspace and completes in place after checks. Isolated delivery workflows
can require human signoff; the browser test does not claim to verify those workflows.

### Try the same walkthrough without keys

```bash
uv sync
uv run python scripts/showcase.py --only S2 --speed 2
# In a second terminal:
cd ui
npm ci
npm run dev
# Open http://localhost:5173/?follow=1
```

To run the API-backed browser check and regenerate the screenshots:

```bash
cd ui
npx playwright install chromium
npm run test:showcase
```

[Capture details and verification scope](docs/SHOWCASE.md).

## What it does

- **One entry point.** Every message goes to Root, which decides whether to answer (read-only file, git, memory
  and web search tools), ask a clarifying question, or hand a task to the team.
- **Convergence, not a single shot.** Planner and Coder iterate until the configured reviewers report
  no blocking or major findings, or the loop escalates to you.
- **Deterministic control.** Revision checks, retries, convergence, oscillation detection, routing and approvals are
  plain Python, never delegated to a model.
- **Human signoff.** Coding deliveries require your approval. The signoff card shows the goal and acceptance criteria,
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
| Runtimes | Raw gateways, optional Codex SDK Coding → Claude Agent SDK Review, offline fake | `src/agentlab/adapters/runtime/` |
| Gate and sandbox | Optional objective checks (built-in Python gate), Docker or local sandbox | `src/agentlab/adapters/gates/`, `docker/` |
| Storage | PostgreSQL with one schema per project, content-addressed blobs, Git snapshots | `src/agentlab/adapters/store/`, `.agentlab/` |
| Memory | Hybrid retrieval (BM25 + vectors + rerank), summarizer, versioned items | `src/agentlab/core/memory/` |

**Run states.** `PLANNING → CODING → GATING → REVIEWING → ARBITRATING → WAITING_HUMAN → DONE`. Projects without a
matching Gate skip `GATING`. Failures, conflicts and oscillation pause in `WAITING_HUMAN`.
Coding deliveries complete after signoff; read-only reports can complete without a code approval.

Code diffs, Gate results, reviewer results and signoff approvals carry the same source revision.
If source files change during checks, review or an approval pause, the run pauses with `workspace_changed`;
Approve preserves the current files and reruns checks and all reviewers. Partial reviewer results are reused
only while that revision still matches. Older runs without revision bindings also require fresh checks and review.

Coder deliveries and `workspace_write` tools persist file operations before writing, with original and target
SHA-256 hashes. Recovery recognizes applied files, resumes pending files and pauses on `edit_conflict` rather
than overwriting edits made during an interruption. Approve rechecks the same operations; Reject with feedback
starts a fresh Coder execution from the current files. Legacy cached edits without a write baseline require replanning.

**Design principles.**

1. Anything deterministic stays out of the model: revision validation, convergence, retries and routing are code.
2. Configuration is code: agents, prompts, routing, harness settings and gates live in strictly validated YAML under `config/`.
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
| `docs/` | [`DISCOVERY.md`](docs/DISCOVERY.md) (design and roadmap), [`ACCEPTANCE.md`](docs/ACCEPTANCE.md), [`SDK_HANDOFF_ACCEPTANCE.md`](docs/SDK_HANDOFF_ACCEPTANCE.md) |

## Setup

### Prerequisites

- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- Node.js 22.12+ (22.x), 24.x, or 26+ and npm
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
container. Projects can also configure check commands. Projects without a matching Gate are marked as untested at signoff.

## Usage

1. **New project** (left sidebar): name, goal and a local Git repository root. **Choose folder…** opens the macOS
   folder picker. The project planner drafts phases and steps; model settings live in the same dialog.
2. **Talk to Root** in the project conversation. Ask questions ("what is uncommitted on this branch?") or request
   work ("fix calc.add so the tests pass"). Say "answer only" or "go ahead and change it" to steer.
3. **Watch** the office, the run timeline and Gate diagnostics; progress and approvals also appear in the chat.
4. **Decide** on the signoff card: approve, reject with feedback (the team iterates), or abort.
5. **Memory** tab: upload documents globally or per project, test retrieval and rebuild vectors.
   **Monitor** shows cumulative tokens and estimated cost per agent across projects.
6. **⚙ Agent configuration** (console header) edits the current project's dispatch mode, models and
   retrieval, with YAML export and import for version control.

By default, agents edit the selected repository checkout on its current branch, including main/master, so changes are visible immediately in your IDE. Runs do not commit or push in this mode. Select worktree mode explicitly to isolate parallel runs; that mode uses private bookkeeping commits and applies changes back on signoff.

Useful CLI commands:

```bash
uv run agentlab status                 # durable run state
uv run agentlab show RUN_ID            # timeline, artifacts, pending approval
uv run agentlab resume RUN_ID          # continue after a restart or kill -9
uv run agentlab decide RUN_ID approve  # resolve an approval from the terminal
```

## Native SDK workflow (Route B)

Install the optional, pinned native Harness dependencies and opt in per process or run:

```sh
uv sync --extra harness
uv run --extra harness agentlab run 'Fix the failing test' --workspace /absolute/path/to/repo --runtime sdk
# API/UI process:
AGENTLAB_RUNTIME=sdk uv run --extra harness agentlab serve
```

Root, Supervisor, Planner and Summarizer continue using the existing raw gateway. Coding uses
`openai-codex` and the single `correctness-reviewer` uses `claude-agent-sdk`; neither falls back to raw
on SDK failure. Set native model IDs in `config/harness.yaml`. These IDs are separate from raw model
aliases and Supervisor allocation; the frozen run configuration is reused on restore. Existing raw/fake
profiles and their reviewer panels are unchanged. This profile supports coding tasks, not the custom
evidence-contract tools.

SDK authentication is independent of `AGENTLAB_LLM_*`: export `OPENAI_API_KEY` (or sign in with the native
Codex CLI) and `ANTHROPIC_API_KEY` before starting AgentLab. A native Codex login's `auth.json` is copied
into the private invocation state directory; project/user Codex configuration is not copied. Claude uses
a private configuration directory and does not inherit project/user settings, MCP servers, skills or
plugins. No paid SDK call is made during installation or service creation.

The Coder works in a persistent private copy under `AGENTLAB_DATA_DIR/harness/`, including allowed dirty
and untracked source files, with its own Git metadata. Copies are materialized from immutable Git objects
matching the bound revision, rather than a second set of live file reads. Dependencies/caches, credentials
and native SDK project settings are excluded. Codex uses workspace-write sandboxing without network or extra temporary
write roots. Existing Gates still run against the authoritative workspace after promotion. Text additions
and replacements pass through the existing EditJournal and before/after hashes; unsupported deletions,
renames, binary edits, executable-bit changes, symlinks, nested repositories and reserved paths fail before
promotion. Unchanged binary files are preserved in the copy. Dependency installation in the SDK copy is
not part of this minimal profile.

Claude receives a separate, read-only copy pinned to the authoritative revision. Only Read/Glob/Grep and
the SDK's StructuredOutput helper are permitted; a tool hook restricts source reads to that copy. The
terminal structured Verdict is validated locally, and Driver assigns its identity/revision. Missing,
malformed or failed review results cannot approve a run. Gate, Arbiter and human signoff remain unchanged.

Invocation/session IDs, input revision, SDK version, source/output manifests and normalized results are
persisted alongside existing checkpoints. A completed invocation is reused without another model call;
partial promotion replays only pending journal entries and preserves conflicting human edits. A completed
SDK reply awaiting normalization can also recover if its frozen copy is unchanged. Prepared copies are
rechecked against their source manifests before any SDK launch; exported bytes are checked individually
and preserve UTF-8 line endings through blob storage and EditJournal. Legacy Reviewer records without an
iteration also block reissue for the same revision when the input fingerprint changes. **An execution whose
termination is unknown is never automatically resumed or replayed.** It pauses using the existing approval
flow; reject with feedback to create a fresh isolated attempt. Merely approving does not reopen an unknown
writer. Native session data and copies are retained for diagnosis; a session ID alone is not a filesystem
checkpoint. This integration does not add stage deadlines, a new termination policy or multiple SDK reviewers.

SDK usage is recorded once per invocation through the existing usage ledger. Claude's reported cost is an
estimate; Codex exposes tokens but no billed dollar amount here (its cost remains unavailable/zero in the
current numeric cost field). Interrupted calls without terminal usage remain explicitly unmetered.

Native SDK references: [Codex SDK](https://learn.chatgpt.com/docs/codex-sdk) and [Claude Agent SDK for Python](https://code.claude.com/docs/en/agent-sdk/python).

Real SDK handoff, process-interruption recovery, and the JSONB identity regression are documented in [the SDK acceptance record](docs/SDK_HANDOFF_ACCEPTANCE.md).

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
npm --prefix ui exec -- playwright install chromium
npm --prefix ui run test:e2e
npm --prefix ui run check:api
npm --prefix ui run build
npm --prefix ui run check:distribution
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

**Native SDK integration** (real model usage, opt in explicitly):

```bash
uv sync --extra harness
AGENTLAB_LIVE_SDK=1 AGENTLAB_TEST_DATABASE_URL=<disposable-postgres-dsn> \
  uv run --extra harness pytest -q -s tests/live/test_live_sdk_handoff.py
```

Provide the raw gateway and native SDK authentication described above. These tests use disposable repositories
and a disposable database, exercise review-driven repair and signoff, and interrupt processes to verify recovery.

The latest full backend regression run passed **444 tests**, with **3 opt-in live tests skipped**.
The earlier real SDK acceptance run passed both native SDK scenarios; it predates the final isolation review fixes.
Those fixes have offline regression coverage for immutable copies, prepared-copy tampering, exported byte hashes,
legacy reviewer replay protection and CRLF preservation. See [the SDK acceptance record](docs/SDK_HANDOFF_ACCEPTANCE.md)
for the real-run evidence and authentication setup.

See [`docs/ACCEPTANCE.md`](docs/ACCEPTANCE.md) for the full checklist and expected results.

## Limitations

- Alpha software for personal, local use; the API binds to `127.0.0.1` and has no authentication.
- The built-in Gate covers Python; other projects need configured check commands.
- Vector ranking runs in Python; pgvector SQL indexes are planned.
- Project schemas separate data for export and deletion; access control is application-level filtering.
- The ADK runtime and LiteLLM virtual keys are not implemented yet.

See the roadmap in [`docs/DISCOVERY.md`](docs/DISCOVERY.md) §16.

Workspace images in project conversations and task Markdown previews load from the selected project's directory.
PNG, JPEG, GIF, WebP, BMP, ICO, AVIF and SVG are supported up to 10 MiB. Symlink paths and credential files are not previewed.
Interrupted external tool calls remain unresolved until their external result is checked; confirming or closing a record never runs the tool again.
Docker checks mask nested environment files, keys and credential directories. LocalSandbox runs directly on the host and does not provide this filesystem isolation.

## Credits

The workspace visualization and UI components now use project-authored implementations.
Workspace tile art, maps, fictional characters and dialogue are original to this project.
The original artwork and character drawing routines have an MIT notice in `ui/src/assets/LICENSE.txt`.
Bundled fonts remain third-party assets under the SIL OFL.
The replacement scope and source audit are recorded in [UI replacement acceptance](docs/UI_REPLACEMENT.md).
See [`ui/THIRD_PARTY_NOTICES.md`](ui/THIRD_PARTY_NOTICES.md) and
[`ui/src/assets/ATTRIBUTION.md`](ui/src/assets/ATTRIBUTION.md) for full provenance.
Production builds include artwork/font permissions in `THIRD_PARTY_NOTICES.txt` and bundled package licenses in `DEPENDENCY_LICENSES.md`.

## Source, copyright and attribution

Original project: [Elyon0517/Multi-Agent-Platform](https://github.com/Elyon0517/Multi-Agent-Platform), maintained by
[Elyon0517](https://github.com/Elyon0517). See [copyright, attribution and applicable permissions](COPYRIGHT.md). This attribution notice does not itself grant a reuse license; separately licensed material retains its own terms.

For articles, demos and derivatives, please credit the original project and link here.
That link is a courtesy request, not an extra restriction on an existing open-source license.
See [copyright and third-party boundaries](COPYRIGHT.md) and [citation metadata](CITATION.cff).
